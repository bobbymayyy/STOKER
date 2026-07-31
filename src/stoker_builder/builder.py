from __future__ import annotations

import gzip
import logging
import lzma
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import __version__
from .boot import patch_boot_configs
from .config import BuildConfig
from .errors import StokerBuildError
from .repository import build_repository, sign_repository
from .util import (
    copy_tree,
    dump_json,
    dump_yaml,
    ensure_empty_directory,
    hash_file,
    load_yaml,
    make_tree_owner_writable,
    require_command,
    run,
    sha256_file,
)

LOG = logging.getLogger("stoker-builder")


class StokerBuilder:
    def __init__(
        self,
        config: BuildConfig,
        *,
        dry_run: bool = False,
        allow_placeholder_secrets: bool = False,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.allow_placeholder_secrets = allow_placeholder_secrets
        self.work = config.work_directory
        self.generated = self.work / "generated"
        self.apt_root = self.work / "apt"
        self.repository_root = self.work / "repository"
        self.iso_root = self.work / "iso-root"
        self.manifests = self.generated / "manifests"
        self.generated_config = self.generated / "config"
        self.staged_rootfs = self.generated / "rootfs"

    def validate(self, *, require_source_iso: bool = False) -> None:
        data = self.config.data
        source = self.config.source_iso
        if require_source_iso and not source.is_file():
            raise StokerBuildError(
                f"Source ISO not found: {source}\n"
                "Place the Debian netinst image there or change source_iso.path in YAML."
            )
        if source.exists() and not source.is_file():
            raise StokerBuildError(f"source_iso.path is not a regular file: {source}")

        expected = data["source_iso"].get("expected_sha256")
        if source.is_file() and expected:
            actual = sha256_file(source)
            if actual.lower() != expected.lower():
                raise StokerBuildError(
                    f"Source ISO SHA-256 mismatch. Expected {expected}, received {actual}"
                )

        for path_name in ("preseed_template", "scripts_directory"):
            path = self.config.path_value(path_name)
            if not path.exists():
                raise StokerBuildError(f"Configured path does not exist: {path}")

        volume_id = data["output"]["volume_id"]
        if any(ord(character) < 32 or ord(character) > 126 for character in volume_id):
            raise StokerBuildError("output.volume_id must contain printable ASCII characters")

        if data["repository"]["sign"] and not data["repository"].get("signing_key"):
            raise StokerBuildError("repository.sign is true but repository.signing_key is empty")
        if not data["repository"]["trusted"]:
            raise StokerBuildError(
                "v0.1 expects repository.trusted: true for the ISO-local file repository"
            )

        LOG.info("Configuration is valid")
        LOG.info("Requested packages: %d", len(self.config.requested_packages()))
        LOG.info("Enabled modules: %s", ", ".join(self.config.enabled_modules()) or "none")
        LOG.info(
            "Embedded Ansible projects: %s",
            ", ".join(
                project["name"]
                for project in self.config.enabled_ansible_projects()
                if project.get("embed", project.get("source") == "local")
            ) or "none",
        )

    def render(self) -> Path:
        self.validate(require_source_iso=False)
        self.generated.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)
        self.generated_config.mkdir(parents=True, exist_ok=True)

        secrets = self._resolve_secrets()
        build_id = self._build_id()
        template_path = self.config.path_value("preseed_template")
        environment = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        template = environment.get_template(template_path.name)
        rendered = template.render(
            **self.config.data,
            secrets=secrets,
            build_id=build_id,
            builder_version=__version__,
        )
        preseed = self.generated / "preseed.cfg"
        if not self.dry_run:
            preseed.write_text(rendered, encoding="utf-8")
            os.chmod(preseed, 0o600)

        packages = self.config.requested_packages()
        scripts = self.config.post_install_scripts()
        if not self.dry_run:
            (self.manifests / "install-packages.txt").write_text(
                "\n".join(packages) + "\n", encoding="utf-8"
            )
            (self.manifests / "post-install-scripts.txt").write_text(
                "\n".join(scripts) + ("\n" if scripts else ""), encoding="utf-8"
            )
            dump_yaml(
                {
                    "modules": self.config.enabled_modules(),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                self.manifests / "modules-resolved.yaml",
            )
            self._write_repository_source()
            self._write_build_manifest()
            self._stage_rootfs()
        LOG.info("Rendered preseed: %s", preseed)
        return preseed

    def resolve(self) -> Path:
        self.validate(require_source_iso=False)
        require_command("apt-get")
        require_command("dpkg-deb")
        packages = self.config.requested_packages()

        apt_state = self.apt_root / "var/lib/apt"
        apt_cache = self.apt_root / "var/cache/apt"
        archives = apt_cache / "archives"
        lists = apt_state / "lists"
        for directory in (archives / "partial", lists / "partial"):
            directory.mkdir(parents=True, exist_ok=True)
        status = self.apt_root / "var/lib/dpkg/status"
        status.parent.mkdir(parents=True, exist_ok=True)
        status.touch(exist_ok=True)

        for old_package in archives.glob("*.deb"):
            old_package.unlink()

        sources = self.apt_root / "sources.list"
        sources.write_text(self._render_apt_sources(), encoding="utf-8")
        apt_options = self._apt_options(sources, status, apt_state, apt_cache)

        run(["apt-get", *apt_options, "update"], dry_run=self.dry_run)
        install_args = [
            "apt-get",
            *apt_options,
            "--yes",
            "--download-only",
            "--no-install-recommends" if not self.config.data["build"]["include_recommends"] else "--install-recommends",
            "install",
            *packages,
        ]
        run(install_args, dry_run=self.dry_run)

        if not self.dry_run:
            debs = sorted(archives.glob("*.deb"))
            if not debs:
                raise StokerBuildError("APT completed without downloading any .deb packages")
            resolved_lines = []
            for deb in debs:
                result = run(
                    ["dpkg-deb", "-f", deb, "Package", "Version", "Architecture"],
                    capture=True,
                )
                fields = (result.stdout or "").strip().splitlines()
                if len(fields) >= 3:
                    resolved_lines.append("\t".join(fields[:3]))
                else:
                    resolved_lines.append(deb.name)
            self.manifests.mkdir(parents=True, exist_ok=True)
            (self.manifests / "resolved-packages.tsv").write_text(
                "package\tversion\tarchitecture\n" + "\n".join(resolved_lines) + "\n",
                encoding="utf-8",
            )
            self._write_build_manifest(resolved_package_count=len(debs))
            self._stage_rootfs()
            LOG.info("Resolved %d package archives", len(debs))
        return archives

    def repository(self) -> Path:
        archives = self.apt_root / "var/cache/apt/archives"
        project = self.config.data["project"]
        repository = self.config.data["repository"]
        build_repository(
            deb_directory=archives,
            repository_root=self.repository_root,
            suite=repository["suite"],
            component=repository["component"],
            architecture=project["architecture"],
            origin=project["name"],
            version=project["version"],
            dry_run=self.dry_run,
        )
        if repository["sign"]:
            sign_repository(
                self.repository_root,
                repository["suite"],
                repository["signing_key"],
                dry_run=self.dry_run,
            )
        LOG.info("Built embedded repository: %s", self.repository_root)
        return self.repository_root

    def extract(self) -> Path:
        self.validate(require_source_iso=True)
        require_command("xorriso")
        if not self.dry_run:
            ensure_empty_directory(self.iso_root)
        self.config.log_directory.mkdir(parents=True, exist_ok=True)
        run(
            [
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                self.config.source_iso,
                "-extract",
                "/",
                self.iso_root,
            ],
            dry_run=self.dry_run,
            log_path=self.config.log_directory / "xorriso-extract.log",
        )
        if not self.dry_run:
            # ISO9660 files commonly extract without an owner-write bit. The build
            # tree must be editable for boot-menu patching and checksum regeneration.
            make_tree_owner_writable(self.iso_root)
        self._record_source_boot_reports()
        LOG.info("Extracted source ISO: %s", self.iso_root)
        return self.iso_root

    def inject(self) -> Path:
        if not self.iso_root.is_dir() and not self.dry_run:
            raise StokerBuildError("ISO tree is missing. Run the extract stage first.")
        if not (self.generated / "preseed.cfg").exists() and not self.dry_run:
            self.render()
        if not self.repository_root.is_dir() and not self.dry_run:
            raise StokerBuildError("Embedded repository is missing. Run the repository stage first.")

        iso_overlay = self.config.data["paths"].get("iso_overlay")
        if iso_overlay:
            copy_tree(self.config.path_value("iso_overlay"), self.iso_root)

        stoker = self.iso_root / "stoker"
        if not self.dry_run:
            if stoker.exists():
                shutil.rmtree(stoker)
            (stoker / "scripts/modules").mkdir(parents=True)
            shutil.copy2(self.generated / "preseed.cfg", stoker / "preseed.cfg")
            shutil.copy2(
                self.config.path_value("scripts_directory") / "select-install-disk.sh",
                stoker / "scripts/select-install-disk.sh",
            )
            shutil.copy2(
                self.config.path_value("scripts_directory") / "install-offline-packages.sh",
                stoker / "scripts/install-offline-packages.sh",
            )
            for script in self.config.post_install_scripts():
                shutil.copy2(
                    self.config.path_value("scripts_directory") / "modules" / script,
                    stoker / "scripts/modules" / script,
                )
            shutil.copytree(self.repository_root, stoker / "repo", symlinks=True)
            shutil.copytree(self.manifests, stoker / "manifests", symlinks=True)
            shutil.copytree(self.generated_config, stoker / "config", symlinks=True)
            shutil.copytree(self.staged_rootfs, stoker / "rootfs", symlinks=True)

            patched = patch_boot_configs(
                self.iso_root,
                kernel_arguments=self.config.data["boot"]["kernel_arguments"],
                timeout_seconds=self.config.data["boot"]["timeout_seconds"],
                unattended_default=self.config.data["boot"]["unattended_default"],
            )
            LOG.info("Patched boot configurations: %s", ", ".join(map(str, patched)))
        LOG.info("Injected STOKER payload into ISO tree")
        return stoker

    def checksum(self) -> Path:
        if not self.iso_root.is_dir() and not self.dry_run:
            raise StokerBuildError("ISO tree is missing. Run extract and inject first.")
        if self.dry_run:
            return self.iso_root / "md5sum.txt"

        stoker_manifest = self.iso_root / "stoker/manifests/files.sha256"
        stoker_manifest.parent.mkdir(parents=True, exist_ok=True)
        sha_lines = []
        for path in self._iter_iso_files(exclude={stoker_manifest, self.iso_root / "md5sum.txt"}):
            sha_lines.append(f"{hash_file(path, 'sha256')}  ./{path.relative_to(self.iso_root).as_posix()}")
        stoker_manifest.write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

        md5_path = self.iso_root / "md5sum.txt"
        md5_lines = []
        for path in self._iter_iso_files(exclude={md5_path}):
            md5_lines.append(f"{hash_file(path, 'md5')}  ./{path.relative_to(self.iso_root).as_posix()}")
        md5_path.write_text("\n".join(md5_lines) + "\n", encoding="utf-8")
        LOG.info("Regenerated %s with %d entries", md5_path, len(md5_lines))
        return md5_path

    def package(self) -> Path:
        self.validate(require_source_iso=True)
        require_command("xorriso")
        if not self.iso_root.is_dir() and not self.dry_run:
            raise StokerBuildError("ISO tree is missing. Run extract and inject first.")

        output = self.config.output_iso
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()

        command = [
            "xorriso",
            "-indev",
            self.config.source_iso,
            "-outdev",
            output,
            "-update_r",
            self.iso_root,
            "/",
            "-boot_image",
            "any",
            "replay",
            "-volid",
            self.config.data["output"]["volume_id"],
            "-commit",
            "-end",
        ]
        run(
            command,
            dry_run=self.dry_run,
            log_path=self.config.log_directory / "xorriso-package.log",
        )
        LOG.info("Built ISO: %s", output)
        return output

    def verify(self) -> Path:
        output = self.config.output_iso
        if not output.is_file() and not self.dry_run:
            raise StokerBuildError(f"Output ISO does not exist: {output}")
        require_command("xorriso")

        report = run(
            ["xorriso", "-indev", output, "-report_el_torito", "plain", "-end"],
            capture=True,
            dry_run=self.dry_run,
        )
        if not self.dry_run and "El Torito" not in (report.stdout or ""):
            raise StokerBuildError("Output ISO does not report El Torito boot equipment")
        run(
            ["xorriso", "-indev", output, "-ls", "/stoker", "-end"],
            capture=True,
            dry_run=self.dry_run,
        )

        if not self.dry_run:
            digest = sha256_file(output)
            sidecar = output.with_suffix(output.suffix + ".sha256")
            sidecar.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
            self._copy_release_artifacts(output)
            LOG.info("Verified ISO and wrote SHA-256: %s", sidecar)
        return output

    def all(self) -> Path:
        self.validate(require_source_iso=True)
        self.render()
        self.resolve()
        self.repository()
        self.extract()
        self.inject()
        if self.config.data["build"]["regenerate_md5"]:
            self.checksum()
        self.package()
        return self.verify()

    def clean(self) -> None:
        if self.work.exists():
            shutil.rmtree(self.work)
        LOG.info("Removed build work directory: %s", self.work)

    def _resolve_secrets(self) -> dict[str, str]:
        account_env = self.config.data["installer"]["account"]["password_hash_env"]
        luks_env = self.config.data["installer"]["disk"]["luks_passphrase_env"]
        values = {
            "user_password_hash": os.getenv(account_env, ""),
            "luks_passphrase": os.getenv(luks_env, ""),
        }
        missing = [
            env_name
            for env_name, value in ((account_env, values["user_password_hash"]), (luks_env, values["luks_passphrase"]))
            if not value
        ]
        if missing and not self.allow_placeholder_secrets:
            raise StokerBuildError(
                "Missing required build secrets: "
                + ", ".join(missing)
                + ". Export them or use --allow-placeholder-secrets for template testing only."
            )
        if not values["user_password_hash"]:
            values["user_password_hash"] = "CHANGE_ME_STOKER_HASH"
        if not values["luks_passphrase"]:
            values["luks_passphrase"] = "CHANGE_ME_LUKS_PASSPHRASE"
        if (
            values["user_password_hash"] != "CHANGE_ME_STOKER_HASH"
            and not values["user_password_hash"].startswith("$")
        ):
            raise StokerBuildError(
                f"{account_env} does not look like a crypt(3) password hash. Generate one with mkpasswd -m yescrypt."
            )
        return values

    def _render_apt_sources(self) -> str:
        architecture = self.config.data["project"]["architecture"]
        lines = []
        for repository in self.config.enabled_repositories():
            architectures = repository.get("architectures", [architecture])
            if architecture not in architectures:
                continue
            options = [f"arch={architecture}"]
            if self.config.data["build"]["verify_downloads"]:
                signed_by = repository.get("signed_by")
                if not signed_by:
                    raise StokerBuildError(
                        f"Repository {repository['name']} has no signed_by key while download verification is enabled"
                    )
                key_path = Path(signed_by).expanduser()
                if not key_path.is_file():
                    raise StokerBuildError(
                        f"Repository keyring not found for {repository['name']}: {key_path}. "
                        "Install debian-archive-keyring or update repositories.yaml."
                    )
                options.append(f"signed-by={key_path}")
            else:
                options.append("trusted=yes")
            components = " ".join(repository["components"])
            lines.append(
                f"deb [{' '.join(options)}] {repository['uri']} {repository['suite']} {components}"
            )
        if not lines:
            raise StokerBuildError(f"No enabled repository supports architecture {architecture}")
        return "\n".join(lines) + "\n"

    def _apt_options(
        self,
        sources: Path,
        status: Path,
        state: Path,
        cache: Path,
    ) -> list[str]:
        architecture = self.config.data["project"]["architecture"]
        return [
            "-o", f"Dir::Etc::sourcelist={sources}",
            "-o", "Dir::Etc::sourceparts=-",
            "-o", f"Dir::State={state}",
            "-o", f"Dir::State::status={status}",
            "-o", f"Dir::Cache={cache}",
            "-o", f"APT::Architecture={architecture}",
            "-o", f"APT::Architectures::={architecture}",
            "-o", "Acquire::Languages=none",
            "-o", "Debug::NoLocking=true",
            "-o", "APT::Get::List-Cleanup=false",
        ]

    def _write_repository_source(self) -> None:
        repository = self.config.data["repository"]
        lines = [
            "Types: deb",
            "URIs: file:/opt/stoker/repo",
            f"Suites: {repository['suite']}",
            f"Components: {repository['component']}",
        ]
        if repository["trusted"]:
            lines.append("Trusted: yes")
        elif repository["sign"]:
            lines.append("Signed-By: /usr/share/keyrings/stoker-archive-keyring.gpg")
        else:
            raise StokerBuildError(
                "The embedded repository must be trusted or signed; otherwise APT will refuse it"
            )
        (self.generated_config / "repository.sources").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def _stage_rootfs(self) -> None:
        ensure_empty_directory(self.staged_rootfs)
        overlay = self.config.data["paths"].get("rootfs_overlay")
        if overlay:
            copy_tree(self.config.path_value("rootfs_overlay"), self.staged_rootfs)

        etc_stoker = self.staged_rootfs / "etc/stoker"
        etc_stoker.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.manifests / "build.json", etc_stoker / "build.json")
        shutil.copy2(self.manifests / "install-packages.txt", etc_stoker / "install-packages.txt")
        shutil.copy2(self.manifests / "modules-resolved.yaml", etc_stoker / "modules.yaml")

        validator = self.config.path_value("scripts_directory") / "validate-installation.sh"
        destination = self.staged_rootfs / "usr/local/sbin/stoker-validate"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(validator, destination)
        os.chmod(destination, 0o755)

        self._stage_ansible_controller_content()

    def _stage_ansible_controller_content(self) -> None:
        settings = dict(self.config.ansible_settings())
        runtime_projects: list[dict[str, Any]] = []
        embedded_manifest: list[dict[str, Any]] = []

        def target_path(absolute: str) -> Path:
            return self.staged_rootfs / absolute.lstrip("/")

        project_root = target_path(settings["project_root"])
        versions_root = target_path(settings["versions_root"])
        project_root.mkdir(parents=True, exist_ok=True)
        versions_root.mkdir(parents=True, exist_ok=True)

        for project in self.config.enabled_ansible_projects():
            source_type = project["source"]
            embed = bool(project.get("embed", source_type == "local"))
            runtime_project = {
                key: project[key]
                for key in ("name", "enabled", "default_playbook", "repository", "ref")
                if key in project
            }
            runtime_project["enabled"] = True
            runtime_project["source"] = "git" if source_type == "git" else "embedded"

            if embed:
                source_path, revision = self._materialize_ansible_project(project)
                self._validate_ansible_project_tree(project["name"], source_path)
                version_destination = versions_root / project["name"] / revision
                version_destination.parent.mkdir(parents=True, exist_ok=True)
                if version_destination.exists():
                    shutil.rmtree(version_destination)
                shutil.copytree(
                    source_path,
                    version_destination,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"),
                )

                self._stage_ansible_project_dependencies(project, version_destination)

                active_link = project_root / project["name"]
                active_link.unlink(missing_ok=True)
                relative_target = os.path.relpath(version_destination, active_link.parent)
                active_link.symlink_to(relative_target)
                runtime_project["embedded_revision"] = revision
                dependency_lock = version_destination / ".stoker/dependencies.lock"
                embedded_manifest.append(
                    {
                        "name": project["name"],
                        "revision": revision,
                        "source": source_type,
                        "dependencies": load_yaml(dependency_lock)
                        if dependency_lock.is_file()
                        else None,
                    }
                )

            runtime_projects.append(runtime_project)

        runtime_config = {"ansible": settings, "projects": runtime_projects}
        runtime_config_path = self.staged_rootfs / "etc/stoker/ansible-projects.yaml"
        runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
        dump_yaml(runtime_config, runtime_config_path)
        dump_yaml(
            {
                "projects": embedded_manifest,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            self.manifests / "ansible-projects-resolved.yaml",
        )

        runtime_source = self.config.path_value("scripts_directory") / "runtime"
        runtime_destinations = {
            "stoker": self.staged_rootfs / "usr/local/sbin/stoker",
            "stoker-node-enroll": self.staged_rootfs / "usr/local/bin/stoker-node-enroll",
            "stoker-project-sync": self.staged_rootfs / "usr/local/bin/stoker-project-sync",
            "stoker-project-run": self.staged_rootfs / "usr/local/bin/stoker-project-run",
            "stoker-project-import": self.staged_rootfs / "usr/local/bin/stoker-project-import",
            "stoker-network-config": self.staged_rootfs / "usr/local/sbin/stoker-network-config",
            "stoker-nat": self.staged_rootfs / "usr/local/sbin/stoker-nat",
        }
        for name, destination in runtime_destinations.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime_source / name, destination)
            os.chmod(destination, 0o755)

    def _materialize_ansible_project(self, project: dict[str, Any]) -> tuple[Path, str]:
        if project["source"] == "local":
            revision = str(project["version"])
            return self.config.ansible_project_source_path(project), revision

        require_command("git")
        cache_root = self.generated / "ansible-project-cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        destination = cache_root / project["name"]
        if destination.exists():
            shutil.rmtree(destination)
        run(
            ["git", "clone", "--no-tags", str(project["repository"]), destination],
            dry_run=self.dry_run,
        )
        run(
            ["git", "checkout", str(project["ref"])],
            cwd=destination,
            dry_run=self.dry_run,
        )
        if self.dry_run:
            return destination, str(project["ref"])
        result = run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=destination,
            capture=True,
        )
        revision = (result.stdout or "").strip()
        if not revision:
            raise StokerBuildError(f"Unable to determine revision for {project['name']}")
        return destination, revision

    def _stage_ansible_project_dependencies(
        self,
        project: dict[str, Any],
        project_path: Path,
    ) -> None:
        requirements = project_path / "requirements.yml"
        if not requirements.is_file():
            return
        contents = load_yaml(requirements)
        roles = contents.get("roles") or []
        collections = contents.get("collections") or []
        if not isinstance(roles, list) or not isinstance(collections, list):
            raise StokerBuildError(
                f"Invalid roles/collections lists in {requirements}"
            )

        dependency_root = project_path / ".stoker"
        roles_root = dependency_root / "roles"
        collections_root = dependency_root / "collections"
        lock_path = dependency_root / "dependencies.lock"
        requirements_hash = hash_file(requirements, "sha256")

        if lock_path.is_file():
            lock = load_yaml(lock_path)
            roles_ready = not roles or roles_root.is_dir()
            collections_ready = not collections or collections_root.is_dir()
            if (
                lock.get("requirements_sha256") == requirements_hash
                and roles_ready
                and collections_ready
            ):
                return

        if (roles or collections) and not project.get("resolve_dependencies", True):
            raise StokerBuildError(
                f"Ansible project '{project['name']}' has unresolved requirements. "
                "Set resolve_dependencies: true or vendor a matching .stoker/dependencies.lock tree."
            )

        dependency_root.mkdir(parents=True, exist_ok=True)
        roles_root.mkdir(parents=True, exist_ok=True)
        collections_root.mkdir(parents=True, exist_ok=True)
        if roles or collections:
            require_command("ansible-galaxy")
            with tempfile.TemporaryDirectory(prefix="stoker-galaxy-") as temporary:
                temp = Path(temporary)
                if roles:
                    role_requirements = temp / "roles.yml"
                    dump_yaml(roles, role_requirements)
                    run(
                        [
                            "ansible-galaxy",
                            "role",
                            "install",
                            "--force",
                            "--roles-path",
                            roles_root,
                            "-r",
                            role_requirements,
                        ],
                        dry_run=self.dry_run,
                    )
                if collections:
                    collection_requirements = temp / "collections.yml"
                    dump_yaml({"collections": collections}, collection_requirements)
                    run(
                        [
                            "ansible-galaxy",
                            "collection",
                            "install",
                            "--force",
                            "--collections-path",
                            collections_root,
                            "-r",
                            collection_requirements,
                        ],
                        dry_run=self.dry_run,
                    )
        dump_yaml(
            {
                "requirements_sha256": requirements_hash,
                "roles": len(roles),
                "collections": len(collections),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            lock_path,
        )

    def _validate_ansible_project_tree(self, name: str, source: Path) -> None:
        playbooks = source / "playbooks"
        if not playbooks.is_dir():
            raise StokerBuildError(f"Ansible project '{name}' has no playbooks directory: {playbooks}")
        if not any(playbooks.glob("*.yml")) and not any(playbooks.glob("*.yaml")):
            raise StokerBuildError(f"Ansible project '{name}' contains no YAML playbooks")

    def _write_build_manifest(self, resolved_package_count: int | None = None) -> None:
        source = self.config.source_iso
        manifest: dict[str, Any] = {
            "builder_version": __version__,
            "build_id": self._build_id(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project": self.config.data["project"],
            "source_iso": {
                "filename": source.name,
                "sha256": sha256_file(source) if source.is_file() else None,
            },
            "requested_packages": self.config.requested_packages(),
            "enabled_modules": sorted(self.config.enabled_modules()),
            "ansible_projects": [
                {
                    "name": project["name"],
                    "source": project["source"],
                    "embedded": bool(project.get("embed", project["source"] == "local")),
                    "version": project.get("version"),
                    "repository": project.get("repository"),
                    "ref": project.get("ref"),
                }
                for project in self.config.enabled_ansible_projects()
            ],
            "resolved_package_count": resolved_package_count,
        }
        dump_json(manifest, self.manifests / "build.json")

    def _build_id(self) -> str:
        build_id_file = self.work / "build-id"
        if build_id_file.exists():
            return build_id_file.read_text(encoding="utf-8").strip()
        build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if not self.dry_run:
            build_id_file.parent.mkdir(parents=True, exist_ok=True)
            build_id_file.write_text(build_id + "\n", encoding="utf-8")
        return build_id

    def _record_source_boot_reports(self) -> None:
        if self.dry_run:
            return
        for mode in ("plain", "as_mkisofs", "cmd"):
            result = run(
                [
                    "xorriso",
                    "-indev",
                    self.config.source_iso,
                    "-report_el_torito",
                    mode,
                    "-report_system_area",
                    mode,
                    "-end",
                ],
                capture=True,
            )
            (self.config.log_directory / f"source-boot-report-{mode}.txt").write_text(
                result.stdout or "", encoding="utf-8"
            )

    def _iter_iso_files(self, *, exclude: set[Path]) -> list[Path]:
        excluded_resolved = {path.resolve() for path in exclude}
        files = []
        for path in self.iso_root.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in excluded_resolved:
                continue
            if path.relative_to(self.iso_root).as_posix() == "isolinux/boot.cat":
                continue
            files.append(path)
        return sorted(files, key=lambda item: item.relative_to(self.iso_root).as_posix())

    def _copy_release_artifacts(self, output: Path) -> None:
        if not self.manifests.is_dir():
            return
        stem = output.name.removesuffix(".iso")
        mapping = {
            "build.json": f"{stem}-build.json",
            "install-packages.txt": f"{stem}-packages.txt",
            "resolved-packages.tsv": f"{stem}-resolved-packages.tsv",
            "ansible-projects-resolved.yaml": f"{stem}-ansible-projects.yaml",
        }
        for source_name, destination_name in mapping.items():
            source = self.manifests / source_name
            if source.exists():
                shutil.copy2(source, output.parent / destination_name)
        preseed = self.generated / "preseed.cfg"
        if preseed.exists():
            redacted_lines = []
            for line in preseed.read_text(encoding="utf-8").splitlines():
                if "passwd/user-password-crypted password" in line:
                    line = line.split(" password", 1)[0] + " password <REDACTED>"
                elif "partman-crypto/passphrase" in line and " password " in line:
                    line = line.split(" password", 1)[0] + " password <REDACTED>"
                redacted_lines.append(line)
            (output.parent / f"{stem}-preseed.redacted.cfg").write_text(
                "\n".join(redacted_lines) + "\n", encoding="utf-8"
            )

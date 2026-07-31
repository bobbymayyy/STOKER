from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .errors import StokerBuildError
from .util import load_yaml, unique_sorted

PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
INTERFACE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
ANSIBLE_PATH_KEYS = (
    "project_root",
    "versions_root",
    "staging_root",
    "inventory_root",
    "roles_root",
    "collections_root",
    "artifacts_root",
    "logs_root",
    "secrets_root",
)


@dataclass(frozen=True)
class BuildConfig:
    path: Path
    project_root: Path
    data: dict[str, Any]
    repositories_data: dict[str, Any]
    packages_data: dict[str, Any]
    modules_data: dict[str, Any]
    ansible_projects_data: dict[str, Any]
    ansible_projects_path: Path

    @classmethod
    def load(cls, path: str | Path) -> "BuildConfig":
        config_path = Path(path).expanduser().resolve()
        project_root = Path(__file__).resolve().parents[2]
        data = load_yaml(config_path)

        schema_path = project_root / "schemas" / "stoker-build.schema.json"
        if not schema_path.exists():
            raise StokerBuildError(f"Build schema is missing: {schema_path}")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        try:
            jsonschema.Draft202012Validator(schema).validate(data)
        except jsonschema.ValidationError as exc:
            location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
            raise StokerBuildError(f"Invalid build configuration at {location}: {exc.message}") from exc

        base = config_path.parent
        paths = data["paths"]
        repositories_data = load_yaml((base / paths["repositories"]).resolve())
        packages_data = load_yaml((base / paths["packages"]).resolve())
        modules_data = load_yaml((base / paths["modules"]).resolve())
        ansible_projects_path = (base / paths["ansible_projects"]).resolve()
        ansible_projects_data = load_yaml(ansible_projects_path)

        instance = cls(
            path=config_path,
            project_root=project_root,
            data=data,
            repositories_data=repositories_data,
            packages_data=packages_data,
            modules_data=modules_data,
            ansible_projects_data=ansible_projects_data,
            ansible_projects_path=ansible_projects_path,
        )
        instance._validate_referenced_configuration()
        return instance

    @property
    def base_directory(self) -> Path:
        return self.path.parent

    def path_value(self, name: str) -> Path:
        raw = self.data["paths"][name]
        if raw is None:
            raise StokerBuildError(f"Path '{name}' is not configured")
        return (self.base_directory / raw).resolve()

    @property
    def source_iso(self) -> Path:
        return (self.base_directory / self.data["source_iso"]["path"]).resolve()

    @property
    def work_directory(self) -> Path:
        return self.path_value("work_directory")

    @property
    def log_directory(self) -> Path:
        return self.path_value("log_directory")

    @property
    def output_directory(self) -> Path:
        return (self.base_directory / self.data["output"]["directory"]).resolve()

    @property
    def output_iso(self) -> Path:
        project = self.data["project"]
        filename = self.data["output"]["filename"].format(
            name=project["name"].lower(),
            version=project["version"],
            architecture=project["architecture"],
        )
        return self.output_directory / filename

    def enabled_repositories(self) -> list[dict[str, Any]]:
        return [
            repository
            for repository in self.repositories_data.get("repositories", [])
            if repository.get("enabled", True)
        ]

    def enabled_modules(self) -> dict[str, dict[str, Any]]:
        modules = self.modules_data.get("modules", {})
        return {
            name: value
            for name, value in modules.items()
            if isinstance(value, dict) and value.get("enabled", False)
        }

    def enabled_ansible_projects(self) -> list[dict[str, Any]]:
        projects = self.ansible_projects_data.get("projects", [])
        return [
            project
            for project in projects
            if isinstance(project, dict) and project.get("enabled", True)
        ]

    def ansible_settings(self) -> dict[str, Any]:
        return self.ansible_projects_data["ansible"]

    def ansible_project_source_path(self, project: dict[str, Any]) -> Path:
        raw = project.get("path")
        if not isinstance(raw, str) or not raw:
            raise StokerBuildError(f"Local Ansible project '{project.get('name')}' has no path")
        return (self.ansible_projects_path.parent / raw).resolve()

    def requested_packages(self) -> list[str]:
        packages: list[str] = []
        groups = self.packages_data.get("package_groups", {})
        for group in groups.values():
            if isinstance(group, dict) and group.get("enabled", False):
                packages.extend(group.get("packages", []))
        for module in self.enabled_modules().values():
            packages.extend(module.get("packages", []))
        excluded = set(self.packages_data.get("exclude", []))
        return [package for package in unique_sorted(packages) if package not in excluded]

    def post_install_scripts(self) -> list[str]:
        scripts = []
        for module in self.enabled_modules().values():
            script = module.get("post_install_script")
            if script:
                scripts.append(str(script))
        return unique_sorted(scripts)

    @staticmethod
    def _module_configuration(modules: dict[str, Any], name: str) -> dict[str, Any]:
        module = modules.get(name, {})
        if not isinstance(module, dict) or not module.get("enabled", False):
            return {}
        configuration = module.get("configuration", {})
        if not isinstance(configuration, dict):
            raise StokerBuildError(f"modules.{name}.configuration must be a mapping")
        return configuration

    def _validate_network_configuration(self, modules: dict[str, Any]) -> None:
        routing = self._module_configuration(modules, "routing")
        dhcp = self._module_configuration(modules, "dhcp")
        dns = self._module_configuration(modules, "dns")
        if not (routing or dhcp or dns):
            return
        if not dhcp:
            raise StokerBuildError(
                "The routing/DNS integration requires the DHCP module to define the downstream subnet"
            )

        for field, value in (
            ("routing.upstream_interface", routing.get("upstream_interface", "auto")),
            ("dhcp.interface", dhcp.get("interface", "auto")),
        ):
            if value != "auto" and (not isinstance(value, str) or not INTERFACE_NAME_RE.fullmatch(value)):
                raise StokerBuildError(f"{field} must be 'auto' or a valid Linux interface name")

        for field in ("enable_ipv4_forwarding", "enable_nat"):
            value = routing.get(field, field == "enable_ipv4_forwarding")
            if not isinstance(value, bool):
                raise StokerBuildError(f"routing.{field} must be a boolean")

        try:
            subnet = ipaddress.ip_network(str(dhcp["subnet"]), strict=True)
            gateway = ipaddress.ip_address(str(dhcp["gateway"]))
            pool_start = ipaddress.ip_address(str(dhcp["pool_start"]))
            pool_end = ipaddress.ip_address(str(dhcp["pool_end"]))
        except (KeyError, ValueError) as exc:
            raise StokerBuildError(f"Invalid DHCP IPv4 configuration: {exc}") from exc
        if not isinstance(subnet, ipaddress.IPv4Network):
            raise StokerBuildError("dhcp.subnet must be an IPv4 network")
        if subnet.prefixlen > 30:
            raise StokerBuildError("dhcp.subnet must provide usable IPv4 host addresses")
        for label, address in (("gateway", gateway), ("pool_start", pool_start), ("pool_end", pool_end)):
            if not isinstance(address, ipaddress.IPv4Address) or address not in subnet:
                raise StokerBuildError(f"dhcp.{label} must be an IPv4 address inside dhcp.subnet")
        unusable = {subnet.network_address, subnet.broadcast_address}
        if gateway in unusable or pool_start in unusable or pool_end in unusable:
            raise StokerBuildError("DHCP gateway and pool endpoints must be usable host addresses")
        if pool_start > pool_end:
            raise StokerBuildError("dhcp.pool_start must not be greater than dhcp.pool_end")
        if pool_start <= gateway <= pool_end:
            raise StokerBuildError("The DHCP pool must not include the gateway address")

        dns_servers = dhcp.get("dns_servers", [str(gateway)])
        if not isinstance(dns_servers, list) or not dns_servers:
            raise StokerBuildError("dhcp.dns_servers must be a non-empty list")
        for address in dns_servers:
            try:
                parsed = ipaddress.ip_address(str(address))
            except ValueError as exc:
                raise StokerBuildError(f"Invalid DHCP DNS server: {address}") from exc
            if not isinstance(parsed, ipaddress.IPv4Address):
                raise StokerBuildError("dhcp.dns_servers currently supports IPv4 addresses only")

        for field in ("renew_timer", "rebind_timer", "valid_lifetime", "max_valid_lifetime", "subnet_id"):
            if field in dhcp and (type(dhcp[field]) is not int or dhcp[field] < 1):
                raise StokerBuildError(f"dhcp.{field} must be a positive integer")
        if dhcp.get("renew_timer", 900) >= dhcp.get("rebind_timer", 1800):
            raise StokerBuildError("dhcp.renew_timer must be less than dhcp.rebind_timer")
        if dhcp.get("rebind_timer", 1800) >= dhcp.get("valid_lifetime", 3600):
            raise StokerBuildError("dhcp.rebind_timer must be less than dhcp.valid_lifetime")
        if dhcp.get("valid_lifetime", 3600) > dhcp.get("max_valid_lifetime", 7200):
            raise StokerBuildError("dhcp.valid_lifetime must not exceed dhcp.max_valid_lifetime")

        if dns:
            if not isinstance(dns.get("recursion", True), bool):
                raise StokerBuildError("dns.recursion must be a boolean")
            policy = dns.get("forward_policy", "only")
            if policy not in {"first", "only"}:
                raise StokerBuildError("dns.forward_policy must be 'first' or 'only'")
            forwarders = dns.get("forwarders", [])
            if not isinstance(forwarders, list):
                raise StokerBuildError("dns.forwarders must be a list")
            for forwarder in forwarders:
                try:
                    ipaddress.ip_address(str(forwarder))
                except ValueError as exc:
                    raise StokerBuildError(f"Invalid DNS forwarder: {forwarder}") from exc

    def _validate_referenced_configuration(self) -> None:
        repositories = self.repositories_data.get("repositories")
        if not isinstance(repositories, list) or not repositories:
            raise StokerBuildError("repositories.yaml must define a non-empty repositories list")
        for index, repository in enumerate(repositories):
            if not isinstance(repository, dict):
                raise StokerBuildError(f"Repository entry {index} must be a mapping")
            for key in ("name", "uri", "suite", "components"):
                if key not in repository:
                    raise StokerBuildError(f"Repository entry {index} is missing '{key}'")
            if not isinstance(repository["components"], list) or not repository["components"]:
                raise StokerBuildError(f"Repository '{repository['name']}' has no components")

        groups = self.packages_data.get("package_groups")
        if not isinstance(groups, dict):
            raise StokerBuildError("packages.yaml must define package_groups as a mapping")

        modules = self.modules_data.get("modules")
        if not isinstance(modules, dict):
            raise StokerBuildError("modules.yaml must define modules as a mapping")

        requested = self.requested_packages()
        if not requested:
            raise StokerBuildError("No packages are enabled by packages.yaml or modules.yaml")

        scripts_dir = self.path_value("scripts_directory") / "modules"
        for script in self.post_install_scripts():
            if Path(script).name != script:
                raise StokerBuildError(f"Module script must be a simple filename: {script}")
            if not (scripts_dir / script).is_file():
                raise StokerBuildError(f"Enabled module script does not exist: {scripts_dir / script}")

        self._validate_network_configuration(modules)

        runtime_dir = self.path_value("scripts_directory") / "runtime"
        for runtime_script in (
            "stoker",
            "stoker-node-enroll",
            "stoker-project-sync",
            "stoker-project-run",
            "stoker-project-import",
            "stoker-network-config",
            "stoker-nat",
        ):
            if not (runtime_dir / runtime_script).is_file():
                raise StokerBuildError(f"Runtime controller script is missing: {runtime_dir / runtime_script}")

        settings = self.ansible_projects_data.get("ansible")
        if not isinstance(settings, dict):
            raise StokerBuildError("ansible-projects.yaml must define an 'ansible' mapping")
        for key in ANSIBLE_PATH_KEYS:
            value = settings.get(key)
            if not isinstance(value, str) or not value.startswith("/"):
                raise StokerBuildError(f"ansible.{key} must be an absolute path")
        default_inventory = settings.get("default_inventory")
        if not isinstance(default_inventory, str) or not default_inventory:
            raise StokerBuildError("ansible.default_inventory must be a non-empty string")
        retain = settings.get("retain_versions", 3)
        if not isinstance(retain, int) or retain < 1:
            raise StokerBuildError("ansible.retain_versions must be an integer of at least 1")
        validation = settings.get("validation", {})
        if not isinstance(validation, dict):
            raise StokerBuildError("ansible.validation must be a mapping")

        projects = self.ansible_projects_data.get("projects")
        if not isinstance(projects, list) or not projects:
            raise StokerBuildError("ansible-projects.yaml must define a non-empty projects list")
        names: set[str] = set()
        for index, project in enumerate(projects):
            if not isinstance(project, dict):
                raise StokerBuildError(f"Ansible project entry {index} must be a mapping")
            name = project.get("name")
            if not isinstance(name, str) or not PROJECT_NAME_RE.fullmatch(name):
                raise StokerBuildError(f"Ansible project entry {index} has an invalid name")
            if name in names:
                raise StokerBuildError(f"Duplicate Ansible project name: {name}")
            names.add(name)
            source = project.get("source")
            if source not in {"local", "git"}:
                raise StokerBuildError(f"Ansible project '{name}' source must be local or git")
            if source == "local":
                project_path = self.ansible_project_source_path(project)
                if not project_path.is_dir():
                    raise StokerBuildError(f"Local Ansible project does not exist: {project_path}")
                version = project.get("version")
                if not isinstance(version, str) or not PROJECT_NAME_RE.fullmatch(version):
                    raise StokerBuildError(
                        f"Local Ansible project '{name}' version must be a safe revision label"
                    )
                playbooks = project_path / "playbooks"
                if not playbooks.is_dir() or not (
                    any(playbooks.glob("*.yml")) or any(playbooks.glob("*.yaml"))
                ):
                    raise StokerBuildError(
                        f"Local Ansible project '{name}' must contain playbooks/*.yml or *.yaml"
                    )
            else:
                if not project.get("repository"):
                    raise StokerBuildError(f"Git Ansible project '{name}' must define repository")
                if not project.get("ref"):
                    raise StokerBuildError(f"Git Ansible project '{name}' must define ref")
            resolve_dependencies = project.get("resolve_dependencies", True)
            if not isinstance(resolve_dependencies, bool):
                raise StokerBuildError(
                    f"Ansible project '{name}' resolve_dependencies must be boolean"
                )
            if project.get("embed", source == "local") and source == "git":
                # Supported by the builder, but the actual clone is intentionally deferred
                # until render so validation remains network-free.
                pass

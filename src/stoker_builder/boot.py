from __future__ import annotations

from pathlib import Path

from .errors import StokerBuildError

MARKER = "### STOKER GENERATED BOOT ENTRY ###"


def patch_boot_configs(
    iso_root: Path,
    *,
    kernel_arguments: list[str],
    timeout_seconds: int,
    unattended_default: bool,
) -> list[Path]:
    patched: list[Path] = []
    arguments = " ".join(kernel_arguments)

    isolinux_cfg = iso_root / "isolinux" / "txt.cfg"
    if isolinux_cfg.exists():
        text = isolinux_cfg.read_text(encoding="utf-8", errors="replace")
        if MARKER not in text:
            stanza = (
                f"{MARKER}\n"
                "label stoker\n"
                "\tmenu label ^Install STOKER unattended\n"
                + ("\tmenu default\n" if unattended_default else "")
                + "\tkernel /install.amd/vmlinuz\n"
                + f"\tappend {arguments} initrd=/install.amd/initrd.gz --- quiet\n\n"
            )
            isolinux_cfg.write_text(stanza + text, encoding="utf-8")
        patched.append(isolinux_cfg)

        menu_cfg = iso_root / "isolinux" / "isolinux.cfg"
        if menu_cfg.exists():
            menu_text = menu_cfg.read_text(encoding="utf-8", errors="replace")
            timeout_line = f"timeout {timeout_seconds * 10}"
            lines = [line for line in menu_text.splitlines() if not line.lower().startswith("timeout ")]
            lines.insert(0, timeout_line)
            menu_cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
            patched.append(menu_cfg)

    grub_cfg = iso_root / "boot" / "grub" / "grub.cfg"
    if grub_cfg.exists():
        text = grub_cfg.read_text(encoding="utf-8", errors="replace")
        if MARKER not in text:
            stanza = (
                f"{MARKER}\n"
                + ("set default=0\n" if unattended_default else "")
                + f"set timeout={timeout_seconds}\n"
                "menuentry 'Install STOKER unattended' {\n"
                f"    linux /install.amd/vmlinuz {arguments} --- quiet\n"
                "    initrd /install.amd/initrd.gz\n"
                "}\n\n"
            )
            grub_cfg.write_text(stanza + text, encoding="utf-8")
        patched.append(grub_cfg)

    if not patched:
        raise StokerBuildError(
            "No supported Debian boot configuration was found. Expected isolinux/txt.cfg or boot/grub/grub.cfg."
        )
    return patched

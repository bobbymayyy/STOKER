from pathlib import Path

from stoker_builder.boot import MARKER, patch_boot_configs


def test_boot_patch_adds_bios_and_uefi_entries(tmp_path: Path) -> None:
    isolinux = tmp_path / "isolinux"
    grub = tmp_path / "boot/grub"
    isolinux.mkdir(parents=True)
    grub.mkdir(parents=True)
    (isolinux / "txt.cfg").write_text("label install\n", encoding="utf-8")
    (isolinux / "isolinux.cfg").write_text("timeout 0\ninclude menu.cfg\n", encoding="utf-8")
    (grub / "grub.cfg").write_text("menuentry 'Install' {}\n", encoding="utf-8")

    patch_boot_configs(
        tmp_path,
        kernel_arguments=["auto=true", "preseed/file=/cdrom/stoker/preseed.cfg"],
        timeout_seconds=5,
        unattended_default=True,
    )

    bios = (isolinux / "txt.cfg").read_text(encoding="utf-8")
    uefi = (grub / "grub.cfg").read_text(encoding="utf-8")
    assert MARKER in bios
    assert MARKER in uefi
    assert "menu default" in bios
    assert "set default=0" in uefi
    assert "preseed/file=/cdrom/stoker/preseed.cfg" in bios
    assert "preseed/file=/cdrom/stoker/preseed.cfg" in uefi

    # Patching is idempotent.
    patch_boot_configs(
        tmp_path,
        kernel_arguments=["auto=true", "preseed/file=/cdrom/stoker/preseed.cfg"],
        timeout_seconds=5,
        unattended_default=True,
    )
    assert (isolinux / "txt.cfg").read_text(encoding="utf-8").count(MARKER) == 1
    assert (grub / "grub.cfg").read_text(encoding="utf-8").count(MARKER) == 1

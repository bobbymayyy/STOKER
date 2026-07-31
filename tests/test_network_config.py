from __future__ import annotations

import importlib.machinery
import importlib.util
import ipaddress
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_network_module():
    path = ROOT / "scripts/runtime/stoker-network-config"
    loader = importlib.machinery.SourceFileLoader("stoker_network_config", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_auto_interface_selection_uses_dhcp_interface_then_next_nic() -> None:
    network = load_network_module()
    upstream, downstream = network.select_interfaces(
        ["enp1s0", "enp2s0", "enp3s0"],
        configured_dhcp_interfaces=["enp1s0"],
    )
    assert upstream == "enp1s0"
    assert downstream == "enp2s0"


def test_explicit_interfaces_remain_distinct() -> None:
    network = load_network_module()
    upstream, downstream = network.select_interfaces(
        ["eno1", "eno2"],
        configured_upstream="eno2",
        configured_downstream="eno1",
    )
    assert (upstream, downstream) == ("eno2", "eno1")


def test_dns_forwarders_and_policy_render() -> None:
    network = load_network_module()
    rendered = network.build_bind_options(
        ipaddress.ip_network("192.168.88.0/24"),
        {
            "recursion": True,
            "forwarders": ["1.1.1.1", "9.9.9.9"],
            "forward_policy": "only",
        },
    )
    assert "1.1.1.1;" in rendered
    assert "9.9.9.9;" in rendered
    assert "forward only;" in rendered
    assert "192.168.88.0/24;" in rendered


def test_nat_rules_are_runtime_toggleable() -> None:
    network = load_network_module()
    disabled = network.build_nftables(
        "enp1s0", "enp2s0", ipaddress.ip_network("192.168.88.0/24"), False
    )
    enabled = network.build_nftables(
        "enp1s0", "enp2s0", ipaddress.ip_network("192.168.88.0/24"), True
    )
    assert "masquerade" not in disabled
    assert "destroy table ip stoker_nat" in disabled
    assert "flush ruleset" not in disabled
    assert "masquerade" in enabled
    assert "table ip stoker_nat" in enabled


def test_apply_renders_coherent_network_stack(tmp_path, monkeypatch) -> None:
    network = load_network_module()
    modules = yaml.safe_load((ROOT / "config/modules.yaml").read_text(encoding="utf-8"))
    module_path = tmp_path / "etc/stoker/modules.yaml"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(yaml.safe_dump(modules, sort_keys=False), encoding="utf-8")

    interfaces = tmp_path / "etc/network/interfaces"
    interfaces.parent.mkdir(parents=True)
    interfaces.write_text(
        "auto enp1s0\niface enp1s0 inet dhcp\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(network, "list_candidate_interfaces", lambda: ["enp1s0", "enp2s0"])
    monkeypatch.setattr(network, "default_route_interface", lambda: None)

    upstream, downstream, nat = network.apply_configuration(
        tmp_path,
        validate=False,
    )

    assert (upstream, downstream, nat) == ("enp1s0", "enp2s0", False)
    assert "source /etc/network/interfaces.d/*" in interfaces.read_text(encoding="utf-8")
    downstream_config = (tmp_path / "etc/network/interfaces.d/90-stoker-downstream").read_text()
    assert "auto enp2s0" in downstream_config
    assert "allow-hotplug enp2s0" in downstream_config
    assert "address 192.168.88.1/24" in downstream_config

    kea = (tmp_path / "etc/kea/kea-dhcp4.conf").read_text(encoding="utf-8")
    assert '"interfaces": [' in kea
    assert '"enp2s0"' in kea
    assert "192.168.88.100 - 192.168.88.200" in kea

    bind = (tmp_path / "etc/bind/named.conf.options").read_text(encoding="utf-8")
    assert "forward only;" in bind
    assert "1.1.1.1;" in bind

    nftables = (tmp_path / "etc/nftables.conf").read_text(encoding="utf-8")
    assert "masquerade" not in nftables
    assert (tmp_path / "etc/systemd/system/stoker-network-config.service").is_file()


def test_installer_context_defers_only_kernel_bound_nft_check(monkeypatch) -> None:
    network = load_network_module()
    commands: list[list[str]] = []
    monkeypatch.setattr(network, "run_checked", lambda command, **kwargs: commands.append(command))

    network.validate_generated_configuration(
        dns_enabled=True,
        dhcp_enabled=True,
        routing_enabled=True,
        installer_context=True,
    )

    assert ["named-checkconf"] in commands
    assert ["kea-dhcp4", "-t", "/etc/kea/kea-dhcp4.conf"] in commands
    assert ["nft", "-c", "-f", "/etc/nftables.conf"] not in commands


def test_normal_runtime_still_validates_nftables(monkeypatch) -> None:
    network = load_network_module()
    commands: list[list[str]] = []
    monkeypatch.setattr(network, "run_checked", lambda command, **kwargs: commands.append(command))

    network.validate_generated_configuration(
        dns_enabled=False,
        dhcp_enabled=False,
        routing_enabled=True,
        installer_context=False,
    )

    assert commands == [["nft", "-c", "-f", "/etc/nftables.conf"]]

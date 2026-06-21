"""Distribution config renderer (M50).

Reads ``DistributionConfigValue`` rows for a given distribution and renders
them into config files inside a rootfs staging directory.

Each config key belongs to a *namespace* that maps to a file:

    hostapd.*   → /etc/hostapd.conf
    nanodhcp.*  → /etc/nanodhcp/nanodhcp.conf
    tinywifi.*  → /etc/tinywifi/web.toml
    network.*   → /etc/init.d/S40network  (injected into the script vars)

The renderer only writes files for namespaces that have at least one key set.
If the staging dir already has the file (from an .ofpkg), it is replaced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osfabricum.db.models import Distribution, DistributionConfigValue

# ---------------------------------------------------------------------------
# Config key catalogue
# Keys a user can set, grouped by namespace.
# ---------------------------------------------------------------------------

CONFIG_SCHEMA: dict[str, dict[str, Any]] = {
    # hostapd — WiFi access point
    "hostapd.ssid": {
        "label": "WiFi SSID",
        "description": "Network name broadcast by the AP",
        "default": "tinywifi",
    },
    "hostapd.passphrase": {
        "label": "WiFi Passphrase",
        "description": "WPA2-PSK password (8–63 chars)",
        "default": "tinywifi123",
    },
    "hostapd.channel": {
        "label": "WiFi Channel",
        "description": "2.4 GHz channel (1–13, default 6)",
        "default": "6",
    },
    "hostapd.interface": {
        "label": "WiFi Interface",
        "description": "Linux wireless interface name",
        "default": "wlan0",
    },
    # nanodhcp — DHCP server
    "nanodhcp.server_ip": {
        "label": "AP IP Address",
        "description": "IP address assigned to the AP interface",
        "default": "192.168.42.1",
    },
    "nanodhcp.pool_start": {
        "label": "DHCP Pool Start",
        "description": "First client IP in the DHCP pool",
        "default": "192.168.42.10",
    },
    "nanodhcp.pool_end": {
        "label": "DHCP Pool End",
        "description": "Last client IP in the DHCP pool",
        "default": "192.168.42.100",
    },
    "nanodhcp.lease_time": {
        "label": "DHCP Lease Time (s)",
        "description": "Lease duration in seconds",
        "default": "3600",
    },
    "nanodhcp.interface": {
        "label": "DHCP Interface",
        "description": "Interface nanodhcp binds to",
        "default": "wlan0",
    },
    # tinywifi-web — management panel
    "tinywifi.listen": {
        "label": "Web Panel Listen Address",
        "description": 'Address:port for tinywifi-web (e.g. "0.0.0.0:80")',
        "default": "0.0.0.0:80",
    },
    # network — S40network init script
    "network.ap_iface": {
        "label": "AP Network Interface",
        "description": "Interface that gets the static IP for AP mode",
        "default": "wlan0",
    },
    "network.ap_addr": {
        "label": "AP Static IP",
        "description": "Static IP/prefix configured on the AP interface",
        "default": "192.168.42.1",
    },
    "network.ap_prefix": {
        "label": "AP Prefix Length",
        "description": "Prefix length (subnet mask bits)",
        "default": "24",
    },
}


def _v(vals: dict[str, str], key: str) -> str:
    """Return user-set value or default."""
    schema = CONFIG_SCHEMA.get(key, {})
    return vals.get(key, schema.get("default", ""))


# ---------------------------------------------------------------------------
# File renderers — one per namespace
# ---------------------------------------------------------------------------

def _render_hostapd_conf(vals: dict[str, str]) -> str:
    return (
        "# /etc/hostapd.conf — rendered by osfabricum\n"
        f"interface={_v(vals, 'hostapd.interface')}\n"
        "driver=nl80211\n"
        f"ssid={_v(vals, 'hostapd.ssid')}\n"
        "hw_mode=g\n"
        f"channel={_v(vals, 'hostapd.channel')}\n"
        "ieee80211n=1\n"
        "wmm_enabled=1\n"
        "macaddr_acl=0\n"
        "auth_algs=1\n"
        "ignore_broadcast_ssid=0\n"
        "wpa=2\n"
        f"wpa_passphrase={_v(vals, 'hostapd.passphrase')}\n"
        "wpa_key_mgmt=WPA-PSK\n"
        "rsn_pairwise=CCMP\n"
    )


def _render_nanodhcp_conf(vals: dict[str, str]) -> str:
    return (
        "# /etc/nanodhcp/nanodhcp.conf — rendered by osfabricum\n"
        f"interface={_v(vals, 'nanodhcp.interface')}\n"
        f"server_ip={_v(vals, 'nanodhcp.server_ip')}\n"
        f"pool_start={_v(vals, 'nanodhcp.pool_start')}\n"
        f"pool_end={_v(vals, 'nanodhcp.pool_end')}\n"
        f"lease_time={_v(vals, 'nanodhcp.lease_time')}\n"
    )


def _render_web_toml(vals: dict[str, str]) -> str:
    return (
        "# /etc/tinywifi/web.toml — rendered by osfabricum\n\n"
        "[web]\n"
        f'listen = "{_v(vals, "tinywifi.listen")}"\n\n'
        "[display]\n"
        "refresh_secs = 5\n\n"
        "[paths]\n"
        'hostapd_conf  = "/etc/hostapd.conf"\n'
        'nanodhcp_conf = "/etc/nanodhcp/nanodhcp.conf"\n'
        'leases_file   = "/var/lib/nanodhcp/leases"\n\n'
        "[services]\n"
        'hostapd   = "hostapd"\n'
        'nanodhcp  = "nanodhcp"\n'
        'web       = "tinywifi-web"\n'
    )


def _render_s40_network(vals: dict[str, str]) -> str:
    iface = _v(vals, "network.ap_iface")
    addr = _v(vals, "network.ap_addr")
    prefix = _v(vals, "network.ap_prefix")
    return (
        "#!/bin/sh\n"
        "# /etc/init.d/S40network — rendered by osfabricum\n\n"
        f"AP_IFACE={iface}\n"
        f"AP_ADDR={addr}\n"
        f"AP_PREFIX={prefix}\n\n"
        "case \"$1\" in\n"
        "start)\n"
        "    ip link set lo up 2>/dev/null || true\n"
        "    ip link set \"$AP_IFACE\" up 2>/dev/null || true\n"
        "    ip addr flush dev \"$AP_IFACE\" 2>/dev/null || true\n"
        "    ip addr add \"$AP_ADDR/$AP_PREFIX\" dev \"$AP_IFACE\" 2>/dev/null || true\n"
        "    echo 1 > /proc/sys/net/ipv4/ip_forward\n"
        "    ;;\n"
        "stop)\n"
        "    ip addr flush dev \"$AP_IFACE\" 2>/dev/null || true\n"
        "    ;;\n"
        "esac\n"
    )


# Mapping: namespace prefix → (file path, renderer)
_RENDERERS: list[tuple[set[str], str, Any]] = [
    ({"hostapd"}, "etc/hostapd.conf", _render_hostapd_conf),
    ({"nanodhcp"}, "etc/nanodhcp/nanodhcp.conf", _render_nanodhcp_conf),
    ({"tinywifi"}, "etc/tinywifi/web.toml", _render_web_toml),
    ({"network"}, "etc/init.d/S40network", _render_s40_network),
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_config_values(session: Session, distribution_id: str) -> dict[str, str]:
    """Return all config key→value pairs for a distribution."""
    rows = session.scalars(
        select(DistributionConfigValue).where(
            DistributionConfigValue.distribution_id == distribution_id
        )
    ).all()
    return {r.key: r.value for r in rows if r.value is not None}


def set_config_value(
    session: Session, distribution_id: str, key: str, value: str | None
) -> DistributionConfigValue:
    """Upsert a single config value. Caller must commit."""
    from datetime import datetime, UTC  # noqa: PLC0415

    if key not in CONFIG_SCHEMA:
        raise ValueError(f"Unknown config key: {key!r}")
    row = session.scalar(
        select(DistributionConfigValue).where(
            DistributionConfigValue.distribution_id == distribution_id,
            DistributionConfigValue.key == key,
        )
    )
    if row is None:
        row = DistributionConfigValue(
            distribution_id=distribution_id,
            key=key,
            value=value,
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(row)
    else:
        row.value = value
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return row


# ---------------------------------------------------------------------------
# Compose-time renderer
# ---------------------------------------------------------------------------

def apply_distro_configs(
    stage_dir: Path,
    vals: dict[str, str],
    *,
    logs: list[str] | None = None,
) -> list[str]:
    """Write rendered config files into *stage_dir*.

    Only namespaces that have at least one key present in *vals* (or always,
    if the corresponding file already exists from an .ofpkg) are written.
    Always writes all four files so that defaults are consistently applied.

    Returns list of written relative paths.
    """
    _logs = logs if logs is not None else []
    written: list[str] = []

    for _namespaces, rel_path, renderer in _RENDERERS:
        content = renderer(vals)
        dest = stage_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        if rel_path == "etc/init.d/S40network":
            dest.chmod(0o755)
        _logs.append(f"[config] wrote {rel_path}")
        written.append(rel_path)

    return written

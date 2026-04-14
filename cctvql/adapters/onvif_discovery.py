"""
ONVIF WS-Discovery
------------------
Discovers ONVIF cameras on the local network using the WS-Discovery protocol
(UDP multicast on 239.255.255.250:3702).

No external dependencies — uses Python's built-in socket and asyncio.

Usage:
    from cctvql.adapters.onvif_discovery import discover_onvif_devices

    devices = await discover_onvif_devices(timeout=3.0)
    for d in devices:
        print(d["address"], d["types"], d["name"])
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# WS-Discovery multicast address and port (ONVIF standard)
_WSD_MULTICAST_IP = "239.255.255.250"
_WSD_PORT = 3702

# WS-Discovery Probe message template
_PROBE_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope
  xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
  xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <s:Header>
    <a:Action s:mustUnderstand="1">\
http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
    <a:MessageID>urn:uuid:{msg_id}</a:MessageID>
    <a:To s:mustUnderstand="1">\
urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
  </s:Header>
  <s:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </s:Body>
</s:Envelope>"""


class DiscoveredDevice:
    """A device found via WS-Discovery."""

    def __init__(self, address: str, types: list[str], scopes: list[str]) -> None:
        self.address = address  # Primary ONVIF endpoint URL
        self.types = types  # e.g. ["NetworkVideoTransmitter"]
        self.scopes = scopes  # e.g. ["onvif://www.onvif.org/name/SomeCam"]
        self._name: str | None = None
        self._hardware: str | None = None

    @property
    def name(self) -> str:
        """Best-effort display name extracted from scopes."""
        if self._name:
            return self._name
        for scope in self.scopes:
            m = re.search(r"onvif://www\.onvif\.org/name/([^/\s]+)", scope)
            if m:
                self._name = m.group(1).replace("%20", " ")
                return self._name
        # Fall back to the IP from the address URL
        m2 = re.search(r"://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", self.address)
        return m2.group(1) if m2 else self.address

    @property
    def hardware(self) -> str | None:
        if self._hardware:
            return self._hardware
        for scope in self.scopes:
            m = re.search(r"onvif://www\.onvif\.org/hardware/([^/\s]+)", scope)
            if m:
                self._hardware = m.group(1).replace("%20", " ")
                return self._hardware
        return None

    @property
    def host(self) -> str | None:
        """IP address extracted from the ONVIF endpoint URL."""
        m = re.search(r"://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", self.address)
        return m.group(1) if m else None

    @property
    def port(self) -> int:
        """Port extracted from the endpoint URL, defaults to 80."""
        m = re.search(r"://[^:/]+:([0-9]+)/", self.address)
        return int(m.group(1)) if m else 80

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "host": self.host,
            "port": self.port,
            "name": self.name,
            "hardware": self.hardware,
            "types": self.types,
            "scopes": self.scopes,
        }

    def __repr__(self) -> str:
        return f"<DiscoveredDevice name={self.name!r} host={self.host} address={self.address!r}>"


# ---------------------------------------------------------------------------
# Internal XML parsing helpers (no lxml/ElementTree dependency on WSDL format)
# ---------------------------------------------------------------------------


def _extract_text_between(xml: str, tag: str) -> list[str]:
    """Extract all text content between occurrences of <tag>...</tag>."""
    results = []
    pattern = re.compile(
        r"<[^/>]*" + re.escape(tag) + r"[^>]*>(.*?)</[^>]*" + re.escape(tag) + r">",
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(xml):
        content = m.group(1).strip()
        if content:
            results.append(content)
    return results


def _parse_probe_match(xml: str) -> list[DiscoveredDevice]:
    """Parse a WS-Discovery ProbeMatch response XML into DiscoveredDevice objects."""
    devices: list[DiscoveredDevice] = []

    # Each ProbeMatch block is one device
    pm_pattern = re.compile(
        r"<[^/>]*ProbeMatch[^>]*>(.*?)</[^>]*ProbeMatch>",
        re.DOTALL | re.IGNORECASE,
    )
    for pm_match in pm_pattern.finditer(xml):
        pm_xml = pm_match.group(1)

        # XAddrs — space-separated list of endpoint URLs
        xaddrs_list = _extract_text_between(pm_xml, "XAddrs")
        if not xaddrs_list:
            continue
        xaddrs = xaddrs_list[0].split()
        if not xaddrs:
            continue

        # Types
        types_raw = _extract_text_between(pm_xml, "Types")
        types = []
        for t in types_raw:
            for part in t.split():
                # strip namespace prefix e.g. "dn:NetworkVideoTransmitter"
                local = part.split(":")[-1]
                if local:
                    types.append(local)

        # Scopes
        scopes_raw = _extract_text_between(pm_xml, "Scopes")
        scopes = []
        for s in scopes_raw:
            scopes.extend(s.split())

        devices.append(DiscoveredDevice(address=xaddrs[0], types=types, scopes=scopes))

    return devices


# ---------------------------------------------------------------------------
# UDP discovery
# ---------------------------------------------------------------------------


async def discover_onvif_devices(
    timeout: float = 3.0,
    interface: str = "",
) -> list[DiscoveredDevice]:
    """
    Send a WS-Discovery Probe and collect ONVIF device responses.

    Args:
        timeout:   How many seconds to wait for responses (default: 3.0)
        interface: Local interface IP to bind to (default: "" = all interfaces)

    Returns:
        List of DiscoveredDevice objects — one per responding camera/NVR.
        Empty list if no devices found or if network access fails.
    """
    probe = _PROBE_TEMPLATE.format(msg_id=str(uuid.uuid4())).encode("utf-8")
    found: list[DiscoveredDevice] = []
    seen_addresses: set[str] = set()

    def _run_discovery() -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            sock.settimeout(timeout)
            if interface:
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(interface),
                )
            sock.sendto(probe, (_WSD_MULTICAST_IP, _WSD_PORT))

            import time

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, _ = sock.recvfrom(65535)
                    xml = data.decode("utf-8", errors="replace")
                    for device in _parse_probe_match(xml):
                        if device.address not in seen_addresses:
                            seen_addresses.add(device.address)
                            found.append(device)
                            logger.debug("Discovered ONVIF device: %s", device)
                except TimeoutError:
                    break
                except OSError:
                    break
        except OSError as exc:
            logger.warning("WS-Discovery failed (network error): %s", exc)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_discovery)

    logger.info("WS-Discovery found %d ONVIF device(s)", len(found))
    return found


async def discover_and_format(
    timeout: float = 3.0,
    interface: str = "",
) -> list[dict[str, Any]]:
    """Discover ONVIF devices and return as list of plain dicts (JSON-serialisable)."""
    devices = await discover_onvif_devices(timeout=timeout, interface=interface)
    return [d.to_dict() for d in devices]

"""BLE backend that replays captured payloads, with exact BEF conformance probes.

The payloads below are real advertisements and characteristic values recorded
from hardware on 2026-07-20, not hand-written examples. Tests that decode them
therefore check the shipped profiles against bytes the devices actually sent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from lab_ble_mcp.backend import BleBackend, BleBackendError, BleTransportError
from lab_ble_mcp.profile import Advertisement, Gatt
from lab_ble_mcp.resource import parse_resource_name


DEFAULT_MOCK_RESOURCE = "BLE::omron_2jcie/D0:ED:3E:53:EE:22"
CONFORMANCE_QUERY = "*IDN?"
CONFORMANCE_WRITE = "CONF"

# profile -> access mode -> payload exactly as captured from hardware.
CAPTURED_PAYLOADS: dict[str, dict[str, bytes]] = {
    "omron_2jcie": {
        # seq 0x3f: 27.47 degC, 63.49 %RH, 45 lx, 1003.703 hPa,
        #           56.05 dB, 0 ppb eTVOC, 400 ppm eCO2
        "advertisement": bytes.fromhex("013fbb0acd182d00b7500f00e51500009001ff"),
        # seq 0x72: 27.46 degC, 63.49 %RH, 45 lx, 1003.715 hPa,
        #           57.91 dB, 0 ppb eTVOC, 403 ppm eCO2
        "gatt": bytes.fromhex("72ba0acd182d00c3500f009f1600009301"),
    },
    "switchbot_meter": {
        # 28.3 degC, 49 %RH, battery 69 %
        "advertisement": bytes.fromhex("5400c5039c31"),
    },
}


class MockBleBackend(BleBackend):
    """Deterministic BLE backend for tests; never touches a radio."""

    backend_id = "mock-ble"

    def __init__(
        self,
        resources: Iterable[str] | None = None,
        *,
        payloads: Mapping[str, Mapping[str, bytes]] | None = None,
        cache_ttl_ms: int = 0,
        allow_conformance_probes: bool = True,
    ) -> None:
        selected = (DEFAULT_MOCK_RESOURCE,) if resources is None else tuple(resources)
        super().__init__(resources=selected, cache_ttl_ms=cache_ttl_ms)
        self._payloads = {
            profile: dict(modes)
            for profile, modes in (payloads or CAPTURED_PAYLOADS).items()
        }
        self._profile_by_address = {
            parsed.address: parsed.profile
            for parsed in (parse_resource_name(name) for name in selected)
        }
        self._allow_conformance_probes = allow_conformance_probes

    def _require_configured(self, resource_name: str) -> None:
        if self._closed:
            raise BleBackendError("backend is closed")
        parse_resource_name(resource_name)
        if resource_name not in self._resources:
            raise BleBackendError(f"resource is not configured: {resource_name!r}")

    async def query(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> str:
        if self._allow_conformance_probes and command == CONFORMANCE_QUERY:
            self._require_configured(resource_name)
            return "TECTOS,MockBleBackend,0,0.1.0"
        return await super().query(
            resource_name, command, timeout_ms, read_termination, write_termination
        )

    async def write(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> None:
        """Accept only the contract's write probe; reject every real write.

        The probe exists so the frozen BEF signature can be exercised. It is
        deliberately the single command that does not raise, which keeps the
        read-only guarantee visible in tests.
        """
        if self._allow_conformance_probes and command == CONFORMANCE_WRITE:
            self._require_configured(resource_name)
            return None
        return await super().write(
            resource_name, command, timeout_ms, read_termination, write_termination
        )

    def _captured(self, address: str, mode: str) -> bytes:
        profile = self._profile_by_address.get(address)
        if profile is None:
            raise BleTransportError(f"no mock payload registered for {address}")
        try:
            return self._payloads[profile][mode]
        except KeyError as exc:
            raise BleTransportError(
                f"no captured {mode} payload for profile {profile!r}"
            ) from exc

    async def _read_advertisement(
        self, address: str, source: Advertisement, timeout_ms: int
    ) -> bytes:
        del source, timeout_ms
        return self._captured(address, "advertisement")

    async def _read_gatt(self, address: str, source: Gatt, timeout_ms: int) -> bytes:
        del source, timeout_ms
        return self._captured(address, "gatt")


__all__ = [
    "CAPTURED_PAYLOADS",
    "CONFORMANCE_QUERY",
    "CONFORMANCE_WRITE",
    "DEFAULT_MOCK_RESOURCE",
    "MockBleBackend",
]

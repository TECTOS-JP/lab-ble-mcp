"""BLE backend that replays captured payloads, with exact BEF conformance probes.

The payloads below are real advertisements and characteristic values recorded
from hardware on 2026-07-20, not hand-written examples. Tests that decode them
therefore check the shipped profiles against bytes the devices actually sent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from lab_ble_mcp.backend import BleBackend, BleBackendError, BleTransportError
from lab_ble_mcp.bitalino_frame import decode_frame, encode_frame, frame_size
from lab_ble_mcp.profile import Advertisement, Gatt, Stream
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

# Sixteen consecutive six-channel frames streamed by a BiTalino (r)evolution over
# RFCOMM at 100 Hz on 2026-07-24 (unit 20:16:12:22:46:14). Sequence numbers run
# 0..15 with no gap and every CRC verifies. A1 was floating and shows real ADC
# noise around 427; the remaining channels had nothing wired to them. The BLE
# unit streams this same frame format, so replaying these exercises both
# transports' decoding.
CAPTURED_BITALINO_FRAMES: bytes = bytes.fromhex(
    "0000000000acc6070000000000b0c6190000000000acc621"
    "0000000001a8c6300000000000acc64b0000000000b0c655"
    "0000000000acc66d0000000000a8c6760000000000acc68c"
    "0000000001b0c6980000000000acc6aa0000000000acc6b9"
    "0000000000acc6c00000000000b0c6de0000000000acc6e6"
    "0000000000acc6f5"
)


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
        artifact_dir: str | None = None,
        max_samples: int | None = None,
    ) -> None:
        selected = (DEFAULT_MOCK_RESOURCE,) if resources is None else tuple(resources)
        super().__init__(
            resources=selected,
            cache_ttl_ms=cache_ttl_ms,
            artifact_dir=artifact_dir,
            max_samples=max_samples,
        )
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

    async def _acquire_frames(
        self, address: str, stream: Stream, samples: int, rate_hz: int, timeout_ms: int
    ) -> bytes:
        """Replay frames captured from a real board; never touch a radio.

        For the shipped six-channel BiTalino profiles this returns the bytes the
        hardware actually streamed, cycling the capture when more samples are
        asked for than were recorded. The sequence counter keeps running across
        repeats so a replayed burst stays gap-free like the original. Profiles
        the capture does not fit fall back to synthesized frames, which are
        format-correct but carry no hardware evidence.
        """
        del address, timeout_ms, rate_hz
        n_channels = len(stream.channels)
        size = frame_size(n_channels)
        captured = (
            [
                CAPTURED_BITALINO_FRAMES[i * size : (i + 1) * size]
                for i in range(len(CAPTURED_BITALINO_FRAMES) // size)
            ]
            if n_channels == 6 and len(CAPTURED_BITALINO_FRAMES) % size == 0
            else []
        )
        out = bytearray()
        for i in range(samples):
            if captured:
                frame = decode_frame(captured[i % len(captured)], n_channels)
                analog = frame.analog
                digital = frame.digital
            else:
                analog = tuple(
                    (100 * (c + 1) + i) % (1 << channel.bits)
                    for c, channel in enumerate(stream.channels)
                )
                digital = (0, 0, 0, 0)
            out.extend(encode_frame(i % 16, digital, analog))
        return bytes(out)


__all__ = [
    "CAPTURED_BITALINO_FRAMES",
    "CAPTURED_PAYLOADS",
    "CONFORMANCE_QUERY",
    "CONFORMANCE_WRITE",
    "DEFAULT_MOCK_RESOURCE",
    "MockBleBackend",
]

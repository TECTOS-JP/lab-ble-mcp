"""BLE sensor backend over bleak, with the transport isolated behind two hooks.

``bleak`` is imported lazily inside the transport hooks so that importing this
module, constructing a mock, or running the conformance kit never touches a
Bluetooth stack.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from lab_ble_mcp.bitalino_frame import (
    STOP_COMMAND,
    DecodedFrame,
    decode_frame,
    frame_size,
    start_command,
)
from lab_ble_mcp.profile import Advertisement, Gatt, Profile, Stream, load_profile
from lab_ble_mcp.resource import BleResource, parse_resource_name
from lab_ble_mcp.wire import WireCommand, parse_wire_command


DEFAULT_CACHE_TTL_MS = 10_000

# Nominal SPP baud; a Bluetooth virtual serial port ignores it, but pyserial
# requires a value to open the port.
_RFCOMM_BAUD = 115200


class BleBackendError(RuntimeError):
    """Base error for backend-level failures."""


class BleTransportError(BleBackendError):
    """A scan or connection failed, or produced no usable payload."""


class BleWriteRejected(BleBackendError):
    """A write was attempted against a read-only measurement backend."""


def _format_value(value: float) -> str:
    """Render a decoded quantity without float representation noise."""
    return f"{value:.10g}"


class BleBackend:
    """Read-only backend for BLE environment sensors.

    Reads prefer a device's advertisement over a GATT connection whenever the
    profile exposes the measurand both ways. Broadcasts cost no connection
    slot, so polling one sensor cannot lock out a phone app or another host.
    """

    backend_id = "ble"

    def __init__(
        self,
        resources: Iterable[str] | None = None,
        *,
        cache_ttl_ms: int = DEFAULT_CACHE_TTL_MS,
        artifact_dir: str | Path | None = None,
        max_samples: int | None = None,
        port_map: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(cache_ttl_ms, int) or isinstance(cache_ttl_ms, bool):
            raise TypeError("cache_ttl_ms must be an integer")
        if cache_ttl_ms < 0:
            raise ValueError("cache_ttl_ms must not be negative")
        if max_samples is not None and (
            isinstance(max_samples, bool)
            or not isinstance(max_samples, int)
            or max_samples < 1
        ):
            raise ValueError("max_samples must be a positive integer when set")
        normalized: list[str] = []
        for resource in resources or ():
            parsed = parse_resource_name(resource)
            load_profile(parsed.profile)
            if resource in normalized:
                raise ValueError(f"duplicate BLE resource: {resource!r}")
            normalized.append(resource)
        self._resources = tuple(normalized)
        self._cache_ttl_s = cache_ttl_ms / 1000
        self._cache: dict[tuple[str, str], tuple[float, bytes]] = {}
        self._artifact_dir = Path(artifact_dir) if artifact_dir is not None else None
        self._max_samples = max_samples
        self._port_map = dict(port_map or {})
        self._closed = False

    async def list_resources(self) -> list[str]:
        """Return configured resources without touching a transport.

        BLE discovery would report every nearby beacon, including devices this
        backend has no profile for, so enumeration stays configuration-driven.
        """
        return list(self._resources)

    def _validate(
        self, resource_name: str, command: str
    ) -> tuple[BleResource, WireCommand]:
        if self._closed:
            raise BleBackendError("backend is closed")
        resource = parse_resource_name(resource_name)
        if resource_name not in self._resources:
            raise BleBackendError(f"resource is not configured: {resource_name!r}")
        return resource, parse_wire_command(command)

    async def query(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> str:
        del read_termination, write_termination
        resource, parsed = self._validate(resource_name, command)
        profile = load_profile(resource.profile)
        if parsed.opcode == "INFO":
            assert parsed.name is not None
            return self._info(resource, profile, parsed.name)
        if parsed.opcode == "ACQUIRE":
            assert parsed.samples is not None and parsed.rate_hz is not None
            return await self._acquire(
                resource, profile, parsed.samples, parsed.rate_hz, timeout_ms
            )
        assert parsed.name is not None
        mode, field = profile.field(parsed.name)
        payload = await self._payload(resource, profile, mode, timeout_ms)
        return _format_value(field.decode(payload))

    async def write(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> None:
        """Always reject: this backend never writes to a sensor.

        The validation above still runs so that a malformed resource or command
        fails the same way it would on a read.
        """
        del timeout_ms, read_termination, write_termination
        if self._closed:
            raise BleBackendError("backend is closed")
        parse_resource_name(resource_name)
        raise BleWriteRejected(
            "BLE sensor backend is read-only; it exposes no write commands"
        )

    @staticmethod
    def _info(resource: BleResource, profile: Profile, name: str) -> str:
        if name == "address":
            return resource.address
        if name == "profile":
            return profile.name
        if name == "measurands":
            return ",".join(sorted(profile.measurands))
        value = profile.metadata.get(name)
        if not isinstance(value, str):
            raise BleBackendError(
                f"INFO {name!r} is not available for profile {profile.name!r}"
            )
        return value

    async def _payload(
        self, resource: BleResource, profile: Profile, mode: str, timeout_ms: int
    ) -> bytes:
        source = profile.advertisement if mode == "advertisement" else profile.gatt
        assert source is not None
        key = (resource.address, mode)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self._cache_ttl_s:
            return cached[1]
        if mode == "advertisement":
            assert isinstance(source, Advertisement)
            payload = await self._read_advertisement(
                resource.address, source, timeout_ms
            )
        else:
            assert isinstance(source, Gatt)
            payload = await self._read_gatt(resource.address, source, timeout_ms)
        self._cache[key] = (time.monotonic(), payload)
        return payload

    # --- streaming acquisition (P1) --------------------------------------

    async def _acquire(
        self,
        resource: BleResource,
        profile: Profile,
        samples: int,
        rate_hz: int,
        timeout_ms: int,
    ) -> str:
        """Capture a finite stream and return a reference to its artifact.

        Like the NI-DAQ backend's ACQUIRE, a bounded burst is written to an
        on-disk artifact and only a JSON reference crosses the frozen
        ``query() -> str`` boundary, so continuous data never has to be inlined.
        """
        stream = profile.stream
        if stream is None:
            raise BleBackendError(
                f"profile {profile.name!r} is read-only; ACQUIRE needs a "
                "streaming profile"
            )
        if self._artifact_dir is None or self._max_samples is None:
            raise BleBackendError(
                "ACQUIRE requires artifact_dir and max_samples in this backend's "
                "configuration; read-only sensor profiles need neither"
            )
        if samples > self._max_samples:
            raise BleBackendError("sample count exceeds configured max_samples")
        if rate_hz not in stream.rates_hz:
            raise BleBackendError(
                f"rate {rate_hz} Hz is not supported by profile {profile.name!r}; "
                f"supported: {list(stream.rates_hz)!r}"
            )
        raw = await self._acquire_frames(
            resource.address, stream, samples, rate_hz, timeout_ms
        )
        return self._write_acquisition_artifact(
            raw, resource, profile, stream, samples, rate_hz
        )

    def _write_acquisition_artifact(
        self,
        raw: bytes,
        resource: BleResource,
        profile: Profile,
        stream: Stream,
        samples: int,
        rate_hz: int,
    ) -> str:
        import numpy as np

        assert self._artifact_dir is not None
        n_channels = len(stream.channels)
        size = frame_size(n_channels)
        if len(raw) != size * samples:
            raise BleTransportError(
                f"expected {size * samples} bytes for {samples} frames, "
                f"received {len(raw)}"
            )
        frames = [
            decode_frame(raw[i * size : (i + 1) * size], n_channels)
            for i in range(samples)
        ]
        analog = np.asarray([f.analog for f in frames], dtype=float)
        digital = np.asarray([f.digital for f in frames], dtype=int)
        sequence = np.asarray([f.sequence for f in frames], dtype=int)
        dropped = _count_sequence_gaps(frames)

        acquired_at = datetime.now(timezone.utc)
        channels = [
            {"name": c.name, "unit": c.unit, "bits": c.bits} for c in stream.channels
        ]
        meta = {
            "profile": profile.name,
            "address": resource.address,
            "transport": stream.transport,
            "channels": channels,
            "samples": samples,
            "rate_hz": rate_hz,
            "dropped_frames": dropped,
            "acquired_at": acquired_at.isoformat(),
        }
        name = (
            f"acq-{acquired_at.strftime('%Y%m%dT%H%M%S.%fZ')}-"
            f"{profile.name}-{resource.address.replace(':', '')}.npz"
        )
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self._artifact_dir / name
        np.savez_compressed(
            path,
            analog=analog,
            digital=digital,
            sequence=sequence,
            meta=np.asarray(json.dumps(meta)),
        )
        contents = path.read_bytes()
        return json.dumps(
            {
                "artifact": "v1",
                "name": name,
                "sha256": hashlib.sha256(contents).hexdigest(),
                "bytes": len(contents),
                "shape": list(analog.shape),
                "rate_hz": rate_hz,
                "channels": [c["name"] for c in channels],
                "unit": "adc",
                "dropped_frames": dropped,
            },
            separators=(",", ":"),
        )

    # --- transport hooks -------------------------------------------------
    # Both hooks import bleak lazily and are the only methods that touch a
    # radio. Mock backends override these and nothing else.

    async def _read_advertisement(
        self, address: str, source: Advertisement, timeout_ms: int
    ) -> bytes:
        """Scan until this address broadcasts a payload the profile can decode."""
        from bleak import BleakScanner

        found: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()

        def on_detection(device: Any, advertisement: Any) -> None:
            if found.done() or device.address != address:
                return
            payload = _extract_advertisement(advertisement, source)
            if payload is not None:
                found.set_result(payload)

        scanner = BleakScanner(detection_callback=on_detection)
        try:
            await scanner.start()
        except Exception as exc:  # pragma: no cover - depends on host radio
            raise BleTransportError(f"failed to start BLE scan: {exc}") from exc
        try:
            return await asyncio.wait_for(found, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError as exc:
            raise BleTransportError(
                f"no decodable advertisement from {address} within {timeout_ms} ms; "
                "broadcast intervals of several seconds may need a larger timeout_ms"
            ) from exc
        finally:
            try:
                await scanner.stop()
            except Exception:  # pragma: no cover - best effort teardown
                pass

    async def _read_gatt(self, address: str, source: Gatt, timeout_ms: int) -> bytes:
        """Connect, read one characteristic, and disconnect."""
        from bleak import BleakClient

        timeout_s = timeout_ms / 1000
        try:
            async with BleakClient(address, timeout=timeout_s) as client:
                return bytes(await client.read_gatt_char(source.characteristic))
        except asyncio.TimeoutError as exc:
            raise BleTransportError(
                f"GATT read from {address} timed out after {timeout_ms} ms"
            ) from exc
        except Exception as exc:
            raise BleTransportError(f"GATT read from {address} failed: {exc}") from exc

    # These are the only hooks that ever write to a device, and only the two
    # start/stop bytes, only to the control path a streaming profile declared.
    # Mock backends override _acquire_frames and nothing else.

    async def _acquire_frames(
        self, address: str, stream: Stream, samples: int, rate_hz: int, timeout_ms: int
    ) -> bytes:
        """Dispatch to the streaming transport the profile declared."""
        if stream.transport == "rfcomm":
            return await self._acquire_rfcomm(
                address, stream, samples, rate_hz, timeout_ms
            )
        if stream.transport == "ble":
            return await self._acquire_ble(
                address, stream, samples, rate_hz, timeout_ms
            )
        raise BleTransportError(f"unsupported stream transport: {stream.transport!r}")

    async def _acquire_rfcomm(
        self, address: str, stream: Stream, samples: int, rate_hz: int, timeout_ms: int
    ) -> bytes:
        """Acquire over a Bluetooth Classic RFCOMM serial port (BiTalino BT)."""
        port = self._port_map.get(address)
        if port is None:
            raise BleTransportError(
                f"no serial port configured for {address}; set "
                f"port_map[{address!r}] to the bound RFCOMM port (e.g. 'COM7' "
                "on Windows or '/dev/rfcomm0')"
            )
        return await asyncio.to_thread(
            self._rfcomm_session, port, stream, samples, rate_hz, timeout_ms
        )

    def _rfcomm_session(
        self, port: str, stream: Stream, samples: int, rate_hz: int, timeout_ms: int
    ) -> bytes:
        try:
            import serial  # lazy: pyserial is only needed for RFCOMM streaming
        except ImportError as exc:  # pragma: no cover - depends on host install
            raise BleTransportError(
                "pyserial is required for RFCOMM streaming; install lab-ble-mcp[rfcomm]"
            ) from exc

        n_channels = len(stream.channels)
        need = frame_size(n_channels) * samples
        deadline = time.monotonic() + max(timeout_ms / 1000, samples / rate_hz + 5.0)
        buffer = bytearray()
        try:
            connection = serial.Serial(port, _RFCOMM_BAUD, timeout=1.0)
        except Exception as exc:  # pragma: no cover - depends on host radio
            raise BleTransportError(
                f"failed to open RFCOMM port {port}: {exc}"
            ) from exc
        try:
            connection.write(start_command(rate_hz, n_channels))
            while len(buffer) < need and time.monotonic() < deadline:
                chunk = connection.read(need - len(buffer))
                if chunk:
                    buffer.extend(chunk)
        finally:
            try:
                connection.write(bytes((STOP_COMMAND,)))
            finally:
                connection.close()
        if len(buffer) < need:
            raise BleTransportError(
                f"acquired {len(buffer) // frame_size(n_channels)}/{samples} "
                "frames before timeout"
            )
        return bytes(buffer[:need])

    async def _acquire_ble(
        self, address: str, stream: Stream, samples: int, rate_hz: int, timeout_ms: int
    ) -> bytes:
        """Acquire over BLE notifications (BiTalino BLE)."""
        from bleak import BleakClient

        n_channels = len(stream.channels)
        need = frame_size(n_channels) * samples
        buffer = bytearray()
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()

        def on_frame(_characteristic: Any, data: bytearray) -> None:
            if done.done():
                return
            buffer.extend(data)
            if len(buffer) >= need:
                done.set_result(None)

        wait_s = max(timeout_ms / 1000, samples / rate_hz + 5.0)
        try:
            async with BleakClient(address, timeout=timeout_ms / 1000) as client:
                await client.start_notify(stream.frame_characteristic, on_frame)
                # The commands characteristic exposes "write" (with response),
                # not write-without-response, so acknowledged writes are required.
                await client.write_gatt_char(
                    stream.control_characteristic,
                    start_command(rate_hz, n_channels),
                    response=True,
                )
                try:
                    await asyncio.wait_for(done, timeout=wait_s)
                finally:
                    try:
                        await client.write_gatt_char(
                            stream.control_characteristic,
                            bytes((STOP_COMMAND,)),
                            response=True,
                        )
                        await client.stop_notify(stream.frame_characteristic)
                    except Exception:  # pragma: no cover - best effort teardown
                        pass
        except asyncio.TimeoutError as exc:
            raise BleTransportError(
                f"acquired {len(buffer) // frame_size(n_channels)}/{samples} "
                f"frames from {address} before timeout"
            ) from exc
        except BleTransportError:
            raise
        except Exception as exc:
            raise BleTransportError(
                f"BLE acquisition from {address} failed: {exc}"
            ) from exc
        return bytes(buffer[:need])

    def close(self) -> None:
        """Close idempotently without raising.

        Connections are opened and closed per read, so there is no socket to
        tear down here.
        """
        self._closed = True
        self._cache.clear()


def _count_sequence_gaps(frames: list[DecodedFrame]) -> int:
    """Count frames the 4-bit sequence counter shows were missed between arrivals.

    Each frame's counter should be one more than the last, modulo 16. Anything
    larger means the transport dropped frames; the difference is recorded in the
    artifact rather than silently smoothed over.
    """
    dropped = 0
    for previous, current in zip(frames, frames[1:]):
        dropped += (current.sequence - previous.sequence - 1) % 16
    return dropped


def _extract_advertisement(advertisement: Any, source: Advertisement) -> bytes | None:
    """Pull this profile's payload out of one advertisement, if present."""
    if source.manufacturer_id is not None:
        data = advertisement.manufacturer_data.get(source.manufacturer_id)
    else:
        data = advertisement.service_data.get(source.service_uuid)
    return bytes(data) if data else None


__all__ = [
    "DEFAULT_CACHE_TTL_MS",
    "BleBackend",
    "BleBackendError",
    "BleTransportError",
    "BleWriteRejected",
]

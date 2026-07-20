"""BLE sensor backend over bleak, with the transport isolated behind two hooks.

``bleak`` is imported lazily inside the transport hooks so that importing this
module, constructing a mock, or running the conformance kit never touches a
Bluetooth stack.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import time
from typing import Any

from lab_ble_mcp.profile import Advertisement, Gatt, Profile, load_profile
from lab_ble_mcp.resource import BleResource, parse_resource_name
from lab_ble_mcp.wire import WireCommand, parse_wire_command


DEFAULT_CACHE_TTL_MS = 10_000


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
    ) -> None:
        if not isinstance(cache_ttl_ms, int) or isinstance(cache_ttl_ms, bool):
            raise TypeError("cache_ttl_ms must be an integer")
        if cache_ttl_ms < 0:
            raise ValueError("cache_ttl_ms must not be negative")
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
            return self._info(resource, profile, parsed.name)
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

    def close(self) -> None:
        """Close idempotently without raising.

        Connections are opened and closed per read, so there is no socket to
        tear down here.
        """
        self._closed = True
        self._cache.clear()


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

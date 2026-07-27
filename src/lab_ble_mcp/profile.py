"""Declarative device profiles that map BLE payloads to measurands.

Adding a sensor model means adding one YAML document to ``profiles/``; no
Python change is required unless the payload needs a custom decoder. The
profile also records which access mode a model supports, because that differs
per vendor: SwitchBot broadcasts everything and refuses connections, while
OMRON both broadcasts and serves the same measurands over GATT.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
import re
from typing import Any

import yaml

from lab_ble_mcp.bitalino_frame import CHANNEL_BITS, MAX_CHANNELS
from lab_ble_mcp.codec import Field, build_field


_PROFILE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,31}\Z")
_CHANNEL_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_UUID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_STREAM_TRANSPORTS = frozenset({"rfcomm", "ble"})
_STREAM_RATES = frozenset({1, 10, 100, 1000})
# The lab-executor ecosystem vocabulary (see MetadataConfig.support_level).
# Profiles and the instrument definitions in builtin_instruments/ must agree,
# so this set is deliberately not extended with BLE-specific levels.
_SUPPORT_LEVELS = frozenset({"verified", "tested", "experimental", "draft"})


class BleProfileError(ValueError):
    """A profile document is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Advertisement:
    """Where a broadcast payload lives and how to decode it."""

    manufacturer_id: int | None
    service_uuid: str | None
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Gatt:
    """A readable characteristic and how to decode its value."""

    characteristic: str
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class StreamChannel:
    """One analog channel in an acquisition frame."""

    name: str
    unit: str
    bits: int


@dataclass(frozen=True)
class Stream:
    """A device that streams framed samples instead of a single reading.

    Unlike advertisement and GATT, a stream is *acquired*, not read: starting it
    writes bounded control bytes to the device and stops it again. That write is
    internal to an ``ACQUIRE`` and reaches only the declared control path, so the
    grammar still exposes no general write and the read-only sensor profiles keep
    their guarantee. Channels are the board's analog inputs A1..An in order.
    """

    transport: str
    channels: tuple[StreamChannel, ...]
    rates_hz: tuple[int, ...]
    control_characteristic: str | None
    frame_characteristic: str | None


@dataclass(frozen=True)
class Profile:
    """One sensor model."""

    name: str
    metadata: Mapping[str, Any]
    advertisement: Advertisement | None
    gatt: Gatt | None
    stream: Stream | None = None

    def field(self, measurand: str) -> tuple[str, Field]:
        """Resolve a measurand to its access mode and field.

        Advertisement is preferred when both modes expose the measurand: it
        needs no connection, so it neither disturbs the device nor blocks other
        centrals, and it cannot reach a writable characteristic by accident.
        """
        for mode, source in (
            ("advertisement", self.advertisement),
            ("gatt", self.gatt),
        ):
            if source is None:
                continue
            for field in source.fields:
                if field.name == measurand:
                    return mode, field
        raise BleProfileError(
            f"profile {self.name!r} does not expose measurand {measurand!r}; "
            f"available: {sorted(self.measurands)!r}"
        )

    @property
    def measurands(self) -> frozenset[str]:
        """Every measurand this profile can decode, across access modes."""
        names: set[str] = set()
        for source in (self.advertisement, self.gatt):
            if source is not None:
                names.update(field.name for field in source.fields)
        return frozenset(names)


def _build_fields(raw: Any, where: str) -> tuple[Field, ...]:
    if not isinstance(raw, Mapping) or not raw:
        raise BleProfileError(f"{where} must be a non-empty mapping of fields")
    return tuple(build_field(name, spec) for name, spec in raw.items())


def _build_advertisement(raw: Mapping[str, Any]) -> Advertisement:
    unknown = set(raw) - {"manufacturer_id", "service_uuid", "fields"}
    if unknown:
        raise BleProfileError(f"advertisement has unknown keys: {sorted(unknown)!r}")
    manufacturer_id = raw.get("manufacturer_id")
    service_uuid = raw.get("service_uuid")
    if (manufacturer_id is None) == (service_uuid is None):
        raise BleProfileError(
            "advertisement must declare exactly one of manufacturer_id or service_uuid"
        )
    if manufacturer_id is not None and (
        not isinstance(manufacturer_id, int)
        or isinstance(manufacturer_id, bool)
        or not 0 <= manufacturer_id <= 0xFFFF
    ):
        raise BleProfileError("manufacturer_id must be a 16-bit integer")
    if service_uuid is not None and (
        not isinstance(service_uuid, str) or _UUID_RE.fullmatch(service_uuid) is None
    ):
        raise BleProfileError("service_uuid must be a lowercase 128-bit UUID")
    return Advertisement(
        manufacturer_id=manufacturer_id,
        service_uuid=service_uuid,
        fields=_build_fields(raw.get("fields"), "advertisement.fields"),
    )


def _build_gatt(raw: Mapping[str, Any]) -> Gatt:
    unknown = set(raw) - {"characteristic", "fields"}
    if unknown:
        raise BleProfileError(f"gatt has unknown keys: {sorted(unknown)!r}")
    characteristic = raw.get("characteristic")
    if (
        not isinstance(characteristic, str)
        or _UUID_RE.fullmatch(characteristic) is None
    ):
        raise BleProfileError("gatt.characteristic must be a lowercase 128-bit UUID")
    return Gatt(
        characteristic=characteristic,
        fields=_build_fields(raw.get("fields"), "gatt.fields"),
    )


def _build_stream_channels(raw: Any) -> tuple[StreamChannel, ...]:
    if not isinstance(raw, list) or not raw:
        raise BleProfileError("stream.channels must be a non-empty list")
    if len(raw) > MAX_CHANNELS:
        raise BleProfileError(f"stream.channels must declare at most {MAX_CHANNELS}")
    channels: list[StreamChannel] = []
    seen: set[str] = set()
    for index, spec in enumerate(raw):
        if not isinstance(spec, Mapping):
            raise BleProfileError("each stream channel must be a mapping")
        unknown = set(spec) - {"name", "unit"}
        if unknown:
            raise BleProfileError(
                f"stream channel has unknown keys: {sorted(unknown)!r}"
            )
        cname = spec.get("name")
        if not isinstance(cname, str) or _CHANNEL_NAME_RE.fullmatch(cname) is None:
            raise BleProfileError("stream channel name must be a lowercase identifier")
        if cname in seen:
            raise BleProfileError(f"duplicate stream channel name: {cname!r}")
        seen.add(cname)
        unit = spec.get("unit")
        if not isinstance(unit, str) or not unit:
            raise BleProfileError(f"stream channel {cname!r} must declare a unit")
        channels.append(StreamChannel(name=cname, unit=unit, bits=CHANNEL_BITS[index]))
    return tuple(channels)


def _build_stream(raw: Mapping[str, Any]) -> Stream:
    unknown = set(raw) - {
        "transport",
        "channels",
        "rates_hz",
        "control_characteristic",
        "frame_characteristic",
    }
    if unknown:
        raise BleProfileError(f"stream has unknown keys: {sorted(unknown)!r}")
    transport = raw.get("transport")
    if transport not in _STREAM_TRANSPORTS:
        raise BleProfileError(
            f"stream.transport must be one of {sorted(_STREAM_TRANSPORTS)!r}"
        )
    rates = raw.get("rates_hz")
    if (
        not isinstance(rates, list)
        or not rates
        or any(rate not in _STREAM_RATES for rate in rates)
        or len(set(rates)) != len(rates)
    ):
        raise BleProfileError(
            f"stream.rates_hz must be a non-empty list of distinct rates from "
            f"{sorted(_STREAM_RATES)!r}"
        )
    control = raw.get("control_characteristic")
    frame = raw.get("frame_characteristic")
    if transport == "ble":
        for key, value in (
            ("control_characteristic", control),
            ("frame_characteristic", frame),
        ):
            if not isinstance(value, str) or _UUID_RE.fullmatch(value) is None:
                raise BleProfileError(
                    f"ble stream.{key} must be a lowercase 128-bit UUID"
                )
    elif control is not None or frame is not None:
        raise BleProfileError(
            "rfcomm stream must not declare control/frame characteristics"
        )
    return Stream(
        transport=transport,
        channels=_build_stream_channels(raw.get("channels")),
        rates_hz=tuple(rates),
        control_characteristic=control,
        frame_characteristic=frame,
    )


def build_profile(name: str, document: Any) -> Profile:
    """Validate one profile document loaded from YAML."""
    if _PROFILE_NAME_RE.fullmatch(name) is None:
        raise BleProfileError(f"profile name has an invalid shape: {name!r}")
    if not isinstance(document, Mapping):
        raise BleProfileError(f"profile {name!r} must be a mapping")
    unknown = set(document) - {"profile", "metadata", "access"}
    if unknown:
        raise BleProfileError(f"profile {name!r} has unknown keys: {sorted(unknown)!r}")
    if document.get("profile") != name:
        raise BleProfileError(
            f"profile {name!r} must declare a matching profile key, "
            f"got {document.get('profile')!r}"
        )

    metadata = document.get("metadata")
    if not isinstance(metadata, Mapping):
        raise BleProfileError(f"profile {name!r} must declare metadata")
    for key in ("manufacturer", "model", "support_level", "definition_version"):
        if not isinstance(metadata.get(key), str) or not metadata[key]:
            raise BleProfileError(f"profile {name!r} metadata must declare {key}")
    if metadata["support_level"] not in _SUPPORT_LEVELS:
        raise BleProfileError(
            f"profile {name!r} support_level must be one of {sorted(_SUPPORT_LEVELS)!r}"
        )

    access = document.get("access")
    if not isinstance(access, Mapping) or not access:
        raise BleProfileError(f"profile {name!r} must declare a non-empty access block")
    unknown = set(access) - {"advertisement", "gatt", "stream"}
    if unknown:
        raise BleProfileError(
            f"profile {name!r} access has unknown keys: {sorted(unknown)!r}"
        )

    advertisement = access.get("advertisement")
    gatt = access.get("gatt")
    stream = access.get("stream")
    if stream is not None and (advertisement is not None or gatt is not None):
        raise BleProfileError(
            f"profile {name!r} streams, so it must not also declare "
            "advertisement or gatt access"
        )
    if stream is not None and not isinstance(stream, Mapping):
        raise BleProfileError(f"profile {name!r} stream must be a mapping")
    return Profile(
        name=name,
        metadata=dict(metadata),
        advertisement=_build_advertisement(advertisement) if advertisement else None,
        gatt=_build_gatt(gatt) if gatt else None,
        stream=_build_stream(stream) if stream else None,
    )


@lru_cache(maxsize=None)
def load_profile(name: str) -> Profile:
    """Load and validate one bundled profile by name."""
    if _PROFILE_NAME_RE.fullmatch(name) is None:
        raise BleProfileError(f"profile name has an invalid shape: {name!r}")
    source = resources.files("lab_ble_mcp.profiles").joinpath(f"{name}.yaml")
    if not source.is_file():
        raise BleProfileError(
            f"unknown BLE profile: {name!r}; available: {sorted(available_profiles())!r}"
        )
    return build_profile(name, yaml.safe_load(source.read_text(encoding="utf-8")))


def available_profiles() -> frozenset[str]:
    """Names of every bundled profile document."""
    root = resources.files("lab_ble_mcp.profiles")
    return frozenset(
        entry.name[: -len(".yaml")]
        for entry in root.iterdir()
        if entry.name.endswith(".yaml")
    )


__all__ = [
    "Advertisement",
    "BleProfileError",
    "Gatt",
    "Profile",
    "Stream",
    "StreamChannel",
    "available_profiles",
    "build_profile",
    "load_profile",
]

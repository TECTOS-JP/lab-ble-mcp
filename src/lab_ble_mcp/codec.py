"""Decoders that turn raw BLE payload bytes into physical quantities.

Well-behaved vendors pack each measurand into a fixed-width little-endian
field, which a declarative profile can describe completely. Some do not:
SwitchBot splits one temperature across masked nibbles of two bytes. Rather
than growing the profile schema until it can express arbitrary bit surgery,
odd layouts name a decoder from :data:`CUSTOM_DECODERS` and keep the rest of
the schema simple.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import struct
from typing import Any


class BleCodecError(ValueError):
    """A payload does not match the layout declared by the profile."""


_STRUCT_FORMAT: dict[str, str] = {
    "u8": "<B",
    "i8": "<b",
    "u16le": "<H",
    "i16le": "<h",
    "u32le": "<I",
    "i32le": "<i",
}

_STRUCT_SIZE = {name: struct.calcsize(fmt) for name, fmt in _STRUCT_FORMAT.items()}


def _switchbot_temp_c(payload: bytes) -> float:
    """Decode SwitchBot Meter temperature from its split-nibble encoding.

    Byte 3 carries the fractional digit in its low nibble, byte 4 the integer
    part in its low seven bits, and bit 7 of byte 4 is the sign: set means a
    positive reading.
    """
    if len(payload) < 6:
        raise BleCodecError("SwitchBot service data must be at least 6 bytes")
    magnitude = (payload[4] & 0x7F) + (payload[3] & 0x0F) / 10
    return magnitude if payload[4] & 0x80 else -magnitude


CUSTOM_DECODERS: dict[str, Callable[[bytes], float]] = {
    "switchbot_temp_c": _switchbot_temp_c,
}


@dataclass(frozen=True)
class Field:
    """One decoded measurand within a payload."""

    name: str
    unit: str
    offset: int | None = None
    type: str | None = None
    mask: int | None = None
    scale: float = 1.0
    decoder: str | None = None

    @property
    def end_offset(self) -> int:
        """Smallest payload length that can supply this field."""
        if self.decoder is not None or self.offset is None or self.type is None:
            return 0
        return self.offset + _STRUCT_SIZE[self.type]

    def decode(self, payload: bytes) -> float:
        """Decode this field, rejecting payloads that are too short."""
        if self.decoder is not None:
            return CUSTOM_DECODERS[self.decoder](payload)
        assert self.offset is not None and self.type is not None
        if len(payload) < self.end_offset:
            raise BleCodecError(
                f"field {self.name!r} needs {self.end_offset} bytes, "
                f"payload has {len(payload)}"
            )
        (raw,) = struct.unpack_from(_STRUCT_FORMAT[self.type], payload, self.offset)
        if self.mask is not None:
            raw &= self.mask
        return raw * self.scale


def build_field(name: str, spec: Mapping[str, Any]) -> Field:
    """Validate one field specification from a profile document."""
    if not isinstance(spec, Mapping):
        raise BleCodecError(f"field {name!r} must be a mapping")
    unknown = set(spec) - {"offset", "type", "mask", "scale", "unit", "decoder"}
    if unknown:
        raise BleCodecError(f"field {name!r} has unknown keys: {sorted(unknown)!r}")
    unit = spec.get("unit")
    if not isinstance(unit, str) or not unit:
        raise BleCodecError(f"field {name!r} must declare a non-empty unit")

    decoder = spec.get("decoder")
    if decoder is not None:
        if decoder not in CUSTOM_DECODERS:
            raise BleCodecError(f"field {name!r} names unknown decoder {decoder!r}")
        if {"offset", "type", "mask", "scale"} & set(spec):
            raise BleCodecError(
                f"field {name!r} uses a custom decoder and must not also "
                "declare offset/type/mask/scale"
            )
        return Field(name=name, unit=unit, decoder=decoder)

    offset, type_name = spec.get("offset"), spec.get("type")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise BleCodecError(
            f"field {name!r} must declare a non-negative integer offset"
        )
    if type_name not in _STRUCT_FORMAT:
        raise BleCodecError(
            f"field {name!r} must declare a type from {sorted(_STRUCT_FORMAT)!r}"
        )
    mask = spec.get("mask")
    if mask is not None and (not isinstance(mask, int) or isinstance(mask, bool)):
        raise BleCodecError(f"field {name!r} mask must be an integer")
    scale = spec.get("scale", 1.0)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise BleCodecError(f"field {name!r} scale must be a number")
    return Field(
        name=name,
        unit=unit,
        offset=offset,
        type=type_name,
        mask=mask,
        scale=float(scale),
    )


__all__ = ["BleCodecError", "CUSTOM_DECODERS", "Field", "build_field"]

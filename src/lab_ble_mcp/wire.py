"""Fail-closed parser for the BLE backend's command language.

The language exposes no general write opcode. Sensors expose writable GATT
characteristics that change alarm thresholds or start a firmware update (OMRON
2JCIE-BU01 carries a Nordic buttonless DFU characteristic), and a mis-addressed
write there can leave hardware unusable. Read commands therefore cannot express
a write at all rather than relying on a runtime allowlist.

``ACQUIRE`` is not an exception to that rule. It is a *read*: it returns a
reference to a captured stream, and the only bytes it ever writes are the
board's own bounded start/stop control bytes, sent by the backend to a profile
that has explicitly declared a streaming transport. A caller still cannot name a
characteristic or a value to write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_UINT_RE = re.compile(r"[1-9][0-9]{0,8}\Z")

_ARITY: dict[str, int] = {"READ": 2, "INFO": 2}


class BleWireError(ValueError):
    """A command is malformed or uses an unsupported operation."""


@dataclass(frozen=True)
class WireCommand:
    """Validated BLE read operation."""

    opcode: Literal["READ", "INFO", "ACQUIRE"]
    name: str | None = None
    samples: int | None = None
    rate_hz: int | None = None

    @property
    def is_read(self) -> bool:
        """Every command in this language reads; nothing is ever written."""
        return True


def _parse_acquire(parts: list[str]) -> WireCommand:
    """Parse ``ACQUIRE <samples> @<rate>`` for a streaming profile.

    Channels are fixed by the profile, so the command carries only how many
    samples to capture and at what rate. Both are validated syntactically here;
    the backend enforces the configured sample ceiling and the profile's
    supported rates.
    """
    if len(parts) != 3:
        raise BleWireError("ACQUIRE requires <samples> and @<rate>")
    if _UINT_RE.fullmatch(parts[1]) is None:
        raise BleWireError("ACQUIRE sample count must be a positive integer")
    rate = parts[2]
    if not rate.startswith("@") or _UINT_RE.fullmatch(rate[1:]) is None:
        raise BleWireError("ACQUIRE rate must be written as @<positive integer>")
    return WireCommand(opcode="ACQUIRE", samples=int(parts[1]), rate_hz=int(rate[1:]))


def parse_wire_command(command: str) -> WireCommand:
    """Parse one exact command without normalization or permissive fallback."""
    if not isinstance(command, str):
        raise BleWireError("BLE command must be a string")
    if not command or command != command.strip() or any(c in command for c in "\r\n\t"):
        raise BleWireError("BLE command must be one line without outer whitespace")
    parts = command.split(" ")
    if "" in parts:
        raise BleWireError("BLE command tokens must use single spaces")
    opcode = parts[0]
    if opcode == "ACQUIRE":
        return _parse_acquire(parts)
    expected = _ARITY.get(opcode)
    if expected is None:
        raise BleWireError(f"unknown BLE opcode: {opcode!r}")
    if len(parts) != expected:
        raise BleWireError(f"{opcode} requires exactly {expected - 1} argument(s)")
    name = parts[1]
    if _NAME_RE.fullmatch(name) is None:
        raise BleWireError("BLE name must be a lowercase identifier")
    return WireCommand(opcode=opcode, name=name)  # type: ignore[arg-type]


__all__ = ["BleWireError", "WireCommand", "parse_wire_command"]

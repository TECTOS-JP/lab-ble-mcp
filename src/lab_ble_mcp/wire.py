"""Fail-closed parser for the read-only BLE sensor command language.

The language has no write opcode. These sensors expose writable GATT
characteristics that change alarm thresholds or start a firmware update
(OMRON 2JCIE-BU01 carries a Nordic buttonless DFU characteristic), and a
mis-addressed write there can leave hardware unusable. Measurement backends
have no reason to reach them, so the grammar cannot express a write at all
rather than relying on a runtime allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")

_ARITY: dict[str, int] = {"READ": 2, "INFO": 2}


class BleWireError(ValueError):
    """A command is malformed or uses an unsupported operation."""


@dataclass(frozen=True)
class WireCommand:
    """Validated BLE read operation."""

    opcode: Literal["READ", "INFO"]
    name: str

    @property
    def is_read(self) -> bool:
        """Every command in this language reads; nothing is ever written."""
        return True


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

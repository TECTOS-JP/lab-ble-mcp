"""Fail-closed parser for the example ``GET``/``SET`` wire language."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9._-]{0,63}\Z")
_VALUE_RE = re.compile(r"[\x21-\x7e]{1,256}\Z")


class EchoWireError(ValueError):
    """A command is malformed or uses an unsupported operation."""


@dataclass(frozen=True)
class WireCommand:
    """Validated Echo operation."""

    opcode: Literal["GET", "SET"]
    key: str
    value: str | None = None

    @property
    def is_read(self) -> bool:
        return self.opcode == "GET"

    @property
    def is_write(self) -> bool:
        return self.opcode == "SET"


def parse_wire_command(command: str) -> WireCommand:
    """Parse one exact command without normalization or permissive fallback."""
    if not isinstance(command, str):
        raise EchoWireError("Echo command must be a string")
    if (
        not command
        or command != command.strip()
        or any(ch in command for ch in "\r\n\t")
    ):
        raise EchoWireError("Echo command must be one line without outer whitespace")
    parts = command.split(" ")
    if "" in parts:
        raise EchoWireError("Echo command tokens must use single spaces")
    opcode = parts[0]
    expected = 2 if opcode == "GET" else 3 if opcode == "SET" else None
    if expected is None:
        raise EchoWireError(f"unknown Echo opcode: {opcode!r}")
    if len(parts) != expected:
        raise EchoWireError(f"{opcode} requires exactly {expected - 1} argument(s)")
    key = parts[1]
    if _KEY_RE.fullmatch(key) is None:
        raise EchoWireError("Echo key has an invalid shape")
    value = parts[2] if opcode == "SET" else None
    if value is not None and _VALUE_RE.fullmatch(value) is None:
        raise EchoWireError("Echo value must be 1..256 visible ASCII characters")
    return WireCommand(opcode=opcode, key=key, value=value)  # type: ignore[arg-type]


__all__ = ["EchoWireError", "WireCommand", "parse_wire_command"]

"""Strict resource-name parser for the example Echo protocol."""

from __future__ import annotations

from dataclasses import dataclass
import re


_RESOURCE_RE = re.compile(r"ECHO::(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,63})\Z")


class EchoResourceError(ValueError):
    """The resource name does not belong to the Echo protocol."""


@dataclass(frozen=True)
class EchoResource:
    """Parsed, case-sensitive ``ECHO::<name>`` resource."""

    name: str


def parse_resource_name(resource_name: str) -> EchoResource:
    """Parse an exact Echo resource name, rejecting every unknown shape."""
    if not isinstance(resource_name, str):
        raise EchoResourceError("Echo resource name must be a string")
    match = _RESOURCE_RE.fullmatch(resource_name)
    if match is None:
        raise EchoResourceError(
            "Echo resource must match ECHO::<name> using ASCII letters, digits, '.', '_', or '-'"
        )
    return EchoResource(name=match.group("name"))


__all__ = ["EchoResource", "EchoResourceError", "parse_resource_name"]

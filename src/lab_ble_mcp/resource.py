"""Strict resource-name parser for BLE sensor resources."""

from __future__ import annotations

from dataclasses import dataclass
import re


_RESOURCE_RE = re.compile(
    r"BLE::(?P<profile>[a-z0-9][a-z0-9_]{0,31})/(?P<address>[0-9A-F]{2}(?::[0-9A-F]{2}){5})\Z"
)


class BleResourceError(ValueError):
    """The resource name does not belong to the BLE protocol."""


@dataclass(frozen=True)
class BleResource:
    """Parsed ``BLE::<profile>/<ADDRESS>`` resource.

    The profile slug is part of the resource name on purpose. A BLE payload
    carries no self-describing schema, so the decoder must be chosen before any
    byte is interpreted. Binding it here keeps a mis-configured profile from
    silently decoding one vendor's layout with another vendor's field map.
    """

    profile: str
    address: str


def parse_resource_name(resource_name: str) -> BleResource:
    """Parse an exact BLE resource name, rejecting every unknown shape.

    Addresses must already be canonical: uppercase hexadecimal separated by
    colons. Case folding is deliberately not performed so that one address has
    exactly one spelling in bundles and logs.
    """
    if not isinstance(resource_name, str):
        raise BleResourceError("BLE resource name must be a string")
    match = _RESOURCE_RE.fullmatch(resource_name)
    if match is None:
        raise BleResourceError(
            "BLE resource must match BLE::<profile>/<ADDRESS> with a lowercase "
            "profile slug and an uppercase colon-separated address"
        )
    return BleResource(profile=match.group("profile"), address=match.group("address"))


__all__ = ["BleResource", "BleResourceError", "parse_resource_name"]

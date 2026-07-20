"""lab-executor backend entry-point factory."""

from __future__ import annotations

from typing import Any

from lab_executor.backends import BackendRegistration

from lab_ble_mcp.backend import DEFAULT_CACHE_TTL_MS, BleBackend


def make_backend(config: dict[str, Any] | None = None) -> BackendRegistration:
    """Construct the BLE backend from strict configuration."""
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise TypeError("ble backend config must be a mapping")
    allowed = {"resources", "cache_ttl_ms"}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"unknown ble backend config keys: {sorted(unknown)!r}")
    resources = config.get("resources", [])
    if not isinstance(resources, list) or not all(
        isinstance(resource, str) for resource in resources
    ):
        raise TypeError("ble backend resources must be list[str]")
    cache_ttl_ms = config.get("cache_ttl_ms", DEFAULT_CACHE_TTL_MS)
    if not isinstance(cache_ttl_ms, int) or isinstance(cache_ttl_ms, bool):
        raise TypeError("ble backend cache_ttl_ms must be an integer")
    return BackendRegistration(
        backend=BleBackend(resources=resources, cache_ttl_ms=cache_ttl_ms),
        prefixes=("BLE::",),
    )


__all__ = ["make_backend"]

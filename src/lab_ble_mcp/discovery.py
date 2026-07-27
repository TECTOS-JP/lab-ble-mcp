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
    allowed = {"resources", "cache_ttl_ms", "artifact_dir", "max_samples", "port_map"}
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
    artifact_dir = config.get("artifact_dir")
    if artifact_dir is not None and not isinstance(artifact_dir, str):
        raise TypeError("ble backend artifact_dir must be a string path")
    max_samples = config.get("max_samples")
    if max_samples is not None and (
        isinstance(max_samples, bool) or not isinstance(max_samples, int)
    ):
        raise TypeError("ble backend max_samples must be an integer")
    port_map = config.get("port_map", {})
    if not isinstance(port_map, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in port_map.items()
    ):
        raise TypeError("ble backend port_map must be dict[str, str]")
    return BackendRegistration(
        backend=BleBackend(
            resources=resources,
            cache_ttl_ms=cache_ttl_ms,
            artifact_dir=artifact_dir,
            max_samples=max_samples,
            port_map=port_map,
        ),
        prefixes=("BLE::",),
    )


__all__ = ["make_backend"]

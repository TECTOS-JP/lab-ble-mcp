"""lab-executor backend entry-point factory."""

from __future__ import annotations

from typing import Any

from lab_executor.backends import BackendRegistration

from lab_backend_template.backend import EchoBackend


def make_backend(config: dict[str, Any] | None = None) -> BackendRegistration:
    """Construct the Echo backend from strict configuration."""
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise TypeError("echo backend config must be a mapping")
    allowed = {"resources", "initial_values"}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"unknown echo backend config keys: {sorted(unknown)!r}")
    resources = config.get("resources", [])
    if not isinstance(resources, list) or not all(
        isinstance(resource, str) for resource in resources
    ):
        raise TypeError("echo backend resources must be list[str]")
    initial_values = config.get("initial_values")
    if initial_values is not None and not isinstance(initial_values, dict):
        raise TypeError("echo backend initial_values must be a mapping")
    return BackendRegistration(
        backend=EchoBackend(resources=resources, initial_values=initial_values),
        prefixes=("ECHO::",),
    )


__all__ = ["make_backend"]

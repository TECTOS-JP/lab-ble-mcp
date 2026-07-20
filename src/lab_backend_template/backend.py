"""Working in-memory Echo backend and transport-replacement seam."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from lab_backend_template.resource import parse_resource_name
from lab_backend_template.wire import WireCommand, parse_wire_command


class EchoBackendError(RuntimeError):
    """Base error for backend-level failures."""


class EchoKeyError(EchoBackendError):
    """A requested key has not been initialized."""


def _copy_initial_values(values: Mapping[str, str] | None) -> dict[str, str]:
    copied: dict[str, str] = {}
    for key, value in (values or {}).items():
        if not isinstance(key, str):
            raise TypeError("initial Echo keys must be strings")
        parsed = parse_wire_command(f"GET {key}")
        if not isinstance(value, str):
            raise TypeError("initial Echo values must be strings")
        # Validate value with the same grammar used by SET.
        parse_wire_command(f"SET {parsed.key} {value}")
        copied[parsed.key] = value
    return copied


class EchoBackend:
    """A complete memory transport that is safe to run after cloning.

    Replace only the state access in :meth:`query` and :meth:`write` when
    adapting the template to a physical transport. Resource and wire validation
    intentionally happen before that transport seam.
    """

    backend_id = "echo"

    def __init__(
        self,
        resources: Iterable[str] | None = None,
        *,
        initial_values: Mapping[str, str] | None = None,
    ) -> None:
        normalized: list[str] = []
        for resource in resources or ():
            parse_resource_name(resource)
            if resource in normalized:
                raise ValueError(f"duplicate Echo resource: {resource!r}")
            normalized.append(resource)
        seed = _copy_initial_values(initial_values)
        self._resources = tuple(normalized)
        self._state = {resource: dict(seed) for resource in self._resources}
        self._closed = False

    async def list_resources(self) -> list[str]:
        """Return configured resources without touching a transport."""
        return list(self._resources)

    def _validate(self, resource_name: str, command: str, *, read: bool) -> WireCommand:
        if self._closed:
            raise EchoBackendError("backend is closed")
        parse_resource_name(resource_name)
        if resource_name not in self._state:
            raise EchoBackendError(f"resource is not configured: {resource_name!r}")
        parsed = parse_wire_command(command)
        if parsed.is_read != read:
            expected = "query" if read else "write"
            raise EchoBackendError(f"{expected} received the wrong operation")
        return parsed

    async def query(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> str:
        del timeout_ms, read_termination, write_termination
        parsed = self._validate(resource_name, command, read=True)
        if parsed.key not in self._state[resource_name]:
            raise EchoKeyError(f"Echo key is not initialized: {parsed.key!r}")
        return self._state[resource_name][parsed.key]

    async def write(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> None:
        del timeout_ms, read_termination, write_termination
        parsed = self._validate(resource_name, command, read=False)
        assert parsed.value is not None
        self._state[resource_name][parsed.key] = parsed.value

    def close(self) -> None:
        """Close idempotently without raising."""
        self._closed = True


__all__ = ["EchoBackend", "EchoBackendError", "EchoKeyError"]

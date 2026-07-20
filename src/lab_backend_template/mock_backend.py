"""In-memory Echo backend with exact BEF conformance probes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from lab_backend_template.backend import EchoBackend, EchoBackendError
from lab_backend_template.resource import parse_resource_name
from lab_backend_template.wire import parse_wire_command


DEFAULT_MOCK_RESOURCE = "ECHO::mock"
CONFORMANCE_QUERY = "*IDN?"
CONFORMANCE_WRITE = "CONF"


class MockEchoBackend(EchoBackend):
    """Deterministic Echo backend for tests; state is isolated per resource."""

    backend_id = "mock-echo"

    def __init__(
        self,
        *,
        resources: Iterable[str] | None = None,
        initial_values: Mapping[str, str] | None = None,
        allow_conformance_probes: bool = True,
    ) -> None:
        selected = (DEFAULT_MOCK_RESOURCE,) if resources is None else resources
        super().__init__(resources=selected, initial_values=initial_values)
        self._allow_conformance_probes = allow_conformance_probes

    def _require_open_resource(self, resource_name: str) -> None:
        if self._closed:
            raise EchoBackendError("backend is closed")
        parse_resource_name(resource_name)
        if resource_name not in self._state:
            raise EchoBackendError(f"resource is not configured: {resource_name!r}")

    async def query(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> str:
        self._require_open_resource(resource_name)
        if self._allow_conformance_probes and command == CONFORMANCE_QUERY:
            return "TECTOS,MockEchoBackend,0,0.1.0"
        return await super().query(
            resource_name,
            command,
            timeout_ms,
            read_termination,
            write_termination,
        )

    async def write(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> None:
        self._require_open_resource(resource_name)
        if self._allow_conformance_probes and command == CONFORMANCE_WRITE:
            return
        # Parse first to make the strict-mode probe failure explicit and fail closed.
        parse_wire_command(command)
        await super().write(
            resource_name,
            command,
            timeout_ms,
            read_termination,
            write_termination,
        )


__all__ = [
    "CONFORMANCE_QUERY",
    "CONFORMANCE_WRITE",
    "DEFAULT_MOCK_RESOURCE",
    "MockEchoBackend",
]

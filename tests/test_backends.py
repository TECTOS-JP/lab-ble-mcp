from __future__ import annotations

import inspect

import pytest

from lab_executor.backends import InstrumentBackend
from lab_executor.testing.backend_conformance import assert_backend_contract

from lab_backend_template.backend import EchoBackend, EchoBackendError, EchoKeyError
from lab_backend_template.mock_backend import DEFAULT_MOCK_RESOURCE, MockEchoBackend
from lab_backend_template.wire import EchoWireError


def test_backends_satisfy_runtime_protocol():
    assert isinstance(EchoBackend(), InstrumentBackend)
    assert isinstance(MockEchoBackend(), InstrumentBackend)


@pytest.mark.asyncio
async def test_mock_backend_passes_bef_conformance():
    backend = MockEchoBackend()
    returned = await assert_backend_contract(
        backend,
        sample_resource=DEFAULT_MOCK_RESOURCE,
    )
    assert returned is backend


@pytest.mark.asyncio
async def test_query_write_round_trip_and_path_separation():
    backend = MockEchoBackend(initial_values={"value": "1"})
    await backend.write(DEFAULT_MOCK_RESOURCE, "SET value 2")
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "GET value") == "2"
    with pytest.raises(EchoBackendError, match="wrong operation"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "SET value 3")
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "GET value") == "2"
    with pytest.raises(EchoBackendError, match="wrong operation"):
        await backend.write(DEFAULT_MOCK_RESOURCE, "GET value")
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "GET value") == "2"


@pytest.mark.asyncio
async def test_resource_state_is_isolated():
    first = "ECHO::first"
    second = "ECHO::second"
    backend = MockEchoBackend(
        resources=[first, second], initial_values={"value": "seed"}
    )
    await backend.write(first, "SET value changed")
    assert await backend.query(first, "GET value") == "changed"
    assert await backend.query(second, "GET value") == "seed"


@pytest.mark.asyncio
async def test_missing_key_and_unknown_resource_fail_closed():
    backend = MockEchoBackend()
    with pytest.raises(EchoKeyError):
        await backend.query(DEFAULT_MOCK_RESOURCE, "GET missing")
    with pytest.raises(EchoBackendError, match="not configured"):
        await backend.write("ECHO::other", "SET value 1")


@pytest.mark.asyncio
async def test_conformance_probes_are_exact_optional_and_noop():
    backend = MockEchoBackend(initial_values={"value": "9"})
    assert "MockEchoBackend" in await backend.query(DEFAULT_MOCK_RESOURCE, "*IDN?")
    assert await backend.write(DEFAULT_MOCK_RESOURCE, "CONF") is None
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "GET value") == "9"
    strict = MockEchoBackend(allow_conformance_probes=False)
    with pytest.raises(EchoWireError):
        await strict.query(DEFAULT_MOCK_RESOURCE, "*IDN?")
    with pytest.raises(EchoWireError):
        await strict.write(DEFAULT_MOCK_RESOURCE, "CONF")
    with pytest.raises(EchoWireError):
        await backend.query(DEFAULT_MOCK_RESOURCE, "*IDN? ")
    with pytest.raises(EchoWireError):
        await backend.write(DEFAULT_MOCK_RESOURCE, "CONF ")


@pytest.mark.asyncio
async def test_explicit_empty_resource_list_remains_empty():
    backend = MockEchoBackend(resources=[])
    assert await backend.list_resources() == []
    with pytest.raises(EchoBackendError, match="not configured"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "GET value")


@pytest.mark.asyncio
async def test_close_is_synchronous_idempotent_and_blocks_io():
    backend = MockEchoBackend()
    assert not inspect.iscoroutinefunction(backend.close)
    assert backend.close() is None
    assert backend.close() is None
    with pytest.raises(EchoBackendError, match="closed"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "GET value")


def test_no_separate_raw_write_api_is_exposed():
    backend = MockEchoBackend()
    for name in ("raw_write", "set_key", "set_value", "write_raw"):
        assert not hasattr(backend, name)


def test_constructor_rejects_duplicate_or_invalid_seed_values():
    with pytest.raises(ValueError, match="duplicate"):
        EchoBackend(resources=["ECHO::same", "ECHO::same"])
    with pytest.raises(EchoWireError):
        EchoBackend(resources=["ECHO::one"], initial_values={"bad/key": "1"})
    with pytest.raises(TypeError):
        EchoBackend(
            resources=["ECHO::one"],
            initial_values={"value": 1},  # type: ignore[dict-item]
        )
    with pytest.raises(TypeError):
        EchoBackend(
            resources=["ECHO::one"],
            initial_values={1: "value"},  # type: ignore[dict-item]
        )

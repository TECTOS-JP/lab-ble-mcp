from __future__ import annotations

import inspect

import pytest

from lab_executor.backends import InstrumentBackend
from lab_executor.testing.backend_conformance import assert_backend_contract

from lab_ble_mcp.backend import BleBackend, BleBackendError, BleWriteRejected
from lab_ble_mcp.mock_backend import DEFAULT_MOCK_RESOURCE, MockBleBackend
from lab_ble_mcp.profile import BleProfileError
from lab_ble_mcp.wire import BleWireError


SWITCHBOT = "BLE::switchbot_meter/D6:DF:02:E9:08:48"


def test_backends_satisfy_runtime_protocol():
    assert isinstance(BleBackend(), InstrumentBackend)
    assert isinstance(MockBleBackend(), InstrumentBackend)


@pytest.mark.asyncio
async def test_mock_backend_passes_bef_conformance():
    backend = MockBleBackend()
    returned = await assert_backend_contract(
        backend,
        sample_resource=DEFAULT_MOCK_RESOURCE,
    )
    assert returned is backend


@pytest.mark.asyncio
async def test_every_real_write_is_rejected():
    backend = MockBleBackend()
    for command in ("READ temperature", "SET temperature 20", "WRITE 1", "CONF extra"):
        with pytest.raises(BleBackendError):
            await backend.write(DEFAULT_MOCK_RESOURCE, command)


@pytest.mark.asyncio
async def test_base_backend_rejects_writes_even_for_the_conformance_probe():
    """Only the mock may accept ``CONF``; the hardware backend never writes."""
    backend = BleBackend(resources=[DEFAULT_MOCK_RESOURCE])
    with pytest.raises(BleWriteRejected):
        await backend.write(DEFAULT_MOCK_RESOURCE, "CONF")


@pytest.mark.asyncio
async def test_reads_decode_captured_payloads():
    backend = MockBleBackend(resources=[DEFAULT_MOCK_RESOURCE, SWITCHBOT])
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "READ temperature") == "27.47"
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "READ pressure") == "1003.703"
    assert await backend.query(SWITCHBOT, "READ temperature") == "28.3"
    assert await backend.query(SWITCHBOT, "READ humidity") == "49"


@pytest.mark.asyncio
async def test_info_reports_profile_metadata_without_transport():
    backend = MockBleBackend()
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "INFO model") == "2JCIE-BU01"
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "INFO manufacturer") == "OMRON"
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "INFO address") == (
        "D0:ED:3E:53:EE:22"
    )
    with pytest.raises(BleBackendError, match="not available"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "INFO nonexistent")


@pytest.mark.asyncio
async def test_unknown_measurand_and_unconfigured_resource_fail_closed():
    backend = MockBleBackend()
    with pytest.raises(BleProfileError, match="does not expose"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "READ voltage")
    with pytest.raises(BleBackendError, match="not configured"):
        await backend.query("BLE::omron_2jcie/AA:BB:CC:DD:EE:FF", "READ temperature")


@pytest.mark.asyncio
async def test_conformance_probes_are_exact_and_optional():
    backend = MockBleBackend()
    assert "MockBleBackend" in await backend.query(DEFAULT_MOCK_RESOURCE, "*IDN?")
    assert await backend.write(DEFAULT_MOCK_RESOURCE, "CONF") is None
    strict = MockBleBackend(allow_conformance_probes=False)
    with pytest.raises(BleWireError):
        await strict.query(DEFAULT_MOCK_RESOURCE, "*IDN?")
    with pytest.raises(BleWriteRejected):
        await strict.write(DEFAULT_MOCK_RESOURCE, "CONF")
    with pytest.raises(BleWireError):
        await backend.query(DEFAULT_MOCK_RESOURCE, "*IDN? ")


@pytest.mark.asyncio
async def test_explicit_empty_resource_list_remains_empty():
    backend = MockBleBackend(resources=[])
    assert await backend.list_resources() == []
    with pytest.raises(BleBackendError, match="not configured"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "READ temperature")


@pytest.mark.asyncio
async def test_close_is_synchronous_idempotent_and_blocks_io():
    backend = MockBleBackend()
    assert not inspect.iscoroutinefunction(backend.close)
    assert backend.close() is None
    assert backend.close() is None
    with pytest.raises(BleBackendError, match="closed"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "READ temperature")
    with pytest.raises(BleBackendError, match="closed"):
        await backend.write(DEFAULT_MOCK_RESOURCE, "READ temperature")


def test_no_raw_write_or_connect_api_is_exposed():
    backend = MockBleBackend()
    for name in ("raw_write", "write_gatt", "write_gatt_char", "connect", "pair"):
        assert not hasattr(backend, name)


def test_constructor_rejects_duplicates_unknown_profiles_and_bad_ttl():
    with pytest.raises(ValueError, match="duplicate"):
        BleBackend(resources=[DEFAULT_MOCK_RESOURCE, DEFAULT_MOCK_RESOURCE])
    with pytest.raises(BleProfileError, match="unknown BLE profile"):
        BleBackend(resources=["BLE::not_a_profile/D0:ED:3E:53:EE:22"])
    with pytest.raises(ValueError, match="negative"):
        BleBackend(cache_ttl_ms=-1)
    with pytest.raises(TypeError):
        BleBackend(cache_ttl_ms="1000")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cache_serves_repeat_reads_and_expires_with_zero_ttl():
    """One scan must answer every measurand; a zero TTL must not cache at all."""
    cached = MockBleBackend(cache_ttl_ms=60_000)
    calls = 0
    original = cached._read_advertisement

    async def counting(address, source, timeout_ms):
        nonlocal calls
        calls += 1
        return await original(address, source, timeout_ms)

    cached._read_advertisement = counting  # type: ignore[method-assign]
    await cached.query(DEFAULT_MOCK_RESOURCE, "READ temperature")
    await cached.query(DEFAULT_MOCK_RESOURCE, "READ humidity")
    assert calls == 1

    uncached = MockBleBackend(cache_ttl_ms=0)
    calls = 0
    original = uncached._read_advertisement
    uncached._read_advertisement = counting  # type: ignore[method-assign]
    await uncached.query(DEFAULT_MOCK_RESOURCE, "READ temperature")
    await uncached.query(DEFAULT_MOCK_RESOURCE, "READ humidity")
    assert calls == 2

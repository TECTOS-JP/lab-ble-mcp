"""End-to-end ACQUIRE tests for the BiTalino streaming profile.

The mock synthesizes CRC-correct frames, so these exercise the whole path a real
board would take — start parameters, framing, CRC, artifact — without a radio.
They also pin the guarantees that keep the read-only sensors safe: ACQUIRE is
rejected for a non-streaming profile, and it refuses to run without an artifact
directory and a sample ceiling.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from lab_ble_mcp.backend import (
    BleBackend,
    BleBackendError,
    BleTransportError,
    BleWriteRejected,
)
from lab_ble_mcp.bitalino_frame import decode_frame, encode_frame, frame_size
from lab_ble_mcp.mock_backend import CAPTURED_BITALINO_FRAMES, MockBleBackend
from lab_ble_mcp.profile import load_profile

BITALINO = "BLE::bitalino_bt/AA:BB:CC:DD:EE:FF"
OMRON = "BLE::omron_2jcie/D0:ED:3E:53:EE:22"


def _streaming_backend(tmp_path, *, max_samples: int = 5000) -> MockBleBackend:
    return MockBleBackend(
        resources=[BITALINO], artifact_dir=str(tmp_path), max_samples=max_samples
    )


@pytest.mark.asyncio
async def test_acquire_writes_artifact_and_returns_reference(tmp_path):
    backend = _streaming_backend(tmp_path)
    reference = json.loads(await backend.query(BITALINO, "ACQUIRE 100 @100"))

    assert reference["artifact"] == "v1"
    assert reference["shape"] == [100, 6]
    assert reference["rate_hz"] == 100
    assert reference["channels"] == ["a1", "a2", "a3", "a4", "a5", "a6"]
    assert reference["unit"] == "adc"
    assert reference["dropped_frames"] == 0

    path = tmp_path / reference["name"]
    assert path.is_file()
    with np.load(path, allow_pickle=False) as data:
        analog = data["analog"]
        sequence = data["sequence"]
        meta = json.loads(str(data["meta"]))

    assert analog.shape == (100, 6)
    # The mock replays frames captured from hardware: A1 was floating and shows
    # real ADC noise near 427; nothing was wired to the other channels.
    assert 420 <= analog[:, 0].min() <= analog[:, 0].max() <= 435
    assert analog[:, 2:].max() == 0
    assert sequence.tolist() == [i % 16 for i in range(100)]
    assert meta["profile"] == "bitalino_bt"
    assert meta["rate_hz"] == 100
    assert meta["channels"][4] == {"name": "a5", "unit": "adc", "bits": 6}


@pytest.mark.asyncio
async def test_acquire_is_rejected_for_a_read_only_sensor(tmp_path):
    backend = MockBleBackend(
        resources=[OMRON], artifact_dir=str(tmp_path), max_samples=5000
    )
    with pytest.raises(BleBackendError, match="read-only"):
        await backend.query(OMRON, "ACQUIRE 100 @100")


@pytest.mark.asyncio
async def test_acquire_requires_artifact_configuration():
    backend = MockBleBackend(resources=[BITALINO])  # no artifact_dir / max_samples
    with pytest.raises(BleBackendError, match="artifact_dir and max_samples"):
        await backend.query(BITALINO, "ACQUIRE 100 @100")


@pytest.mark.asyncio
async def test_acquire_enforces_the_sample_ceiling(tmp_path):
    backend = _streaming_backend(tmp_path, max_samples=50)
    with pytest.raises(BleBackendError, match="exceeds configured max_samples"):
        await backend.query(BITALINO, "ACQUIRE 100 @100")


@pytest.mark.asyncio
async def test_acquire_rejects_a_rate_the_profile_does_not_support(tmp_path):
    backend = _streaming_backend(tmp_path)
    with pytest.raises(BleBackendError, match="not supported"):
        await backend.query(BITALINO, "ACQUIRE 100 @250")


@pytest.mark.asyncio
async def test_streaming_profile_still_rejects_every_write(tmp_path):
    backend = _streaming_backend(tmp_path)
    with pytest.raises(BleWriteRejected):
        await backend.write(BITALINO, "ACQUIRE 100 @100")


def test_captured_hardware_frames_decode_cleanly():
    """Every frame the board actually streamed must verify and run in sequence.

    This is the hardware evidence behind the BiTalino profiles: bytes recorded
    from a real unit on 2026-07-24, not values written by hand. A CRC error or a
    sequence gap here would mean the decoder disagrees with the device.
    """
    size = frame_size(6)
    assert len(CAPTURED_BITALINO_FRAMES) % size == 0
    count = len(CAPTURED_BITALINO_FRAMES) // size
    assert count == 16

    frames = [
        decode_frame(CAPTURED_BITALINO_FRAMES[i * size : (i + 1) * size], 6)
        for i in range(count)
    ]
    # decode_frame raises on a bad CRC, so reaching here proves all 16 verified.
    assert [f.sequence for f in frames] == list(range(16))
    a1 = [f.analog[0] for f in frames]
    assert 420 <= min(a1) <= max(a1) <= 435  # floating input, real ADC noise
    assert len(set(a1)) > 1  # genuine noise, not a constant stuck value
    assert all(f.analog[2:] == (0, 0, 0, 0) for f in frames)


class _FlakySerial:
    """Stand-in for pyserial that refuses the first ``failures`` opens."""

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.opens = 0

    def Serial(self, port, baud, timeout):
        self.opens += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise OSError(22, "semaphore timeout")
        return object()


def test_rfcomm_open_retries_while_the_previous_link_releases(monkeypatch):
    """A reopen right after a session must not fail the acquisition.

    Observed on hardware: an open issued immediately after a completed capture
    fails with a semaphore timeout and succeeds moments later. Retrying the open
    is safe because no start byte has reached the board yet.
    """
    monkeypatch.setattr("lab_ble_mcp.backend.time.sleep", lambda _s: None)
    flaky = _FlakySerial(failures=2)
    assert BleBackend._open_rfcomm(flaky, "COM5") is not None
    assert flaky.opens == 3


def test_rfcomm_open_gives_up_with_a_diagnostic(monkeypatch):
    monkeypatch.setattr("lab_ble_mcp.backend.time.sleep", lambda _s: None)
    flaky = _FlakySerial(failures=99)
    with pytest.raises(BleTransportError, match="after 3 attempts"):
        BleBackend._open_rfcomm(flaky, "COM5")


@pytest.mark.asyncio
async def test_dropped_frames_are_reported_not_smoothed(tmp_path):
    backend = _streaming_backend(tmp_path)
    load_profile("bitalino_bt")  # ensure the profile is loadable
    # Sequence 0, 2, 3: the counter skips 1, so one frame was dropped.
    stream_bytes = b"".join(
        encode_frame(seq, (0, 0, 0, 0), (1, 2, 3, 4, 5, 6)) for seq in (0, 2, 3)
    )

    async def fake_acquire(address, stream, samples, rate_hz, timeout_ms):
        return stream_bytes

    backend._acquire_frames = fake_acquire  # type: ignore[method-assign]
    reference = json.loads(await backend.query(BITALINO, "ACQUIRE 3 @100"))
    assert reference["dropped_frames"] == 1

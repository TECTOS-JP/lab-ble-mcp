"""Tests for the BiTalino frame codec.

Until a board has streamed real frames, these tests pin the wire format against
its documented definition: exact frame sizes, the two start bytes computed by
hand, CRC rejection, and a full encode/decode round-trip for every channel
count. ``encode_frame`` is the strict inverse of ``decode_frame`` including the
CRC, so a round-trip that preserves every ADC count proves the bit surgery is
self-consistent across all six channels.
"""

from __future__ import annotations

import pytest

from lab_ble_mcp.bitalino_frame import (
    STOP_COMMAND,
    BitalinoFrameError,
    decode_frame,
    encode_frame,
    frame_size,
    rate_code,
    start_command,
)


@pytest.mark.parametrize(
    "n_channels, expected",
    [(1, 3), (2, 4), (3, 6), (4, 7), (5, 8), (6, 8)],
)
def test_frame_size_matches_specification(n_channels: int, expected: int) -> None:
    assert frame_size(n_channels) == expected


@pytest.mark.parametrize("rate_hz, code", [(1, 0), (10, 1), (100, 2), (1000, 3)])
def test_rate_code(rate_hz: int, code: int) -> None:
    assert rate_code(rate_hz) == code


@pytest.mark.parametrize("rate_hz", [0, 2, 50, 500, 2000, -1])
def test_rate_code_rejects_unsupported(rate_hz: int) -> None:
    with pytest.raises(BitalinoFrameError):
        rate_code(rate_hz)


def test_start_command_bytes_are_computed_by_hand() -> None:
    # 1000 Hz -> rate code 3 -> (3 << 6) | 0x03 = 0xC3.
    # One channel (A1) -> 0x01 | (1 << 2) = 0x05.
    assert start_command(1000, 1) == bytes((0xC3, 0x05))
    # 100 Hz -> code 2 -> (2 << 6) | 0x03 = 0x83.
    # Six channels -> 0x01 | 0b111111 << 2 = 0x01 | 0xFC = 0xFD.
    assert start_command(100, 6) == bytes((0x83, 0xFD))
    # 1 Hz -> code 0 -> 0x03. Channels A1..A2 -> 0x01 | 0x04 | 0x08 = 0x0D.
    assert start_command(1, 2) == bytes((0x03, 0x0D))


def test_stop_command_is_idle() -> None:
    assert STOP_COMMAND == 0x00


@pytest.mark.parametrize("n_channels", [1, 2, 3, 4, 5, 6])
def test_encode_decode_round_trip(n_channels: int) -> None:
    ten_bit = [0, 1, 512, 1000, 1023]
    six_bit = [0, 1, 31, 63]
    for seq in (0, 7, 15):
        for digital in ((0, 0, 0, 0), (1, 0, 1, 0), (1, 1, 1, 1)):
            analog = tuple(
                (ten_bit if c < 4 else six_bit)[c % 4 % len(six_bit)]
                for c in range(n_channels)
            )
            frame = encode_frame(seq, digital, analog)
            assert len(frame) == frame_size(n_channels)
            decoded = decode_frame(frame, n_channels)
            assert decoded.sequence == seq
            assert decoded.digital == digital
            assert decoded.analog == analog


def test_full_scale_values_survive_round_trip() -> None:
    frame = encode_frame(15, (1, 1, 1, 1), (1023, 1023, 1023, 1023, 63, 63))
    decoded = decode_frame(frame, 6)
    assert decoded.analog == (1023, 1023, 1023, 1023, 63, 63)
    assert decoded.sequence == 15
    assert decoded.digital == (1, 1, 1, 1)


def test_decode_rejects_wrong_length() -> None:
    frame = encode_frame(0, (0, 0, 0, 0), (100,))
    with pytest.raises(BitalinoFrameError, match="must be 3 bytes"):
        decode_frame(frame + b"\x00", 1)


def test_decode_rejects_corrupted_crc() -> None:
    frame = bytearray(encode_frame(3, (0, 0, 0, 0), (123, 456)))
    frame[-1] ^= 0x01  # flip one CRC bit
    with pytest.raises(BitalinoFrameError, match="CRC"):
        decode_frame(bytes(frame), 2)


def test_decode_detects_a_flipped_payload_bit() -> None:
    frame = bytearray(encode_frame(3, (0, 0, 0, 0), (300, 700, 200, 900, 20, 40)))
    frame[0] ^= 0x08  # corrupt an analog bit; CRC must catch it
    with pytest.raises(BitalinoFrameError, match="CRC"):
        decode_frame(bytes(frame), 6)


@pytest.mark.parametrize("n_channels", [0, 7, -1])
def test_channel_bounds(n_channels: int) -> None:
    with pytest.raises(BitalinoFrameError):
        frame_size(n_channels)

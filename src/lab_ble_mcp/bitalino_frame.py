"""Wire-protocol framing for BiTalino (r)evolution acquisition streams.

This is the one place in the package that understands a device whose payload is
a *stream* of frames rather than a single self-contained reading. It stays a
pure module: it turns sampling parameters into the two start bytes, turns raw
frame bytes back into ADC counts, and never touches a radio, a socket, or the
filesystem. The transport that actually writes the start bytes and reads the
frames lives behind a backend hook; this module only says what those bytes mean.

The layout is the documented BiTalino frame (PLUX ``revolution-python-api``).
For ``n`` enabled analog channels (channels A1..An, packed in order) the frame
is::

    ceil((12 + 10*n) / 8) bytes      for n <= 4
    ceil((52 + 6*(n-4)) / 8) bytes   for n  > 4

The trailing byte carries the 4-bit sequence number (high nibble) and a 4-bit
CRC (low nibble); the next nibble holds four digital lines; the analog channels
are bit-packed toward the front of the frame, 10 bits each for A1..A4 and 6 bits
each for A5..A6. The per-channel bit surgery is not a clean contiguous packing,
so each channel names its own extraction indexed from the end of the frame,
exactly as the wire format defines it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class BitalinoFrameError(ValueError):
    """A frame is the wrong length or fails its CRC check."""


# Sampling rates the board accepts, mapped to the 2-bit code the start command
# carries in its top two bits. Nothing else is a legal rate.
_RATE_CODES: dict[int, int] = {1: 0, 10: 1, 100: 2, 1000: 3}

#: Byte that returns the board to idle and ends a live acquisition.
STOP_COMMAND = 0x00

MIN_CHANNELS = 1
MAX_CHANNELS = 6

# Each analog channel decoded from the tail of the frame. The expressions are
# fixed regardless of how many channels are enabled: A1 always sits in the two
# bytes before the digital/seq/crc tail, A2 in the next, and so on toward the
# front. Channels A1..A4 are 10-bit; A5..A6 are 6-bit.
_CHANNEL_DECODERS: tuple[Callable[[list[int]], int], ...] = (
    lambda d: ((d[-2] & 0x0F) << 6) | (d[-3] >> 2),  # A1 (10-bit)
    lambda d: ((d[-3] & 0x03) << 8) | d[-4],  # A2 (10-bit)
    lambda d: (d[-5] << 2) | (d[-6] >> 6),  # A3 (10-bit)
    lambda d: ((d[-6] & 0x3F) << 4) | (d[-7] >> 4),  # A4 (10-bit)
    lambda d: ((d[-7] & 0x0F) << 2) | (d[-8] >> 6),  # A5 (6-bit)
    lambda d: d[-8] & 0x3F,  # A6 (6-bit)
)

CHANNEL_BITS: tuple[int, ...] = (10, 10, 10, 10, 6, 6)


@dataclass(frozen=True)
class DecodedFrame:
    """One acquisition frame after CRC has been verified."""

    sequence: int
    digital: tuple[int, int, int, int]
    analog: tuple[int, ...]


def rate_code(rate_hz: int) -> int:
    """Return the 2-bit sampling-rate code, rejecting unsupported rates."""
    if isinstance(rate_hz, bool) or not isinstance(rate_hz, int):
        raise BitalinoFrameError("sampling rate must be an integer")
    code = _RATE_CODES.get(rate_hz)
    if code is None:
        raise BitalinoFrameError(
            f"unsupported sampling rate {rate_hz!r}; supported: "
            f"{sorted(_RATE_CODES)!r} Hz"
        )
    return code


def _check_channels(n_channels: int) -> None:
    if isinstance(n_channels, bool) or not isinstance(n_channels, int):
        raise BitalinoFrameError("channel count must be an integer")
    if not MIN_CHANNELS <= n_channels <= MAX_CHANNELS:
        raise BitalinoFrameError(
            f"channel count must be {MIN_CHANNELS}..{MAX_CHANNELS}, got {n_channels}"
        )


def start_command(rate_hz: int, n_channels: int) -> bytes:
    """Build the two start bytes: sampling rate, then the channel mask.

    Channels A1..An are enabled in order, matching how :func:`frame_size` and
    the decoders lay out the frame. The first byte's top two bits are the rate
    code with the live-mode marker ``0x03``; the second byte sets bit ``2 + c``
    for each enabled channel ``c`` plus the live-mode bit ``0x01``.
    """
    _check_channels(n_channels)
    rate_byte = (rate_code(rate_hz) << 6) | 0x03
    channel_byte = 0x01
    for channel in range(n_channels):
        channel_byte |= 1 << (2 + channel)
    return bytes((rate_byte, channel_byte))


def frame_size(n_channels: int) -> int:
    """Bytes per frame for ``n_channels`` enabled analog channels."""
    _check_channels(n_channels)
    if n_channels <= 4:
        bits = 12 + 10 * n_channels
    else:
        bits = 52 + 6 * (n_channels - 4)
    return -(-bits // 8)  # ceil division


def _crc4(frame: list[int]) -> int:
    """Compute the BiTalino CRC-4 over a frame whose CRC nibble is zeroed.

    Polynomial x**4 + x + 1: shift left, fold in ``0x03`` whenever bit 4 is set,
    then mix in each bit from the most significant downward.
    """
    remainder = 0
    for byte in frame:
        for bit in range(7, -1, -1):
            remainder <<= 1
            if remainder & 0x10:
                remainder ^= 0x03
            remainder ^= (byte >> bit) & 0x01
    return remainder & 0x0F


def decode_frame(frame: bytes, n_channels: int) -> DecodedFrame:
    """Decode and CRC-check one frame into a sequence number and ADC counts."""
    _check_channels(n_channels)
    expected = frame_size(n_channels)
    if len(frame) != expected:
        raise BitalinoFrameError(
            f"frame for {n_channels} channel(s) must be {expected} bytes, "
            f"got {len(frame)}"
        )
    data = list(frame)
    received_crc = data[-1] & 0x0F
    data[-1] &= 0xF0  # blank the CRC nibble before recomputing over the frame
    if _crc4(data) != received_crc:
        raise BitalinoFrameError("frame CRC check failed")

    sequence = frame[-1] >> 4
    digital = (
        (frame[-2] >> 7) & 0x01,
        (frame[-2] >> 6) & 0x01,
        (frame[-2] >> 5) & 0x01,
        (frame[-2] >> 4) & 0x01,
    )
    analog = tuple(_CHANNEL_DECODERS[c](data) for c in range(n_channels))
    return DecodedFrame(sequence=sequence, digital=digital, analog=analog)


def encode_frame(
    sequence: int, digital: tuple[int, int, int, int], analog: tuple[int, ...]
) -> bytes:
    """Build a valid frame from ADC counts, for tests and the mock backend.

    This is the exact inverse of :func:`decode_frame`, including a correct CRC,
    so a synthesized stream is indistinguishable on the wire from a real one.
    Real captured frames are always preferred once hardware is available.
    """
    n_channels = len(analog)
    _check_channels(n_channels)
    size = frame_size(n_channels)
    data = [0] * size
    data[-1] = (sequence & 0x0F) << 4
    data[-2] = (
        ((digital[0] & 0x01) << 7)
        | ((digital[1] & 0x01) << 6)
        | ((digital[2] & 0x01) << 5)
        | ((digital[3] & 0x01) << 4)
    )
    if n_channels >= 1:
        a = analog[0] & 0x3FF
        data[-2] |= a >> 6
        data[-3] |= (a & 0x3F) << 2
    if n_channels >= 2:
        a = analog[1] & 0x3FF
        data[-3] |= a >> 8
        data[-4] |= a & 0xFF
    if n_channels >= 3:
        a = analog[2] & 0x3FF
        data[-5] |= a >> 2
        data[-6] |= (a & 0x03) << 6
    if n_channels >= 4:
        a = analog[3] & 0x3FF
        data[-6] |= a >> 4
        data[-7] |= (a & 0x0F) << 4
    if n_channels >= 5:
        a = analog[4] & 0x3F
        data[-7] |= a >> 2
        data[-8] |= (a & 0x03) << 6
    if n_channels >= 6:
        data[-8] |= analog[5] & 0x3F
    data[-1] |= _crc4(data)
    return bytes(data)


__all__ = [
    "CHANNEL_BITS",
    "MAX_CHANNELS",
    "MIN_CHANNELS",
    "STOP_COMMAND",
    "BitalinoFrameError",
    "DecodedFrame",
    "decode_frame",
    "encode_frame",
    "frame_size",
    "rate_code",
    "start_command",
]

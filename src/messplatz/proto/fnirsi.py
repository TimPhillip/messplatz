"""
FNIRSI BLE protocol (reverse engineered from the TMP-600 app traffic).

Frame format (both directions)::

    AA 55 | 10 | dir | ... seq:2 LE ... | CRC16

dir: 0x20 = command, 0x00 = poll/keepalive, 0x80/0xA0 = meter -> app.
CRC is CRC-16/MODBUS over all bytes after AA 55, appended high byte first.
"""
import struct
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Iterator, List, Optional

from messplatz.com.base import Transport

MAGIC = b"\xaa\x55"

# Start handshake captured from the official app; replaying it starts streaming.
HANDSHAKE = [
    bytes.fromhex("aa551020020001000a00110006464e49525349464f"),  # seq 1: "FNIRSI" hello
    bytes.fromhex("aa551020020002000c0015000000160000100600008c0f"),  # seq 2: config
    bytes.fromhex("aa55102002000300101001000010020000100800001003000009b5"),  # seq 3: config
]

# Measurement field layout:
# <marker> <function:2> <range_setting:1> <active_range:1> <float32 BE:4> <trailer:2>
MEAS_MARKER = bytes.fromhex("1002000a")
OL_RAW = 0x7F7FFFFF  # float max -> "OL" on the display


class Function(IntEnum):
    DC_VOLTAGE = 0x01
    AC_VOLTAGE = 0x02
    ACDC_VOLTAGE = 0x26
    DC_CURRENT = 0x05
    AC_CURRENT = 0x06
    ACDC_CURRENT = 0x27
    RESISTANCE = 0x03
    RESISTANCE_ONLINE = 0x21
    CONTINUITY = 0x23
    CAPACITANCE = 0x04
    DIODE = 0x22
    FREQUENCY = 0x24
    TEMPERATURE = 0x25


class Range(IntEnum):
    """Range setting; manual ranges are plain indices 0..5."""
    AUTO = 0x07
    AUTO_PLUS = 0x08


# active range index -> displayed unit; the float is the displayed number
_VOLT = {0: "mV", 1: "V", 2: "V", 3: "V", 4: "V"}             # 600mV/6/60/600/1000V (verified)
_AMP = {0: "uA", 1: "uA", 2: "mA", 3: "mA", 4: "A", 5: "A"}   # 600u/6000u/60m/600m/6/10A (range 0 verified)
_OHM = {0: "ohm", 1: "kohm", 2: "kohm", 3: "kohm", 4: "Mohm", 5: "Mohm"}  # guessed
RANGE_UNIT: Dict[int, Dict[int, str]] = {
    Function.DC_VOLTAGE: _VOLT, Function.AC_VOLTAGE: _VOLT, Function.ACDC_VOLTAGE: _VOLT,
    Function.DC_CURRENT: _AMP, Function.AC_CURRENT: _AMP, Function.ACDC_CURRENT: _AMP,
    Function.RESISTANCE: _OHM, Function.RESISTANCE_ONLINE: _OHM,
    Function.CAPACITANCE: {0: "nF", 1: "nF", 2: "uF", 3: "uF", 4: "uF", 5: "mF"},  # guessed
    Function.FREQUENCY: {0: "Hz", 1: "Hz", 2: "kHz", 3: "kHz", 4: "MHz", 5: "MHz"},  # guessed
}
BASE_UNIT = {Function.CONTINUITY: "ohm", Function.DIODE: "V", Function.TEMPERATURE: "degC"}


@dataclass
class Measurement:
    """One reading; value is None when the display shows OL."""
    value: Optional[float]
    unit: str
    function: Optional[Function]
    range_setting: int
    active_range: int


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS (poly 0x8005, init 0xFFFF, reflected)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(body: bytes) -> bytes:
    """Wrap a body (everything after AA 55) with magic and CRC."""
    crc = crc16_modbus(body)
    return MAGIC + body + bytes([crc >> 8, crc & 0xFF])


def check_frame(frame: bytes) -> bool:
    """True if the frame starts with AA 55 and its CRC matches."""
    if len(frame) < 4 or frame[:2] != MAGIC:
        return False
    return crc16_modbus(frame[2:-2]) == (frame[-2] << 8 | frame[-1])


def set_mode_command(function: int, range_setting: int, seq: int) -> bytes:
    """'Set function/range' command, verified byte-exact against the app."""
    payload = bytes([0x10, 0x04, 0x00, 0x02, function, range_setting])
    body = bytes([0x10, 0x20, 0x02, 0x00, seq & 0xFF, (seq >> 8) & 0xFF, len(payload)]) + payload
    return build_frame(body)


def iter_frames(buf: bytes) -> Iterator[bytes]:
    """Yield AA 55 delimited frames from a buffer."""
    starts = [i for i in range(len(buf) - 1) if buf[i:i + 2] == MAGIC]
    for i, start in enumerate(starts):
        yield buf[start:starts[i + 1] if i + 1 < len(starts) else len(buf)]


def decode_measurement(frame: bytes) -> Optional[Measurement]:
    """Decode a measurement frame, or None if the frame holds no measurement."""
    idx = frame.find(MEAS_MARKER)
    if idx < 0:
        return None
    base = idx + len(MEAS_MARKER)
    if base + 8 > len(frame):
        return None

    code, range_setting, active_range = frame[base], frame[base + 2], frame[base + 3]
    try:
        function = Function(code)
    except ValueError:
        function = None

    if code in RANGE_UNIT:
        unit = RANGE_UNIT[code].get(active_range, f"?r{active_range}")
    else:
        unit = BASE_UNIT.get(code, f"?fn{code:#04x}")

    raw = frame[base + 4:base + 8]
    value = None if struct.unpack(">I", raw)[0] == OL_RAW else struct.unpack(">f", raw)[0]
    return Measurement(value, unit, function, range_setting, active_range)


class FnirsiSession:
    """
    Command/stream session with a FNIRSI meter over a notify/write transport.
    """

    def __init__(self, transport: Transport, handshake_delay: float = 0.2):
        self.transport = transport
        self.handshake_delay = handshake_delay
        self._seq = len(HANDSHAKE)

    def start(self) -> None:
        """Replay the app handshake so the meter starts streaming."""
        # the meter needs a pause between the handshake writes (as the app does)
        for cmd in HANDSHAKE:
            self.transport.write(cmd)
            time.sleep(self.handshake_delay)
        self._seq = len(HANDSHAKE)

    def set_mode(self, function: int, range_setting: int = Range.AUTO) -> None:
        self._seq += 1
        self.transport.write(set_mode_command(function, range_setting, self._seq))

    def read_frames(self) -> List[bytes]:
        """Frames of the next notification."""
        return list(iter_frames(self.transport.read()))

    def read_measurement(self, max_notifications: int = 50) -> Measurement:
        """Wait for the next measurement frame."""
        for _ in range(max_notifications):
            for frame in self.read_frames():
                m = decode_measurement(frame)
                if m is not None:
                    return m
        raise TimeoutError("No measurement frame received")

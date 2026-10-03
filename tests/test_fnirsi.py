import struct

from messplatz.proto.fnirsi import (HANDSHAKE, Function, FnirsiSession, Range, build_frame,
                                    check_frame, decode_measurement, iter_frames, set_mode_command)


def test_set_mode_matches_capture():
    # app "set DC V, auto" captured with seq 5
    assert set_mode_command(Function.DC_VOLTAGE, Range.AUTO, seq=5).hex() == \
        "aa5510200200050006100400020107eefc"


def test_handshake_crc():
    assert all(check_frame(f) for f in HANDSHAKE)


def measurement_frame(function, range_setting, active_range, value):
    body = (bytes.fromhex("1080020001000e") + bytes.fromhex("1002000a")
            + bytes([function, function, range_setting, active_range])
            + struct.pack(">f", value) + bytes.fromhex("0201"))
    return build_frame(body)


def test_decode_measurement():
    m = decode_measurement(measurement_frame(0x01, 0x07, 0x01, 1.234))
    assert m.function is Function.DC_VOLTAGE and m.unit == "V" and m.active_range == 1
    assert abs(m.value - 1.234) < 1e-6


def test_decode_overlimit():
    frame = measurement_frame(0x03, 0x07, 0x04, 0.0)
    frame = frame[:-8] + bytes.fromhex("7f7fffff") + frame[-4:]
    assert decode_measurement(frame).value is None


def test_iter_frames_splits():
    a, b = HANDSHAKE[0], HANDSHAKE[1]
    assert list(iter_frames(a + b)) == [a, b]


class FakeBle:
    def __init__(self, notifications):
        self.notifications = list(notifications)
        self.written = []

    def write(self, data):
        self.written.append(data)

    def read(self):
        return self.notifications.pop(0)


def test_session_handshake_seq_and_read():
    t = FakeBle([bytes.fromhex("aa551000020001000601010101"),
                 measurement_frame(0x05, 0x07, 0x02, 12.5)])
    s = FnirsiSession(t)
    s.start()
    s.set_mode(Function.DC_VOLTAGE)
    assert t.written[:3] == HANDSHAKE
    assert t.written[3] == set_mode_command(Function.DC_VOLTAGE, Range.AUTO, seq=4)
    m = s.read_measurement()
    assert (m.value, m.unit) == (12.5, "mA")

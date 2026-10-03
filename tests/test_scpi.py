from messplatz.com.base import Transport
from messplatz.devices.osci.upo1000hd import UPO1000HD
from messplatz.proto.scpi import Scpi


class FakeTransport(Transport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.written = []

    def open(self):
        pass

    def close(self):
        pass

    def write(self, data):
        self.written.append(data)

    def read(self):
        return self.responses.pop(0)


def test_query_appends_terminator_and_strips_response():
    t = FakeTransport([b"UNI-T,UPO1102CS,123,1.0\n"])
    assert Scpi(t).query("*IDN?") == "UNI-T,UPO1102CS,123,1.0"
    assert t.written == [b"*IDN?\n"]


def test_device_info_uses_idn():
    t = FakeTransport([b"UNI-T,UPO1000HD\r\n"])
    assert UPO1000HD(Scpi(t)).info == "UNI-T,UPO1000HD"

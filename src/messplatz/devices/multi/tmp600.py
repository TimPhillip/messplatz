from typing import Optional

from messplatz.com.bluetooth import Ble
from messplatz.devices.core.multi import Multi
from messplatz.proto.fnirsi import FnirsiSession, Function, Measurement, Range


class TMP600(Multi):
    """
    FNIRSI TMP-600 multimeter over BLE.

    The official app must be disconnected, the meter allows one BLE central.
    """

    NAME = "TMP-600"
    NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"
    WRITE_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"

    def __init__(self, address: Optional[str] = None):
        self.transport = Ble(name=None if address else self.NAME, address=address,
                             notify_uuid=self.NOTIFY_UUID, write_uuid=self.WRITE_UUID)
        self.transport.open()
        self.session = FnirsiSession(self.transport)
        self.session.start()

    def close(self) -> None:
        self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def info(self) -> str:
        return f"FNIRSI {self.NAME}"

    def set_mode(self, function: Function, range_setting: int = Range.AUTO) -> None:
        self.session.set_mode(function, range_setting)

    def read(self) -> Measurement:
        """Current reading: drops buffered old readings and waits for a fresh one."""
        self.transport.flush()
        return self.session.read_measurement()

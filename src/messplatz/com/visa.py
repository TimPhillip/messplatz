from typing import Optional

from messplatz.com.base import Transport


class Visa(Transport):
    """
    PyVISA transport (USB-TMC, TCPIP, serial, ...), using the pure Python
    pyvisa-py backend by default.

    If no resource string is given, the first USB instrument found is used.
    """

    def __init__(self, resource: Optional[str] = None, backend: str = "@py",
                 timeout_ms: int = 2000):
        self.resource = resource
        self.backend = backend
        self.timeout_ms = timeout_ms
        self._inst = None

    def open(self) -> None:
        import pyvisa

        rm = pyvisa.ResourceManager(self.backend)
        if self.resource is None:
            found = rm.list_resources("USB?*INSTR")
            if not found:
                raise ConnectionError("No USB instrument found")
            self.resource = found[0]
        self._inst = rm.open_resource(self.resource)
        self._inst.timeout = self.timeout_ms

    def close(self) -> None:
        if self._inst is not None:
            self._inst.close()
            self._inst = None

    def write(self, data: bytes) -> None:
        self._inst.write_raw(data)

    def read(self) -> bytes:
        return self._inst.read_raw()

import os

from messplatz.com.base import Transport


class UsbTmc(Transport):
    """
    USB-TMC transport via the Linux usbtmc kernel driver (/dev/usbtmcN).
    """

    def __init__(self, path: str = "/dev/usbtmc0", chunk_size: int = 65536):
        self.path = path
        self.chunk_size = chunk_size
        self._fd = None

    def open(self) -> None:
        self._fd = os.open(self.path, os.O_RDWR)

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def write(self, data: bytes) -> None:
        os.write(self._fd, data)

    def read(self) -> bytes:
        # The driver returns one USB-TMC transfer per read
        return os.read(self._fd, self.chunk_size)

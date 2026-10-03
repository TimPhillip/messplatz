import socket

from messplatz.com.base import Transport


class Ethernet(Transport):
    """
    Raw TCP socket transport (e.g. SCPI on port 5555 or 5025).
    """

    def __init__(self, host: str, port: int = 5555, timeout: float = 2.0,
                 terminator: bytes = b"\n"):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.terminator = terminator
        self._sock = None
        self._buf = b""

    def open(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), self.timeout)
        self._buf = b""

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def read(self) -> bytes:
        # Read until terminator; keep anything after it for the next read
        while self.terminator not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed by device")
            self._buf += chunk
        msg, _, self._buf = self._buf.partition(self.terminator)
        return msg + self.terminator

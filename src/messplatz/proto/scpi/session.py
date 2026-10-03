"""
SCPI session: executes commands over a transport.
"""
import time
from typing import Any, Optional, Protocol, Type

from messplatz.com.base import Transport
from messplatz.proto.scpi.types import SCPIBlock, SCPIType


class Executable(Protocol):
    """
    Anything the session can execute. ``response_type`` is None for
    commands without a response.
    """

    response_type: Optional[Type[SCPIType]]

    def compile(self) -> str:
        ...


class SCPIError(Exception):
    """
    Error reported by the device via :SYSTem:ERRor?.
    """

    def __init__(self, code: int, message: str, command: str = ""):
        self.code = code
        self.message = message
        self.command = command
        super().__init__(f"{code},{message!r}" + (f" after {command!r}" if command else ""))


class SCPISession:
    """
    Sends SCPI commands through a transport and parses the responses.

    With ``check_errors`` the error queue is read after every command and an
    SCPIError is raised if the device reported one.
    """

    def __init__(self, transport: Transport, terminator: str = "\n",
                 encoding: str = "ascii", check_errors: bool = False):
        self.transport = transport
        self.terminator = terminator
        self.encoding = encoding
        self.check_errors = check_errors

    def execute(self, cmd: Executable) -> Any:
        text = cmd.compile()
        self.write(text)

        result = None
        rtype = cmd.response_type
        if rtype is not None:
            if issubclass(rtype, SCPIBlock):
                result = rtype.parse(self.read_block())
            else:
                result = rtype.parse(self.read())

        if self.check_errors:
            self.raise_on_error(text)
        return result

    def write(self, text: str) -> None:
        self.transport.write((text + self.terminator).encode(self.encoding))

    def read(self) -> str:
        return self.transport.read().decode(self.encoding).rstrip("\r\n")

    def query(self, text: str) -> str:
        self.write(text)
        return self.read()

    def read_block(self) -> bytes:
        """
        Read a complete binary block, possibly spread over several reads.
        """
        data = self.transport.read()
        size = SCPIBlock.expected_size(data)
        if data[1:2] == b"0":
            # indefinite length: read until the message ends with a terminator
            while not data.endswith(self.terminator.encode(self.encoding)):
                data += self.transport.read()
            return data
        while size < 0 or len(data) < size:
            data += self.transport.read()
            size = SCPIBlock.expected_size(data)
        return data

    def wait_complete(self, timeout: float = 5.0, interval: float = 0.02) -> None:
        """
        Poll *OPC? until the device reports the last command as executed.

        Some devices (e.g. UNI-T) answer *OPC? immediately with 0 while still
        busy instead of blocking until completion, so the query is repeated.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self.query("*OPC?").strip() == "1":
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Device did not complete the last command within {timeout} s")
            time.sleep(interval)

    def error(self) -> Optional[SCPIError]:
        """
        Pop one entry from the error queue; None if it is empty.
        """
        code, _, message = self.query(":SYSTem:ERRor?").partition(",")
        code = int(code)
        if code == 0:
            return None
        return SCPIError(code, message.strip().strip('"'))

    def raise_on_error(self, command: str = "") -> None:
        err = self.error()
        if err is not None:
            raise SCPIError(err.code, err.message, command)

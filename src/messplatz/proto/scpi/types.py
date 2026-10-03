"""
SCPI data types.

Each type is a codec: ``parse`` turns a response into a plain Python value,
``format`` turns a Python value into a command parameter.
"""
import math
from enum import Enum
from typing import Generic, List, Type, TypeVar

T = TypeVar("T")
E = TypeVar("E", bound=Enum)

# SCPI special numbers (SCPI-99, 7.2.1.5)
SCPI_INF = 9.9e37
SCPI_NAN = 9.91e37


class SCPIType(Generic[T]):
    """
    Base class of all SCPI data types.
    """

    @classmethod
    def parse(cls, text: str) -> T:
        raise NotImplementedError

    @classmethod
    def format(cls, value: T) -> str:
        return str(value)


class SCPIString(SCPIType[str]):
    """
    String response, surrounding quotes are removed.
    """

    @classmethod
    def parse(cls, text: str) -> str:
        text = text.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1]
        return text

    @classmethod
    def format(cls, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'


class SCPIFloat(SCPIType[float]):
    """
    Numeric response (NR1/NR2/NR3). Maps SCPI special numbers to inf/nan.
    """

    @classmethod
    def parse(cls, text: str) -> float:
        value = float(text)
        if value == SCPI_NAN:
            return math.nan
        if abs(value) == SCPI_INF:
            return math.copysign(math.inf, value)
        return value

    @classmethod
    def format(cls, value: float) -> str:
        if math.isnan(value):
            return "NAN"
        if math.isinf(value):
            return "INF" if value > 0 else "NINF"
        return repr(float(value))


class SCPIInt(SCPIType[int]):
    """
    Integer response; accepts float notation like ``1.000E+00``.
    """

    @classmethod
    def parse(cls, text: str) -> int:
        return int(float(text))

    @classmethod
    def format(cls, value: int) -> str:
        return str(int(value))


class SCPIBool(SCPIType[bool]):
    """
    Boolean response: ``1``/``0`` or ``ON``/``OFF``.
    """

    @classmethod
    def parse(cls, text: str) -> bool:
        text = text.strip().upper()
        if text in ("1", "ON"):
            return True
        if text in ("0", "OFF"):
            return False
        raise ValueError(f"Invalid SCPI boolean: {text!r}")

    @classmethod
    def format(cls, value: bool) -> str:
        return "ON" if value else "OFF"


class SCPIEnum(SCPIType[E]):
    """
    Enum response. Subclass with ``enum`` set, e.g.::

        class CouplingType(SCPIEnum[Coupling]):
            enum = Coupling

    Enum values use SCPI notation (``"EDGe"``); long and short form are
    accepted case-insensitively, the short form is sent.
    """

    enum: Type[E]

    @classmethod
    def parse(cls, text: str) -> E:
        text = text.strip().strip("\"'").upper()
        for member in cls.enum:
            value = str(member.value)
            if text in (value.upper(), _short_form(value)):
                return member
        raise ValueError(f"Invalid {cls.enum.__name__}: {text!r}")

    @classmethod
    def format(cls, value: E) -> str:
        return _short_form(str(value.value))


class SCPIList(SCPIType[List[T]]):
    """
    Comma separated list. Subclass with ``item`` set, e.g.::

        class FloatList(SCPIList[float]):
            item = SCPIFloat
    """

    item: Type[SCPIType[T]]

    @classmethod
    def parse(cls, text: str) -> List[T]:
        text = text.strip()
        if not text:
            return []
        return [cls.item.parse(part) for part in text.split(",")]

    @classmethod
    def format(cls, value: List[T]) -> str:
        return ",".join(cls.item.format(v) for v in value)


class SCPIBlock(SCPIType[bytes]):
    """
    IEEE 488.2 binary block (``#<n><length><data>``), e.g. waveform data.

    The session reads blocks as raw bytes; ``parse`` takes the complete
    response and returns the payload.
    """

    @classmethod
    def parse(cls, data: bytes) -> bytes:  # type: ignore[override]
        if data[:1] != b"#":
            raise ValueError("Missing '#' in binary block header")
        digits = int(data[1:2])
        if digits == 0:
            # indefinite length: data runs until the terminator
            return data[2:].rstrip(b"\r\n")
        length = int(data[2:2 + digits])
        start = 2 + digits
        if len(data) < start + length:
            raise ValueError("Binary block is incomplete")
        return data[start:start + length]

    @classmethod
    def expected_size(cls, data: bytes) -> int:
        """
        Total size of the block (header + payload), or -1 if not yet known
        or of indefinite length.
        """
        if len(data) < 2:
            return -1
        digits = int(data[1:2])
        if digits == 0 or len(data) < 2 + digits:
            return -1
        return 2 + digits + int(data[2:2 + digits])


def _short_form(value: str) -> str:
    """``EDGe`` -> ``EDG``; all-caps or all-lowercase values stay whole."""
    short = "".join(c for c in value if not c.islower())
    return (short or value).upper()

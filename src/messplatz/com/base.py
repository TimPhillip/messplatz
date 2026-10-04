from abc import ABC, abstractmethod


class Transport(ABC):
    """
    Raw byte transport. Knows nothing about the protocol on top.
    """

    @abstractmethod
    def open(self) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def write(self, data: bytes) -> None:
        ...

    @abstractmethod
    def read(self) -> bytes:
        """Read one complete message."""
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        ...

    def ensure_open(self) -> None:
        """Open lazily on first use, so devices can be created without hardware."""
        if not self.is_open:
            self.open()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

from abc import ABC, abstractmethod


class Device(ABC):

    @property
    @abstractmethod
    def info(self) -> str:
        ...

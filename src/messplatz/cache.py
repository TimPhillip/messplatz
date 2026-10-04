"""
Record and replay measurements.

Inside a ``with cached_measure("experiment_1"):`` block, methods decorated with
``@measurement`` are recorded to ``measurements/experiment_1.pkl`` on the
first run and replayed from that file afterwards, without touching the
hardware. Methods decorated with ``@control`` (state changes without a
result) run while recording and are skipped while replaying.

Entries are keyed by method, arguments and occurrence within the block,
e.g. ``UPO1000HD.get_waveform(1)#0``; a key missing from the file raises
CacheMissError.
"""
import contextvars
import functools
import pickle
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

CACHE_DIR = Path("measurements")

_active: contextvars.ContextVar[Optional["Experiment"]] = contextvars.ContextVar("experiment", default=None)


class CacheMissError(KeyError):
    """A replayed block requested a measurement that was not recorded."""


class Experiment:

    def __init__(self, name: str, remeasure: bool = False, directory: Optional[Path] = None):
        self.name = name
        self.path = Path(directory or CACHE_DIR) / f"{name}.pkl"
        self.replay = self.path.exists() and not remeasure
        self.entries: Dict[str, Dict[str, Any]] = {}
        self._occurrences: Dict[str, int] = {}
        self._token = None
        self._depth = 0   # >0 while a recorded call runs; nested calls are not recorded

    def __enter__(self) -> "Experiment":
        if _active.get() is not None:
            raise RuntimeError("cached_measure() blocks cannot be nested")
        if self.replay:
            with open(self.path, "rb") as f:
                self.entries = pickle.load(f)["entries"]
        self._token = _active.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _active.reset(self._token)
        if exc_type is None and not self.replay:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "wb") as f:
                pickle.dump({"name": self.name, "created": time.time(), "entries": self.entries}, f)

    def _key(self, func: Callable, args: tuple, kwargs: dict) -> str:
        parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in sorted(kwargs.items())]
        base = f"{func.__qualname__}({', '.join(parts)})"
        n = self._occurrences.get(base, 0)
        self._occurrences[base] = n + 1
        return f"{base}#{n}"

    def measure(self, func: Callable, obj: Any, args: tuple, kwargs: dict) -> Any:
        key = self._key(func, args, kwargs)
        if self.replay:
            if key not in self.entries:
                raise CacheMissError(f"{key!r} was not recorded in experiment {self.name!r}")
            return self.entries[key]["value"]
        self._depth += 1
        try:
            value = func(obj, *args, **kwargs)
        finally:
            self._depth -= 1
        self.entries[key] = {"value": value, "time": time.time()}
        return value

    def control(self, func: Callable, obj: Any, args: tuple, kwargs: dict) -> Any:
        if self.replay:
            return None
        return func(obj, *args, **kwargs)


def cached_measure(name: str, remeasure: bool = False, directory: Optional[Path] = None) -> Experiment:
    """
    Context manager: record measurements under ``name`` or replay them if
    the file already exists (``remeasure=True`` forces recording).
    """
    return Experiment(name, remeasure=remeasure, directory=directory)


def measurement(func: Callable) -> Callable:
    """Method decorator: the result is recorded/replayed inside cached_measure()."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        experiment = _active.get()
        if experiment is None or experiment._depth:
            return func(self, *args, **kwargs)
        return experiment.measure(func, self, args, kwargs)

    return wrapper


def control(func: Callable) -> Callable:
    """Method decorator: a state change that is skipped while replaying."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        experiment = _active.get()
        if experiment is None or experiment._depth:
            return func(self, *args, **kwargs)
        return experiment.control(func, self, args, kwargs)

    return wrapper

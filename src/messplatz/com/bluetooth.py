import asyncio
import queue
import threading
from typing import Optional

from messplatz.com.base import Transport


class Ble(Transport):
    """
    BLE UART-style transport using bleak: writes go to one characteristic,
    notifications from another are buffered and returned by read().

    bleak is async; it runs in a background thread with its own event loop so
    this transport can be used synchronously like the others.
    """

    def __init__(self, name: Optional[str] = None, address: Optional[str] = None,
                 notify_uuid: str = "", write_uuid: str = "",
                 scan_timeout: float = 30.0, read_timeout: float = 2.0, buffer_size: int = 1000):
        if name is None and address is None:
            raise ValueError("Ble needs a device name or address")
        self.name = name
        self.address = address
        self.notify_uuid = notify_uuid
        self.write_uuid = write_uuid
        self.scan_timeout = scan_timeout
        self.read_timeout = read_timeout
        self._rx: "queue.Queue[bytes]" = queue.Queue(maxsize=buffer_size)
        self._loop = None
        self._thread = None
        self._client = None

    def open(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        try:
            self._run(self._connect())
        except Exception:
            self._stop_loop()
            raise

    @property
    def is_open(self) -> bool:
        return self._client is not None

    def close(self) -> None:
        if self._client is not None:
            try:
                self._run(self._disconnect())
            finally:
                self._client = None
        self._stop_loop()

    def write(self, data: bytes, response: bool = False) -> None:
        self._run(self._client.write_gatt_char(self.write_uuid, data, response=response))

    def read(self, timeout: Optional[float] = None) -> bytes:
        """Return the next notification; raises TimeoutError if none arrives."""
        try:
            return self._rx.get(timeout=self.read_timeout if timeout is None else timeout)
        except queue.Empty:
            raise TimeoutError("No BLE notification received") from None

    def flush(self) -> None:
        """Drop all buffered notifications."""
        while not self._rx.empty():
            self._rx.get_nowait()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def _stop_loop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()
            self._loop.close()
            self._loop = None
            self._thread = None

    async def _connect(self) -> None:
        from bleak import BleakClient, BleakScanner

        if self.address is not None:
            device = await BleakScanner.find_device_by_address(self.address, timeout=self.scan_timeout)
        else:
            device = await BleakScanner.find_device_by_filter(
                lambda d, adv: (d.name or adv.local_name) == self.name,
                timeout=self.scan_timeout)
        if device is None:
            raise ConnectionError(f"BLE device {self.address or self.name!r} not found")

        self._client = BleakClient(device)
        await self._client.connect()
        await self._client.start_notify(self.notify_uuid, lambda _s, data: self._receive(bytes(data)))

    def _receive(self, data: bytes) -> None:
        # keep the newest notifications, drop the oldest when the buffer is full
        if self._rx.full():
            try:
                self._rx.get_nowait()
            except queue.Empty:
                pass
        self._rx.put_nowait(data)

    async def _disconnect(self) -> None:
        try:
            await self._client.stop_notify(self.notify_uuid)
        except Exception:
            pass
        await self._client.disconnect()

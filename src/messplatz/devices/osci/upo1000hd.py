from messplatz.cache import control, measurement
from messplatz.com.visa import Visa
from messplatz.devices.core.osci import Osci
from messplatz.proto.scpi.core import SCPICoreSpec
from messplatz.proto.scpi.unit1000hdspec import Unit1000HDSCPISpec, _Unit1000HD_TriggerSpec
from messplatz.proto.scpi.session import SCPISession

from functools import cached_property
import time
from typing import Tuple
import numpy as np
from numpy.typing import NDArray


class UPO1000HDChannel:

    def __init__(self, channel_number: int, osci: Osci):
        self.channel_number = channel_number
        self.osci = osci

    @property
    @measurement
    def display(self) -> bool:
        return self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).display.query())

    @display.setter
    @control
    def display(self, value: bool) -> None:
        self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).display(value))
        self.osci.session.wait_complete()


class UPO1000HDTrigger:

    class Status:
        RESET = "RESET"
        ARMED = "ARMED"
        TRIGGERED = "TRIGGERED"
        AUTO = "AUTO"

    @property
    @measurement
    def status(self) -> "Status":
        return self.osci.session.execute(self.osci.unit_scpi.trigger.status.query())


class UPO1000HDTimebase:

    pass


class UPO1000HD(Osci):
    """
    UPO1000HD oscilloscope device class.
    """

    # TODO: make configurable; None uses the first USB instrument
    RESOURCE = "USB0::0x5656::0x0832::APH1325310189::INSTR"

    def __init__(self):

        # TODO: make the transport configurable (USB, Ethernet, ...)
        self.transport = Visa(self.RESOURCE)   # opened on first command
        self.session = SCPISession(self.transport)

        # use the SCPI core specification for this device (TODO: replace later with UniT)
        self.scpi = SCPICoreSpec()
        self.unit_scpi = Unit1000HDSCPISpec()

        # TODO: infere the number of channels from the device, for now we assume 4 channels
        self.channels = [UPO1000HDChannel(i, self) for i in range(1, 5)]

    def close(self) -> None:
        if self.transport.is_open:
            self.transport.close()

    @cached_property
    @measurement
    def info(self) -> str:
        return self.session.execute(self.scpi.identification.query())


    @property
    @measurement
    def trigger_status(self) -> _Unit1000HD_TriggerSpec.Status:
        return self.session.execute(self.unit_scpi.trigger.status.query())

    def wait_for_acquisition(self, timeout: float = 5.0, interval: float = 0.05) -> None:
        """
        Wait until the scope has acquired data after a restart (:RUN, :AUTO,
        front panel) and the waveform buffer is valid.

        *OPC? always returns 1 on this scope, so the trigger status is polled
        instead: it goes RESET -> ARMED -> TRIGED (or AUTO without a trigger
        in AUTO sweep mode) within about 0.6-1 s. Until then the waveform
        buffer holds only 0xFFFF fill values.
        """
        status = self.unit_scpi.trigger.Status
        pending = {status.RESET, status.ARMED, status.READY, status.WAIT}
        deadline = time.monotonic() + timeout
        while (current := self.trigger_status) in pending:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Scope did not acquire within {timeout} s (trigger status {current.name}): "
                    "no trigger event, check the trigger level or use AUTO sweep mode")
            time.sleep(interval)

    @control
    def run(self) -> None:
        self.session.execute(self.unit_scpi.run())

    @control
    def stop(self) -> None:
        self.session.execute(self.unit_scpi.stop())
        self.session.wait_complete()

    @control
    def autoset(self) -> None:
        self.session.execute(self.unit_scpi.autoset())

    @control
    def lock(self, locked: bool) -> None:
        self.session.execute(self.unit_scpi.system.lock(locked))
        self.session.wait_complete()

    @control
    def lock_touch(self, locked: bool) -> None:
        self.session.execute(self.unit_scpi.system.touch.lock(locked))
        self.session.wait_complete()

    @property
    @measurement
    def is_locked(self) -> bool:
        return self.session.execute(self.unit_scpi.system.lock.query())

    @property
    @measurement
    def is_touch_locked(self) -> bool:
        return self.session.execute(self.unit_scpi.system.touch.lock.query())


    @measurement
    def get_waveform(self, channel: int, timeout: float = 5.0) -> Tuple[NDArray[np.float32], NDArray[np.float32]]:
        """
        Read the waveform shown on screen; returns (time in s, voltage in V).

        Waits up to ``timeout`` seconds for the scope to acquire data; raises
        TimeoutError if it does not trigger in time.
        """

        self.wait_for_acquisition(timeout)

        # setup the waveform acquisition for the given channel
        self.session.execute(self.unit_scpi.waveform.source(channel=channel))
        self.session.execute(self.unit_scpi.waveform.mode(self.unit_scpi.waveform.Modes.NORMAL))
        self.session.execute(self.unit_scpi.waveform.format(self.unit_scpi.waveform.Formats.WORD))

        # the scope is in an undefined state until the setup has been applied
        self.session.wait_complete()

        # retrieve the waveform data from the device
        raw_data = self.session.execute(self.unit_scpi.waveform.data.query())

        # WORD: unsigned 16 bit ADC values, little-endian
        adc = np.frombuffer(raw_data, dtype="<u2")

        # the buffer is filled with 0xFFFF while the scope has not acquired yet
        if np.all(adc == 0xFFFF):
            raise RuntimeError("No waveform data acquired yet (buffer holds only fill values)")
        adc = adc.astype(np.float32)

        # scaling parameters of the selected source
        y_increment = self.session.execute(self.unit_scpi.waveform.y_increment.query())
        y_origin = self.session.execute(self.unit_scpi.waveform.y_origin.query())
        y_reference = self.session.execute(self.unit_scpi.waveform.y_reference.query())

        x_increment = self.session.execute(self.unit_scpi.waveform.x_increment.query())
        x_origin = self.session.execute(self.unit_scpi.waveform.x_origin.query())
        x_reference = self.session.execute(self.unit_scpi.waveform.x_reference.query())

        # convert to volts and seconds, see :WAVeform:DATA? in the programming manual
        # TODO: verify y_origin handling with a non-zero channel offset
        voltage = ((adc - y_reference) * y_increment + y_origin).astype(np.float32)
        time = ((np.arange(len(adc)) - x_reference) * x_increment + x_origin).astype(np.float32)

        return time, voltage
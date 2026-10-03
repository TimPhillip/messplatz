from messplatz.com.visa import Visa
from messplatz.devices.core.osci import Osci
from messplatz.proto.scpi.core import SCPICoreSpec
from messplatz.proto.scpi.unit1000hdspec import Unit1000HDSCPISpec
from messplatz.proto.scpi.session import SCPISession

from functools import cached_property
from typing import Tuple
import numpy as np
from numpy.typing import NDArray


class UPO1000HDChannel:

    def __init__(self, channel_number: int, osci: Osci):
        self.channel_number = channel_number
        self.osci = osci

    @property
    def display(self) -> bool:
        return self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).display.query())

    @display.setter
    def display(self, value: bool) -> None:
        self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).display(value))


class UPO1000HD(Osci):
    """
    UPO1000HD oscilloscope device class.
    """

    # TODO: make configurable; None uses the first USB instrument
    RESOURCE = "USB0::0x5656::0x0832::APH1325310189::INSTR"

    def __init__(self):

        # TODO: make the transport configurable (USB, Ethernet, ...)
        self.transport = Visa(self.RESOURCE)
        self.transport.open()
        self.session = SCPISession(self.transport)

        # use the SCPI core specification for this device (TODO: replace later with UniT)
        self.scpi = SCPICoreSpec()
        self.unit_scpi = Unit1000HDSCPISpec()

        # TODO: infere the number of channels from the device, for now we assume 4 channels
        self.channels = [UPO1000HDChannel(i, self) for i in range(1, 5)]

    def close(self) -> None:
        self.transport.close()

    @cached_property
    def info(self) -> str:
        return self.session.execute(self.scpi.identification.query())


    def run(self) -> None:
        self.session.execute(self.unit_scpi.run())

    def stop(self) -> None:
        self.session.execute(self.unit_scpi.stop())

    def autoset(self) -> None:
        self.session.execute(self.unit_scpi.autoset())

    def lock(self, locked: bool) -> None:
        self.session.execute(self.unit_scpi.system.lock(locked))

    def lock_touch(self, locked: bool) -> None:
        self.session.execute(self.unit_scpi.system.touch.lock(locked))

    @property
    def is_locked(self) -> bool:
        return self.session.execute(self.unit_scpi.system.lock.query())

    @property
    def is_touch_locked(self) -> bool:
        return self.session.execute(self.unit_scpi.system.touch.lock.query())


    def get_waveform(self, channel: int) -> Tuple[NDArray[np.float32], NDArray[np.float32]]:
        """
        Read the waveform shown on screen; returns (time in s, voltage in V).
        """

        # setup the waveform acquisition for the given channel
        self.session.execute(self.unit_scpi.waveform.source(channel=channel))
        self.session.execute(self.unit_scpi.waveform.mode(self.unit_scpi.waveform.Modes.NORMAL))
        self.session.execute(self.unit_scpi.waveform.format(self.unit_scpi.waveform.Formats.WORD))

        # retrieve the waveform data from the device
        raw_data = self.session.execute(self.unit_scpi.waveform.data.query())

        # WORD: unsigned 16 bit ADC values, little-endian
        adc = np.frombuffer(raw_data, dtype="<u2").astype(np.float32)

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
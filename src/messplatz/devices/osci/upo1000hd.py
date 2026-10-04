from messplatz.cache import control, measurement
from messplatz.com.visa import Visa
from messplatz.devices.core.osci import Osci
from messplatz.proto.scpi.core import SCPICoreSpec
from messplatz.proto.scpi.unit1000hdspec import Unit1000HDSCPISpec, _Unit1000HD_TriggerSpec
from messplatz.proto.scpi.session import SCPISession
from messplatz.proto.scpi.types import SCPIFloat, SCPIString

from functools import cached_property
import math
import time
import warnings
from typing import Optional, Tuple
import numpy as np
from numpy.typing import NDArray


class UPO1000HDChannel:

    # longest label the scope keeps; longer strings are cut off by the device
    # (observed on the UPO1084HD, not documented in the programming manual)
    MAX_LABEL_LENGTH = 16

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

    @property
    @measurement
    def volts_per_division(self) -> float:
        """
        Vertical scale in V/div (:CHANnel<n>:SCALe?), including the probe attenuation.
        """
        return self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).scale.query())

    @volts_per_division.setter
    @control
    def volts_per_division(self, value: float) -> None:
        """
        Set the vertical scale in V/div.

        With fine tuning (:CHANnel<n>:VERNier) off the scope only accepts the
        1-2-5 sequence, 500 uV/div to 10 V/div at 1X probe attenuation; read
        the property back to get the value actually applied.
        """
        self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).scale(SCPIFloat.format(value)))
        self.osci.session.wait_complete()

    @property
    @measurement
    def label(self) -> str:
        """
        Channel label text (:CHANnel<n>:LABel?).
        """
        return self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).label.query())

    @label.setter
    @control
    def label(self, text: str) -> None:
        """
        Set the channel label text. ASCII letters, digits and some punctuation
        only; the label is shown on screen when :attr:`label_visible` is True.
        Text longer than ``MAX_LABEL_LENGTH`` is trimmed with a warning;
        non-ASCII or control characters raise ValueError.
        """
        if not text.isascii() or not text.isprintable():
            bad = sorted({c for c in text if not (c.isascii() and c.isprintable())})
            raise ValueError(f"Channel label {text!r} contains characters the scope cannot display: {bad!r}")
        if len(text) > self.MAX_LABEL_LENGTH:
            warnings.warn(f"Channel {self.channel_number} label {text!r} exceeds {self.MAX_LABEL_LENGTH} "
                          f"characters, trimmed to {text[:self.MAX_LABEL_LENGTH]!r}", stacklevel=3)
            text = text[:self.MAX_LABEL_LENGTH]
        self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).label(SCPIString.format(text)))
        self.osci.session.wait_complete()

    @property
    @measurement
    def label_visible(self) -> bool:
        """
        Whether the channel label is shown on screen (:CHANnel<n>:LABel:ENABle?).
        """
        return self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).label.enable.query())

    @label_visible.setter
    @control
    def label_visible(self, value: bool) -> None:
        self.osci.session.execute(self.osci.unit_scpi.channel(self.channel_number).label.enable(value))
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

    def __init__(self, osci: Osci):
        self.osci = osci
        # scale reported by the scope right before the last change (None if unknown);
        # wait_to_fill_storage() uses it to tell the old screen from the new one
        self.previous_seconds_per_division: Optional[float] = None

    @property
    @measurement
    def seconds_per_division(self) -> float:
        """
        Main time base scale in s/div (:TIMebase:SCALe?).
        """
        return self.osci.session.execute(self.osci.unit_scpi.timebase.scale.query())

    @seconds_per_division.setter
    @control
    def seconds_per_division(self, value: float) -> None:
        """
        Set the main time base scale in s/div.

        With fine tuning (:TIMebase:VERNier) off the scope only accepts the
        1-2-5 sequence (2 ns/div or 5 ns/div up to 1 ks/div depending on the
        model); read the property back to get the value actually applied.
        """
        current = self.seconds_per_division
        # an exact no-op request leaves nothing to wait for; a request that the scope
        # rounds to the current value is handled by the settle time in wait_to_fill_storage()
        self.previous_seconds_per_division = None if math.isclose(current, value, rel_tol=1e-6) else current
        self.osci.session.execute(self.osci.unit_scpi.timebase.scale(SCPIFloat.format(value)))
        self.osci.session.wait_complete()

    @property
    @measurement
    def num_divisions(self) -> int:
        """
        Number of horizontal divisions on screen as currently reported by the
        scope (8 on the UPO1000HD, see ``UPO1000HD.HORIZONTAL_DIVISIONS``).

        The scope has no query for this, so it is derived from a screen read:
        points on screen (:WAVeform:POINts?) times the time per point
        (:WAVeform:XINCrement?) divided by the time base scale. Only valid in
        a settled state; right after a time base change the increment and the
        scale belong to different settings and the result is wrong.
        """
        waveform = self.osci.unit_scpi.waveform
        self.osci.session.execute(waveform.mode(waveform.Modes.NORMAL))
        points = self.osci.session.execute(waveform.points.query())
        x_increment = self.osci.session.execute(waveform.x_increment.query())
        scale = self.osci.session.execute(self.osci.unit_scpi.timebase.scale.query())
        return round(points * x_increment / scale)

    @control
    def step_up(self) -> None:
        """
        Increase the main time base by one step (:TIMebase:SCALe UP).
        """
        self.previous_seconds_per_division = self.seconds_per_division
        self.osci.session.execute(self.osci.unit_scpi.timebase.scale("UP"))
        self.osci.session.wait_complete()

    @control
    def step_down(self) -> None:
        """
        Decrease the main time base by one step (:TIMebase:SCALe DOWN).
        """
        self.previous_seconds_per_division = self.seconds_per_division
        self.osci.session.execute(self.osci.unit_scpi.timebase.scale("DOWN"))
        self.osci.session.wait_complete()


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
        self.timebase = UPO1000HDTimebase(self)

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

    # WORD format fill value while the screen buffer has not been (re)filled yet
    FILL_VALUE = 0xFFFF

    # horizontal divisions of a screen read; the scope has no query for it, see
    # UPO1000HDTimebase.num_divisions for the measured value (8 on the UPO1000HD)
    HORIZONTAL_DIVISIONS = 8
    VERTICAL_DIVISIONS = 8

    @control
    def wait_to_fill_storage(self, timeout: float = 5.0, interval: float = 0.05,
                             settle_time: float = 1.0) -> None:
        """
        Wait until the screen buffer is valid for the current time base.

        After a time base change the trigger status still shows the previous
        acquisition, *OPC? reports completion and for a short while the scope
        even serves the complete previous screen (old XINC, no fill values),
        so none of these alone can detect the refill. This method first sleeps
        for one screen time (divisions * s/div, the minimum a refill needs) and
        then polls until all of the following hold:

        1. the time base scale reported by the scope differs from the one read
           before the change (the requested value is rounded to the 1-2-5
           sequence by the scope, so it cannot serve as reference). If the
           scale is still unchanged after ``settle_time`` the request is taken
           to have been rounded to the current scale and the screen is valid
           as it is,
        2. the waveform increment matches it: points * XINC == divisions * scale,
        3. the origin matches: XOR == -(points * XINC) / 2 (trigger at center),
        4. the screen buffer holds no fill values (``FILL_VALUE``).

        Raises TimeoutError if that does not happen in time.
        """
        waveform = self.unit_scpi.waveform
        self.session.execute(waveform.mode(waveform.Modes.NORMAL))
        self.session.execute(waveform.format(waveform.Formats.WORD))
        self.session.wait_complete()

        started = time.monotonic()
        deadline = started + timeout
        # not timebase.num_divisions: that is derived from XINC and the scale, which are
        # inconsistent with each other during the transient this method waits for
        divisions = self.HORIZONTAL_DIVISIONS
        previous = self.timebase.previous_seconds_per_division

        # the refill cannot be done before one screen worth of samples has been acquired
        time.sleep(divisions * self.timebase.seconds_per_division)

        def close(a: float, b: float, rel: float = 0.01) -> bool:
            return abs(a - b) <= rel * max(abs(a), abs(b))

        while True:
            scale = self.timebase.seconds_per_division
            points = self.session.execute(waveform.points.query())
            x_increment = self.session.execute(waveform.x_increment.query())
            x_origin = self.session.execute(waveform.x_origin.query())
            span = points * x_increment

            settled = time.monotonic() - started >= settle_time
            preamble_ok = ((previous is None or not close(scale, previous) or settled)
                           and close(span, divisions * scale)
                           and close(x_origin, -span / 2))
            if preamble_ok:
                raw_data = self.session.execute(waveform.data.query())
                adc = np.frombuffer(raw_data, dtype="<u2")
                if len(adc) and not np.any(adc == self.FILL_VALUE):
                    self.timebase.previous_seconds_per_division = None
                    return
                state = f"{int(np.count_nonzero(adc != self.FILL_VALUE))}/{len(adc)} points valid"
            else:
                state = (f"scale {scale:g} s/div (before change {previous}), span {span:g} s, "
                         f"origin {x_origin:g} s")

            if time.monotonic() >= deadline:
                raise TimeoutError(f"Screen buffer did not refill within {timeout} s ({state})")
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
        if np.all(adc == self.FILL_VALUE):
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
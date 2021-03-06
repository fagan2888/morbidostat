# -*- coding: utf-8 -*-
"""
Continuously monitor the bioreactor and take action. This is the core of the io algorithm
"""
import time, sys, os

from typing import Iterator
import json
import time

import click
import numpy as np

from morbidostat.actions.add_media import add_media
from morbidostat.actions.remove_waste import remove_waste
from morbidostat.actions.add_alt_media import add_alt_media
from morbidostat.pubsub import publish, subscribe_and_callback
from morbidostat.utils import log_start, log_stop
from morbidostat.utils.timing import every
from morbidostat.utils.streaming_calculations import PID
from morbidostat.whoami import unit, experiment
from morbidostat.background_jobs.subjobs.alt_media_calculating import AltMediaCalculator
from morbidostat.background_jobs.subjobs.throughput_calculating import ThroughputCalculator
from morbidostat.background_jobs.utils import events
from morbidostat.background_jobs import BackgroundJob

VIAL_VOLUME = 14
JOB_NAME = os.path.splitext(os.path.basename((__file__)))[0]


def brief_pause():
    if "pytest" in sys.modules or os.environ.get("TESTING"):
        return
    else:
        time.sleep(10.0)
        return


class ControlAlgorithm(BackgroundJob):
    """
    This is the super class that algorithms inherit from. The `run` function will
    execute every N minutes (selected at the start of the program). This calls the `execute` function,
    which is what subclasses will define.
    """

    latest_growth_rate = None
    latest_od = None
    latest_od_timestamp = None
    latest_growth_rate_timestamp = None
    editable_settings = ["volume", "target_od", "target_growth_rate", "display_name"]

    def __init__(self, unit=None, experiment=None, verbose=0, sensor="135/A", **kwargs):
        super(ControlAlgorithm, self).__init__(job_name=JOB_NAME, verbose=verbose, unit=unit, experiment=experiment)

        self.sensor = sensor
        self.alt_media_calculator = AltMediaCalculator(unit=self.unit, experiment=self.experiment, verbose=self.verbose)
        self.throughput_calculator = ThroughputCalculator(unit=self.unit, experiment=self.experiment, verbose=self.verbose)
        self.display_name = "ControlAlgorithm"

        self.start_passive_listeners()

    def run(self, counter=None):
        if (self.latest_growth_rate is None) or (self.latest_od is None):
            time.sleep(10)  # wait some time for data to arrive, and try again.
            return self.run(counter=counter)

        if self.state != self.READY:
            event = events.NoEvent(f"currently in state {self.state}")

        elif (time.time() - self.most_stale_time) > 5 * 60:
            event = events.NoEvent(
                "readings are too stale (over 5 minutes old) - are `Optical density job` and `Growth rate job` running?"
            )
        else:
            event = self.execute(counter)

        publish(f"morbidostat/{self.unit}/{self.experiment}/log", f"[{JOB_NAME}]: triggered {event}.", verbose=self.verbose)
        return event

    def execute(self, counter) -> events.Event:
        raise NotImplementedError

    def execute_io_action(self, alt_media_ml=0, media_ml=0, waste_ml=0, log=True):
        assert (
            abs(alt_media_ml + media_ml - waste_ml) < 1e-5
        ), f"in order to keep same volume, IO should be equal. {alt_media_ml}, {media_ml}, {waste_ml}"

        if log:
            # TODO: this is not being stored or used.
            publish(
                f"morbidostat/{self.unit}/{self.experiment}/io_batched",
                json.dumps({"alt_media_ml": alt_media_ml, "media_ml": media_ml, "waste_ml": waste_ml}),
                verbose=self.verbose,
            )

        max_ = 0.3
        if (media_ml > max_) or (alt_media_ml > max_):
            if media_ml > max_:
                self.execute_io_action(alt_media_ml=0, media_ml=media_ml / 2, waste_ml=media_ml / 2, log=False)
                self.execute_io_action(alt_media_ml=0, media_ml=media_ml / 2, waste_ml=media_ml / 2, log=False)

            if alt_media_ml > max_:
                self.execute_io_action(alt_media_ml=alt_media_ml / 2, media_ml=0, waste_ml=alt_media_ml / 2, log=False)
                self.execute_io_action(alt_media_ml=alt_media_ml / 2, media_ml=0, waste_ml=alt_media_ml / 2, log=False)
        else:
            if alt_media_ml > 0:
                add_alt_media(ml=alt_media_ml, verbose=self.verbose)
                brief_pause()  # allow time for the addition to mix, and reduce the step response that can cause ringing in the output V.
            if media_ml > 0:
                add_media(ml=media_ml, verbose=self.verbose)
                brief_pause()
            if waste_ml > 0:
                remove_waste(ml=waste_ml, verbose=self.verbose)
                # run remove_waste for an additional second to keep volume constant (determined by the length of the waste tube)
                remove_waste(duration=1, verbose=self.verbose)
                brief_pause()

    def set_growth_rate(self, message):
        self.previous_growth_rate = self.latest_growth_rate
        self.latest_growth_rate = float(message.payload)
        self.latest_growth_rate_timestamp = time.time()

    def set_OD(self, message):
        self.previous_od = self.latest_od
        self.latest_od = float(message.payload)
        self.latest_od_timestamp = time.time()

    @property
    def most_stale_time(self):
        return min(self.latest_od_timestamp, self.latest_growth_rate_timestamp)

    def start_passive_listeners(self):
        subscribe_and_callback(self.set_OD, f"morbidostat/{self.unit}/{self.experiment}/od_filtered/{self.sensor}")
        subscribe_and_callback(self.set_growth_rate, f"morbidostat/{self.unit}/{self.experiment}/growth_rate")


######################
# modes of operation
######################


class Silent(ControlAlgorithm):
    def __init__(self, **kwargs):
        super(Silent, self).__init__(**kwargs)
        self.display_name = "Silent"

    def execute(self, *args, **kwargs) -> events.Event:
        return events.NoEvent("never execute IO events in Silent mode")


class Turbidostat(ControlAlgorithm):
    """
    turbidostat mode - try to keep cell density constant. The algorithm should run at
    near every minute (limited by the OD reading rate)
    """

    def __init__(self, target_od=None, volume=None, **kwargs):
        super(Turbidostat, self).__init__(**kwargs)
        self.display_name = "Turbidostat"
        self.target_od = target_od
        self.volume = volume

    def execute(self, *args, **kwargs) -> events.Event:
        if self.latest_od >= self.target_od:
            self.execute_io_action(media_ml=self.volume, waste_ml=self.volume)
            return events.DilutionEvent(f"latest OD={self.latest_od:.2f}V >= target OD={self.target_od:.2f}V")
        else:
            return events.NoEvent(f"latest OD={self.latest_od:.2f}V < target OD={self.target_od:.2f}V")


class PIDTurbidostat(ControlAlgorithm):
    """
    turbidostat mode - try to keep cell density constant using a PID target at the OD.

    The PID tells use what fraction of volume we should limit. For example, of PID
    returns 0.03, then we should remove ~97% of the volume. Choose volume to be about 1.5ml - 2.0ml.
    """

    def __init__(self, target_od=None, volume=None, duration=None, verbose=0, **kwargs):
        super(PIDTurbidostat, self).__init__(verbose=verbose, **kwargs)
        assert target_od is not None, "`target_od` must be set"
        assert volume is not None, "`volume` must be set"
        self.display_name = "Turbidostat"
        self.target_od = target_od
        self.volume = volume
        self.verbose = verbose
        self.duration = duration
        self.pid = PID(-2, -0.15, -0, setpoint=self.target_od, output_limits=(0, 1), sample_time=None, verbose=self.verbose)

    def execute(self, *args, **kwargs) -> events.Event:
        if self.latest_od <= self.min_od:
            return events.NoEvent(f"current OD, {self.latest_od:.2f}, less than OD to start diluting, {self.min_od:.2f}")
        else:
            output = self.pid.update(self.latest_od, dt=self.duration)

            volume_to_cycle = output * self.volume

            if volume_to_cycle < 0.01:
                return events.NoEvent(f"PID output={output:.2f}, so practically no volume to cycle")
            else:
                self.execute_io_action(media_ml=volume_to_cycle, waste_ml=volume_to_cycle)
                e = events.DilutionEvent(f"PID output={output:.2f}, volume to cycle={volume_to_cycle:.2f}mL")
                e.volume_to_cycle = volume_to_cycle
                e.pid_output = output
                return e

    @property
    def min_od(self):
        return 0.75 * self.target_od

    @property
    def target_od(self):
        return self._target_od

    @target_od.setter
    def target_od(self, value):
        self._target_od = value
        try:
            # may not be defined yet...
            self.pid.set_setpoint(self.target_od)
        except:
            pass


class PIDMorbidostat(ControlAlgorithm):
    """
    As defined in Zhong 2020
    """

    def __init__(self, target_growth_rate=None, target_od=None, duration=None, volume=None, verbose=0, **kwargs):
        super(PIDMorbidostat, self).__init__(verbose=verbose, **kwargs)
        assert target_od is not None, "`target_od` must be set"
        assert target_growth_rate is not None, "`target_growth_rate` must be set"
        assert duration is not None, "`duration` must be set"

        self.display_name = "Morbidostat"
        self.target_growth_rate = target_growth_rate
        self.target_od = target_od
        self.duration = duration

        self.pid = PID(
            -0.5, -0.0001, -0.25, setpoint=self.target_growth_rate, output_limits=(0, 1), sample_time=None, verbose=self.verbose
        )

        if volume is not None:
            publish(
                f"morbidostat/{self.unit}/{self.experiment}/log",
                f"[{JOB_NAME}]: Ignoring volume parameter; volume set by target growth rate and duration.",
                verbose=self.verbose,
            )

        self.volume = self.target_growth_rate * VIAL_VOLUME * (self.duration / 60)
        self.verbose = verbose

    def execute(self, *args, **kwargs) -> events.Event:
        if self.latest_od <= self.min_od:
            return events.NoEvent(f"latest OD less than OD to start diluting, {self.min_od:.2f}")
        else:
            fraction_of_alt_media_to_add = self.pid.update(
                self.latest_growth_rate, dt=self.duration
            )  # duration is measured in minutes, not seconds (as simple_pid would want)

            # dilute more if our OD keeps creeping up - we want to stay in the linear range.
            if self.latest_od > self.max_od:
                publish(
                    f"morbidostat/{self.unit}/{self.experiment}/log",
                    f"[{JOB_NAME}]: executing double dilution since we are above max OD, {self.max_od:.2f}.",
                    verbose=self.verbose,
                )
                volume = 2 * self.volume
            else:
                volume = self.volume

            alt_media_ml = fraction_of_alt_media_to_add * volume
            media_ml = (1 - fraction_of_alt_media_to_add) * volume

            self.execute_io_action(alt_media_ml=alt_media_ml, media_ml=media_ml, waste_ml=volume)
            event = events.AltMediaEvent(
                f"PID output={fraction_of_alt_media_to_add:.2f}, alt_media_ml={alt_media_ml:.2f}mL, media_ml={media_ml:.2f}mL"
            )
            event.media_ml = media_ml  # can be used for testing later
            event.alt_media_ml = alt_media_ml
            return event

    @property
    def min_od(self):
        return 0.7 * self.target_od

    @property
    def max_od(self):
        return 1.25 * self.target_od

    @property
    def target_growth_rate(self):
        return self._target_growth_rate

    @target_growth_rate.setter
    def target_growth_rate(self, value):
        self._target_growth_rate = value
        try:
            self.pid.set_setpoint(self.target_od)
        except:
            pass


class Morbidostat(ControlAlgorithm):
    """
    As defined in Toprak 2013.
    """

    def __init__(self, target_od=None, volume=None, **kwargs):
        super(Morbidostat, self).__init__(**kwargs)
        self.display_name = "Morbidostat"
        self.target_od = target_od
        self.volume = volume

    def execute(self, *args, **kwargs) -> events.Event:
        """
        morbidostat mode - keep cell density below and threshold using chemical means. The conc.
        of the chemical is diluted slowly over time, allowing the microbes to recover.
        """
        if self.previous_od is None:
            return events.NoEvent("skip first event to wait for OD readings.")
        elif self.latest_od >= self.target_od and self.latest_od >= self.previous_od:
            # if we are above the threshold, and growth rate is greater than dilution rate
            # the second condition is an approximation of this.
            self.execute_io_action(alt_media_ml=self.volume, waste_ml=self.volume)
            return events.AltMediaEvent(
                f"latest OD, {self.latest_od:.2f} >= Target OD, {self.target_od:.2f} and Latest OD, {self.latest_od:.2f} >= Previous OD, {self.previous_od:.2f}"
            )
        else:
            self.execute_io_action(media_ml=self.volume, waste_ml=self.volume)
            return events.DilutionEvent(
                f"latest OD, {self.latest_od:.2f} < Target OD, {self.target_od:.2f} or Latest OD, {self.latest_od:.2f} < Previous OD, {self.previous_od:.2f}"
            )


@log_start(unit, experiment)
@log_stop(unit, experiment)
def io_controlling(mode=None, duration=None, verbose=0, sensor="135/A", skip_first_run=False, **kwargs) -> Iterator[events.Event]:

    algorithms = {
        "silent": Silent,
        "morbidostat": Morbidostat,
        "turbidostat": Turbidostat,
        "pid_turbidostat": PIDTurbidostat,
        "pid_morbidostat": PIDMorbidostat,
    }

    assert mode in algorithms.keys()

    publish(
        f"morbidostat/{unit}/{experiment}/log",
        f"[{JOB_NAME}]: starting {mode} with {duration}min intervals, metadata: {kwargs}",
        verbose=verbose,
    )

    if skip_first_run:
        publish(f"morbidostat/{unit}/{experiment}/log", f"[{JOB_NAME}]: skipping first run", verbose=verbose)
        time.sleep(duration * 60)

    kwargs["verbose"] = verbose
    kwargs["duration"] = duration
    kwargs["unit"] = unit
    kwargs["experiment"] = experiment
    kwargs["sensor"] = sensor

    algo = algorithms[mode](**kwargs)

    def _gen():
        try:
            yield from every(duration * 60, algo.run)
        except Exception as e:
            publish(f"morbidostat/{unit}/{experiment}/error_log", f"[{JOB_NAME}]: failed {str(e)}", verbose=verbose)
            raise e

    return _gen()


@click.command()
@click.option("--mode", default="silent", help="set the mode of the system: turbidostat, morbidostat, silent, etc.")
@click.option("--target-od", default=None, type=float)
@click.option("--target-growth-rate", default=None, type=float, help="used in PIDMorbidostat only")
@click.option("--duration", default=60, help="Time, in minutes, between every monitor check")
@click.option("--volume", default=None, help="the volume to exchange, mL", type=float)
@click.option("--sensor", default="135/A")
@click.option(
    "--skip-first-run",
    is_flag=True,
    help="Normally IO will run immediately. Set this flag to wait <duration>min before executing.",
)
@click.option("--verbose", "-v", count=True, help="print to std.out")
def click_io_controlling(mode, target_od, target_growth_rate, duration, volume, sensor, skip_first_run, verbose):
    controller = io_controlling(
        mode=mode,
        target_od=target_od,
        target_growth_rate=target_growth_rate,
        duration=duration,
        volume=volume,
        skip_first_run=skip_first_run,
        sensor=sensor,
        verbose=verbose,
    )
    while True:
        next(controller)


if __name__ == "__main__":
    click_io_controlling()

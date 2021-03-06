# -*- coding: utf-8 -*-
"""
Continuously take an optical density reading (more accurately: a backscatter reading, which is a proxy for OD).
This script is designed to run in a background process and push data to MQTT.

>>> nohup python3 -m morbidostat.background_jobs.od_reading &
"""
import time, os, traceback, signal, sys

import click
import RPi.GPIO as GPIO

from morbidostat.utils import log_start, log_stop
from morbidostat.whoami import unit, experiment
from morbidostat.config import config
from morbidostat.pubsub import publish, subscribe_and_callback
from morbidostat.utils.timing import every
from morbidostat.background_jobs import BackgroundJob

GPIO.setmode(GPIO.BCM)
JOB_NAME = os.path.splitext(os.path.basename((__file__)))[0]


class Stirrer(BackgroundJob):
    """
    Send message to "morbidostat/{unit}/{experiment}/stirring/duty_cycle/set" to change the stirring speed.
    Send a "-1" to revert to original speed, as defined in config.ini.
    """

    editable_settings = ["duty_cycle"]

    def __init__(self, duty_cycle, unit, experiment, verbose=0, hertz=50, pin=int(config["rpi_pins"]["fan"])):
        super(Stirrer, self).__init__(job_name=JOB_NAME, verbose=verbose, unit=unit, experiment=experiment)

        self.hertz = hertz
        self.pin = pin

        GPIO.setup(self.pin, GPIO.OUT)
        GPIO.output(self.pin, 0)
        self.pwm = GPIO.PWM(self.pin, self.hertz)
        self._duty_cycle = duty_cycle
        self.start_stirring()

    def start_stirring(self):
        self.pwm.start(90)  # get momentum to start
        time.sleep(0.25)
        self.pwm.ChangeDutyCycle(self.duty_cycle)

    def stop_stirring(self):
        self.pwm.stop()

    def __setattr__(self, name, value):
        if name == "state":
            if value != self.READY:
                try:
                    self.stop_stirring()
                except:
                    pass
        super(Stirrer, self).__setattr__(name, value)

    @property
    def duty_cycle(self):
        return self._duty_cycle

    @duty_cycle.setter
    def duty_cycle(self, value):
        self._duty_cycle = value
        self.pwm.ChangeDutyCycle(self.duty_cycle)


def stirring(duty_cycle=int(config["stirring"][f"duty_cycle{unit}"]), duration=None, verbose=0):
    def terminate(*args):
        GPIO.cleanup()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    publish(f"morbidostat/{unit}/{experiment}/log", f"[stirring]: start stirring with duty cycle={duty_cycle}", verbose=verbose)

    try:
        stirrer = Stirrer(duty_cycle, unit, experiment)
        stirrer.start_stirring()

        if duration is None:
            signal.pause()
        else:
            time.sleep(duration)

    except Exception as e:
        GPIO.cleanup()
        publish(f"morbidostat/{unit}/{experiment}/error_log", f"[stirring] failed with {str(e)}", verbose=verbose)
        raise e
    finally:
        GPIO.cleanup()
    return


@click.command()
@click.option("--duty-cycle", default=int(config["stirring"][f"duty_cycle{unit}"]), help="set the duty cycle")
@click.option(
    "--verbose", "-v", count=True, help="print to std. out (may be redirected to morbidostat.log). Increasing values log more."
)
def click_stirring(duty_cycle, verbose):
    stirring(duty_cycle=duty_cycle, verbose=verbose)


if __name__ == "__main__":
    click_stirring()

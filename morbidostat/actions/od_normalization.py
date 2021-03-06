# -*- coding: utf-8 -*-
"""
TODO: how do I handle a gain that is too small? Ex: an OD is 0.9, but the OD reading starts at max 0.512.

"""
import time
import json
from collections import defaultdict
from statistics import median, variance
import click
import threading
from click import echo, style

from morbidostat.config import config
from morbidostat.utils import log_start, log_stop
from morbidostat.whoami import unit, experiment, hostname
from morbidostat import pubsub
from morbidostat.background_jobs.od_reading import od_reading
from morbidostat.background_jobs.stirring import Stirrer


def stirring(duty_cycle=int(config["stirring"][f"duty_cycle{unit}"]), duration=None, verbose=0):
    # if this look familiar, it's because it is. I can't use `signal` in threads, so I just cp'ed this here.
    publish(f"morbidostat/{unit}/{experiment}/log", f"[stirring]: start stirring with duty cycle={duty_cycle}", verbose=verbose)

    try:
        stirrer = Stirrer(duty_cycle, unit, experiment)
        stirrer.start_stirring()
        time.sleep(duration)

    except Exception as e:
        GPIO.cleanup()
        publish(f"morbidostat/{unit}/{experiment}/error_log", f"[stirring] failed with {str(e)}", verbose=verbose)
        raise e
    finally:
        GPIO.cleanup()
    return


def start_stirring_in_background_thread(verbose):
    thread = threading.Thread(target=stirring, kwargs={"verbose": verbose, "duration": 30})
    thread.start()
    return thread


def green(msg):
    return style(msg, fg="green")


def bold(msg):
    return style(msg, bold=True)


@log_start(unit, experiment)
@log_stop(unit, experiment)
def od_normalization(od_angle_channel, verbose):
    echo()
    echo(bold(f"This task will compute statistics from {hostname}."))

    echo(bold("Starting stirring"))
    stirring_thread = start_stirring_in_background_thread(verbose)
    time.sleep(0.5)
    readings = defaultdict(list)
    sampling_rate = 0.5
    N_samples = 50

    try:

        with click.progressbar(length=N_samples) as bar:
            for count, batched_reading in enumerate(od_reading(od_angle_channel, verbose, sampling_rate)):
                for (sensor, reading) in batched_reading.items():
                    readings[sensor].append(reading)

                bar.update(1)
                if count == N_samples:
                    break

        variances = {}
        medians = {}
        for sensor, reading_series in readings.items():
            # measure the variance and publish. The variance will be used in downstream jobs.
            var = variance(reading_series)
            echo(green(f"variance of {sensor} = {var}"))
            variances[sensor] = var
            # measure the median and publish. The median will be used to normalize the readings in downstream jobs
            med = median(reading_series)
            echo(green(f"median of {sensor} = {med}"))
            medians[sensor] = med

        pubsub.publish(
            f"morbidostat/{unit}/{experiment}/od_normalization/variance",
            json.dumps(variances),
            qos=pubsub.QOS.AT_LEAST_ONCE,
            verbose=verbose,
            retain=True,
        )
        pubsub.publish(
            f"morbidostat/{unit}/{experiment}/od_normalization/median",
            json.dumps(medians),
            qos=pubsub.QOS.AT_LEAST_ONCE,
            verbose=verbose,
            retain=True,
        )
        echo(bold("Gathering of statistics complete. They are stored in the message broker."))
        return
    except:
        pass
    finally:
        # need to gracefully exit the stirring routine
        stirring_thread.join()


@click.command()
@click.option(
    "--od-angle-channel",
    multiple=True,
    default=list(config["od_config"].values()),
    type=click.STRING,
    help="""
pair of angle,channel for optical density reading. Can be invoked multiple times. Ex:

--od-angle-channel 135,0 --od-angle-channel 90,1 --od-angle-channel 45,2

""",
)
@click.option(
    "--verbose", "-v", count=True, help="print to std. out (may be redirected to morbidostat.log). Increasing values log more."
)
def click_od_normalization(od_angle_channel, verbose):
    od_normalization(od_angle_channel, verbose)


if __name__ == "__main__":
    click_od_normalization()

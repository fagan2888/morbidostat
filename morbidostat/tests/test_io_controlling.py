# -*- coding: utf-8 -*-
import time
import pytest

from morbidostat.background_jobs.io_controlling import io_controlling, ControlAlgorithm, PIDMorbidostat, PIDTurbidostat
from morbidostat.background_jobs import events
from morbidostat.whoami import unit, experiment
from morbidostat import pubsub


def pause():
    # to avoid race conditions
    time.sleep(0.5)


def test_silent_algorithm():
    io = io_controlling(mode="silent", volume=None, duration=60, verbose=2)
    pause()
    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", "0.01")
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", "1.0")
    pause()
    assert isinstance(next(io), events.NoEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", "0.02")
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", "1.1")
    pause()
    assert isinstance(next(io), events.NoEvent)


def test_turbidostat_algorithm():
    target_od = 1.0
    algo = io_controlling(mode="turbidostat", target_od=target_od, duration=60, volume=0.25, verbose=2)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.98)
    pause()
    assert isinstance(next(algo), events.NoEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 1.0)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 1.01)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.99)
    pause()
    assert isinstance(next(algo), events.NoEvent)


def test_pid_turbidostat_algorithm():

    target_od = 1.0
    algo = io_controlling(mode="pid_turbidostat", target_od=target_od, volume=0.25, duration=60, verbose=2)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01, verbose=100)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.20, verbose=100)
    pause()
    assert isinstance(next(algo), events.NoEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.81)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.88)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.95)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.97)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)


def test_morbidostat_algorithm():
    target_od = 1.0
    algo = io_controlling(mode=f"morbidostat", target_od=target_od, duration=60, volume=0.25, verbose=2)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.95)
    pause()
    assert isinstance(next(algo), events.NoEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.99)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 1.05)
    pause()
    assert isinstance(next(algo), events.AltMediaEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 1.03)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 1.04)
    pause()
    assert isinstance(next(algo), events.AltMediaEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.01)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.99)
    pause()
    assert isinstance(next(algo), events.DilutionEvent)


def test_pid_morbidostat_algorithm():
    target_growth_rate = 0.09
    algo = io_controlling(mode="pid_morbidostat", target_od=1.0, target_growth_rate=target_growth_rate, duration=60, verbose=2)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.08)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.500)
    pause()
    assert isinstance(next(algo), events.NoEvent)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.08)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.95)
    pause()
    assert isinstance(next(algo), events.AltMediaEvent)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.07)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.95)
    pause()
    assert isinstance(next(algo), events.AltMediaEvent)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.065)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 0.95)
    pause()
    assert isinstance(next(algo), events.AltMediaEvent)


def test_execute_io_action():
    ca = ControlAlgorithm(verbose=2, unit="{unit}", experiment="{experiment}")
    ca.execute_io_action(media_ml=0.65, alt_media_ml=0.15, waste_ml=0.80)


def test_changing_parameters_over_mqtt():

    target_growth_rate = 0.05
    algo = PIDMorbidostat(
        target_growth_rate=target_growth_rate, target_od=1.0, duration=60, verbose=2, unit=unit, experiment=experiment
    )
    assert algo.target_growth_rate == target_growth_rate
    pause()
    pubsub.publish(f"morbidostat/{unit}/{experiment}/io_controlling/target_growth_rate/set", 0.07)
    pause()
    assert algo.target_growth_rate == 0.07


def test_changing_volume_over_mqtt():

    og_volume = 0.5
    algo = PIDTurbidostat(volume=og_volume, target_od=1.0, duration=0.0001, verbose=2, unit=unit, experiment=experiment)
    assert algo.volume == og_volume

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.05)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 1.0)
    pause()
    algo.run()

    pubsub.publish(f"morbidostat/{unit}/{experiment}/io_controlling/volume/set", 1.0)
    pause()

    pubsub.publish(f"morbidostat/{unit}/{experiment}/growth_rate", 0.05)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/od_filtered/135/A", 1.0)
    algo.run()

    assert algo.volume == 1.0


def test_changing_parameters_over_mqtt_with_unknown_parameter():

    algo = ControlAlgorithm(target_growth_rate=0.05, target_od=1.0, duration=60, verbose=2, unit=unit, experiment=experiment)
    pubsub.publish(f"morbidostat/{unit}/{experiment}/io_controlling/garbage/set", 0.07)
    pause()


def test_pause_in_io_controlling():

    algo = ControlAlgorithm(target_growth_rate=0.05, target_od=1.0, duration=60, verbose=2, unit=unit, experiment=experiment)
    assert algo.active == 1
    pause()
    pubsub.publish(f"morbidostat/{unit}/{experiment}/io_controlling/active/set", 1)
    pause()
    assert algo.active == 1
    assert isinstance(algo.run(), events.NoEvent)

    pubsub.publish(f"morbidostat/{unit}/{experiment}/io_controlling/active/set", 0)
    pause()
    assert algo.active == 0

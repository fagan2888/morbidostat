# -*- coding: utf-8 -*-
import pytest
from morbidostat.actions.add_media import add_media
from morbidostat.actions.add_alt_media import add_alt_media
from morbidostat.actions.remove_waste import remove_waste
from morbidostat.actions.clean_tubes import clean_tubes


def test_pump_io():
    add_media(ml=0.1)
    add_alt_media(ml=0.1)
    remove_waste(ml=0.1)

    add_media(duration=0.1)
    add_alt_media(duration=0.1)
    remove_waste(duration=0.1)


def test_pump_io_doesnt_allow_negative():
    with pytest.raises(AssertionError):
        add_media(ml=-1)
    with pytest.raises(AssertionError):
        add_alt_media(ml=-1)
    with pytest.raises(AssertionError):
        remove_waste(ml=-1)

    with pytest.raises(AssertionError):
        add_media(duration=-1)
    with pytest.raises(AssertionError):
        add_alt_media(duration=-1)
    with pytest.raises(AssertionError):
        remove_waste(duration=-1)


def test_cleaning():
    clean_tubes(0.1)


def test_pump_io_cant_set_both_duration_and_ml():
    with pytest.raises(AssertionError):
        add_media(ml=1, duration=1)
    with pytest.raises(AssertionError):
        add_alt_media(ml=1, duration=1)
    with pytest.raises(AssertionError):
        remove_waste(ml=1, duration=1)

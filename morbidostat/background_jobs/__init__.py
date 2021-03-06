# -*- coding: utf-8 -*-
import signal
from typing import Optional, Union
import sys
import atexit
from collections import namedtuple

from morbidostat.pubsub import subscribe_and_callback
from morbidostat import utils
from morbidostat.pubsub import publish, QOS
from morbidostat.whoami import UNIVERSAL_IDENTIFIER
from morbidostat.config import leader_hostname
import paho.mqtt.client as mqtt


def split_topic_for_setting(topic):
    SetAttrSplitTopic = namedtuple("SetAttrSplitTopic", ["unit", "experiment", "job_name", "attr"])
    v = topic.split("/")
    assert len(v) == 6, "something is wrong"
    return SetAttrSplitTopic(v[1], v[2], v[3], v[4])


class BackgroundJob:

    """
    This class handles the fanning out of class attributes, and the setting of those attributes. Use
    `morbidostat/<unit>/<experiment>/<job_name>/<attr>/set` to set an attribute.


    So this class controls most of the Homie convention that we follow:

    1. The device lifecycle: init -> ready -> disconnect (or lost).
        1. The job starts in `init`, where we publish `editable_settings` is a list  of variables that will be sent
            to the broker on initialization and retained.
        2. The job moves to `ready`.
        3. We catch key interrupts and kill signals from the underlying machine, and set the state to
           `disconnected`. This should not empty the attributes, since they may be needed upon node restart.
        4. If the job exits otherwise (kill -9 or power loss), the state is `lost`, and a last-will saying so is broadcast.
    2. Attributes are broadcast under $properties, and each has $settable set to True. This isn't used at the moment.

    """

    # Homie device lifecycle
    INIT = "init"
    READY = "ready"
    DISCONNECTED = "disconnected"
    SLEEPING = "sleeping"
    LOST = "lost"

    editable_settings = []

    def __init__(self, job_name: str, verbose: int = 0, experiment: Optional[str] = None, unit: Optional[str] = None) -> None:
        self.job_name = job_name
        self.experiment = experiment
        self.verbose = verbose
        self.unit = unit
        self.editable_settings = self.editable_settings + ["state"]

        self.set_state(self.INIT)
        self.set_state(self.READY)

    def init(self):
        self.state = self.INIT

        def disconnect_gracefully(*args):
            self.set_state("disconnected")

        signal.signal(signal.SIGTERM, disconnect_gracefully)
        signal.signal(signal.SIGINT, disconnect_gracefully)
        atexit.register(disconnect_gracefully)

        self.send_will_to_leader()
        self.declare_settable_properties_to_broker()
        self.start_general_passive_listeners()

    def ready(self):
        self.state = self.READY

    def sleeping(self):
        self.state = self.SLEEPING

    def disconnected(self):
        self.state = self.DISCONNECTED
        self._client.disconnect()

    def declare_settable_properties_to_broker(self):
        # this follows some of the Homie convention: https://homieiot.github.io/specification/
        publish(
            f"morbidostat/{self.unit}/{self.experiment}/{self.job_name}/$properties",
            ",".join(self.editable_settings),
            verbose=self.verbose,
            qos=QOS.AT_LEAST_ONCE,
        )

        for setting in self.editable_settings:
            publish(
                f"morbidostat/{self.unit}/{self.experiment}/{self.job_name}/{setting}/$settable",
                True,
                verbose=self.verbose,
                qos=QOS.AT_LEAST_ONCE,
            )

    def set_state(self, new_state):
        if hasattr(self, "state"):
            current_state = self.state
            publish(
                f"morbidostat/{self.unit}/{self.experiment}/log",
                f"[{self.job_name}] Updated state from {current_state} to {new_state}.",
                verbose=self.verbose,
            )
        getattr(self, new_state)()

    def set_attr_from_message(self, message):

        new_value = message.payload.decode()
        info_from_topic = split_topic_for_setting(message.topic)
        attr = info_from_topic.attr

        if attr == "$state":
            return self.set_state(new_value)

        if attr not in self.editable_settings:
            return

        assert hasattr(self, attr), f"{self.job_name} has no attr {attr}."
        previous_value = getattr(self, attr)

        try:
            # make sure to cast the input to the same value
            setattr(self, attr, type(previous_value)(new_value))
        except:
            setattr(self, attr, new_value)

        publish(
            f"morbidostat/{self.unit}/{self.experiment}/log",
            f"[{self.job_name}] Updated {attr} from {previous_value} to {getattr(self, attr)}.",
            verbose=self.verbose,
        )

    def publish_attr(self, attr: str) -> None:
        if attr == "state":
            attr_name = "$state"
        else:
            attr_name = attr

        publish(
            f"morbidostat/{self.unit}/{self.experiment}/{self.job_name}/{attr_name}",
            getattr(self, attr),
            verbose=self.verbose,
            retain=True,
            qos=QOS.EXACTLY_ONCE,
        )

    def start_general_passive_listeners(self) -> None:

        subscribe_and_callback(
            self.set_attr_from_message, f"morbidostat/{self.unit}/{self.experiment}/{self.job_name}/+/set", qos=QOS.EXACTLY_ONCE
        )

        # everyone listens to $unit (TODO: even leader?)
        subscribe_and_callback(
            self.set_attr_from_message,
            f"morbidostat/{UNIVERSAL_IDENTIFIER}/{self.experiment}/{self.job_name}/+/set",
            qos=QOS.EXACTLY_ONCE,
        )

    def send_will_to_leader(self):
        last_will = {
            "topic": f"morbidostat/{self.unit}/{self.experiment}/{self.job_name}/$state",
            "payload": self.LOST,
            "qos": QOS.EXACTLY_ONCE,
            "retain": True,
        }
        self._client = mqtt.Client()
        self._client.connect(leader_hostname)
        self._client.will_set(**last_will)

    def __setattr__(self, name: str, value: Union[int, str]) -> None:
        super(BackgroundJob, self).__setattr__(name, value)
        if (name in self.editable_settings) and hasattr(self, name):
            self.publish_attr(name)

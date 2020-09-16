import sys
import configparser
import socket

def get_leader_hostname():
    if "pytest" in sys.modules:
        return "localhost"
    else:
        return get_config()["network"]["leader_hostname"]

def get_hostname():
    if "pytest" in sys.modules:
        return "localhost"
    else:
        return socket.gethostname()

def get_config():
    config = configparser.ConfigParser()
    config.read("config.ini")
    return config

def get_unit_from_hostname():
    import re
    hostname = get_hostname()

    if hostname == "leader":
        return "0"
    elif hostname == "localhost":
        return "0"
    elif re.match("morbidostat(\d)", hostname):
        # TODO: turn me into walrus operator
        return re.match("morbidostat(\d)", hostname).groups()[0]
    else:
        return None


def pump_ml_to_duration(ml, rate, bias):
    """
    ml = rate * duration + bias
    """
    duration = (ml - bias) / rate
    assert duration >= 0, "pump duration is negative"
    return duration


def execute_sql_statement(SQL):
    import pandas as pd
    import sqlite3

    db_location = config["data"]["observation_database"]
    conn = sqlite3.connect(db_location)
    df = pd.read_sql_query(SQL, conn)
    conn.close()
    return df


leader_hostname = get_leader_hostname()
config = get_config()
# create_tables.sql

CREATE TABLE IF NOT EXISTS od_readings_raw
    timestamp              TEXT  NOT NULL
    measurement_source     TEXT  NOT NULL
    od_reading_v           REAL  NOT NULL
    experiment             TEXT  NOT NULL

CREATE TABLE IF NOT EXISTS od_readings_filtered
    timestamp              TEXT  NOT NULL
    measurement_source     TEXT  NOT NULL
    od_reading_v           REAL  NOT NULL
    experiment             TEXT  NOT NULL

CREATE TABLE IF NOT EXISTS dilution_events
    timestamp              TEXT  NOT NULL
    experiment             TEXT  NOT NULL
    event                  TEXT  NOT NULL
    volume_change_ml       REAL  NOT NULL


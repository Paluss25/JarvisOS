import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.dos.fit_import import (
    _field_dict_from_frame,
    _promote_record,
    _promote_session,
)


class FakeField:
    def __init__(self, name, value, units=None):
        self.name = name
        self.value = value
        self.units = units


class FakeFrame:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields


def test_field_dict_from_frame_keeps_values_and_units():
    frame = FakeFrame("record", [FakeField("heart_rate", 142, "bpm")])

    fields, units = _field_dict_from_frame(frame)

    assert fields == {"heart_rate": 142}
    assert units == {"heart_rate": "bpm"}


def test_promote_session_maps_known_fit_fields():
    start = dt.datetime(2026, 4, 27, 10, 30, tzinfo=dt.timezone.utc)
    fields = {
        "sport": "running",
        "sub_sport": "generic",
        "start_time": start,
        "total_elapsed_time": 3600,
        "total_timer_time": 3500,
        "total_distance": 10200,
        "total_calories": 800,
        "avg_heart_rate": 145,
        "max_heart_rate": 171,
        "avg_cadence": 82,
        "avg_power": 230,
        "total_ascent": 120,
        "total_training_effect": 3.1,
        "total_anaerobic_training_effect": 1.2,
    }

    promoted = _promote_session(fields)

    assert promoted["sport"] == "running"
    assert promoted["start_time"] == start
    assert promoted["total_elapsed_time_s"] == 3600
    assert promoted["total_distance_m"] == 10200
    assert promoted["training_effect"] == 3.1
    assert promoted["anaerobic_training_effect"] == 1.2


def test_promote_record_converts_semicircle_positions_to_degrees():
    timestamp = dt.datetime(2026, 4, 27, 10, 31, tzinfo=dt.timezone.utc)
    fields = {
        "timestamp": timestamp,
        "position_lat": 536870912,
        "position_long": 1073741824,
        "distance": 1000,
        "altitude": 250.5,
        "heart_rate": 140,
        "cadence": 80,
        "speed": 3.5,
        "power": 210,
        "temperature": 18,
        "fractional_cadence": 0.5,
    }

    promoted = _promote_record(fields)

    assert promoted["timestamp"] == timestamp
    assert promoted["position_lat"] == pytest.approx(45.0)
    assert promoted["position_long"] == pytest.approx(90.0)
    assert promoted["speed_mps"] == 3.5
    assert promoted["power_w"] == 210

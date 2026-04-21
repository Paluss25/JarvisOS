from datetime import datetime
from zoneinfo import ZoneInfo
from src.agent_runner.scheduler.cron_store import parse_schedule, is_due, was_missed, CronEntry

_TZ = ZoneInfo("Europe/Rome")


def test_parse_interval_15m():
    kind, params = parse_schedule("interval@15m")
    assert kind == "interval"
    assert params == {"minutes": 15}


def test_parse_interval_5m():
    kind, params = parse_schedule("interval@5m")
    assert kind == "interval"
    assert params["minutes"] == 5


def test_parse_interval_invalid():
    import pytest
    with pytest.raises(ValueError, match="interval"):
        parse_schedule("interval@45m")


def test_is_due_interval_never_ran():
    entry = CronEntry({
        "id": "aaa", "name": "poll", "schedule": "interval@15m",
        "prompt": "check", "last_run": None, "enabled": True, "builtin": True,
    })
    now = datetime(2026, 4, 21, 10, 0, 0, tzinfo=_TZ)
    assert is_due(entry, now) is True


def test_is_due_interval_elapsed():
    entry = CronEntry({
        "id": "bbb", "name": "poll", "schedule": "interval@15m",
        "prompt": "check",
        "last_run": datetime(2026, 4, 21, 9, 44, 0, tzinfo=_TZ).isoformat(),
        "enabled": True, "builtin": True,
    })
    now = datetime(2026, 4, 21, 10, 0, 0, tzinfo=_TZ)  # 16 min later
    assert is_due(entry, now) is True


def test_is_due_interval_not_elapsed():
    entry = CronEntry({
        "id": "ccc", "name": "poll", "schedule": "interval@15m",
        "prompt": "check",
        "last_run": datetime(2026, 4, 21, 9, 50, 0, tzinfo=_TZ).isoformat(),
        "enabled": True, "builtin": True,
    })
    now = datetime(2026, 4, 21, 10, 0, 0, tzinfo=_TZ)  # only 10 min later
    assert is_due(entry, now) is False


def test_was_missed_interval_always_false():
    entry = CronEntry({
        "id": "ddd", "name": "poll", "schedule": "interval@15m",
        "prompt": "check", "last_run": None, "enabled": True, "builtin": True,
    })
    now = datetime(2026, 4, 21, 10, 0, 0, tzinfo=_TZ)
    assert was_missed(entry, now) is False

from datetime import datetime
import json
from zoneinfo import ZoneInfo
from agent_runner.scheduler.cron_store import CronStore, parse_schedule, is_due, was_missed, CronEntry

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


def test_is_due_interval_exactly_elapsed():
    entry = CronEntry({
        "id": "eee", "name": "poll", "schedule": "interval@15m",
        "prompt": "check",
        "last_run": datetime(2026, 4, 21, 9, 45, 0, tzinfo=_TZ).isoformat(),
        "enabled": True, "builtin": True,
    })
    now = datetime(2026, 4, 21, 10, 0, 0, tzinfo=_TZ)  # exactly 15 min later
    assert is_due(entry, now) is True


def test_was_missed_interval_always_false():
    entry = CronEntry({
        "id": "ddd", "name": "poll", "schedule": "interval@15m",
        "prompt": "check", "last_run": None, "enabled": True, "builtin": True,
    })
    now = datetime(2026, 4, 21, 10, 0, 0, tzinfo=_TZ)
    assert was_missed(entry, now) is False


def test_seed_updates_existing_builtin_prompt_without_resetting_runtime_state(tmp_path):
    existing_last_run = datetime(2026, 5, 6, 8, 45, tzinfo=_TZ).isoformat()
    (tmp_path / "crons.json").write_text(
        json.dumps(
            {
                "version": 1,
                "crons": [
                    {
                        "id": "abc12345",
                        "name": "morning_briefing",
                        "schedule": "daily@08:45",
                        "prompt": "old prompt",
                        "session_id": "heartbeat-morning",
                        "telegram_notify": True,
                        "enabled": True,
                        "created_at": "2026-04-18T09:10:44+02:00",
                        "last_run": existing_last_run,
                        "last_status": "ok",
                        "last_error": None,
                        "builtin": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    store = CronStore(tmp_path)
    store.seed(
        [
            {
                "name": "morning_briefing",
                "schedule": "daily@08:50",
                "prompt": "new prompt",
                "session_id": "heartbeat-new",
                "telegram_notify": False,
                "builtin": True,
            }
        ]
    )

    entry = store.get("abc12345")
    assert entry is not None
    assert entry.prompt == "new prompt"
    assert entry.schedule == "daily@08:50"
    assert entry.session_id == "heartbeat-new"
    assert entry.telegram_notify is False
    assert entry.last_run == existing_last_run
    assert entry.last_status == "ok"

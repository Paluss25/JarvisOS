# tests/test_daily_logger_multiuser.py
import datetime
import sys
from pathlib import Path
import tempfile
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_runner.memory.daily_logger import DailyLogger


def test_no_user_id_writes_to_memory_root(tmp_path):
    dl = DailyLogger(tmp_path)
    dl.log("system entry")
    today = datetime.date.today().isoformat()
    expected = tmp_path / "memory" / f"{today}.md"
    assert expected.exists()
    assert "system entry" in expected.read_text()


def test_user_id_writes_to_user_subdir(tmp_path):
    dl = DailyLogger(tmp_path, user_id=12345)
    dl.log("user entry")
    today = datetime.date.today().isoformat()
    expected = tmp_path / "memory" / "user-12345" / f"{today}.md"
    assert expected.exists()
    assert "user entry" in expected.read_text()


def test_different_users_are_isolated(tmp_path):
    dl_a = DailyLogger(tmp_path, user_id=111)
    dl_b = DailyLogger(tmp_path, user_id=222)
    dl_a.log("message from user A")
    dl_b.log("message from user B")
    today = datetime.date.today().isoformat()
    text_a = (tmp_path / "memory" / "user-111" / f"{today}.md").read_text()
    text_b = (tmp_path / "memory" / "user-222" / f"{today}.md").read_text()
    assert "message from user A" in text_a
    assert "message from user A" not in text_b
    assert "message from user B" in text_b
    assert "message from user B" not in text_a


def test_read_today_returns_user_log(tmp_path):
    dl = DailyLogger(tmp_path, user_id=99)
    dl.log("check read")
    assert "check read" in dl.read_today()


def test_read_today_system_does_not_see_user_log(tmp_path):
    DailyLogger(tmp_path, user_id=99).log("user-only")
    assert "user-only" not in DailyLogger(tmp_path).read_today()


def test_read_date_with_user_id(tmp_path):
    dl = DailyLogger(tmp_path, user_id=42)
    dl.log("dated entry")
    today = datetime.date.today()
    assert "dated entry" in dl.read_date(today)

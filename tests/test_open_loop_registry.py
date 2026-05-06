"""Tests for structured open-loop freshness handling."""

from datetime import datetime, timezone
import json

from agent_runner.client import _build_system_prompt
from agent_runner.memory.open_loop_registry import render_open_loop_context
from agent_runner.memory.workspace_loader import load_workspace_context


def test_open_loop_context_prioritizes_fresh_open_and_recent_resolved(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "open_loops.json").write_text(
        json.dumps(
            {
                "open_loops": [
                    {
                        "id": "cfo-pool",
                        "title": "CFO patch approval overdue",
                        "status": "resolved",
                        "owner": "cio",
                        "updated_at": "2026-05-06T10:00:00+02:00",
                        "evidence": "cfo-data-service:1.0.1 live and healthy",
                    },
                    {
                        "id": "alloy-pipeline",
                        "title": "Verify Alloy pipeline",
                        "status": "open",
                        "owner": "cio",
                        "last_verified_at": "2026-05-06T08:30:00+02:00",
                        "evidence": "fresh live check required",
                    },
                    {
                        "id": "grafana-contact-point",
                        "title": "Grafana contact point pending",
                        "status": "open",
                        "owner": "cio",
                        "last_verified_at": "2026-05-03T08:30:00+02:00",
                        "evidence": "old narrative memory",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    rendered = render_open_loop_context(
        tmp_path,
        now=datetime(2026, 5, 6, 10, 30, tzinfo=timezone.utc),
        fresh_hours=48,
    )

    assert "OPEN: alloy-pipeline" in rendered
    assert "RESOLVED: cfo-pool" in rendered
    assert "STALE_NEEDS_REVERIFY: grafana-contact-point" in rendered
    assert "do not report as an active action" in rendered


def test_workspace_prompt_includes_freshness_guard_before_long_term_memory(tmp_path):
    for filename in ("SOUL.md", "AGENTS.md", "USER.md"):
        (tmp_path / filename).write_text(filename, encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text(
        "CFO patch approval overdue and pending.",
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "open_loops.json").write_text(
        json.dumps(
            {
                "open_loops": [
                    {
                        "id": "cfo-pool",
                        "title": "CFO patch approval overdue",
                        "status": "resolved",
                        "updated_at": "2026-05-06T10:00:00+02:00",
                        "evidence": "live deployment verified",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    ctx = load_workspace_context(tmp_path)
    prompt = _build_system_prompt(ctx)

    assert "## Memory Freshness Guard" in prompt
    assert "## Open Loop Registry" in prompt
    assert prompt.index("## Memory Freshness Guard") < prompt.index("## Long-Term Memory")
    assert "RESOLVED: cfo-pool" in prompt
    assert "Do not reopen stale MEMORY.md" in prompt

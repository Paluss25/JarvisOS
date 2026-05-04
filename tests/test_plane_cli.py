import json

from integrations.plane.cli import main


def _handler_result(body: str) -> dict:
    return {"content": [{"type": "text", "text": body}]}


def test_project_subcommand_calls_project_handler(capsys):
    captured = {}

    def fake_project(args):
        captured.update(args)
        return _handler_result(json.dumps({"id": "fake-project-1"}))

    exit_code = main(
        [
            "project",
            "--domain",
            "jarvios-platform",
            "--title",
            "Plane task sync",
            "--description",
            "Add Plane integration.",
            "--external-id",
            "projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md",
            "--priority",
            "high",
        ],
        handlers={"plane_sync_project": fake_project},
    )

    out = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(out.out)["id"] == "fake-project-1"
    assert out.err == ""
    assert captured == {
        "domain": "jarvios-platform",
        "title": "Plane task sync",
        "description": "Add Plane integration.",
        "external_id": "projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md",
        "priority": "high",
    }


def test_incident_subcommand_calls_incident_handler_with_repeatable_resolution_plan(capsys):
    captured = {}

    def fake_incident(args):
        captured.update(args)
        return _handler_result(json.dumps({"id": "fake-incident-1"}))

    exit_code = main(
        [
            "incident",
            "--service",
            "traefik",
            "--title",
            "Routing failure",
            "--problem",
            "Dashboard unavailable",
            "--severity",
            "p1",
            "--status",
            "triaged",
            "--root-cause",
            "Bad label",
            "--resolution-plan",
            "Inspect labels",
            "--resolution-plan",
            "Redeploy jarvios-platform",
        ],
        handlers={"plane_sync_incident": fake_incident},
    )

    out = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(out.out)["id"] == "fake-incident-1"
    assert out.err == ""
    assert captured["domain"] == "homelab-operations"
    assert captured["resolution_plan"] == [
        "Inspect labels",
        "Redeploy jarvios-platform",
    ]
    assert captured["service"] == "traefik"
    assert captured["title"] == "Routing failure"
    assert captured["problem"] == "Dashboard unavailable"
    assert captured["severity"] == "p1"
    assert captured["status"] == "triaged"
    assert captured["root_cause"] == "Bad label"


def test_handler_failure_text_returns_exit_code_2_and_writes_stderr(capsys):
    def fake_project(_args):
        return _handler_result("Plane operation failed: unavailable")

    exit_code = main(
        [
            "project",
            "--domain",
            "jarvios-platform",
            "--title",
            "Plane task sync",
            "--description",
            "Add Plane integration.",
            "--external-id",
            "projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md",
        ],
        handlers={"plane_sync_project": fake_project},
    )

    out = capsys.readouterr()
    assert exit_code == 2
    assert out.out == ""
    assert out.err == "Plane operation failed: unavailable\n"


def test_plan_subcommand_parses_plan_and_calls_plan_handler(tmp_path, capsys):
    plan_path = tmp_path / "2026-05-04-plane-task-sync.md"
    plan_path.write_text(
        """---
project: executive_secretariat_agent
domain: jarvios-platform
---

# Plane task sync

**Goal:** Sync plans to Plane.

## P0 — Foundation

### P0.T1 — Add config
""",
        encoding="utf-8",
    )
    captured = {}

    def fake_plan(args):
        captured.update(args)
        return _handler_result(json.dumps({"id": "fake-plan-1"}))

    exit_code = main(
        [
            "plan",
            str(plan_path),
        ],
        handlers={"plane_sync_plan": fake_plan},
    )

    out = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(out.out)["id"] == "fake-plan-1"
    assert out.err == ""
    assert captured["path"] == str(plan_path)
    assert captured["title"] == "Plane task sync"
    assert captured["domain"] == "jarvios-platform"
    assert [phase.id for phase in captured["phases"]] == ["P0"]
    assert [task.id for task in captured["tasks"]] == ["P0.T1"]

import json

from agents.cio.plane_payload import (
    build_incident_resolution_payload,
    build_plane_incident_cli_args,
)
from integrations.plane.cli import main


def _handler_result(body: str) -> dict:
    return {"content": [{"type": "text", "text": body}]}


def test_build_incident_resolution_payload_normalizes_resolution_plan():
    payload = build_incident_resolution_payload(
        {
            "service": "traefik",
            "title": "Routing failure",
            "severity": "P1",
            "status": "triaged",
            "problem": "Dashboard unavailable",
            "root_cause": "Wrong service port",
            "resolution_plan": "Inspect labels\n- Redeploy service",
        }
    )

    assert payload["type"] == "incident_resolution_update"
    assert payload["source_agent"] == "cio"
    assert payload["severity"] == "p1"
    assert payload["resolution_plan"] == ["Inspect labels", "Redeploy service"]
    assert payload["domain"] == "homelab-operations"


def test_build_plane_incident_cli_args_invokes_plane_cli(capsys):
    captured = {}

    def fake_handler(args):
        captured.update(args)
        return _handler_result(json.dumps({"id": "fake-incident-1"}))

    argv = build_plane_incident_cli_args(
        {
            "service": "traefik",
            "title": "Routing failure",
            "severity": "P1",
            "status": "triaged",
            "problem": "Dashboard unavailable",
            "root_cause": "Wrong service port",
            "resolution_plan": ["Inspect labels", "Redeploy service"],
        }
    )

    exit_code = main(argv, handlers={"plane_sync_incident": fake_handler})

    out = capsys.readouterr()
    assert exit_code == 0
    assert captured["resolution_plan"] == ["Inspect labels", "Redeploy service"]
    assert captured["domain"] == "homelab-operations"
    assert json.loads(out.out)["id"] == "fake-incident-1"

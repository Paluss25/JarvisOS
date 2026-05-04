import json

from agents.mt.plane_tools import build_plane_tool_handlers


class FakeService:
    def __init__(self):
        self.synced = []

    def resolve_project_id(self, domain=""):
        return "project-ai"

    def sync_work_item(self, project_id, draft):
        self.synced.append((project_id, draft))
        return {"id": "wi-1", "name": draft.name, "external_id": draft.external_id}

    def sync_incident_with_steps(self, update, domain="homelab-operations"):
        return {"id": "incident-1", "name": update.title, "external_id": update.external_id()}


def _text(result):
    return result["content"][0]["text"]


def test_plane_sync_project_tool_creates_parent_work_item():
    service = FakeService()
    handlers = build_plane_tool_handlers(lambda: service)

    result = handlers["plane_sync_project"]({
        "domain": "jarvios-platform",
        "title": "Plane task sync",
        "description": "Add <maintenance> & Plane integration.",
        "external_id": "projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md",
    })

    body = json.loads(_text(result))
    assert body["id"] == "wi-1"
    assert body["external_id"] == "projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md"
    _project_id, draft = service.synced[0]
    assert draft.description_html == "<p>Add &lt;maintenance&gt; &amp; Plane integration.</p>"


def test_plane_sync_incident_tool_accepts_cio_payload():
    handlers = build_plane_tool_handlers(lambda: FakeService())

    result = handlers["plane_sync_incident"]({
        "service": "traefik",
        "title": "Routing failure",
        "severity": "p1",
        "status": "triaged",
        "problem": "Dashboard unavailable",
        "root_cause": "Bad label",
        "resolution_plan": ["Inspect labels"],
    })

    body = json.loads(_text(result))
    assert body["id"] == "incident-1"

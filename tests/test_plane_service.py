from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from integrations.plane.config import PlaneConfig
from integrations.plane.client import PlaneAPIError
from integrations.plane.models import IncidentResolutionUpdate, PlaneWorkItemDraft
from integrations.plane.plan_parser import ParsedPhase, ParsedPlan, ParsedTask
from integrations.plane.service import PlaneSyncService, format_plane_error


class FakePlaneClient:
    def __init__(self):
        self.config = PlaneConfig(
            api_key="plane_secret_key",
            workspace_slug="homelab",
            default_project_id="project-default",
            project_map={"homelab-operations": "project-ops"},
        )
        self.search_results = []
        self.searches = []
        self.created = []
        self.updated = []
        self.comments = []

    def search_work_items(self, query, project_id=None):
        self.searches.append((query, project_id))
        return list(self.search_results)

    def create_work_item(self, project_id, payload):
        self.created.append((project_id, payload))
        return {"id": "created-item", "project_id": project_id, **payload}

    def update_work_item(self, project_id, work_item_id, payload):
        self.updated.append((project_id, work_item_id, payload))
        return {"id": work_item_id, "project_id": project_id, **payload}

    def add_comment(self, project_id, work_item_id, comment_html, external_source, external_id):
        self.comments.append((project_id, work_item_id, comment_html, external_source, external_id))
        return {"id": "comment-1", "work_item_id": work_item_id}


class UniqueIdFakePlaneClient(FakePlaneClient):
    def create_work_item(self, project_id, payload):
        work_item_id = f"created-{len(self.created) + 1}"
        self.created.append((project_id, payload))
        return {"id": work_item_id, "project_id": project_id, **payload}


class ConflictPlaneClient(FakePlaneClient):
    def create_work_item(self, project_id, payload):
        self.created.append((project_id, payload))
        raise PlaneAPIError(
            'Plane API request failed with HTTP 409: '
            '{"error":"Issue with the same external id and external source already exists",'
            '"id":"existing-conflict"}'
        )


class CountingPlaneSyncService(PlaneSyncService):
    def __init__(self, client):
        super().__init__(client=client)
        self.project_resolutions = 0

    def resolve_project_id(self, domain=""):
        self.project_resolutions += 1
        return super().resolve_project_id(domain)


def test_format_plane_error_redacts_api_keys():
    message = format_plane_error(RuntimeError("Plane API error 401: plane_api_secret <rejected>"))

    assert "401" in message
    assert "plane_api_secret" not in message
    assert "secret" not in message
    assert "&lt;rejected&gt;" in message
    assert "Plane operation failed" in message


def test_sync_work_item_creates_when_external_id_has_no_exact_match():
    client = FakePlaneClient()
    client.search_results = [{"id": "near-match", "external_id": "ticket-other"}]
    service = PlaneSyncService(client=client)
    draft = PlaneWorkItemDraft(
        name="Fix router",
        description_html="<p>Router is offline.</p>",
        priority="high",
        external_id="ticket-123",
    )

    result = service.sync_work_item("project-ops", draft)

    assert result["id"] == "created-item"
    assert client.searches == [("ticket-123", "project-ops")]
    assert client.created == [("project-ops", draft.to_payload())]
    assert client.updated == []


def test_sync_work_item_updates_when_external_id_exists():
    client = FakePlaneClient()
    client.search_results = [
        {"id": "wrong-item", "external_id": "ticket-other"},
        {"id": "existing-item", "external_id": "ticket-123"},
    ]
    service = PlaneSyncService(client=client)
    draft = PlaneWorkItemDraft(
        name="Fix router",
        description_html="<p>Router is offline.</p>",
        priority="high",
        external_id="ticket-123",
    )

    result = service.sync_work_item("project-ops", draft)

    assert result["id"] == "existing-item"
    assert client.created == []
    assert client.updated == [("project-ops", "existing-item", draft.to_payload())]


def test_sync_work_item_updates_when_create_reports_external_id_conflict():
    client = ConflictPlaneClient()
    service = PlaneSyncService(client=client)
    draft = PlaneWorkItemDraft(
        name="Existing plan",
        description_html="<p>Updated.</p>",
        priority="medium",
        external_source="homelab-planning",
        external_id="projects/example/plan.md",
    )

    result = service.sync_work_item("project-ops", draft)

    assert result["id"] == "existing-conflict"
    assert client.created == [("project-ops", draft.to_payload())]
    assert client.updated == [("project-ops", "existing-conflict", draft.to_payload())]


def test_resolve_project_id_uses_project_map_and_falls_back_to_default():
    service = PlaneSyncService(client=FakePlaneClient())

    assert service.resolve_project_id("homelab-operations") == "project-ops"
    assert service.resolve_project_id("unknown-domain") == "project-default"
    assert service.resolve_project_id() == "project-default"


def test_add_progress_comment_delegates_to_client():
    client = FakePlaneClient()
    service = PlaneSyncService(client=client)

    result = service.add_progress_comment(
        "project-ops",
        "work-item-1",
        "<p>Restarted worker.</p>",
        external_source="jarvisos-cio",
        external_id="comment-123",
    )

    assert result == {"id": "comment-1", "work_item_id": "work-item-1"}
    assert client.comments == [
        ("project-ops", "work-item-1", "<p>Restarted worker.</p>", "jarvisos-cio", "comment-123")
    ]


def test_sync_incident_update_builds_escaped_cio_work_item_with_priority_and_project_lookup():
    client = FakePlaneClient()
    service = PlaneSyncService(client=client)
    update = IncidentResolutionUpdate(
        service="router",
        title="WAN <down>",
        severity="critical",
        status="investigating",
        problem="Packet loss > 90% & rising",
        root_cause="ISP <maintenance>",
        resolution_plan=["Fail over to LTE", "Open ISP ticket & monitor"],
    )

    result = service.sync_incident_update(update)

    assert result["id"] == "created-item"
    project_id, payload = client.created[0]
    assert project_id == "project-ops"
    assert payload["name"] == "[router] WAN <down>"
    assert payload["priority"] == "urgent"
    assert payload["external_source"] == "jarvisos-cio"
    assert payload["external_id"] == update.external_id()
    assert "&lt;maintenance&gt;" in payload["description_html"]
    assert "Packet loss &gt; 90% &amp; rising" in payload["description_html"]
    assert "Open ISP ticket &amp; monitor" in payload["description_html"]
    assert "<maintenance>" not in payload["description_html"]


def test_sync_incident_with_steps_creates_parent_and_child_work_items_with_parent_link():
    client = FakePlaneClient()
    service = CountingPlaneSyncService(client=client)
    update = IncidentResolutionUpdate(
        service="traefik",
        title="Dashboard routing failure",
        severity="p1",
        status="triaged",
        problem="jarvis-dashboard is unavailable",
        root_cause="Router points to wrong service port",
        resolution_plan=["Inspect local Traefik labels", "Redeploy jarvios-platform"],
    )

    result = service.sync_incident_with_steps(update)

    assert result["id"] == "created-item"
    assert len(client.created) == 3
    parent_project_id, parent_payload = client.created[0]
    assert parent_project_id == "project-ops"
    assert parent_payload["name"] == "[traefik] Dashboard routing failure"
    assert parent_payload["priority"] == "high"
    assert parent_payload["external_source"] == "jarvisos-cio"
    assert parent_payload["external_id"] == update.external_id()
    assert "jarvis-dashboard is unavailable" in parent_payload["description_html"]
    assert "Router points to wrong service port" in parent_payload["description_html"]

    first_child_project_id, first_child_payload = client.created[1]
    assert first_child_project_id == "project-ops"
    assert first_child_payload["name"] == "Inspect local Traefik labels"
    assert first_child_payload["priority"] == "high"
    assert first_child_payload["external_source"] == "jarvisos-cio"
    assert first_child_payload["external_id"] == f"{update.external_id()}:step:1"
    assert first_child_payload["parent"] == result["id"]
    assert "parent_id" not in first_child_payload
    assert "Remediation step 1" in first_child_payload["description_html"]
    assert "Dashboard routing failure" in first_child_payload["description_html"]

    second_child_payload = client.created[2][1]
    assert second_child_payload["name"] == "Redeploy jarvios-platform"
    assert second_child_payload["external_id"] == f"{update.external_id()}:step:2"
    assert second_child_payload["parent"] == result["id"]
    assert "Redeploy jarvios-platform" in second_child_payload["description_html"]
    assert service.project_resolutions == 1


def test_sync_parsed_plan_creates_parent_phases_and_tasks_with_external_ids():
    client = UniqueIdFakePlaneClient()
    service = PlaneSyncService(client=client)
    plan = ParsedPlan(
        path=Path("projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md"),
        title="Executive Secretariat Plane Task Sync",
        project="executive_secretariat_agent",
        domain="homelab-operations",
        goal="Sync approved plans to Plane.",
        external_id="projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md",
        phases=[
            ParsedPhase(
                id="P0",
                name="Foundation",
                external_id="projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md#P0",
            )
        ],
        tasks=[
            ParsedTask(
                id="P0.T1",
                name="Add config",
                phase_id="P0",
                external_id="projects/executive_secretariat_agent/2026-05-04-plane-task-sync.md#P0.T1",
            )
        ],
    )

    result = service.sync_parsed_plan(plan)

    assert result["id"] == "created-1"
    assert len(client.created) == 3
    parent_project_id, parent_payload = client.created[0]
    phase_project_id, phase_payload = client.created[1]
    task_project_id, task_payload = client.created[2]

    assert parent_project_id == "project-ops"
    assert parent_payload["name"] == "Executive Secretariat Plane Task Sync"
    assert parent_payload["external_source"] == "homelab-planning"
    assert parent_payload["external_id"] == plan.external_id
    assert "Sync approved plans to Plane." in parent_payload["description_html"]

    assert phase_project_id == "project-ops"
    assert phase_payload["name"] == "P0 - Foundation"
    assert phase_payload["parent"] == result["id"]
    assert phase_payload["external_id"] == plan.phases[0].external_id

    assert task_project_id == "project-ops"
    assert task_payload["name"] == "P0.T1 - Add config"
    assert task_payload["parent"] == "created-2"
    assert task_payload["external_id"] == plan.tasks[0].external_id

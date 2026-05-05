import os
import sys
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from integrations.plane.client import PlaneAPIError, PlaneClient
from integrations.plane.config import PlaneConfig, load_plane_config
from integrations.plane.models import IncidentResolutionUpdate, PlaneWorkItemDraft, priority_from_severity


def test_load_plane_config_reads_env_without_exposing_key(monkeypatch):
    monkeypatch.setenv("PLANE_API_KEY", "plane_api_secret")
    monkeypatch.setenv("PLANE_BASE_URL", "https://api.plane.so")
    monkeypatch.setenv("PLANE_WORKSPACE_SLUG", "homelab")
    monkeypatch.setenv("PLANE_DEFAULT_PROJECT_ID", "project-123")
    monkeypatch.setenv("PLANE_PROJECT_MAP_JSON", '{"jarvios-platform": "project-ai"}')

    config = load_plane_config()

    assert config.api_key == "plane_api_secret"
    assert config.base_url == "https://api.plane.so"
    assert config.workspace_slug == "homelab"
    assert config.default_project_id == "project-123"
    assert config.project_map == {"jarvios-platform": "project-ai"}
    assert "plane_api_secret" not in repr(config)


def test_load_plane_config_requires_api_key(monkeypatch):
    for key in list(os.environ):
        if key.startswith("PLANE_"):
            monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError, match="PLANE_API_KEY"):
        load_plane_config()


def test_load_plane_config_blank_base_url_uses_default(monkeypatch):
    monkeypatch.setenv("PLANE_API_KEY", "plane_api_secret")
    monkeypatch.setenv("PLANE_BASE_URL", "   ")
    monkeypatch.setenv("PLANE_WORKSPACE_SLUG", "homelab")
    monkeypatch.setenv("PLANE_DEFAULT_PROJECT_ID", "project-123")

    config = load_plane_config()

    assert config.base_url == "https://api.plane.so"


def test_priority_from_severity_maps_incident_severity_to_plane_priority():
    assert priority_from_severity("p0") == "urgent"
    assert priority_from_severity("critical") == "urgent"
    assert priority_from_severity("urgent") == "urgent"
    assert priority_from_severity("p1") == "high"
    assert priority_from_severity("high") == "high"
    assert priority_from_severity("p2") == "medium"
    assert priority_from_severity("medium") == "medium"
    assert priority_from_severity("normal") == "medium"
    assert priority_from_severity("p3") == "low"
    assert priority_from_severity("low") == "low"
    assert priority_from_severity("unknown") == "none"


def test_plane_work_item_draft_to_payload_emits_plane_fields():
    draft = PlaneWorkItemDraft(
        name="Resolve degraded auth",
        description_html="<p>Auth API has elevated latency.</p>",
        priority="high",
        external_source="jarvisos-mt",
        external_id="cio:auth:abc123",
    )

    assert draft.to_payload() == {
        "name": "Resolve degraded auth",
        "description_html": "<p>Auth API has elevated latency.</p>",
        "priority": "high",
        "external_source": "jarvisos-mt",
        "external_id": "cio:auth:abc123",
    }


def test_plane_work_item_draft_to_payload_includes_parent_when_set():
    draft = PlaneWorkItemDraft(
        name="Apply remediation",
        description_html="<p>Restart worker pool.</p>",
        parent="parent-work-item-id",
        state="state-open",
    )

    assert draft.to_payload()["parent"] == "parent-work-item-id"
    assert "parent_id" not in draft.to_payload()
    assert draft.to_payload()["state"] == "state-open"


def test_incident_resolution_update_external_id_is_stable_and_cio_scoped():
    update = IncidentResolutionUpdate(
        service="Auth",
        title="Elevated latency",
        severity="p1",
        status="investigating",
        problem="Auth API latency is above SLO.",
    )

    assert update.external_id() == update.external_id()
    assert update.external_id().startswith("cio:auth:")
    assert len(update.external_id().rsplit(":", maxsplit=1)[-1]) == 16


def _plane_config() -> PlaneConfig:
    return PlaneConfig(
        api_key="plane_secret_key",
        workspace_slug="homelab",
        default_project_id="project-123",
        base_url="https://api.plane.so",
    )


def test_plane_client_sends_api_key_header():
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=[])

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))

    assert client.list_projects() == []
    assert seen_headers["x-api-key"] == "plane_secret_key"
    assert seen_headers["content-type"] == "application/json"


def test_plane_client_paginates_results():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url)
        cursor = request.url.params.get("cursor")
        if cursor == "next-page":
            return httpx.Response(200, json={"results": [{"id": "second"}], "next_page_results": False, "next_cursor": None})
        return httpx.Response(200, json={"results": [{"id": "first"}], "next_page_results": True, "next_cursor": "next-page"})

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))

    assert list(client.paginate("/workspaces/homelab/projects/", params={"archived": "false"})) == [
        {"id": "first"},
        {"id": "second"},
    ]
    assert requests[0].params["archived"] == "false"
    assert requests[1].params["cursor"] == "next-page"


def test_plane_client_stops_when_next_page_results_is_false_even_with_cursor():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "results": [{"id": "first"}],
                "next_page_results": False,
                "next_cursor": "should-not-be-used",
            },
        )

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))

    assert list(client.paginate("/workspaces/homelab/projects/")) == [{"id": "first"}]
    assert calls == 1


def test_plane_client_search_work_items_uses_search_endpoint_and_project_param():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))

    assert client.search_work_items("router", project_id="project-123") == []
    assert seen["path"] == "/api/v1/workspaces/homelab/work-items/search/"
    assert seen["params"]["search"] == "router"
    assert seen["params"]["project"] == "project-123"
    assert "project_id" not in seen["params"]


def test_plane_client_raises_auth_error_without_leaking_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key plane_secret_key"})

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(PlaneAPIError) as exc_info:
        client.list_projects()

    message = str(exc_info.value)
    assert "401" in message
    assert "plane_secret_key" not in message


def test_plane_client_retries_once_on_rate_limit_without_real_sleep(monkeypatch):
    calls = 0
    sleeps = []
    monkeypatch.setattr("integrations.plane.client.time.time", lambda: 1000.0)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"X-RateLimit-Reset": "1003"}, json={"detail": "slow down"})
        return httpx.Response(200, json={"ok": True})

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))
    client.sleep = sleeps.append

    assert client.request("GET", "/workspaces/homelab/projects/") == {"ok": True}
    assert calls == 2
    assert sleeps == [3.0]


def test_plane_client_retries_multiple_rate_limits_without_real_sleep(monkeypatch):
    calls = 0
    sleeps = []
    monkeypatch.setattr("integrations.plane.client.time.time", lambda: 1000.0)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 4:
            return httpx.Response(429, headers={"X-RateLimit-Reset": "1001"}, json={"detail": "slow down"})
        return httpx.Response(200, json={"ok": True})

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))
    client.sleep = sleeps.append

    assert client.request("GET", "/workspaces/homelab/projects/") == {"ok": True}
    assert calls == 4
    assert sleeps == [1.0, 1.0, 1.0]


def test_plane_client_uses_retry_after_header_for_rate_limit():
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "8"}, json={"detail": "slow down"})

    client = PlaneClient(_plane_config(), transport=httpx.MockTransport(handler))
    client.max_rate_limit_retries = 1
    client.sleep = sleeps.append

    with pytest.raises(PlaneAPIError):
        client.request("GET", "/workspaces/homelab/projects/")

    assert sleeps == [8.0]

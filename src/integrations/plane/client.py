"""Low-level REST client for the Plane API."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from typing import Any

import httpx

from integrations.plane.config import PlaneConfig


class PlaneAPIError(RuntimeError):
    """Raised when the Plane API returns an unsuccessful response."""


class PlaneClient:
    max_rate_limit_retries = 10

    def __init__(self, config: PlaneConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.sleep = time.sleep
        self._client = httpx.Client(
            base_url=config.base_url,
            headers={
                "X-API-Key": config.api_key,
                "Content-Type": "application/json",
            },
            timeout=20.0,
            transport=transport,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        retries = 0
        while response.status_code == 429 and retries < self.max_rate_limit_retries:
            retries += 1
            self.sleep(self._rate_limit_delay(response))
            response = self._client.request(method, path, **kwargs)

        if response.status_code >= 400:
            raise PlaneAPIError(self._error_message(response))

        if response.status_code == 204:
            return None
        return response.json()

    def paginate(self, path: str, params: Mapping[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        next_cursor: str | None = None
        while True:
            page_params = dict(params or {})
            if next_cursor:
                page_params["cursor"] = next_cursor

            data = self.request("GET", path, params=page_params)
            if isinstance(data, list):
                yield from data
                return

            results = data.get("results", [])
            yield from results

            next_cursor = data.get("next_cursor")
            if not data.get("next_page_results", bool(next_cursor)):
                return
            if not next_cursor:
                return

    def list_projects(self) -> list[dict[str, Any]]:
        return list(self.paginate(f"/api/v1/workspaces/{self.config.workspace_slug}/projects/"))

    def search_work_items(self, query: str, project_id: str | None = None) -> list[dict[str, Any]]:
        params = {
            "search": query,
            "fields": "id,name,external_id,external_source,project_id",
        }
        if project_id:
            params["project"] = project_id
        return list(self.paginate(f"/api/v1/workspaces/{self.config.workspace_slug}/work-items/search/", params=params))

    def create_work_item(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/api/v1/workspaces/{self.config.workspace_slug}/projects/{project_id}/work-items/",
            json=dict(payload),
        )

    def update_work_item(self, project_id: str, work_item_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request(
            "PATCH",
            f"/api/v1/workspaces/{self.config.workspace_slug}/projects/{project_id}/work-items/{work_item_id}/",
            json=dict(payload),
        )

    def add_comment(
        self,
        project_id: str,
        work_item_id: str,
        comment_html: str,
        external_source: str,
        external_id: str,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/api/v1/workspaces/{self.config.workspace_slug}/projects/{project_id}/work-items/{work_item_id}/comments/",
            json={
                "comment_html": comment_html,
                "external_source": external_source,
                "external_id": external_id,
            },
        )

    def _rate_limit_delay(self, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.5), 60.0)
            except ValueError:
                pass

        raw_reset = response.headers.get("X-RateLimit-Reset", "0")
        try:
            reset_epoch = float(raw_reset)
        except ValueError:
            return 2.0
        delay = reset_epoch - time.time()
        return min(max(delay, 0.5), 60.0)

    def _error_message(self, response: httpx.Response) -> str:
        body = response.text.replace(self.config.api_key, "[REDACTED]")
        return f"Plane API request failed with HTTP {response.status_code}: {body}"

"""Idempotent Plane work item synchronization service."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import re
from typing import Any

from integrations.plane.client import PlaneAPIError, PlaneClient
from integrations.plane.models import IncidentResolutionUpdate, PlaneWorkItemDraft, priority_from_severity


_PLANE_API_KEY_RE = re.compile(r"plane_api_[A-Za-z0-9._-]+")


def format_plane_error(exc: Exception) -> str:
    text = escape(_PLANE_API_KEY_RE.sub("plane_api_REDACTED", str(exc)))
    return f"Plane operation failed: {text[:500]}"


@dataclass
class PlaneSyncService:
    client: PlaneClient

    def resolve_project_id(self, domain: str = "") -> str:
        return self.client.config.project_map.get(domain, self.client.config.default_project_id)

    def find_by_external_id(self, external_id: str, project_id: str | None = None) -> dict[str, Any] | None:
        for item in self.client.search_work_items(external_id, project_id=project_id):
            if item.get("external_id") == external_id:
                return item
        return None

    def sync_work_item(self, project_id: str, draft: PlaneWorkItemDraft) -> dict[str, Any]:
        payload = draft.to_payload()
        existing = self.find_by_external_id(draft.external_id, project_id=project_id) if draft.external_id else None
        if existing:
            return self.client.update_work_item(project_id, str(existing["id"]), payload)
        try:
            return self.client.create_work_item(project_id, payload)
        except PlaneAPIError as exc:
            conflict_id = _external_id_conflict_id(exc)
            if conflict_id:
                return self.client.update_work_item(project_id, conflict_id, payload)
            raise

    def add_progress_comment(
        self,
        project_id: str,
        work_item_id: str,
        comment_html: str,
        external_source: str,
        external_id: str,
    ) -> dict[str, Any]:
        return self.client.add_comment(project_id, work_item_id, comment_html, external_source, external_id)

    def sync_incident_update(
        self,
        update: IncidentResolutionUpdate,
        domain: str = "homelab-operations",
        *,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        project_id = project_id or self.resolve_project_id(domain)
        draft = PlaneWorkItemDraft(
            name=f"[{update.service}] {update.title}",
            description_html=_incident_description_html(update),
            priority=priority_from_severity(update.severity),
            external_source="jarvisos-cio",
            external_id=update.external_id(),
        )
        return self.sync_work_item(project_id, draft)

    def sync_incident_with_steps(
        self,
        update: IncidentResolutionUpdate,
        domain: str = "homelab-operations",
    ) -> dict[str, Any]:
        project_id = self.resolve_project_id(domain)
        parent = self.sync_incident_update(update, domain=domain, project_id=project_id)
        parent_id = str(parent["id"])
        priority = priority_from_severity(update.severity)
        incident_title = f"[{update.service}] {update.title}"

        for index, step in enumerate(update.resolution_plan, start=1):
            child = PlaneWorkItemDraft(
                name=step,
                description_html=_remediation_step_description_html(index, incident_title, step),
                priority=priority,
                external_source="jarvisos-cio",
                external_id=f"{update.external_id()}:step:{index}",
                parent=parent_id,
            )
            self.sync_work_item(project_id, child)

        return parent

    def sync_parsed_plan(self, plan) -> dict[str, Any]:
        project_id = self.resolve_project_id(plan.domain)
        parent = self.sync_work_item(
            project_id,
            PlaneWorkItemDraft(
                name=plan.title,
                description_html=_plan_description_html(plan),
                priority="medium",
                external_source="homelab-planning",
                external_id=plan.external_id,
            ),
        )
        parent_id = str(parent["id"])
        phase_ids: dict[str, str] = {}

        for phase in plan.phases:
            item = self.sync_work_item(
                project_id,
                PlaneWorkItemDraft(
                    name=f"{phase.id} - {phase.name}",
                    description_html=_source_description_html("Phase", plan.path),
                    priority="medium",
                    external_source="homelab-planning",
                    external_id=phase.external_id,
                    parent=parent_id,
                ),
            )
            phase_ids[phase.id] = str(item["id"])

        for task in plan.tasks:
            self.sync_work_item(
                project_id,
                PlaneWorkItemDraft(
                    name=f"{task.id} - {task.name}",
                    description_html=_source_description_html("Task", plan.path),
                    priority="medium",
                    external_source="homelab-planning",
                    external_id=task.external_id,
                    parent=phase_ids.get(task.phase_id, parent_id),
                ),
            )

        return parent


def _incident_description_html(update: IncidentResolutionUpdate) -> str:
    parts = [
        _section("Status", update.status),
        _section("Problem", update.problem),
    ]
    if update.root_cause:
        parts.append(_section("Root cause", update.root_cause))
    if update.resolution_plan:
        plan_items = "".join(f"<li>{escape(item)}</li>" for item in update.resolution_plan)
        parts.append(f"<h3>Resolution plan</h3><ul>{plan_items}</ul>")
    return "".join(parts)


def _section(label: str, value: str) -> str:
    return f"<h3>{escape(label)}</h3><p>{escape(value)}</p>"


def _remediation_step_description_html(index: int, incident_title: str, step: str) -> str:
    return "".join(
        [
            _section("Remediation step", f"Remediation step {index} for {incident_title}"),
            _section("Action", step),
        ]
    )


def _plan_description_html(plan) -> str:
    parts = []
    if plan.goal:
        parts.append(_section("Goal", plan.goal))
    parts.append(_section("Source", str(plan.path)))
    if plan.project:
        parts.append(_section("Project", plan.project))
    return "".join(parts)


def _source_description_html(label: str, path: object) -> str:
    return _section(label, f"From {path}")


def _external_id_conflict_id(exc: Exception) -> str:
    text = str(exc)
    if "HTTP 409" not in text or "same external id" not in text:
        return ""
    body_start = text.find("{")
    if body_start == -1:
        return ""
    try:
        body = json.loads(text[body_start:])
    except json.JSONDecodeError:
        return ""
    return str(body.get("id") or "")

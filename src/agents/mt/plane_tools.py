"""Plane tool handlers owned by MT."""

from __future__ import annotations

from html import escape
import json

from integrations.plane.client import PlaneClient
from integrations.plane.config import load_plane_config
from integrations.plane.models import IncidentResolutionUpdate, PlaneWorkItemDraft
from integrations.plane.service import PlaneSyncService, format_plane_error


def _text(value: str) -> dict:
    return {"content": [{"type": "text", "text": str(value)}]}


def build_default_plane_service() -> PlaneSyncService:
    return PlaneSyncService(PlaneClient(load_plane_config()))


def build_plane_tool_handlers(service_factory=build_default_plane_service) -> dict:
    def plane_sync_project(args):
        try:
            service = service_factory()
            project_id = service.resolve_project_id(args.get("domain", ""))
            draft = PlaneWorkItemDraft(
                name=args["title"],
                description_html=f"<p>{escape(str(args.get('description', '')))}</p>",
                priority=args.get("priority", "none"),
                external_source="homelab-planning",
                external_id=args["external_id"],
            )
            item = service.sync_work_item(project_id=project_id, draft=draft)
            return _text(json.dumps(item, ensure_ascii=False))
        except Exception as exc:
            return _text(format_plane_error(exc))

    def plane_sync_incident(args):
        try:
            service = service_factory()
            update = IncidentResolutionUpdate(
                service=args["service"],
                title=args["title"],
                severity=args.get("severity", "medium"),
                status=args.get("status", "triaged"),
                problem=args["problem"],
                root_cause=args.get("root_cause", ""),
                resolution_plan=list(args.get("resolution_plan", [])),
            )
            item = service.sync_incident_with_steps(update, domain=args.get("domain", "homelab-operations"))
            return _text(json.dumps(item, ensure_ascii=False))
        except Exception as exc:
            return _text(format_plane_error(exc))

    def plane_sync_plan(args):
        try:
            service = service_factory()
            item = service.sync_parsed_plan(args["plan"])
            return _text(json.dumps(item, ensure_ascii=False))
        except Exception as exc:
            return _text(format_plane_error(exc))

    return {
        "plane_sync_project": plane_sync_project,
        "plane_sync_incident": plane_sync_incident,
        "plane_sync_plan": plane_sync_plan,
    }

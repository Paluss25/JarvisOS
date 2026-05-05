"""Command line entrypoint for syncing Plane work items."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.mt.plane_tools import build_plane_tool_handlers
from integrations.plane.plan_parser import parse_homelab_plan


def _extract_text(result: dict) -> str:
    return str(result["content"][0]["text"])


def _print_result(result: dict) -> int:
    text = _extract_text(result)
    if text.startswith("Plane operation failed"):
        print(text, file=sys.stderr)
        return 2
    print(text)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync HomeLab Plane work items.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    project = subparsers.add_parser("project", help="Sync a planning project work item.")
    project.add_argument("--domain", required=True)
    project.add_argument("--title", required=True)
    project.add_argument("--description", required=True)
    project.add_argument("--external-id", required=True, dest="external_id")
    project.add_argument("--priority", default="none")

    incident = subparsers.add_parser("incident", help="Sync a CIO incident work item.")
    incident.add_argument("--domain", default="homelab-operations")
    incident.add_argument("--service", required=True)
    incident.add_argument("--title", required=True)
    incident.add_argument("--problem", required=True)
    incident.add_argument("--severity", default="medium")
    incident.add_argument("--status", default="triaged")
    incident.add_argument("--root-cause", default="", dest="root_cause")
    incident.add_argument(
        "--resolution-plan",
        action="append",
        default=[],
        dest="resolution_plan",
    )

    plan = subparsers.add_parser("plan", help="Sync a HomeLab implementation plan file.")
    plan.add_argument("plan_path")

    return parser


def main(argv: list[str] | None = None, handlers: dict | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    active_handlers = handlers if handlers is not None else build_plane_tool_handlers()

    if args.command == "project":
        result = active_handlers["plane_sync_project"](
            {
                "domain": args.domain,
                "title": args.title,
                "description": args.description,
                "external_id": args.external_id,
                "priority": args.priority,
            }
        )
        return _print_result(result)

    if args.command == "incident":
        result = active_handlers["plane_sync_incident"](
            {
                "domain": args.domain,
                "service": args.service,
                "title": args.title,
                "problem": args.problem,
                "severity": args.severity,
                "status": args.status,
                "root_cause": args.root_cause,
                "resolution_plan": args.resolution_plan,
            }
        )
        return _print_result(result)

    if args.command == "plan":
        parsed_plan = parse_homelab_plan(Path(args.plan_path))
        result = active_handlers["plane_sync_plan"](
            {
                "path": str(parsed_plan.path),
                "title": parsed_plan.title,
                "project": parsed_plan.project,
                "domain": parsed_plan.domain,
                "goal": parsed_plan.goal,
                "external_id": parsed_plan.external_id,
                "phases": parsed_plan.phases,
                "tasks": parsed_plan.tasks,
                "plan": parsed_plan,
            }
        )
        return _print_result(result)

    parser.error(f"Unsupported command: {args.command}")
    return 2

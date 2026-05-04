"""Helpers for preparing CIO Plane incident updates for the Plane CLI."""

from __future__ import annotations


def _stripped(value: object, default: str = "") -> str:
    if value is None:
        return default
    stripped = str(value).strip()
    return stripped or default


def _normalize_resolution_plan(value: object) -> list[str]:
    if isinstance(value, str):
        items = value.splitlines()
    elif isinstance(value, list):
        items = value
    else:
        return []

    steps: list[str] = []
    for item in items:
        step = str(item).strip()
        if step.startswith("- "):
            step = step[2:].strip()
        if step:
            steps.append(step)
    return steps


def build_incident_resolution_payload(args: dict) -> dict:
    """Normalize a CIO incident remediation update for downstream CLI sync."""
    return {
        "type": "incident_resolution_update",
        "source_agent": "cio",
        "service": _stripped(args.get("service"), "unknown"),
        "title": _stripped(args.get("title"), "HomeLab incident"),
        "severity": _stripped(args.get("severity"), "medium").lower(),
        "status": _stripped(args.get("status"), "triaged").lower(),
        "problem": _stripped(args.get("problem")),
        "root_cause": _stripped(args.get("root_cause")),
        "domain": _stripped(args.get("domain"), "homelab-operations"),
        "resolution_plan": _normalize_resolution_plan(args.get("resolution_plan")),
    }


def build_plane_incident_cli_args(args: dict) -> list[str]:
    """Build argv for integrations.plane.cli.main without a script path."""
    payload = build_incident_resolution_payload(args)
    argv = [
        "incident",
        "--domain",
        payload["domain"],
        "--service",
        payload["service"],
        "--title",
        payload["title"],
        "--problem",
        payload["problem"],
        "--severity",
        payload["severity"],
        "--status",
        payload["status"],
    ]

    if payload["root_cause"]:
        argv.extend(["--root-cause", payload["root_cause"]])

    for step in payload["resolution_plan"]:
        argv.extend(["--resolution-plan", step])

    return argv

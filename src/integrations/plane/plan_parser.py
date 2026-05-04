from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ParsedPhase:
    id: str
    name: str
    external_id: str


@dataclass(frozen=True)
class ParsedTask:
    id: str
    name: str
    phase_id: str
    external_id: str


@dataclass(frozen=True)
class ParsedPlan:
    path: Path
    title: str
    project: str
    domain: str
    goal: str
    external_id: str
    phases: list[ParsedPhase]
    tasks: list[ParsedTask]


_FRONTMATTER_VALUE_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)\s*$")
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
_PHASE_RE = re.compile(r"^##\s+(P\d+)\s+—\s+(.+?)\s*$")
_TASK_RE = re.compile(r"^###\s+(P\d+\.T\d+)\s+—\s+(.+?)\s*$")
_GOAL_RE = re.compile(r"\*\*Goal:\*\*\s*(.+?)\s*$")


def parse_homelab_plan(path: Path) -> ParsedPlan:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    frontmatter, body_lines = _split_frontmatter(lines)
    metadata = _parse_frontmatter(frontmatter)

    title = ""
    goal = ""
    phases: list[ParsedPhase] = []
    tasks: list[ParsedTask] = []
    current_phase_id = ""
    in_fence = False

    for line in body_lines:
        if _is_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        if not title:
            title_match = _TITLE_RE.match(line)
            if title_match:
                title = title_match.group(1).strip()

        if not goal:
            goal_match = _GOAL_RE.search(line)
            if goal_match:
                goal = goal_match.group(1).strip()

        phase_match = _PHASE_RE.match(line)
        if phase_match:
            current_phase_id = phase_match.group(1)
            phases.append(
                ParsedPhase(
                    id=current_phase_id,
                    name=phase_match.group(2).strip(),
                    external_id=f"{path}#{current_phase_id}",
                )
            )
            continue

        task_match = _TASK_RE.match(line)
        if task_match:
            task_id = task_match.group(1)
            phase_id = current_phase_id or task_id.split(".", 1)[0]
            tasks.append(
                ParsedTask(
                    id=task_id,
                    name=task_match.group(2).strip(),
                    phase_id=phase_id,
                    external_id=f"{path}#{task_id}",
                )
            )

    return ParsedPlan(
        path=path,
        title=title or path.stem,
        project=metadata.get("project", ""),
        domain=metadata.get("domain", ""),
        goal=goal,
        external_id=str(path),
        phases=phases,
        tasks=tasks,
    )


def _split_frontmatter(lines: list[str]) -> tuple[list[str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return [], lines

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index], lines[index + 1 :]

    return [], lines


def _parse_frontmatter(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        match = _FRONTMATTER_VALUE_RE.match(line.strip())
        if not match:
            continue
        value = match.group(2).strip()
        values[match.group(1)] = value.strip("\"'")
    return values


def _is_fence(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("```") or stripped.startswith("~~~")

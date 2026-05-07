from __future__ import annotations

import os

import httpx

DEFAULT_PLATFORM_URL = "http://localhost:8900"


def platform_url() -> str:
    return os.environ.get("JARVIOS_PLATFORM_URL", DEFAULT_PLATFORM_URL).rstrip("/")


async def create_task(
    agent_id: str,
    *,
    title: str,
    description: str = "",
    priority: str = "normal",
    depends_on: list[str] | None = None,
    assign_to: str | None = None,
) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{platform_url()}/api/tasks",
            json={
                "title": title,
                "description": description,
                "priority": priority,
                "depends_on": depends_on or [],
                "assign_to": assign_to,
                "created_by": agent_id,
            },
        )
        return resp.text


async def update_task(task_id: str, *, status: str, summary: str | None = None) -> str:
    body: dict = {"status": status}
    if summary:
        body["summary"] = summary
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(f"{platform_url()}/api/tasks/{task_id}", json=body)
        return resp.text


async def list_my_tasks(agent_id: str, *, status: str | None = None) -> str:
    params: dict = {"assigned_to": agent_id}
    if status:
        params["status"] = status
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{platform_url()}/api/tasks", params=params)
        return resp.text

"""Task management MCP tools — exposed to all agents."""

import logging

import httpx

logger = logging.getLogger(__name__)

_PLATFORM_URL = "http://localhost:8900"


def create_task_tools(agent_id: str):
    """Return MCP tool callables for task management."""

    async def create_task(
        title: str,
        description: str = "",
        priority: str = "normal",
        depends_on: list[str] | None = None,
        assign_to: str | None = None,
    ) -> str:
        """Create a new task in Mission Control.

        Args:
            title: Short task title.
            description: Detailed task description.
            priority: low | normal | high | urgent.
            depends_on: List of task UUIDs that must complete first.
            assign_to: Agent ID to assign to, or None for auto-assign.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_PLATFORM_URL}/api/tasks",
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

    async def update_task(task_id: str, status: str, summary: str | None = None) -> str:
        """Update a task's status and optional summary.

        Args:
            task_id: UUID of the task to update.
            status: pending | running | done | failed.
            summary: Optional result/outcome text.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            body: dict = {"status": status}
            if summary:
                body["summary"] = summary
            resp = await client.patch(f"{_PLATFORM_URL}/api/tasks/{task_id}", json=body)
            return resp.text

    async def list_my_tasks(status: str | None = None) -> str:
        """List tasks assigned to this agent.

        Args:
            status: Filter by status (pending | running | done | failed).
        """
        params: dict = {"assigned_to": agent_id}
        if status:
            params["status"] = status
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_PLATFORM_URL}/api/tasks", params=params)
            return resp.text

    return [create_task, update_task, list_my_tasks]

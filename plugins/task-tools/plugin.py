from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools.task_client import create_task, list_my_tasks, update_task

    async def _create(args: dict) -> str:
        return await create_task(
            context.agent_id,
            title=str(args.get("title", "")),
            description=str(args.get("description", "")),
            priority=str(args.get("priority", "normal")),
            depends_on=args.get("depends_on") or [],
            assign_to=args.get("assign_to") or None,
        )

    async def _update(args: dict) -> str:
        return await update_task(
            str(args.get("task_id", "")),
            status=str(args.get("status", "")),
            summary=args.get("summary") or None,
        )

    async def _list(args: dict) -> str:
        return await list_my_tasks(context.agent_id, status=args.get("status") or None)

    return [
        ToolSpec(
            name="create_task",
            description="Create a new task in Mission Control.",
            schema={
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "priority": {"type": "string", "default": "normal"},
                "depends_on": {"type": "array", "items": {"type": "string"}, "default": []},
                "assign_to": {"type": "string", "default": ""},
            },
            handler=_create,
        ),
        ToolSpec(
            name="update_task",
            description="Update a task status and optional summary.",
            schema={
                "task_id": {"type": "string"},
                "status": {"type": "string"},
                "summary": {"type": "string", "default": ""},
            },
            handler=_update,
        ),
        ToolSpec(
            name="list_my_tasks",
            description="List tasks assigned to this agent.",
            schema={"status": {"type": "string", "default": ""}},
            handler=_list,
        ),
    ]

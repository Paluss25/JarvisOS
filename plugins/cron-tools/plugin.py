from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools.cron_client import create_cron, delete_cron, list_crons, update_cron

    return [
        ToolSpec(
            name="cron_create",
            description=(
                "Create a new scheduled task. schedule format: "
                "daily@HH:MM | weekly@DOW@HH:MM | once@YYYY-MM-DD@HH:MM."
            ),
            schema={"name": str, "schedule": str, "prompt": str, "session_id": str, "telegram_notify": bool},
            handler=lambda args: create_cron(context.workspace_path, args),
        ),
        ToolSpec(
            name="cron_list",
            description="List all scheduled tasks with their current status.",
            schema={},
            handler=lambda args: list_crons(context.workspace_path),
        ),
        ToolSpec(
            name="cron_update",
            description="Update a scheduled task by its id.",
            schema={
                "id": str,
                "name": str,
                "schedule": str,
                "prompt": str,
                "session_id": str,
                "telegram_notify": bool,
                "enabled": bool,
            },
            handler=lambda args: update_cron(context.workspace_path, args),
        ),
        ToolSpec(
            name="cron_delete",
            description="Delete a user-created scheduled task by its id.",
            schema={"id": str},
            handler=lambda args: delete_cron(context.workspace_path, args),
        ),
    ]

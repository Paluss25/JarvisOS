from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools import calendar_client

    return [
        ToolSpec(
            name="calendar_list",
            description="List all calendars available in Radicale.",
            schema={},
            handler=calendar_client.calendar_list,
        ),
        ToolSpec(
            name="calendar_get_events",
            description="Fetch calendar events for a date range. Dates: YYYY-MM-DD.",
            schema={"start_date": str, "end_date": str, "calendar": {"type": "string", "default": ""}},
            handler=calendar_client.calendar_get_events,
        ),
        ToolSpec(
            name="calendar_create_event",
            description="Create a calendar event after conflict check and confirmation gate.",
            schema={
                "title": str,
                "start_datetime": str,
                "end_datetime": str,
                "description": {"type": "string", "default": ""},
                "calendar": {"type": "string", "default": ""},
                "confirmed": {"type": "boolean", "default": False},
            },
            handler=calendar_client.calendar_create_event,
        ),
        ToolSpec(
            name="calendar_update_event",
            description="Update an existing calendar event by UID after confirmation gate.",
            schema={
                "uid": str,
                "title": str,
                "start_datetime": str,
                "end_datetime": str,
                "description": {"type": "string", "default": ""},
                "calendar": {"type": "string", "default": ""},
                "confirmed": {"type": "boolean", "default": False},
            },
            handler=calendar_client.calendar_update_event,
        ),
        ToolSpec(
            name="calendar_delete_event",
            description="Delete a calendar event by UID after confirmation gate.",
            schema={"uid": str, "calendar": {"type": "string", "default": ""}, "confirmed": {"type": "boolean", "default": False}},
            handler=calendar_client.calendar_delete_event,
        ),
    ]

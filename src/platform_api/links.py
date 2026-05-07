"""Shared dashboard route builders for platform API responses."""

from urllib.parse import urlencode


def build_chat_link(
    agent_id: str | None,
    *,
    task_id: str | None = None,
    trace_id: str | None = None,
    log_event_id: str | None = None,
    memory_event_id: str | None = None,
) -> str | None:
    if not agent_id:
        return None

    params = [
        ("task_id", task_id),
        ("trace_id", trace_id),
        ("log_event_id", log_event_id),
        ("memory_event_id", memory_event_id),
    ]
    query = urlencode([(key, value) for key, value in params if value])
    path = f"/agents/{agent_id}/chat"
    return f"{path}?{query}" if query else path

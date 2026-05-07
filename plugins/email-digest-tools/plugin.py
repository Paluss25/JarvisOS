from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools.email_digest_client import read_email_digest

    async def _read(args: dict) -> dict:
        return await read_email_digest(context.workspace_path, args)

    return [
        ToolSpec(
            name="read_email_digest",
            description="Read unprocessed entries from the MT email digest.",
            schema={"max_items": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
            handler=_read,
        )
    ]

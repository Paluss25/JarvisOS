from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools.memory_box_client import query_agent_memory

    async def _query(args: dict) -> dict:
        return await query_agent_memory(
            context.agent_id,
            str(args.get("query", "")),
            agent_filter=str(args.get("agent_filter", "")).strip() or None,
            limit=int(args.get("limit") or 10),
        )

    return [
        ToolSpec(
            name="query_agent_memory",
            description=(
                "Search the shared memory store for entries across all agents. "
                "query is required; agent_filter optionally restricts results."
            ),
            schema={
                "query": {"type": "string"},
                "agent_filter": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 10},
            },
            handler=_query,
        )
    ]

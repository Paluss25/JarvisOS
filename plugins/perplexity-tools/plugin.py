from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools.perplexity_client import search_perplexity

    async def _search(args: dict) -> dict:
        return await search_perplexity(str(args.get("query", "")), workspace_path=context.workspace_path)

    return [
        ToolSpec(
            name="perplexity_search",
            description=(
                "Search the web using Perplexity AI for real-time information. "
                "Use this for current events, facts, or topics requiring up-to-date information."
            ),
            schema={"query": str},
            handler=_search,
        )
    ]

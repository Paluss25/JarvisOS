"""Shared Perplexity web search tool for all agents.

Provides web search via the Perplexity API (sonar model).
Results are logged to the agent's daily memory file.
"""

class PerplexitySearchTools:
    """Legacy Perplexity search class (agno-free). Not used by SDK-based agents."""

    def __init__(self):
        pass

    def search(self, query: str) -> str:
        """Search the web using Perplexity AI and return a summarised answer.

        Args:
            query: The search query.

        Returns:
            A text answer with sources cited inline.
        """
        from config import settings
        from agent_runner.tools.perplexity_client import search_perplexity_sync

        return search_perplexity_sync(
            query,
            workspace_path=settings.workspace_path,
            api_key=settings.PERPLEXITY_API_KEY,
        )

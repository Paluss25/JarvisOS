"""Auto-assign tasks to agents using Gemini Flash."""

import json
import logging
import os

from google import genai

from agent_runner.registry import list_agents

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.7


async def auto_assign(task_title: str, task_description: str) -> dict:
    """Ask Gemini Flash to pick the best agent for this task.

    Returns: {"agent_id": str | None, "confidence": float, "reason": str}
    If confidence < threshold, returns agent_id=None (manual queue).
    """
    agents = list_agents()
    agent_list = "\n".join(
        f"- {a['id']}: capabilities={a.get('capabilities', [])}, domains={a.get('domains', [])}"
        for a in agents
    )

    prompt = f"""Given these agents:
{agent_list}

Assign this task to the best agent:
Title: {task_title}
Description: {task_description or 'N/A'}

Respond with JSON: {{"agent_id": "...", "confidence": 0.0-1.0, "reason": "..."}}
If no agent fits well, set confidence below {_CONFIDENCE_THRESHOLD}.
"""

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("task_router: GEMINI_API_KEY not set — skipping auto-assign")
        return {"agent_id": None, "confidence": 0.0, "reason": "GEMINI_API_KEY not configured"}

    try:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        result = json.loads(response.text)
        if result.get("confidence", 0) < _CONFIDENCE_THRESHOLD:
            result["agent_id"] = None
        return result
    except Exception as exc:
        logger.warning("task_router: Gemini call failed — %s", exc)
        return {"agent_id": None, "confidence": 0.0, "reason": f"router error: {exc}"}

"""MealVisionAgent — analyzes meal photos using Claude Vision."""

import base64
import json
import logging
from pathlib import Path

import anthropic

from agents.don.models import VisionHypothesis, VisionResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a precise nutrition vision assistant. Analyze the meal photo and identify every food item visible.

Rules:
- Only report ingredients that are clearly visible in the image. Do not invent invisible items.
- Provide a maximum of 3 hypotheses per ambiguous food item (e.g., if the protein is unclear).
- Be conservative with portion estimates — round down rather than up.
- Express portions in grams.
- For each food item, provide a confidence score between 0.0 and 1.0.

Respond ONLY with valid JSON matching this exact schema:
{
  "hypotheses": [
    {
      "food_name": "<name>",
      "visible_ingredients": ["<ingredient1>", "<ingredient2>"],
      "portion_estimate_g": <number>,
      "confidence": <0.0-1.0>,
      "notes": "<optional notes>"
    }
  ],
  "scene_complexity": "low|medium|high",
  "needs_confirmation": <true|false>
}

Set needs_confirmation=true when:
- The dish is composed of many mixed ingredients (e.g., stew, salad)
- You cannot confidently distinguish the protein source
- Portion size is very hard to judge from the angle
"""


class MealVisionAgent:
    """Analyzes meal photos with Claude Vision and returns food hypotheses."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.Anthropic()
        self._model = model

    async def analyze(self, image_path: str | Path) -> VisionResult:
        """Analyze a meal photo and return vision hypotheses.

        Args:
            image_path: Absolute path to the image file (JPEG or PNG).

        Returns:
            VisionResult with hypotheses for each identified food item.
        """
        image_data = _load_image_base64(image_path)
        media_type = _detect_media_type(str(image_path))

        message = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Identify all food items in this meal photo and estimate their portions.",
                        },
                    ],
                }
            ],
        )

        raw_text = message.content[0].text.strip()
        return _parse_vision_response(raw_text)


def _load_image_base64(image_path: str | Path) -> str:
    with open(str(image_path), "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _detect_media_type(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def _parse_vision_response(raw: str) -> VisionResult:
    """Parse Claude's JSON response into VisionResult."""
    try:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data = json.loads(raw)
        hypotheses = [
            VisionHypothesis(
                food_name=h["food_name"],
                visible_ingredients=h.get("visible_ingredients", []),
                portion_estimate_g=float(h["portion_estimate_g"]),
                confidence=float(h["confidence"]),
                notes=h.get("notes", ""),
            )
            for h in data.get("hypotheses", [])
        ]
        return VisionResult(
            hypotheses=hypotheses,
            scene_complexity=data.get("scene_complexity", "low"),
            needs_confirmation=bool(data.get("needs_confirmation", False)),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Failed to parse vision response: %s — raw: %.200s", exc, raw)
        return VisionResult(hypotheses=[], scene_complexity="high", needs_confirmation=True)

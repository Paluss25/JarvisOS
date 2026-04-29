"""USDA FoodData Central API client — generic food fallback."""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.nal.usda.gov/fdc/v1"


@dataclass
class USDAFood:
    fdc_id: int
    food_name: str
    calories: float
    protein: float
    carbs: float
    fat: float
    serving_g: float = 100
    confidence: float = 0.70


class USDAClient:
    def __init__(self):
        self._api_key = os.environ.get("USDA_API_KEY", "")

    async def search_foods(self, query: str, max_results: int = 3) -> list[USDAFood]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/foods/search",
                params={
                    "api_key": self._api_key,
                    "query": query,
                    "pageSize": max_results,
                    "dataType": ["Foundation", "SR Legacy"],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for food in data.get("foods", [])[:max_results]:
            nutrients = {n["nutrientName"]: n.get("value", 0) for n in food.get("foodNutrients", [])}
            results.append(USDAFood(
                fdc_id=food.get("fdcId", 0),
                food_name=food.get("description", ""),
                calories=float(nutrients.get("Energy", 0)),
                protein=float(nutrients.get("Protein", 0)),
                carbs=float(nutrients.get("Carbohydrate, by difference", 0)),
                fat=float(nutrients.get("Total lipid (fat)", 0)),
            ))
        return results

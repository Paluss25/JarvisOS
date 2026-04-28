"""FatSecret Platform API client — OAuth2 client_credentials flow."""

import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
API_URL = "https://platform.fatsecret.com/rest/server.api"


@dataclass
class FatSecretFood:
    food_id: str
    food_name: str
    brand: str
    serving_description: str
    calories: float
    protein: float
    carbs: float
    fat: float
    serving_g: float
    confidence: float = 0.85


class FatSecretClient:
    def __init__(self):
        self._client_id = os.environ.get("FATSECRET_CLIENT_ID", "")
        self._client_secret = os.environ.get("FATSECRET_CLIENT_SECRET", "")
        self._token: str = ""
        self._token_expires: float = 0

    async def _ensure_token(self):
        if self._token and time.time() < self._token_expires:
            return
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials", "scope": "basic"},
                auth=(self._client_id, self._client_secret),
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 86400) - 60

    async def search_foods(self, query: str, max_results: int = 3) -> list[FatSecretFood]:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                API_URL,
                params={
                    "method": "foods.search",
                    "search_expression": query,
                    "format": "json",
                    "max_results": max_results,
                },
                headers={"Authorization": f"Bearer {self._token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        foods_data = data.get("foods", {}).get("food", [])
        if isinstance(foods_data, dict):
            foods_data = [foods_data]

        results = []
        for f in foods_data[:max_results]:
            desc = f.get("food_description", "")
            parsed = self._parse_description(desc)
            results.append(FatSecretFood(
                food_id=f.get("food_id", ""),
                food_name=f.get("food_name", ""),
                brand=f.get("brand_name", ""),
                serving_description=desc,
                calories=parsed.get("calories", 0),
                protein=parsed.get("protein", 0),
                carbs=parsed.get("carbs", 0),
                fat=parsed.get("fat", 0),
                serving_g=parsed.get("serving_g", 100),
            ))
        return results

    @staticmethod
    def _parse_description(desc: str) -> dict:
        """Parse FatSecret food_description format:
        'Per 100g - Calories: 165kcal | Fat: 3.60g | Carbs: 0.00g | Protein: 31.02g'
        """
        result = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "serving_g": 100}

        serving_match = re.search(r"Per\s+(\d+(?:\.\d+)?)\s*g", desc)
        if serving_match:
            result["serving_g"] = float(serving_match.group(1))

        cal_match = re.search(r"Calories:\s*(\d+(?:\.\d+)?)", desc)
        if cal_match:
            result["calories"] = float(cal_match.group(1))

        fat_match = re.search(r"Fat:\s*(\d+(?:\.\d+)?)", desc)
        if fat_match:
            result["fat"] = float(fat_match.group(1))

        carb_match = re.search(r"Carbs:\s*(\d+(?:\.\d+)?)", desc)
        if carb_match:
            result["carbs"] = float(carb_match.group(1))

        prot_match = re.search(r"Protein:\s*(\d+(?:\.\d+)?)", desc)
        if prot_match:
            result["protein"] = float(prot_match.group(1))

        return result

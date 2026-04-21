"""Open Food Facts API client — barcode lookup for packaged products."""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://world.openfoodfacts.org/api/v2/product"


@dataclass
class OFFProduct:
    barcode: str
    product_name: str
    brand: str
    serving_g: float
    calories_per_100g: float
    protein_per_100g: float
    carbs_per_100g: float
    fat_per_100g: float
    confidence: float = 0.95


class OpenFoodFactsClient:
    def __init__(self):
        self._user_agent = os.environ.get(
            "OPENFOODFACTS_USER_AGENT", "DrHouse/1.0 (paluss@homelab)"
        )

    async def lookup_barcode(self, barcode: str) -> OFFProduct | None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/{barcode}.json",
                headers={"User-Agent": self._user_agent},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            if data.get("status") != 1:
                return None

            product = data.get("product", {})
            nutrients = product.get("nutriments", {})

            return OFFProduct(
                barcode=barcode,
                product_name=product.get("product_name", "Unknown"),
                brand=product.get("brands", ""),
                serving_g=float(product.get("serving_quantity", 100) or 100),
                calories_per_100g=float(nutrients.get("energy-kcal_100g", 0) or 0),
                protein_per_100g=float(nutrients.get("proteins_100g", 0) or 0),
                carbs_per_100g=float(nutrients.get("carbohydrates_100g", 0) or 0),
                fat_per_100g=float(nutrients.get("fat_100g", 0) or 0),
            )

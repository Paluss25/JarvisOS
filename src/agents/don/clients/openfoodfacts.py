"""Open Food Facts API client — barcode lookup and ingredient text search.

Text search uses the Italian OFF endpoint (it.openfoodfacts.org) for better
coverage of Italian packaged foods, falling back to world.openfoodfacts.org.
Returns per-100g macros; callers must scale by (quantity_g / 100).

Note: OFF text search is reliable for branded/packaged Italian products
(Barilla pasta, Mulino Bianco biscuits, San Pellegrino, etc.).
For artisanal or restaurant dishes, Haiku estimates are more accurate.
"""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://world.openfoodfacts.org/api/v2/product"
_SEARCH_URL = "https://it.openfoodfacts.org/cgi/search.pl"
_TIMEOUT = 8.0


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


@dataclass
class OFFSearchResult:
    name: str
    serving_g: float        # always 100g for per-100g entries; callers scale
    calories: float         # kcal per serving_g
    protein: float
    carbs: float
    fat: float
    source: str = "openfoodfacts"


class OpenFoodFactsClient:
    def __init__(self):
        self._user_agent = os.environ.get(
            "OPENFOODFACTS_USER_AGENT", "DrHouse/1.0 (paluss@homelab)"
        )

    async def search_foods(self, query: str, max_results: int = 3) -> list[OFFSearchResult]:
        """Text search on the Italian OFF endpoint.

        Returns results scaled per 100g (serving_g=100). Callers must scale:
            scale = quantity_g / result.serving_g
        Filters out entries with zero calories to avoid empty/incomplete records.
        """
        params = {
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": max(max_results * 3, 9),   # fetch more, filter empties
            "fields": "product_name,brands,nutriments,serving_quantity",
            "sort_by": "unique_scans_n",             # most-scanned first → more complete data
            "countries_tags": "en:italy",            # Italian products only
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={"User-Agent": self._user_agent},
                )
                if resp.status_code != 200:
                    logger.debug("OFF search HTTP %s for '%s'", resp.status_code, query)
                    return []

                data = resp.json()
                products = data.get("products", [])
        except Exception as exc:
            logger.debug("OFF search error for '%s' — %s", query, exc)
            return []

        results: list[OFFSearchResult] = []
        for p in products:
            nutrients = p.get("nutriments", {})
            kcal = float(nutrients.get("energy-kcal_100g", 0) or 0)
            if kcal <= 0:
                continue    # skip incomplete entries

            results.append(OFFSearchResult(
                name=p.get("product_name") or query,
                serving_g=100.0,
                calories=kcal,
                protein=float(nutrients.get("proteins_100g", 0) or 0),
                carbs=float(nutrients.get("carbohydrates_100g", 0) or 0),
                fat=float(nutrients.get("fat_100g", 0) or 0),
            ))
            if len(results) >= max_results:
                break

        logger.debug("OFF search '%s' → %d results (of %d raw)", query, len(results), len(products))
        return results

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

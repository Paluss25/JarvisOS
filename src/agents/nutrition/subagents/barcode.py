"""BarcodeAgent — resolves packaged food nutrition via Open Food Facts."""

import logging

from agents.nutrition.clients.openfoodfacts import OpenFoodFactsClient
from agents.nutrition.models import ResolvedFood

logger = logging.getLogger(__name__)


class BarcodeAgent:
    """Thin wrapper around OpenFoodFactsClient that returns a ResolvedFood."""

    def __init__(self):
        self._client = OpenFoodFactsClient()

    async def lookup(self, barcode: str, portion_g: float = 100.0) -> ResolvedFood | None:
        """Look up a product by barcode and scale nutrition to requested portion.

        Args:
            barcode: EAN-13 or similar barcode string.
            portion_g: Desired portion in grams for scaling; defaults to 100 g.

        Returns:
            ResolvedFood with confidence 0.95, or None if barcode not found.
        """
        product = await self._client.lookup_barcode(barcode)
        if product is None:
            logger.debug("Barcode not found in Open Food Facts: %s", barcode)
            return None

        scale = portion_g / 100.0
        return ResolvedFood(
            canonical_name=_format_name(product.product_name, product.brand),
            source_database="openfoodfacts",
            portion_g=portion_g,
            calories=round(product.calories_per_100g * scale, 2),
            protein=round(product.protein_per_100g * scale, 2),
            carbs=round(product.carbs_per_100g * scale, 2),
            fat=round(product.fat_per_100g * scale, 2),
            match_confidence=0.95,
            barcode=barcode,
        )


def _format_name(product_name: str, brand: str) -> str:
    if brand and brand.lower() not in product_name.lower():
        return f"{product_name} ({brand})"
    return product_name

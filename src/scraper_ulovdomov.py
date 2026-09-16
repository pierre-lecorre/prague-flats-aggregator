import logging
from typing import Any, Dict, List

from config import MAX_PRICE_CZK, MIN_SIZE_M2
from scraper_base import BaseScraper, ScrapeError, http_client

logger = logging.getLogger(__name__)

API_URL = "https://www.ulovdomov.cz/fe-api/find/seperated-offers-within-bounds"
PRAGUE_BOUNDS = {
    "north_east": {"lat": 50.177, "lng": 14.707},
    "south_west": {"lat": 49.942, "lng": 14.224},
}
# 1 = whole-flat rent. Shared rooms are 24–28.
APARTMENT_DISPOSITIONS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]


class UlovDomovScraper(BaseScraper):
    source_name = "ulovdomov"
    base_url = "https://www.ulovdomov.cz"

    async def scrape(self) -> List[Dict[str, Any]]:
        payload = {
            "acreage_from": MIN_SIZE_M2 or "",
            "acreage_to": "",
            "added_before": "",
            "banner_panel_width_type": 480,
            "bounds": PRAGUE_BOUNDS,
            "conveniences": [],
            "dispositions": APARTMENT_DISPOSITIONS,
            "furnishing": [],
            "is_price_commision_free": None,
            "limit": 50,
            "offer_type_id": 1,
            "page": 1,
            "price_from": "",
            "price_to": MAX_PRICE_CZK,
            "query": "",
            "sort_by": "date:desc",
            "sticker": None,
        }
        async with http_client() as client:
            try:
                response = await client.post(API_URL, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                raise ScrapeError(f"ulovdomov API failed: {exc}") from exc

        offers = data.get("offers") or []
        if not offers:
            raise ScrapeError("ulovdomov: API returned 0 offers")

        listings: List[Dict[str, Any]] = []
        for offer in offers:
            listing = self._parse_offer(offer)
            if listing:
                listings.append(listing)

        listings = self.dedupe(listings)
        if not listings:
            raise ScrapeError("ulovdomov: parsed 0 listings")
        logger.info("ulovdomov: %d listings", len(listings))
        return listings

    def _parse_offer(self, offer: Dict[str, Any]):
        if offer.get("offer_type_id") not in (None, 1):
            return None
        if offer.get("disposition_id") in {24, 25, 26, 27, 28}:
            return None
        url = offer.get("absolute_url") or ""
        village = (offer.get("village") or {}).get("label") or "Praha"
        street = (offer.get("street") or {}).get("label")
        part = (offer.get("village_part") or {}).get("label")
        address_parts = [p for p in (street, village, part) if p]
        photos = offer.get("photos") or []
        images = [p.get("path") for p in photos if p.get("path")]
        size = offer.get("acreage")
        title = offer.get("seo") or ""
        if size:
            title = f"Pronájem {size} m², {', '.join(address_parts)}"
        elif address_parts:
            title = f"Pronájem, {', '.join(address_parts)}"
        return self.make_listing(
            url=url,
            title=title,
            price=offer.get("price_rental"),
            size_m2=float(size) if size else None,
            address=", ".join(address_parts),
            description=offer.get("description") or "",
            images=images[:5],
            latitude=offer.get("lat"),
            longitude=offer.get("lng"),
            listed_at=offer.get("published_at"),
            listed_fees=int(offer["price_monthly_fee"]) if offer.get("price_monthly_fee") else None,
        )

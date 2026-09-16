import logging
from typing import Any, Dict, List

from config import MAX_PRICE_CZK, MIN_SIZE_M2
from scraper_base import BaseScraper, ScrapeError, http_client

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.bezrealitky.cz/graphql/"
PRAGUE_OSM_ID = "R435514"
SEARCH_QUERY = """
query AdvertList(
  $estateType: [EstateType],
  $offerType: [OfferType],
  $regionOsmIds: [ID],
  $limit: Int = 50,
  $offset: Int = 0,
  $order: ResultOrder = TIMEORDER_DESC,
  $priceTo: Int,
  $surfaceFrom: Int,
  $currency: Currency,
  $locale: Locale!,
  $roommate: Boolean
) {
  listAdverts(
    offerType: $offerType
    estateType: $estateType
    regionOsmIds: $regionOsmIds
    limit: $limit
    offset: $offset
    order: $order
    priceTo: $priceTo
    surfaceFrom: $surfaceFrom
    currency: $currency
    roommate: $roommate
  ) {
    totalCount
    list {
      id
      uri
      imageAltText(locale: $locale)
      address(locale: $locale)
      surface
      price
      charges
      roommate
      gps { lat lng }
    }
  }
}
"""


class BezrealitkyScraper(BaseScraper):
    source_name = "bezrealitky"
    base_url = "https://www.bezrealitky.cz"

    async def scrape(self) -> List[Dict[str, Any]]:
        payload = {
            "operationName": "AdvertList",
            "query": SEARCH_QUERY,
            "variables": {
                "locale": "CS",
                "estateType": ["BYT"],
                "offerType": ["PRONAJEM"],
                "regionOsmIds": [PRAGUE_OSM_ID],
                "limit": 50,
                "offset": 0,
                "priceTo": MAX_PRICE_CZK,
                "surfaceFrom": MIN_SIZE_M2,
                "currency": "CZK",
                "roommate": False,
            },
        }
        async with http_client() as client:
            try:
                response = await client.post(GRAPHQL_URL, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                raise ScrapeError(f"bezrealitky GraphQL failed: {exc}") from exc

        errors = data.get("errors")
        if errors:
            raise ScrapeError(f"bezrealitky GraphQL errors: {errors}")
        items = ((data.get("data") or {}).get("listAdverts") or {}).get("list") or []
        if not items:
            raise ScrapeError("bezrealitky: listAdverts returned 0 items")

        listings: List[Dict[str, Any]] = []
        for item in items:
            listing = self._parse_item(item)
            if listing:
                listings.append(listing)

        listings = self.dedupe(listings)
        if not listings:
            raise ScrapeError("bezrealitky: parsed 0 listings")
        logger.info("bezrealitky: %d listings", len(listings))
        return listings

    def _parse_item(self, item: Dict[str, Any]):
        if item.get("roommate"):
            return None
        uri = item.get("uri") or ""
        if not uri:
            return None
        title = item.get("imageAltText") or f"Pronájem bytu {item.get('surface') or ''} m²"
        gps = item.get("gps") or {}
        desc_bits = [title, item.get("address") or ""]
        if item.get("charges"):
            desc_bits.append(f"poplatky {item['charges']} CZK")
        return self.make_listing(
            url=f"{self.base_url}/nemovitosti-byty-domy/{uri}",
            title=title,
            price=item.get("price"),
            size_m2=float(item["surface"]) if item.get("surface") else None,
            address=item.get("address") or "",
            description=", ".join(b for b in desc_bits if b),
            latitude=gps.get("lat"),
            longitude=gps.get("lng"),
        )

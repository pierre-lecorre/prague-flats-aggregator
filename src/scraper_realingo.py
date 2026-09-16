import logging
from typing import Any, Dict, List
from urllib.parse import urljoin

from config import MAX_PRICE_CZK, MIN_SIZE_M2
from scraper_base import BaseScraper, ScrapeError, http_client

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://www.realingo.cz/graphql"
SEARCH_QUERY = """
query SearchOffer(
  $purpose: OfferPurpose,
  $property: PropertyType,
  $address: String,
  $price: RangeInput,
  $area: RangeInput,
  $sort: OfferSort = NEWEST,
  $first: Int = 20,
  $skip: Int = 0
) {
  searchOffer(
    filter: {
      purpose: $purpose,
      property: $property,
      address: $address,
      price: $price,
      area: $area
    }
    sort: $sort
    first: $first
    skip: $skip
    save: false
  ) {
    total
    items {
      id
      url
      category
      price { total currency }
      area { main }
      location { address latitude longitude }
    }
  }
}
"""

_CATEGORY_LABEL = {
    "FLAT1_KK": "Byt 1+kk",
    "FLAT11": "Byt 1+1",
    "FLAT2_KK": "Byt 2+kk",
    "FLAT21": "Byt 2+1",
    "FLAT3_KK": "Byt 3+kk",
    "FLAT31": "Byt 3+1",
    "FLAT4_KK": "Byt 4+kk",
    "FLAT41": "Byt 4+1",
    "FLAT5_KK": "Byt 5+kk",
    "FLAT51": "Byt 5+1",
    "FLAT6_AND_MORE": "Byt 6+",
    "OTHERS_FLAT": "Atypický byt",
}


class RealingoScraper(BaseScraper):
    source_name = "realingo"
    base_url = "https://www.realingo.cz"

    async def scrape(self) -> List[Dict[str, Any]]:
        payload = {
            "query": SEARCH_QUERY,
            "operationName": "SearchOffer",
            "variables": {
                "purpose": "RENT",
                "property": "FLAT",
                "address": "Praha",
                "price": {"from": None, "to": MAX_PRICE_CZK},
                "area": {"from": MIN_SIZE_M2, "to": None},
                "sort": "NEWEST",
                "first": 50,
                "skip": 0,
            },
        }
        async with http_client() as client:
            try:
                response = await client.post(GRAPHQL_URL, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                raise ScrapeError(f"realingo GraphQL failed: {exc}") from exc

        errors = data.get("errors")
        if errors:
            raise ScrapeError(f"realingo GraphQL errors: {errors}")
        items = ((data.get("data") or {}).get("searchOffer") or {}).get("items") or []
        if not items:
            raise ScrapeError("realingo: searchOffer returned 0 items")

        listings: List[Dict[str, Any]] = []
        for item in items:
            listing = self._parse_item(item)
            if listing:
                listings.append(listing)

        listings = self.dedupe(listings)
        if not listings:
            raise ScrapeError("realingo: parsed 0 listings")
        logger.info("realingo: %d listings", len(listings))
        return listings

    def _parse_item(self, item: Dict[str, Any]):
        loc = item.get("location") or {}
        area = (item.get("area") or {}).get("main")
        cat = _CATEGORY_LABEL.get(item.get("category") or "", item.get("category") or "Byt")
        title_parts = [cat]
        if area:
            title_parts.append(f"{area} m²")
        if loc.get("address"):
            title_parts.append(loc["address"])
        return self.make_listing(
            url=urljoin(self.base_url, item.get("url") or ""),
            title=", ".join(title_parts),
            price=(item.get("price") or {}).get("total"),
            size_m2=float(area) if area else None,
            address=loc.get("address") or "",
            description=", ".join(title_parts),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
        )

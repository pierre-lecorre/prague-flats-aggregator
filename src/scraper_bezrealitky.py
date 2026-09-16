import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from config import MAX_PRICE_CZK, MIN_SIZE_M2
from scraper_base import (
    BaseScraper,
    ScrapeError,
    http_client,
    listed_at_from_days_active,
)

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.bezrealitky.cz/graphql/"
PRAGUE_OSM_ID = "R435514"
SEARCH_URL = (
    "https://www.bezrealitky.cz/vyhledat"
    "?offerType=PRONAJEM&estateType=BYT&location=praha"
    f"&regionOsmIds={PRAGUE_OSM_ID}"
    f"&priceTo={MAX_PRICE_CZK}&currency=CZK&surfaceFrom={MIN_SIZE_M2}"
)
GRAPHQL_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.bezrealitky.cz",
    "Referer": SEARCH_URL,
}
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
      isNew
      daysActive
      mainImage { url }
    }
  }
}
"""
_RETRY_STATUSES = {429, 502, 503, 504}


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
                "limit": 20,
                "offset": 0,
                "priceTo": MAX_PRICE_CZK,
                "surfaceFrom": MIN_SIZE_M2,
                "currency": "CZK",
                "roommate": False,
            },
        }
        items = await self._fetch_graphql(payload)
        if items is None:
            logger.warning("bezrealitky GraphQL down — fallback HTML __NEXT_DATA__")
            items = await self._fetch_next_data()
        if not items:
            raise ScrapeError("bezrealitky: listAdverts returned 0 items")

        listings: List[Dict[str, Any]] = []
        for item in items:
            listing = self._parse_item(item)
            if listing:
                listings.append(listing)

        listings = self.dedupe(listings)
        logger.info("bezrealitky: %d fresh listings", len(listings))
        return listings

    async def _fetch_graphql(self, payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        last_error = None
        async with http_client() as client:
            for attempt in range(1, 4):
                try:
                    response = await client.post(
                        GRAPHQL_URL, json=payload, headers=GRAPHQL_HEADERS
                    )
                    if response.status_code in _RETRY_STATUSES:
                        last_error = f"HTTP {response.status_code}"
                        logger.warning(
                            "bezrealitky GraphQL %s (try %d/3)",
                            response.status_code,
                            attempt,
                        )
                        await asyncio.sleep(1.5 * attempt)
                        continue
                    response.raise_for_status()
                    data = response.json()
                except httpx.HTTPStatusError as exc:
                    last_error = str(exc)
                    if exc.response is not None and exc.response.status_code in _RETRY_STATUSES:
                        await asyncio.sleep(1.5 * attempt)
                        continue
                    raise ScrapeError(f"bezrealitky GraphQL failed: {exc}") from exc
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning("bezrealitky GraphQL error (try %d/3): %s", attempt, exc)
                    await asyncio.sleep(1.5 * attempt)
                    continue

                errors = data.get("errors")
                if errors:
                    raise ScrapeError(f"bezrealitky GraphQL errors: {errors}")
                items = ((data.get("data") or {}).get("listAdverts") or {}).get("list") or []
                if items:
                    return items
                last_error = "empty listAdverts"
                await asyncio.sleep(1.5 * attempt)
        logger.warning("bezrealitky GraphQL gave up: %s", last_error)
        return None

    async def _fetch_next_data(self) -> List[Dict[str, Any]]:
        async with http_client() as client:
            try:
                response = await client.get(
                    SEARCH_URL,
                    headers={
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                        "Referer": "https://www.bezrealitky.cz/",
                    },
                )
                response.raise_for_status()
            except Exception as exc:
                raise ScrapeError(f"bezrealitky HTML fallback failed: {exc}") from exc

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            response.text,
            re.DOTALL,
        )
        if not match:
            raise ScrapeError("bezrealitky: __NEXT_DATA__ missing on search page")
        try:
            payload = json.loads(match.group(1))
            cache = payload["props"]["pageProps"]["apolloCache"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ScrapeError(f"bezrealitky: NEXT_DATA parse failed: {exc}") from exc
        items = self._adverts_from_apollo(cache)
        logger.info("bezrealitky HTML fallback: %d adverts", len(items))
        return items

    def _adverts_from_apollo(self, cache: Dict[str, Any]) -> List[Dict[str, Any]]:
        root = cache.get("ROOT_QUERY") or {}
        prague_refs: List[Any] = []
        for key, value in root.items():
            if not str(key).startswith("listAdverts(") or "discountedOnly" in str(key):
                continue
            if not isinstance(value, dict):
                continue
            items = value.get("list") or []
            if not items:
                continue
            if PRAGUE_OSM_ID in str(key):
                prague_refs = items
        best = prague_refs
        if not best:
            raise ScrapeError("bezrealitky HTML fallback missing Prague listAdverts")
        adverts: List[Dict[str, Any]] = []
        for ref in best:
            if isinstance(ref, dict) and ref.get("__ref"):
                item = cache.get(ref["__ref"])
            elif isinstance(ref, dict):
                item = ref
            else:
                item = None
            if isinstance(item, dict):
                adverts.append(item)
        return adverts

    def _pick(self, item: Dict[str, Any], name: str):
        if name in item:
            return item[name]
        prefix = name + "("
        for key, value in item.items():
            if str(key).startswith(prefix):
                return value
        return None

    def _parse_item(self, item: Dict[str, Any]):
        if item.get("roommate"):
            return None
        uri = item.get("uri") or ""
        if not uri:
            return None
        title = self._pick(item, "imageAltText") or f"Pronájem bytu {item.get('surface') or ''} m²"
        gps = item.get("gps") or {}
        address = self._pick(item, "address") or ""
        desc_bits = [title, address]
        charges = item.get("charges")
        if charges:
            desc_bits.append(f"poplatky {charges} CZK")
        images = []
        main = item.get("mainImage")
        if isinstance(main, dict) and main.get("url"):
            images.append(main["url"])
        return self.make_listing(
            url=f"{self.base_url}/nemovitosti-byty-domy/{uri}",
            title=title,
            price=item.get("price"),
            size_m2=float(item["surface"]) if item.get("surface") else None,
            address=address,
            description=", ".join(b for b in desc_bits if b),
            images=images,
            latitude=gps.get("lat"),
            longitude=gps.get("lng"),
            listed_at=listed_at_from_days_active(
                self._pick(item, "daysActive") or item.get("daysActive"),
                item.get("isNew") or self._pick(item, "isNew"),
            ),
            listed_fees=int(charges) if charges is not None else None,
        )

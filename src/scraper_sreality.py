import json
import logging
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from config import MAX_LISTING_AGE_HOURS, SOURCES
from scraper_base import BaseScraper, ScrapeError, http_client

logger = logging.getLogger(__name__)

_CATEGORY_TYPE = {1: "prodej", 2: "pronajem", 3: "drazby"}
_CATEGORY_MAIN = {1: "byt", 2: "dum", 3: "pozemek", 4: "komercni", 5: "ostatni"}
_CATEGORY_SUB = {
    2: "1+kk",
    3: "1+1",
    4: "2+kk",
    5: "2+1",
    6: "3+kk",
    7: "3+1",
    8: "4+kk",
    9: "4+1",
    10: "5+kk",
    11: "5+1",
    12: "6-a-vice",
    16: "atypicky",
    47: "pokoj",
}


class SrealityScraper(BaseScraper):
    source_name = "sreality"
    base_url = "https://www.sreality.cz"

    async def scrape(self) -> List[Dict[str, Any]]:
        url = SOURCES["sreality"]
        if MAX_LISTING_AGE_HOURS and MAX_LISTING_AGE_HOURS <= 24:
            sep = "&" if "?" in url else "?"
            if "stari=" not in url:
                url = f"{url}{sep}stari=dnes"
        elif MAX_LISTING_AGE_HOURS and MAX_LISTING_AGE_HOURS <= 24 * 8:
            sep = "&" if "?" in url else "?"
            if "stari=" not in url:
                url = f"{url}{sep}stari=tyden"
        async with http_client() as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except Exception as exc:
                raise ScrapeError(f"sreality HTTP failed: {exc}") from exc

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            response.text,
            re.DOTALL,
        )
        if not match:
            raise ScrapeError("sreality: __NEXT_DATA__ missing — page shape changed")

        try:
            payload = json.loads(match.group(1))
            queries = payload["props"]["pageProps"]["dehydratedState"]["queries"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ScrapeError(f"sreality: NEXT_DATA parse failed: {exc}") from exc

        results = None
        for query in queries:
            key = query.get("queryKey") or []
            if isinstance(key, list) and key and key[0] == "estatesSearch":
                results = (query.get("state") or {}).get("data", {}).get("results")
                break
        if results is None:
            raise ScrapeError("sreality: estatesSearch results empty")

        listings: List[Dict[str, Any]] = []
        for item in results:
            listing = self._parse_item(item)
            if listing:
                listings.append(listing)

        listings = self.dedupe(listings)
        logger.info("sreality: %d fresh listings", len(listings))
        return listings

    def _parse_item(self, item: Dict[str, Any]):
        loc = item.get("locality") or {}
        title = item.get("name") or ""
        address_parts = [
            loc.get("street"),
            loc.get("cityPart") or loc.get("city"),
            loc.get("district"),
        ]
        address = ", ".join(p for p in address_parts if p)
        images = []
        if item.get("images"):
            img = item["images"][0].get("url") or ""
            if img:
                images.append("https:" + img if img.startswith("//") else img)
        return self.make_listing(
            url=self._offer_url(item),
            title=title,
            price=item.get("priceCzk") or item.get("priceSummaryCzk"),
            size_m2=self.parse_size(title),
            address=address,
            description=title,
            images=images,
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
        )

    def _offer_url(self, item: Dict[str, Any]) -> str:
        cat_type = _CATEGORY_TYPE.get((item.get("categoryTypeCb") or {}).get("value"), "pronajem")
        cat_main = _CATEGORY_MAIN.get((item.get("categoryMainCb") or {}).get("value"), "byt")
        cat_sub = _CATEGORY_SUB.get((item.get("categorySubCb") or {}).get("value"), "byt")
        loc = item.get("locality") or {}
        locality = "-".join(
            p for p in (
                loc.get("citySeoName"),
                loc.get("cityPartSeoName"),
                loc.get("streetSeoName"),
            ) if p
        ) or "praha"
        return urljoin(self.base_url, f"/detail/{cat_type}/{cat_main}/{cat_sub}/{locality}/{item['id']}")

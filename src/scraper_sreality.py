import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
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
        async with http_client() as client:
            await self._fill_details(client, listings)
        logger.info("sreality: %d fresh listings", len(listings))
        return listings

    async def _fill_details(self, client, listings: List[Dict[str, Any]]) -> None:
        sem = asyncio.Semaphore(2)

        async def one(listing: Dict[str, Any]) -> None:
            async with sem:
                try:
                    response = await client.get(listing["url"])
                    response.raise_for_status()
                except Exception as exc:
                    logger.warning("sreality detail failed %s: %s", listing.get("url"), exc)
                    return
                estate = self._estate_from_html(response.text)
                if not estate:
                    return
                desc = (estate.get("description") or "").strip()
                if desc:
                    listing["description"] = desc
                loc = estate.get("locality") if isinstance(estate.get("locality"), dict) else {}
                address = self._address_from_loc(loc) or listing.get("address")
                if address:
                    listing["address"] = address
                if loc.get("latitude") is not None:
                    listing["latitude"] = loc.get("latitude")
                    listing["longitude"] = loc.get("longitude")
                images = self._images_from(estate.get("images") or listing.get("images") or [])
                if images:
                    listing["images"] = images
                await asyncio.sleep(0.35)

        if listings:
            await asyncio.gather(*[one(item) for item in listings])

    def _estate_from_html(self, html: str) -> Optional[Dict[str, Any]]:
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
            queries = payload["props"]["pageProps"]["dehydratedState"]["queries"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
        for query in queries:
            key = query.get("queryKey") or []
            if isinstance(key, list) and key and key[0] == "estate":
                data = (query.get("state") or {}).get("data")
                if isinstance(data, dict):
                    return data
        return None

    def _address_from_loc(self, loc: Any) -> str:
        if isinstance(loc, str):
            return loc.strip()
        if not isinstance(loc, dict):
            return ""
        street = loc.get("street") or ""
        num = loc.get("streetNumber") or loc.get("houseNumber")
        if street and num:
            street = f"{street} {num}"
        parts = [
            street,
            loc.get("cityPart") or loc.get("quarter"),
            loc.get("district") or loc.get("city"),
        ]
        return ", ".join(p for p in parts if p)

    def _images_from(self, raw: Any) -> List[str]:
        urls: List[str] = []
        items = raw if isinstance(raw, list) else []
        for item in items:
            img = item.get("url") if isinstance(item, dict) else item
            if not img:
                continue
            url = "https:" + img if str(img).startswith("//") else str(img)
            if url not in urls:
                urls.append(url)
            if len(urls) >= 3:
                break
        return urls

    def _parse_item(self, item: Dict[str, Any]):
        loc = item.get("locality") if isinstance(item.get("locality"), dict) else {}
        title = (item.get("name") or "").replace("\xa0", " ")
        address = self._address_from_loc(loc)
        return self.make_listing(
            url=self._offer_url(item),
            title=title,
            price=item.get("priceCzk") or item.get("priceSummaryCzk"),
            size_m2=self.parse_size(title),
            address=address,
            description=title,
            images=self._images_from(item.get("images") or []),
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

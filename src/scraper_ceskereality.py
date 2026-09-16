import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from config import MAPY_API_KEY, SOURCES
from scraper_base import BaseScraper, ScrapeError, http_client
from commute import _geocode_address

logger = logging.getLogger(__name__)

_COORD_RE = re.compile(
    r'data-coord-lat="([0-9.]+)"[^>]*data-coord-lng="([0-9.]+)"'
    r'|[?&]q=([0-9.]+),([0-9.]+)',
    re.IGNORECASE,
)


class CeskeRealityScraper(BaseScraper):
    source_name = "ceskereality"
    base_url = "https://www.ceskereality.cz"

    async def scrape(self) -> List[Dict[str, Any]]:
        url = SOURCES["ceskereality"]
        async with http_client() as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except Exception as exc:
                raise ScrapeError(f"ceskereality HTTP failed: {exc}") from exc

            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select("article.i-estate")
            if not cards:
                raise ScrapeError("ceskereality: no article.i-estate cards — markup changed")

            listings: List[Dict[str, Any]] = []
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)

            listings = self.dedupe(listings)
            if not listings:
                raise ScrapeError("ceskereality: parsed 0 listings")
            await self._fill_coords(client, listings)

        logger.info("ceskereality: %d listings", len(listings))
        return listings

    async def _fill_coords(self, client, listings: List[Dict[str, Any]]) -> None:
        sem = asyncio.Semaphore(2)

        async def one(listing: Dict[str, Any]) -> None:
            async with sem:
                coords = await self._coords_from_detail(client, listing["url"])
                if coords:
                    listing["latitude"], listing["longitude"] = coords
                    return
                geocoded = _geocode_address(
                    listing.get("address") or listing.get("title") or "",
                    MAPY_API_KEY,
                )
                if geocoded:
                    listing["latitude"], listing["longitude"] = geocoded

        await asyncio.gather(*(one(item) for item in listings))
        missing = sum(1 for item in listings if item.get("latitude") is None)
        if missing:
            logger.warning("ceskereality: %d/%d listings still have no GPS", missing, len(listings))

    async def _coords_from_detail(self, client, url: str) -> Optional[Tuple[float, float]]:
        last_exc = None
        for attempt in range(1, 4):
            try:
                response = await client.get(url)
                if response.status_code == 429:
                    last_exc = f"HTTP 429"
                    await asyncio.sleep(1.5 * attempt)
                    continue
                response.raise_for_status()
            except Exception as exc:
                last_exc = exc
                logger.warning("ceskereality detail failed %s: %s", url, exc)
                return None
            match = _COORD_RE.search(response.text)
            if not match:
                return None
            lat = match.group(1) or match.group(3)
            lon = match.group(2) or match.group(4)
            try:
                return float(lat), float(lon)
            except (TypeError, ValueError):
                return None
        logger.warning("ceskereality detail gave up %s: %s", url, last_exc)
        return None

    def _parse_card(self, card):
        link = card.select_one("a.i-estate__title-link")
        if not link or not link.get("href"):
            return None
        title = link.get_text(strip=True)
        price_el = card.select_one(".i-estate__footer-price-value")
        desc_el = card.select_one(".i-estate__description-text")
        img = card.select_one("img")
        return self.make_listing(
            url=link["href"],
            title=title,
            price=self.parse_price(price_el.get_text() if price_el else ""),
            size_m2=self.parse_size(title),
            address=self._address_from_title(title),
            description=desc_el.get_text(" ", strip=True) if desc_el else "",
            images=[img["src"]] if img and img.get("src") else [],
        )

    def _address_from_title(self, title: str) -> str:
        marker = "m²"
        idx = title.find(marker)
        if idx == -1:
            marker = "m2"
            idx = title.lower().find(marker)
        if idx == -1:
            return ""
        return title[idx + len(marker):].strip(" ,")

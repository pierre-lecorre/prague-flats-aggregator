import asyncio
import logging
from typing import Any, Dict, List

from bs4 import BeautifulSoup
import httpx

from config import MAPY_API_KEY, SOURCES
from scraper_base import (
    BaseScraper,
    ScrapeError,
    http_client,
    parse_czech_relative,
)
from commute import _geocode_address

logger = logging.getLogger(__name__)

_RETRY_STATUSES = {429, 502, 503, 504}
_HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.ceskereality.cz/",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
}


class CeskeRealityScraper(BaseScraper):
    source_name = "ceskereality"
    base_url = "https://www.ceskereality.cz"

    async def scrape(self) -> List[Dict[str, Any]]:
        url = SOURCES["ceskereality"]
        async with http_client() as client:
            await self._warmup(client)
            response = await self._get_list(client, url)

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
                logger.info("ceskereality: 0 fresh listings")
                return listings
            self._fill_coords(listings)

        logger.info("ceskereality: %d fresh listings", len(listings))
        return listings

    async def _warmup(self, client: httpx.AsyncClient) -> None:
        try:
            await client.get("https://www.ceskereality.cz/", headers=_HTML_HEADERS)
            await asyncio.sleep(2.0)
        except Exception as exc:
            logger.warning("ceskereality homepage warmup failed: %s", exc)

    async def _get_list(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        last_error = None
        for attempt in range(1, 8):
            try:
                response = await client.get(url, headers=_HTML_HEADERS)
                if response.status_code in _RETRY_STATUSES:
                    wait = self._retry_after(response, attempt)
                    last_error = f"HTTP {response.status_code}"
                    logger.warning(
                        "ceskereality %s (try %d/7), sleep %.1fs",
                        last_error,
                        attempt,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = str(exc)
                if exc.response is not None and exc.response.status_code in _RETRY_STATUSES:
                    await asyncio.sleep(self._retry_after(exc.response, attempt))
                    continue
                raise ScrapeError(f"ceskereality HTTP failed: {exc}") from exc
            except Exception as exc:
                last_error = str(exc)
                logger.warning("ceskereality HTTP error (try %d/7): %s", attempt, exc)
                await asyncio.sleep(2.0 * attempt)
        raise ScrapeError(f"ceskereality HTTP failed: {last_error}")

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After")
        try:
            header = float(raw) if raw else 0.0
        except ValueError:
            header = 0.0
        if response.status_code == 429:
            wait = max(header, 20.0 * attempt)
        else:
            wait = header or (2.5 * attempt)
        return min(max(wait, 2.0), 90.0)

    def _fill_coords(self, listings: List[Dict[str, Any]]) -> None:
        for listing in listings:
            geocoded = _geocode_address(
                listing.get("address") or "",
                MAPY_API_KEY,
            )
            if geocoded:
                listing["latitude"], listing["longitude"] = geocoded
        missing = sum(1 for item in listings if item.get("latitude") is None)
        if missing:
            logger.warning("ceskereality: %d/%d listings still have no GPS", missing, len(listings))

    def _parse_card(self, card):
        link = card.select_one("a.i-estate__title-link")
        if not link or not link.get("href"):
            return None
        title = link.get_text(strip=True)
        price_el = card.select_one(".i-estate__footer-price-value")
        desc_el = card.select_one(".i-estate__description-text")
        img = card.select_one("img")
        listed_at = parse_czech_relative(card.get_text(" ", strip=True))
        return self.make_listing(
            url=link["href"],
            title=title,
            price=self.parse_price(price_el.get_text() if price_el else ""),
            size_m2=self.parse_size(title),
            address=self._address_from_title(title),
            description=desc_el.get_text(" ", strip=True) if desc_el else "",
            images=[img["src"]] if img and img.get("src") else [],
            listed_at=listed_at,
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

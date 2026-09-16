import logging
from typing import Any, Dict, List

from bs4 import BeautifulSoup

from config import MAPY_API_KEY, SOURCES
from scraper_base import (
    BaseScraper,
    ScrapeError,
    http_client,
    parse_czech_relative,
)
from commute import _geocode_address

logger = logging.getLogger(__name__)


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
                logger.info("ceskereality: 0 fresh listings")
                return listings
            self._fill_coords(listings)

        logger.info("ceskereality: %d fresh listings", len(listings))
        return listings

    def _fill_coords(self, listings: List[Dict[str, Any]]) -> None:
        for listing in listings:
            geocoded = _geocode_address(
                listing.get("address") or listing.get("title") or "",
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

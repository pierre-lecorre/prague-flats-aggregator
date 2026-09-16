import logging
from typing import Any, Dict, List

from bs4 import BeautifulSoup

from config import SOURCES
from scraper_base import BaseScraper, ScrapeError, http_client

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
            raise ScrapeError("ceskereality: parsed 0 listings")
        logger.info("ceskereality: %d listings", len(listings))
        return listings

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

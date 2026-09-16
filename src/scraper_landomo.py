"""Landomo.cz scraper via Playwright, same intercept as landomo-scraper.

POST /api/explore/search is Cloudflare-gated (403 without browser attest).
Navigate the search page, capture that JSON, then fetch descriptions in-page.
https://github.com/pierre-lecorre/landomo-scraper
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from config import LANDOMO_SEARCH_URL
from scraper_base import BaseScraper, ScrapeError, USER_AGENT

logger = logging.getLogger(__name__)


class LandomoScraper(BaseScraper):
    source_name = "landomo"
    base_url = "https://landomo.cz"

    async def scrape(self) -> List[Dict[str, Any]]:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeout
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ScrapeError(
                "landomo needs playwright: pip install playwright && playwright install chromium"
            ) from exc

        captured: List[Dict[str, Any]] = []

        async def on_response(response) -> None:
            if "api/explore/search" not in response.url:
                return
            if response.request.method != "POST":
                return
            try:
                data = await response.json()
            except Exception:
                return
            if isinstance(data, dict) and "results" in data:
                captured.append(data)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(user_agent=USER_AGENT)
                page = await context.new_page()
                page.on("response", on_response)
                logger.info("landomo: opening %s", LANDOMO_SEARCH_URL)
                try:
                    await page.goto(LANDOMO_SEARCH_URL, wait_until="networkidle", timeout=45000)
                except PlaywrightTimeout:
                    logger.warning("landomo: page load timed out, using captured data if any")

                if not captured:
                    await browser.close()
                    raise ScrapeError(
                        "landomo: no /api/explore/search intercept (Cloudflare or bad URL)"
                    )

                results = captured[-1].get("results") or []
                await browser.close()
        except ScrapeError:
            raise
        except Exception as exc:
            raise ScrapeError(f"landomo Playwright failed: {exc}") from exc

        listings: List[Dict[str, Any]] = []
        for item in results:
            listing = self._parse_item(item)
            if listing:
                listings.append(listing)

        listings = self.dedupe(listings)
        if not listings:
            raise ScrapeError("landomo: parsed 0 listings")
        logger.info("landomo: %d listings", len(listings))
        return listings

    def _parse_item(self, item: Dict[str, Any]):
        listing_id = item.get("id")
        url = (
            item.get("source_url")
            or item.get("url")
            or (f"{self.base_url}/en/property/{listing_id}" if listing_id else "")
        )
        lat = item.get("latitude") if item.get("latitude") is not None else item.get("lat")
        lon = (
            item.get("longitude")
            if item.get("longitude") is not None
            else item.get("lon") or item.get("lng")
        )
        size = item.get("sqm") or item.get("area") or item.get("size")
        price = item.get("price")
        address = item.get("address") or item.get("location") or ""
        district = item.get("district") or item.get("city_part") or ""
        title = item.get("title") or ""
        if not title:
            bits = ["Pronájem"]
            if size:
                bits.append(f"{size} m²")
            if address or district:
                bits.append(str(address or district))
            title = ", ".join(bits)
        listed_at = (
            item.get("listed_at")
            or item.get("updated_at")
            or item.get("created_at")
            or item.get("first_seen_at")
        )
        bedrooms = item.get("bedrooms") or item.get("rooms")
        try:
            bedrooms = int(bedrooms) if bedrooms is not None else None
        except (TypeError, ValueError):
            bedrooms = None
        images = item.get("images") or item.get("photos") or []
        if images and isinstance(images[0], dict):
            images = [p.get("url") or p.get("path") for p in images if p.get("url") or p.get("path")]
        desc_bits = [
            item.get("czech_disposition"),
            f"ownership {item['ownership_scope']}" if item.get("ownership_scope") else None,
            f"sale_method {item['sale_method']}" if item.get("sale_method") else None,
            f"floor {item['floor']}" if item.get("floor") is not None else None,
            "elevator" if item.get("has_elevator") else None,
            item.get("city"),
            item.get("region"),
            item.get("description"),
        ]
        return self.make_listing(
            url=url,
            title=title,
            price=int(price) if price is not None else None,
            size_m2=float(size) if size else None,
            address=address,
            description=". ".join(str(b) for b in desc_bits if b),
            images=[img for img in images[:5] if img],
            latitude=float(lat) if lat is not None else None,
            longitude=float(lon) if lon is not None else None,
            listed_at=str(listed_at) if listed_at else None,
            bedrooms=bedrooms,
            district=district or item.get("region") or None,
        )

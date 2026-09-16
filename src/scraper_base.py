from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import hashlib
import re

import httpx

from config import HTTP_SSL_VERIFY, MAX_LISTING_AGE_HOURS, MAX_PRICE_CZK, MIN_SIZE_M2

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "cs,en;q=0.9",
}
HTTP_TIMEOUT = 40.0
MAX_LISTINGS_PER_SOURCE = 20


class ScrapeError(RuntimeError):
    """Raised when a source cannot produce listings."""


def freshness_days() -> int:
    hours = MAX_LISTING_AGE_HOURS or 24
    return max(1, (int(hours) + 23) // 24)


def parse_listed_at(raw: Any) -> Optional[datetime]:
    """Parse ISO / unix / '+0200' timestamps to UTC."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_fresh_timestamp(raw: Any) -> bool:
    """True if unknown date or within MAX_LISTING_AGE_HOURS."""
    if not MAX_LISTING_AGE_HOURS:
        return True
    dt = parse_listed_at(raw)
    if dt is None:
        return True
    return datetime.now(timezone.utc) - dt <= timedelta(hours=MAX_LISTING_AGE_HOURS, minutes=30)


def parse_czech_relative(text: str) -> Optional[str]:
    """'před hodinou' / 'před 3 dny' → ISO UTC."""
    if not text:
        return None
    blob = text.lower()
    now = datetime.now(timezone.utc)
    rules = (
        (r"před\s+chvílí", timedelta(minutes=5)),
        (r"před\s+minutou", timedelta(minutes=1)),
        (r"před\s+(\d+)\s+minut", "minutes"),
        (r"před\s+hodinou", timedelta(hours=1)),
        (r"před\s+(\d+)\s+hodin", "hours"),
        (r"včera", timedelta(days=1)),
        (r"před\s+dnem", timedelta(days=1)),
        (r"před\s+(\d+)\s+dn[eiyíůu]+", "days"),
        (r"před\s+týdnem", timedelta(days=7)),
        (r"před\s+(\d+)\s+týdn", "weeks"),
        (r"před\s+měsícem", timedelta(days=30)),
        (r"před\s+(\d+)\s+měsíc", "months"),
    )
    for pat, spec in rules:
        match = re.search(pat, blob)
        if not match:
            continue
        if isinstance(spec, timedelta):
            delta = spec
        else:
            n = int(match.group(1))
            delta = {
                "minutes": timedelta(minutes=n),
                "hours": timedelta(hours=n),
                "days": timedelta(days=n),
                "weeks": timedelta(days=7 * n),
                "months": timedelta(days=30 * n),
            }[spec]
        return (now - delta).isoformat()
    return None


def listed_at_from_days_active(days_active: Any, is_new: Any = False) -> Optional[str]:
    match = re.search(r"(\d+)", str(days_active or ""))
    if match:
        days = int(match.group(1))
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if is_new:
        return datetime.now(timezone.utc).isoformat()
    return None


class ScrapeError(RuntimeError):
    """Raised when a source cannot produce listings."""


class BaseScraper(ABC):
    source_name: str = "base"
    base_url: str = ""

    @abstractmethod
    async def scrape(self) -> List[Dict[str, Any]]:
        pass

    def generate_listing_id(self, url: str) -> str:
        return f"{self.source_name}_{hashlib.md5(url.encode()).hexdigest()[:12]}"

    def parse_price(self, price_str: str) -> Optional[int]:
        if not price_str:
            return None
        match = re.search(r"(\d[\d\s,]*)", str(price_str))
        if not match:
            return None
        digits = re.sub(r"[^\d]", "", match.group(1))
        return int(digits) if digits else None

    def parse_size(self, size_str: str) -> Optional[float]:
        if not size_str:
            return None
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*m", str(size_str), re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "."))
        match = re.search(r"(\d+(?:[.,]\d+)?)", str(size_str))
        if match:
            return float(match.group(1).replace(",", "."))
        return None

    def make_listing(
        self,
        url: str,
        title: str = "",
        price: Optional[int] = None,
        size_m2: Optional[float] = None,
        address: str = "",
        description: str = "",
        images: Optional[List[str]] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        listed_at: Optional[str] = None,
        bedrooms: Optional[int] = None,
        district: Optional[str] = None,
        listed_fees: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        if not url:
            return None
        if url.startswith("/"):
            url = self.base_url.rstrip("/") + url
        if size_m2 is None and title:
            size_m2 = self.parse_size(title)
        if price is not None and MAX_PRICE_CZK and price > MAX_PRICE_CZK:
            return None
        if size_m2 is not None and MIN_SIZE_M2 and size_m2 < MIN_SIZE_M2:
            return None
        if listed_at and not is_fresh_timestamp(listed_at):
            return None
        return {
            "id": self.generate_listing_id(url),
            "source": self.source_name,
            "title": title,
            "price": price,
            "size_m2": size_m2,
            "address": address,
            "url": url,
            "description": description or "",
            "images": images or [],
            "latitude": latitude,
            "longitude": longitude,
            "listed_at": listed_at,
            "bedrooms": bedrooms,
            "district": district,
            "listed_fees": listed_fees,
        }

    def dedupe(self, listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out = []
        for item in listings:
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(item)
            if len(out) >= MAX_LISTINGS_PER_SOURCE:
                break
        return out


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        verify=HTTP_SSL_VERIFY,
    )

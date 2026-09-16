import os
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


def _env_point(name: str, default: str) -> Dict[str, float]:
    raw = os.getenv(name, default)
    lat_s, lon_s = [p.strip() for p in raw.split(",", 1)]
    return {"lat": float(lat_s), "lon": float(lon_s)}


def _env_list(name: str) -> List[str]:
    raw = os.getenv(name, "")
    return [p.strip() for p in raw.split(",") if p.strip()]


# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Two commute anchors (lat,lon) — MOTIS public transit, same idea as landomo-scraper
POINT_A_NAME = os.getenv("COMMUTE_POINT_A_NAME", "Palmovka")
POINT_A = _env_point("COMMUTE_POINT_A", "50.1067,14.4639")
POINT_B_NAME = os.getenv("COMMUTE_POINT_B_NAME", "Muzeum")
POINT_B = _env_point("COMMUTE_POINT_B", "50.0796,14.4309")
COMMUTE_MAX_MINUTES = int(os.getenv("COMMUTE_MAX_MINUTES", "40"))
MAPY_API_KEY = os.getenv("MAPY_API_KEY", "") or None
# landomo-scraper uses foot_fast; Mapy has no public-transit routeType
MAPY_ROUTE_TYPE = os.getenv("MAPY_ROUTE_TYPE", "foot_fast")

# Flat criteria (fed to the LLM)
MIN_SIZE_M2 = int(os.getenv("MIN_SIZE_M2", "25"))
MAX_PRICE_CZK = int(os.getenv("MAX_PRICE_CZK", "20000"))
MIN_BEDROOMS = int(os.getenv("MIN_BEDROOMS", "1"))
PREFERRED_DISTRICTS = _env_list("PREFERRED_DISTRICTS")
CRITERIA_NOTES = os.getenv(
    "CRITERIA_NOTES",
    "Whole apartment only. No flatshare, no room rental, no auction. Long-term Prague rental.",
)
MIN_SCORE = int(os.getenv("MIN_SCORE", "60"))
MAX_LISTING_AGE_HOURS = int(os.getenv("MAX_LISTING_AGE_HOURS", "24"))
# Monthly utilities / service charges if the listing does not state poplatky
DEFAULT_MONTHLY_FEES_CZK = int(os.getenv("DEFAULT_MONTHLY_FEES_CZK", "4000"))

# Ollama LLM
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

# Run mode
DRY_RUN = _env_bool("DRY_RUN", "false")

# TLS verify. Set HTTP_SSL_VERIFY=false behind corporate SSL intercept.
HTTP_SSL_VERIFY = os.getenv("HTTP_SSL_VERIFY", "true").lower() not in ("0", "false", "no")

# Landomo (Playwright). Off by default — enable later with ENABLE_LANDOMO=true
ENABLE_LANDOMO = _env_bool("ENABLE_LANDOMO", "false")
LANDOMO_SEARCH_URL = os.getenv(
    "LANDOMO_SEARCH_URL",
    "https://landomo.cz/en/search?cat=flat&type=rent&pmax=20000&pcur=CZK&amin=25"
    "&q=Praha&bn=50.127&bs=50.06&be=14.511&bw=14.347",
)

# Source URLs (search pages / APIs used by scrapers)
SOURCES = {
    "ceskereality": "https://www.ceskereality.cz/pronajem/byty/praha-hlavni-mesto/do-20000/",
    "ulovdomov": "https://www.ulovdomov.cz/pronajem/bytu/praha?cena-do=20000kc",
    "realingo": "https://www.realingo.cz/graphql",
    "sreality": "https://www.sreality.cz/hledani/pronajem/byty/praha?cena-od=0&cena-do=20000",
    "bezrealitky": "https://api.bezrealitky.cz/graphql/",
    "landomo": LANDOMO_SEARCH_URL,
}

USER_CRITERIA = {
    "max_price_czk": MAX_PRICE_CZK,
    "min_sqm": MIN_SIZE_M2,
    "min_bedrooms": MIN_BEDROOMS,
    "preferred_districts": PREFERRED_DISTRICTS,
    "max_commute_minutes": COMMUTE_MAX_MINUTES,
    "commute_point_a": f"{POINT_A_NAME} ({POINT_A['lat']},{POINT_A['lon']})",
    "commute_point_b": f"{POINT_B_NAME} ({POINT_B['lat']},{POINT_B['lon']})",
    "notes": CRITERIA_NOTES,
    "default_monthly_fees_czk": DEFAULT_MONTHLY_FEES_CZK,
}

"""Commute A→flat and B→flat — same stack as landomo-scraper.

1. MOTIS public transit (metro/tram/bus + walk) — Mapy has no PID profile.
2. Fallback: Mapy.cz ``foot_fast`` walking
   https://developer.mapy.com/rest-api-mapy-cz/function/routing/

https://github.com/pierre-lecorre/landomo-scraper
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, Optional, Tuple, List

import httpx

from config import HTTP_SSL_VERIFY, MAPY_API_KEY, MAPY_ROUTE_TYPE, POINT_A, POINT_B

logger = logging.getLogger(__name__)

MOTIS_BASE = "https://europe.motis-project.de/api/v1/plan"
MOTIS_UA = "PragueFlatsAggregator/1.0 (flat-search-tool)"
MAPY_ROUTE_URL = "https://api.mapy.cz/v1/routing/route"
MAPY_GEOCODE_URL = "https://api.mapy.cz/v1/geocode"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_FOOT_URL = "https://router.project-osrm.org/route/v1/foot/{lon1},{lat1};{lon2},{lat2}"

_GEOCODE_CACHE: Dict[str, Optional[Tuple[float, float]]] = {}
_NOMINATIM_MIN_INTERVAL = 1.2
_nominatim_last_at = 0.0
_PRAGUE_CENTROIDS = (
    (50.0755, 14.4378),  # Praha city
    (50.0870, 14.4203),  # Staré Město
    (50.0833, 14.4167),
)
_GENERIC_PLACE = re.compile(
    r"^(praha|prague)(\s+\d+)?(\s*[-–]\s*[\wáčďéěíňóřšťúůýž\s]+)?$",
    re.IGNORECASE,
)


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, verify=HTTP_SSL_VERIFY, follow_redirects=True)


def _transit_duration(origin: Dict[str, float], dest: Dict[str, float]) -> Optional[float]:
    """Public-transit duration in seconds via MOTIS (PID + walking)."""
    params = {
        "fromPlace": f"{origin['lat']},{origin['lon']}",
        "toPlace": f"{dest['lat']},{dest['lon']}",
        "mode": "TRANSIT,WALK",
        "numItineraries": 3,
    }
    try:
        with _client() as client:
            resp = client.get(MOTIS_BASE, params=params, headers={"User-Agent": MOTIS_UA})
            resp.raise_for_status()
            itineraries = resp.json().get("itineraries") or []
        if not itineraries:
            return None
        return float(min(it["duration"] for it in itineraries if "duration" in it))
    except Exception as exc:
        logger.warning("MOTIS transit request failed: %s", exc)
        return None


def _mapy_seconds(payload: Dict[str, Any]) -> Optional[float]:
    """Mapy.cz returns duration in seconds at the top level."""
    if payload.get("duration") is not None:
        return float(payload["duration"])
    routes = payload.get("routes") or []
    if routes and routes[0].get("duration") is not None:
        return float(routes[0]["duration"])
    return None


def _walking_duration(
    origin: Dict[str, float],
    dest: Dict[str, float],
    mapy_key: Optional[str],
) -> Optional[float]:
    """Walking duration in seconds via Mapy.cz (same call as landomo-scraper)."""
    if not mapy_key:
        return None
    params = {
        "start": f"{origin['lon']},{origin['lat']}",
        "end": f"{dest['lon']},{dest['lat']}",
        "routeType": MAPY_ROUTE_TYPE,
        "apikey": mapy_key,
    }
    try:
        with _client() as client:
            resp = client.get(MAPY_ROUTE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        duration = _mapy_seconds(data)
        if duration is None:
            logger.warning("Mapy.cz response has no duration: %s", list(data)[:8])
        return duration
    except Exception as exc:
        logger.warning("Mapy.cz %s request failed: %s", MAPY_ROUTE_TYPE, exc)
        return None


def _osrm_duration(origin: Dict[str, float], dest: Dict[str, float]) -> Optional[float]:
    url = OSRM_FOOT_URL.format(
        lon1=origin["lon"], lat1=origin["lat"], lon2=dest["lon"], lat2=dest["lat"]
    )
    try:
        with _client() as client:
            resp = client.get(url, params={"overview": "false"})
            resp.raise_for_status()
            routes = resp.json().get("routes") or []
        if not routes:
            return None
        return float(routes[0]["duration"])
    except Exception as exc:
        logger.warning("OSRM foot request failed: %s", exc)
        return None


def _to_minutes(seconds: Optional[float]) -> Optional[float]:
    if seconds is None:
        return None
    return round(seconds / 60, 1)


def _is_praha_place(part: str) -> bool:
    blob = re.sub(r"\s+", " ", (part or "").strip())
    return bool(_GENERIC_PLACE.match(blob))


def _address_has_street(address: str) -> bool:
    raw = (address or "").strip()
    if not raw:
        return False
    if re.search(r"\d+/\d+", raw):
        return True
    if re.search(r"\b(ulice|náměstí|nám\.?|třída|nábřeží)\b", raw, re.IGNORECASE):
        return True
    parts = [p.strip() for p in re.split(r"[,;]", raw) if p.strip()] or [raw]
    streets = []
    for part in parts:
        if _is_praha_place(part):
            continue
        if re.search(r"pronájem|pronajem|\bbyt\b", part, re.IGNORECASE):
            continue
        if re.search(r"[A-Za-zÁ-Žá-ž]{3,}", part):
            streets.append(part)
    return bool(streets)


def _is_prague_centroid(lat: float, lon: float) -> bool:
    for clat, clon in _PRAGUE_CENTROIDS:
        if (lat - clat) ** 2 + (lon - clon) ** 2 < 0.00003:
            return True
    return False


def _geocode_queries(address: str) -> List[str]:
    raw = (address or "").strip()
    if not raw:
        return []
    queries: List[str] = []
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        street = parts[-1]
        queries.append(f"{street}, Praha")
        district = parts[0]
        for prefix in ("Praha ", "Praha-", "Praha"):
            if district.lower().startswith(prefix.lower()) and len(district) > len(prefix):
                district = district[len(prefix):].strip(" -")
                break
        if district and district.lower() not in {"praha", "prague"}:
            queries.append(f"{street}, {district}, Praha")
    queries.append(raw)
    if "praha" not in raw.lower() and "prague" not in raw.lower():
        queries.append(f"{raw}, Praha, Česko")
    seen = set()
    out: List[str] = []
    for query in queries:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(query)
    return out


def _geocode_address(address: str, mapy_key: Optional[str]) -> Optional[Tuple[float, float]]:
    if not _address_has_street(address):
        logger.info("Skip coarse geocode for %r", address)
        return None
    for query in _geocode_queries(address):
        cached = _GEOCODE_CACHE.get(query.lower())
        if query.lower() in _GEOCODE_CACHE:
            if cached:
                return cached
            continue
        coords = None
        if mapy_key:
            coords = _geocode_mapy(query, mapy_key)
        if coords is None:
            coords = _geocode_nominatim(query)
        if coords and _is_prague_centroid(coords[0], coords[1]):
            logger.info("Reject Praha centroid for %r", query)
            coords = None
        _GEOCODE_CACHE[query.lower()] = coords
        if coords:
            return coords
    return None


def _geocode_mapy(query: str, mapy_key: str) -> Optional[Tuple[float, float]]:
    params = {
        "query": query,
        "lang": "cs",
        "limit": 1,
        "locality": "cz",
        "apikey": mapy_key,
    }
    try:
        with _client() as client:
            resp = client.get(MAPY_GEOCODE_URL, params=params)
            resp.raise_for_status()
            items = resp.json().get("items") or []
        if not items:
            return None
        pos = items[0].get("position") or {}
        lon, lat = pos.get("lon"), pos.get("lat")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except Exception as exc:
        logger.warning("Mapy.cz geocode failed: %s", exc)
        return None


def _geocode_nominatim(query: str) -> Optional[Tuple[float, float]]:
    global _nominatim_last_at
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "cz",
    }
    last_error = None
    for attempt in range(1, 4):
        wait = _NOMINATIM_MIN_INTERVAL - (time.monotonic() - _nominatim_last_at)
        if wait > 0:
            time.sleep(wait)
        try:
            with _client() as client:
                resp = client.get(
                    NOMINATIM_URL,
                    params=params,
                    headers={"User-Agent": MOTIS_UA},
                )
                _nominatim_last_at = time.monotonic()
                if resp.status_code == 429:
                    retry = float(resp.headers.get("Retry-After") or (2 * attempt))
                    logger.warning("Nominatim 429 (try %d/3), sleep %.1fs", attempt, retry)
                    time.sleep(min(max(retry, 2.0), 30.0))
                    last_error = "429"
                    continue
                resp.raise_for_status()
                items = resp.json() or []
            if not items:
                return None
            return float(items[0]["lat"]), float(items[0]["lon"])
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Nominatim geocode failed (try %d/3): %s", attempt, exc)
            time.sleep(1.5 * attempt)
    logger.warning("Nominatim gave up for %r: %s", query, last_error)
    return None


def _as_coord(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_commute_to_flat(
    flat: Dict[str, Any],
    point_a: Optional[Dict[str, float]] = None,
    point_b: Optional[Dict[str, float]] = None,
    mapy_key: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Return ``(minutes_from_a, minutes_from_b)``.

    Transit first, Mapy.cz walking if MOTIS fails.
    """
    key = MAPY_API_KEY if mapy_key is None else mapy_key
    point_a = point_a or POINT_A
    point_b = point_b or POINT_B
    flat_lat = _as_coord(flat.get("latitude") if flat.get("latitude") is not None else flat.get("lat"))
    flat_lon = _as_coord(
        flat.get("longitude") if flat.get("longitude") is not None else (flat.get("lon") or flat.get("lng"))
    )
    if flat_lat is None or flat_lon is None:
        address = str(flat.get("address") or "")
        if not _address_has_street(address):
            address = str(flat.get("title") or "")
        geocoded = _geocode_address(address, key)
        if geocoded:
            flat_lat, flat_lon = geocoded
            flat["latitude"], flat["longitude"] = geocoded
            logger.info("Geocoded '%s' → %s,%s", address, flat_lat, flat_lon)
        else:
            logger.warning("Flat '%s' has no coordinates — skip commute.", flat.get("title"))
            return None, None

    dest = {"lat": float(flat_lat), "lon": float(flat_lon)}

    def best(origin: Dict[str, float]) -> Optional[float]:
        transit = _transit_duration(origin, dest)
        if transit is not None:
            return transit
        walking = _walking_duration(origin, dest, key)
        if walking is not None:
            return walking
        return _osrm_duration(origin, dest)

    mins_a = _to_minutes(best(point_a))
    mins_b = _to_minutes(best(point_b))
    logger.info(
        "Commute to '%s': A→flat %s min, B→flat %s min",
        flat.get("title", "?"),
        mins_a,
        mins_b,
    )
    return mins_a, mins_b

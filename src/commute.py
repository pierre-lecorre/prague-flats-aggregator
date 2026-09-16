"""Commute A→flat and B→flat — same stack as landomo-scraper.

1. MOTIS public transit (metro/tram/bus + walk) — Mapy has no PID profile.
2. Fallback: Mapy.cz ``foot_fast`` walking
   https://developer.mapy.com/rest-api-mapy-cz/function/routing/

https://github.com/pierre-lecorre/landomo-scraper
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from config import HTTP_SSL_VERIFY, MAPY_API_KEY, MAPY_ROUTE_TYPE, POINT_A, POINT_B

logger = logging.getLogger(__name__)

MOTIS_BASE = "https://europe.motis-project.de/api/v1/plan"
MOTIS_UA = "PragueFlatsAggregator/1.0 (flat-search-tool)"
MAPY_ROUTE_URL = "https://api.mapy.cz/v1/routing/route"


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


def _to_minutes(seconds: Optional[float]) -> Optional[float]:
    if seconds is None:
        return None
    return round(seconds / 60, 1)


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
    flat_lat = flat.get("latitude") or flat.get("lat")
    flat_lon = flat.get("longitude") or flat.get("lon") or flat.get("lng")
    if flat_lat is None or flat_lon is None:
        logger.warning("Flat '%s' has no coordinates — skip commute.", flat.get("title"))
        return None, None

    dest = {"lat": float(flat_lat), "lon": float(flat_lon)}

    def best(origin: Dict[str, float]) -> Optional[float]:
        transit = _transit_duration(origin, dest)
        if transit is not None:
            return transit
        return _walking_duration(origin, dest, key)

    mins_a = _to_minutes(best(point_a))
    mins_b = _to_minutes(best(point_b))
    logger.info(
        "Commute to '%s': A→flat %s min, B→flat %s min",
        flat.get("title", "?"),
        mins_a,
        mins_b,
    )
    return mins_a, mins_b

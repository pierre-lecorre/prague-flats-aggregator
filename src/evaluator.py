"""Per-flat LLM evaluation via Ollama.

One model call classifies the listing (flatshare / auction / city auction),
scores fit, and extracts monthly fees (or applies the default).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from config import DEFAULT_MONTHLY_FEES_CZK, HTTP_SSL_VERIFY

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a Prague rental-flat screening assistant.
Read the listing (Czech or English) and the renter's criteria.
Judge from meaning, not from a keyword list.

Classify:
- is_flatshare: true if this is a room, shared flat, roommate search, or
  spolubydlení / pokoj — not a whole apartment for one household.
- is_auction: true if the listing is an auction / dražba / aukce.
- is_city_auction: true only if the seller is a city, municipal district,
  magistrát, or similar public body. Private/developer auctions are false.
- is_reserved: true if the listing says the flat is reserved / under
  reservation (rezervováno, předběžně rezervováno, currently reserved).
- is_unavailable: true if already rented, taken, withdrawn, or no longer
  offered (pronajato, již pronajatý, nedostupné, already rented).
  A future move-in date alone is NOT unavailable.

Monthly money (CZK):
- rent = listing.price (nájem). Do not treat deposit, commission, or
  first/last month as fees.
- fees = monthly poplatky / zálohy / services / utilities / SVJ charges.
  If the text or listed_fees states a monthly fee, extract that integer.
  If rent already includes fees ("včetně poplatků", "vč. poplatků",
  "including charges"), fee is 0 and fee_source is "included".
  If fees are not mentioned at all, use default_monthly_fees_czk and
  fee_source "default".
- total_czk = rent + fees.

Score 0–100 how well the listing matches the criteria
(100 = perfect, 0 = fails almost everything).
Use the free-text notes in criteria as hard preferences.
Force score to 0 when is_flatshare, is_city_auction, is_reserved,
or is_unavailable is true.

Reply with JSON only, no markdown, this schema:
{{
  "score": <integer 0-100>,
  "reason": "<one or two sentences>",
  "is_flatshare": <true|false>,
  "is_auction": <true|false>,
  "is_city_auction": <true|false>,
  "is_reserved": <true|false>,
  "is_unavailable": <true|false>,
  "fee_czk": <integer>,
  "fee_source": "extracted" | "included" | "default",
  "total_czk": <integer>
}}

--- LISTING ---
{flat_json}

--- CRITERIA ---
{criteria_json}
"""


@dataclass(frozen=True)
class Evaluation:
    score: int
    reason: str
    is_flatshare: bool = False
    is_auction: bool = False
    is_city_auction: bool = False
    is_reserved: bool = False
    is_unavailable: bool = False
    price: Optional[int] = None
    fee: int = 0
    total: int = 0
    fee_source: str = "default"


def _listing_payload(flat: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "id", "source", "title", "price", "size_m2", "address", "url",
        "description", "bedrooms", "district", "listed_at", "listed_fees",
    )
    payload = {k: flat.get(k) for k in keys}
    desc = payload.get("description") or ""
    if len(desc) > 4000:
        payload["description"] = desc[:4000] + "…"
    return payload


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(float(str(value).replace(" ", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _extract_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in model output: {raw[:200]!r}")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Model JSON is not an object")
    return data


def _resolve_fees(
    data: Dict[str, Any],
    flat: Dict[str, Any],
    default_fee: int,
) -> tuple[int, str, int]:
    price = _as_int(flat.get("price")) or 0
    source = str(data.get("fee_source") or "").strip().lower()
    fee = _as_int(data.get("fee_czk"))
    listed = _as_int(flat.get("listed_fees"))

    if source == "included":
        return 0, "included", price
    if listed is not None:
        return listed, "extracted", price + listed
    if source == "extracted" and fee is not None and 0 <= fee <= 20000:
        return fee, "extracted", price + fee
    if fee is not None and 0 <= fee <= 20000 and source != "default":
        return fee, "extracted", price + fee
    return default_fee, "default", price + default_fee


def _parse_evaluation(
    raw: str,
    flat: Dict[str, Any],
    default_fee: int,
) -> Evaluation:
    data = _extract_json(raw)
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    reason = str(data.get("reason") or "").strip() or raw.strip()
    is_flatshare = _as_bool(data.get("is_flatshare", False))
    is_auction = _as_bool(data.get("is_auction", False))
    is_city_auction = _as_bool(data.get("is_city_auction", False))
    is_reserved = _as_bool(data.get("is_reserved", False))
    is_unavailable = _as_bool(data.get("is_unavailable", False))
    if is_city_auction:
        is_auction = True
    if is_flatshare or is_city_auction or is_reserved or is_unavailable:
        score = 0
    fee, fee_source, total = _resolve_fees(data, flat, default_fee)
    return Evaluation(
        score=score,
        reason=reason,
        is_flatshare=is_flatshare,
        is_auction=is_auction,
        is_city_auction=is_city_auction,
        is_reserved=is_reserved,
        is_unavailable=is_unavailable,
        price=_as_int(flat.get("price")),
        fee=fee,
        total=total,
        fee_source=fee_source,
    )


def _run_llama(model_path: str, prompt: str) -> str:
    """Invoke local Ollama API and return its output."""
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_path,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 400,
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=120, verify=HTTP_SSL_VERIFY)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.error("Ollama API failed: %s", exc)
        raise


def _fallback_evaluation(flat: Dict[str, Any], reason: str) -> Evaluation:
    price = _as_int(flat.get("price")) or 0
    listed = _as_int(flat.get("listed_fees"))
    if listed is not None:
        fee, source = listed, "extracted"
    else:
        fee, source = DEFAULT_MONTHLY_FEES_CZK, "default"
    return Evaluation(
        score=0,
        reason=reason,
        price=_as_int(flat.get("price")),
        fee=fee,
        total=price + fee,
        fee_source=source,
    )


def evaluate_flat(
    flat: Dict[str, Any],
    criteria: Dict[str, Any],
    model_path: Optional[str] = None,
) -> Evaluation:
    """Score, classify, and price a listing with the LLM."""
    default_fee = int(criteria.get("default_monthly_fees_czk") or DEFAULT_MONTHLY_FEES_CZK)
    if not model_path:
        logger.error("No Ollama model configured — cannot evaluate.")
        return _fallback_evaluation(flat, "LLM unavailable: no model configured")

    prompt = _PROMPT_TEMPLATE.format(
        flat_json=json.dumps(_listing_payload(flat), ensure_ascii=False, indent=2),
        criteria_json=json.dumps(criteria, ensure_ascii=False, indent=2),
    )
    try:
        raw = _run_llama(model_path, prompt)
        evaluation = _parse_evaluation(raw, flat, default_fee)
        logger.debug(
            "LLM scored '%s' → %d fee=%d (%s) total=%d",
            flat.get("title", "?"),
            evaluation.score,
            evaluation.fee,
            evaluation.fee_source,
            evaluation.total,
        )
        return evaluation
    except Exception:
        logger.exception("LLM evaluation failed for %s", flat.get("url", "?"))
        return _fallback_evaluation(flat, "LLM evaluation failed")

"""Per-flat LLM evaluation via Ollama.

One model call classifies the listing (flatshare / auction / city auction)
and scores fit against the user's criteria. No keyword or rule fallback.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

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

Score 0–100 how well the listing matches the criteria
(100 = perfect, 0 = fails almost everything).
Use the free-text notes in criteria as hard preferences.
Force score to 0 when is_flatshare or is_city_auction is true.

Reply with JSON only, no markdown, this schema:
{{
  "score": <integer 0-100>,
  "reason": "<one or two sentences>",
  "is_flatshare": <true|false>,
  "is_auction": <true|false>,
  "is_city_auction": <true|false>
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


def _listing_payload(flat: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "id", "source", "title", "price", "size_m2", "address", "url",
        "description", "bedrooms", "district", "listed_at",
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


def _parse_evaluation(raw: str) -> Evaluation:
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
    if is_city_auction:
        is_auction = True
    if is_flatshare or is_city_auction:
        score = 0
    return Evaluation(
        score=score,
        reason=reason,
        is_flatshare=is_flatshare,
        is_auction=is_auction,
        is_city_auction=is_city_auction,
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
            "num_predict": 256,
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.error("Ollama API failed: %s", exc)
        raise


def evaluate_flat(
    flat: Dict[str, Any],
    criteria: Dict[str, Any],
    model_path: Optional[str] = None,
) -> Evaluation:
    """Score and classify a listing with the LLM.

    Returns ``Evaluation``. On LLM failure, score 0 and all flags false
    so the pipeline keeps running.
    """
    if not model_path:
        logger.error("No Ollama model configured — cannot evaluate.")
        return Evaluation(score=0, reason="LLM unavailable: no model configured")

    prompt = _PROMPT_TEMPLATE.format(
        flat_json=json.dumps(_listing_payload(flat), ensure_ascii=False, indent=2),
        criteria_json=json.dumps(criteria, ensure_ascii=False, indent=2),
    )
    try:
        raw = _run_llama(model_path, prompt)
        evaluation = _parse_evaluation(raw)
        logger.debug(
            "LLM scored '%s' → %d (flatshare=%s auction=%s city=%s)",
            flat.get("title", "?"),
            evaluation.score,
            evaluation.is_flatshare,
            evaluation.is_auction,
            evaluation.is_city_auction,
        )
        return evaluation
    except Exception:
        logger.exception("LLM evaluation failed for %s", flat.get("url", "?"))
        return Evaluation(score=0, reason="LLM evaluation failed")

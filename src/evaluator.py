"""Per-flat LLM evaluation via llama-cli.

Each flat is sent individually to the model along with the user's criteria.
The model returns a **fit score from 0 to 100** (100 = perfect match) and a
short justification.
"""

import json
import logging
import re
import requests
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a real-estate assistant. You receive a single flat listing as JSON and \
the buyer/renter's criteria. Your job is to judge how well the flat matches.

Reply with EXACTLY this format (nothing else):
SCORE: <integer 0-100>
REASON: <one or two sentences>

A score of 100 means the flat is a perfect match for every criterion.
A score of 0 means it fails on all counts.

--- FLAT ---
{flat_json}

--- CRITERIA ---
{criteria_json}
"""


# Keywords that suggest flatshare / room rental
FLATSHARE_KEYWORDS = [
    "spoluná¿¿em", "spoluná¿¿emka", "spolubydlí¿¿í¿¿", "spolubydlí¿¿í¿¿í¿¿",
    "pokoj", "room", "flatshare", "shared flat", "roommate",
    "hledá¿¿m spolubydlí¿¿í¿¿í¿¿ho", "hledá¿¿me spolubydlí¿¿í¿¿í¿¿ho",
    "sdí¿¿lení¿¿", "sdí¿¿lená¿¿", "shared accommodation"
]

# Keywords that suggest auctions
AUCTION_KEYWORDS = [
    "aukce", "auction", "dražba", "dražební¿¿",
    "veřejná¿¿ dražba", "public auction", "exekuční¿¿ dražba"
]

# Keywords that suggest city/municipal auctions (to ignore)
CITY_AUCTION_KEYWORDS = [
    "město", "městská¿¿", "městská¿¿ část", "municipal", "city auction",
    "hlavní¿¿ město", "praha", "magistrá¿¿t"
]


def _parse_score(raw: str) -> Tuple[int, str]:
    """Extract the integer score and reason from the model output."""
    match = re.search(r"SCORE:\s*(\d+)", raw, re.IGNORECASE)
    score = int(match.group(1)) if match else 0
    score = max(0, min(100, score))

    match_reason = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE | re.DOTALL)
    reason = match_reason.group(1).strip() if match_reason else raw.strip()
    return score, reason


def _run_llama(model_path: str, prompt: str) -> str:
    """Invoke local Ollama API and return its output."""
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_path,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 256
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.error("Ollama API failed: %s", exc)
        raise


def check_flatshare(description: str, title: str = "") -> bool:
    """Check if listing appears to be a flatshare/room rental."""
    text = (title + " " + description).lower()
    for keyword in FLATSHARE_KEYWORDS:
        if keyword.lower() in text:
            return True
    return False


def check_auction(description: str, title: str = "") -> Tuple[bool, bool]:
    """Check if listing is an auction, and if it's a city/municipal auction."""
    text = (title + " " + description).lower()
    
    is_auction = any(kw.lower() in text for kw in AUCTION_KEYWORDS)
    if not is_auction:
        return False, False
    
    is_city_auction = any(kw.lower() in text for kw in CITY_AUCTION_KEYWORDS)
    return is_auction, is_city_auction


def evaluate_flat(
    flat: Dict[str, Any],
    criteria: Dict[str, Any],
    model_path: Optional[str] = None,
) -> Tuple[int, str]:
    """Score a single flat against the criteria.

    Returns ``(score, reason)``.
    If the LLM is unavailable the function falls back to a simple rule-based
    heuristic so the pipeline never crashes.
    """
    # --- try LLM first ---
    if model_path:
        prompt = _PROMPT_TEMPLATE.format(
            flat_json=json.dumps(flat, ensure_ascii=False, indent=2),
            criteria_json=json.dumps(criteria, ensure_ascii=False, indent=2),
        )
        try:
            raw = _run_llama(model_path, prompt)
            score, reason = _parse_score(raw)
            logger.debug("LLM scored '%s' → %d", flat.get("title", "?"), score)
            return score, reason
        except Exception:
            logger.warning("LLM evaluation failed – falling back to rules.")

    # --- deterministic fallback ---
    return _rule_based_score(flat, criteria)


def _rule_based_score(flat: Dict[str, Any], criteria: Dict[str, Any]) -> Tuple[int, str]:
    """Simple heuristic scoring when no LLM is available."""
    score = 100
    reasons = []

    max_price = criteria.get("max_price_czk")
    if max_price and flat.get("price", 0) > max_price:
        score -= 40
        reasons.append(f"price {flat.get('price')} > {max_price}")

    min_bed = criteria.get("min_bedrooms")
    if min_bed and flat.get("bedrooms", 0) < min_bed:
        score -= 25
        reasons.append(f"bedrooms {flat.get('bedrooms', 0)} < {min_bed}")

    min_sqm = criteria.get("min_sqm")
    if min_sqm and flat.get("sqm", 0) < min_sqm:
        score -= 25
        reasons.append(f"sqm {flat.get('sqm', 0)} < {min_sqm}")

    districts = criteria.get("preferred_districts", [])
    if districts and flat.get("district") not in districts:
        score -= 10
        reasons.append(f"district '{flat.get('district')}' not preferred")

    score = max(0, score)
    reason = "; ".join(reasons) if reasons else "meets all rule-based criteria"
    return score, reason

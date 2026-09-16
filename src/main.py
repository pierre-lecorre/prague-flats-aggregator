import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import (
    DEFAULT_MONTHLY_FEES_CZK,
    DRY_RUN,
    ENABLE_LANDOMO,
    MAX_LISTING_AGE_HOURS,
    MIN_SCORE,
    OLLAMA_MODEL,
    USER_CRITERIA,
)
from db import init_db, listing_exists, insert_listing, get_new_listings, save_evaluation
from evaluator import Evaluation, evaluate_flat
from notifier import send_telegram_message, send_telegram_alert
from commute import compute_commute_to_flat
from scraper_base import ScrapeError

from scraper_ceskereality import CeskeRealityScraper
from scraper_ulovdomov import UlovDomovScraper
from scraper_realingo import RealingoScraper
from scraper_sreality import SrealityScraper
from scraper_bezrealitky import BezrealitkyScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SCRAPERS = {
    "ceskereality": CeskeRealityScraper,
    "ulovdomov": UlovDomovScraper,
    "realingo": RealingoScraper,
    "sreality": SrealityScraper,
    "bezrealitky": BezrealitkyScraper,
}
if ENABLE_LANDOMO:
    from scraper_landomo import LandomoScraper

    SCRAPERS["landomo"] = LandomoScraper


def _parse_listed_at(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _money(
    listing: Dict[str, Any],
    evaluation: Optional[Evaluation] = None,
) -> Dict[str, Any]:
    if evaluation is not None:
        return {
            "price": evaluation.price,
            "fee": evaluation.fee,
            "total": evaluation.total,
            "fee_source": evaluation.fee_source,
        }
    price = listing.get("price")
    listed = listing.get("listed_fees")
    try:
        listed_int = int(listed) if listed is not None else None
    except (TypeError, ValueError):
        listed_int = None
    if listed_int is not None:
        fee, source = listed_int, "extracted"
    else:
        fee, source = DEFAULT_MONTHLY_FEES_CZK, "default"
    try:
        price_int = int(price) if price is not None else 0
    except (TypeError, ValueError):
        price_int = 0
    return {
        "price": price,
        "fee": fee,
        "total": price_int + fee,
        "fee_source": source,
    }


def is_stale(listing: Dict[str, Any]) -> bool:
    if not MAX_LISTING_AGE_HOURS:
        return False
    listed = _parse_listed_at(listing.get("listed_at"))
    if listed is None:
        return False
    return datetime.now(timezone.utc) - listed > timedelta(hours=MAX_LISTING_AGE_HOURS)


async def run_scrapers() -> List[Dict[str, Any]]:
    all_listings: List[Dict[str, Any]] = []
    failures: List[Tuple[str, Exception]] = []

    for source_name, scraper_class in SCRAPERS.items():
        logger.info("Scraping %s...", source_name)
        scraper = scraper_class()
        try:
            listings = await scraper.scrape()
            logger.info("  Found %d listings from %s", len(listings), source_name)
            for listing in listings:
                if not listing_exists(listing["id"]):
                    insert_listing(listing)
                    all_listings.append(listing)
                else:
                    logger.debug("  Duplicate: %s", listing["url"])
        except Exception as e:
            logger.error("Error scraping %s: %s", source_name, e)
            failures.append((source_name, e))

    if failures:
        await alert_scraper_failures(failures)

    return all_listings


async def alert_scraper_failures(failures: List[Tuple[str, Exception]]) -> None:
    lines = ["<b>⚠️ Scraper failure</b>", ""]
    for source_name, exc in failures:
        kind = "empty/broken" if isinstance(exc, ScrapeError) else type(exc).__name__
        detail = str(exc).replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"• <b>{source_name}</b> ({kind}): {detail}")
    lines.append("")
    lines.append("Pipeline kept going for other sources.")
    await send_telegram_alert("\n".join(lines))


async def process_new_listings():
    new_listings = get_new_listings()
    logger.info("Processing %d new listings...", len(new_listings))
    matches = 0

    for listing in new_listings:
        logger.info("Evaluating %s...", listing["url"])

        if is_stale(listing):
            logger.info("  SKIP: older than %sh", MAX_LISTING_AGE_HOURS)
            save_evaluation(
                listing_id=listing["id"],
                score=0,
                reasons=f"Older than {MAX_LISTING_AGE_HOURS}h",
                is_flatshare=False,
                is_auction=False,
                **_money(listing),
            )
            continue

        evaluation = evaluate_flat(
            flat=listing,
            criteria=USER_CRITERIA,
            model_path=OLLAMA_MODEL,
        )
        money = _money(listing, evaluation)

        if evaluation.is_city_auction:
            logger.info("  REJECT: City auction")
            save_evaluation(
                listing_id=listing["id"],
                score=0,
                reasons=evaluation.reason or "City/municipal auction - ignored",
                is_flatshare=evaluation.is_flatshare,
                is_auction=True,
                **money,
            )
            continue

        if evaluation.is_flatshare:
            logger.info("  REJECT: Flatshare")
            save_evaluation(
                listing_id=listing["id"],
                score=0,
                reasons=evaluation.reason or "Flatshare/room rental - ignored",
                is_flatshare=True,
                is_auction=evaluation.is_auction,
                **money,
            )
            continue

        if evaluation.is_auction or evaluation.score < MIN_SCORE:
            why = "auction" if evaluation.is_auction else f"score {evaluation.score} < {MIN_SCORE}"
            logger.info("  SKIP: %s", why)
            save_evaluation(
                listing_id=listing["id"],
                score=evaluation.score,
                reasons=evaluation.reason,
                is_flatshare=evaluation.is_flatshare,
                is_auction=evaluation.is_auction,
                **money,
            )
            continue

        commute_a, commute_b = compute_commute_to_flat(listing)
        save_evaluation(
            listing_id=listing["id"],
            score=evaluation.score,
            reasons=evaluation.reason,
            is_flatshare=evaluation.is_flatshare,
            is_auction=evaluation.is_auction,
            commute_a=commute_a,
            commute_b=commute_b,
            **money,
        )

        logger.info(
            "  Match (score %d) price=%s fee=%s (%s) total=%s — notify",
            evaluation.score,
            money["price"],
            money["fee"],
            money["fee_source"],
            money["total"],
        )
        await send_telegram_message(listing, {
            "score": evaluation.score,
            "reasons": evaluation.reason,
            "commute_a": commute_a,
            "commute_b": commute_b,
            **money,
        })
        matches += 1

    logger.info("Done — %d new matches.", matches)


async def main():
    if DRY_RUN:
        logger.info("DRY_RUN is on")
    logger.info("Initializing database...")
    init_db()

    logger.info("Running scrapers...")
    await run_scrapers()

    logger.info("Processing new listings...")
    await process_new_listings()


if __name__ == "__main__":
    asyncio.run(main())

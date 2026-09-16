import asyncio
import sys
from typing import List, Dict, Any

from config import (
    SOURCES, DRY_RUN,
    MIN_SIZE_M2, MAX_PRICE_CZK,
    COMMUTE_MAX_MINUTES, COMMUTE_TARGET_ADDRESS,
    OLLAMA_MODEL
)
from db import init_db, listing_exists, insert_listing, get_new_listings, save_evaluation, mark_listing_inactive
from evaluator import evaluate_flat, check_flatshare, check_auction
from notifier import send_telegram_message
from commute import calculate_commute_time_with_address

from scraper_ceskereality import CeskeRealityScraper
from scraper_ulovdomov import UlovDomovScraper
from scraper_realingo import RealingoScraper
from scraper_sreality import SrealityScraper
from scraper_bezrealitky import BezrealitkyScraper

SCRAPERS = {
    "ceskereality": CeskeRealityScraper,
    "ulovdomov": UlovDomovScraper,
    "realingo": RealingoScraper,
    "sreality": SrealityScraper,
    "bezrealitky": BezrealitkyScraper,
}

# User criteria for LLM evaluation
USER_CRITERIA = {
    "max_price_czk": MAX_PRICE_CZK,
    "min_sqm": MIN_SIZE_M2,
    "max_commute_minutes": COMMUTE_MAX_MINUTES,
    "commute_target": COMMUTE_TARGET_ADDRESS,
    "min_bedrooms": 1,
    "preferred_districts": [],  # Add preferred Prague districts here if needed
}

async def run_scrapers() -> List[Dict[str, Any]]:
    all_listings = []
    
    for source_name, scraper_class in SCRAPERS.items():
        print(f"Scraping {source_name}...")
        scraper = scraper_class()
        try:
            listings = await scraper.scrape()
            print(f"  Found {len(listings)} listings from {source_name}")
            
            for listing in listings:
                if not listing_exists(listing["id"]):
                    insert_listing(listing)
                    all_listings.append(listing)
                else:
                    print(f"  Duplicate: {listing['url']}")
                    
        except Exception as e:
            print(f"Error scraping {source_name}: {e}")
    
    return all_listings

async def process_new_listings():
    new_listings = get_new_listings()
    print(f"Processing {len(new_listings)} new listings...")
    
    for listing in new_listings:
        print(f"Evaluating {listing['url']}...")
        
        # Check for flatshare and auctions BEFORE LLM evaluation
        description = listing.get("description", "")
        title = listing.get("title", "")
        
        is_flatshare = check_flatshare(description, title)
        is_auction, is_city_auction = check_auction(description, title)
        
        # Skip city auctions immediately
        if is_auction and is_city_auction:
            print(f"  REJECT: City auction - skipping")
            save_evaluation(
                listing_id=listing["id"],
                score=0,
                reasons="City/municipal auction - ignored",
                is_flatshare=is_flatshare,
                is_auction=True,
                commute_minutes=None
            )
            continue
        
        # Skip flatshares
        if is_flatshare:
            print(f"  REJECT: Flatshare - skipping")
            save_evaluation(
                listing_id=listing["id"],
                score=0,
                reasons="Flatshare/room rental - ignored",
                is_flatshare=True,
                is_auction=False,
                commute_minutes=None
            )
            continue
        
        # Calculate commute time
        commute_minutes = None
        if listing.get("latitude") and listing.get("longitude"):
            commute_minutes = calculate_commute_time_with_address(
                listing["latitude"], 
                listing["longitude"], 
                COMMUTE_TARGET_ADDRESS
            )
        
        # Evaluate with LLM (or fallback)
        score, reason = evaluate_flat(
            flat=listing,
            criteria=USER_CRITERIA,
            model_path=OLLAMA_MODEL
        )
        
        save_evaluation(
            listing_id=listing["id"],
            score=score,
            reasons=reason,
            is_flatshare=is_flatshare,
            is_auction=is_auction,
            commute_minutes=commute_minutes
        )
        
        # Skip non-city auctions (but not city auctions - those were already skipped)
        if is_auction:
            print(f"  Skipping auction (non-city): {listing['url']}")
            continue
        
        # Send notification for good matches
        if score >= 60:
            print(f"  Good match (score: {score}) - sending notification")
            await send_telegram_message(listing, {
                "score": score,
                "reasons": reason,
                "commute_minutes": commute_minutes
            })
        else:
            print(f"  Low score ({score}) - skipping")

async def main():
    print("Initializing database...")
    init_db()
    
    print("Running scrapers...")
    new_listings = await run_scrapers()
    
    print("Processing new listings...")
    await process_new_listings()
    
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())

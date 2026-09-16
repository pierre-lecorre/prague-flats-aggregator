import asyncio
import sys
from typing import List, Dict, Any

from config import SOURCES, DRY_RUN
from db import init_db, listing_exists, insert_listing, get_new_listings, save_evaluation, mark_listing_inactive
from evaluator import evaluate_listing
from notifier import send_telegram_message

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
        
        score, reasons, is_flatshare, is_auction, commute_minutes = evaluate_listing(listing)
        
        save_evaluation(
            listing_id=listing["id"],
            score=score,
            reasons=reasons,
            is_flatshare=is_flatshare,
            is_auction=is_auction,
            commute_minutes=commute_minutes
        )
        
        if is_auction:
            print(f"  Skipping auction: {listing['url']}")
            continue
        
        if is_flatshare:
            print(f"  Skipping flatshare: {listing['url']}")
            continue
        
        if score >= 60:
            print(f"  Good match (score: {score}) - sending notification")
            await send_telegram_message(listing, {
                "score": score,
                "reasons": reasons,
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

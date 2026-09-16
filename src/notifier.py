import httpx
from typing import Dict, Any
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DRY_RUN

async def send_telegram_message(listing: Dict[str, Any], evaluation: Dict[str, Any]):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured - skipping notification")
        return
    
    if DRY_RUN:
        print(f"[DRY_RUN] Would send Telegram message for {listing['url']}")
        return
    
    message = format_message(listing, evaluation)
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            print(f"Telegram notification sent for {listing['url']}")
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")

def format_message(listing: Dict[str, Any], evaluation: Dict[str, Any]) -> str:
    title = listing.get("title", "No title")
    price = listing.get("price", "N/A")
    size = listing.get("size_m2", "N/A")
    address = listing.get("address", "N/A")
    url = listing.get("url", "")
    source = listing.get("source", "unknown")
    
    score = evaluation.get("score", "N/A")
    commute = evaluation.get("commute_minutes", "N/A")
    reasons = evaluation.get("reasons", "")
    
    message = f"""<b>🏠 New Flat Match</b>

<b>Title:</b> {title}
<b>Price:</b> {price} CZK
<b>Size:</b> {size} m2
<b>Address:</b> {address}
<b>Source:</b> {source}

<b>Score:</b> {score}/100
<b>Commute to Palmovka:</b> {commute} min

<b>Why it fits:</b>
{reasons}

<a href="{url}">View Listing</a>"""
    
    return message
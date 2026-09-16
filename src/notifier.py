import html
from typing import Any, Dict, Optional

import httpx

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DRY_RUN, POINT_A_NAME, POINT_B_NAME


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
        "disable_web_page_preview": False,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            print(f"Telegram notification sent for {listing['url']}")
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")


async def send_telegram_alert(text: str, parse_mode: Optional[str] = "HTML"):
    """Ops alert (scraper down, empty results, etc.)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured - skipping alert")
        print(text)
        return

    if DRY_RUN:
        print(f"[DRY_RUN] Alert:\n{text}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=30)
            response.raise_for_status()
            print("Telegram alert sent")
        except Exception as e:
            print(f"Failed to send Telegram alert: {e}")
            print(text)


def _fmt_commute(minutes) -> str:
    if minutes is None or minutes == "N/A":
        return "n/a"
    return f"{minutes} min"


def format_message(listing: Dict[str, Any], evaluation: Dict[str, Any]) -> str:
    title = html.escape(str(listing.get("title", "No title")))
    address = html.escape(str(listing.get("address", "N/A")))
    source = html.escape(str(listing.get("source", "unknown")))
    url = listing.get("url", "")
    reason = html.escape(str(evaluation.get("reasons", "")))
    score = evaluation.get("score", "N/A")
    commute_a = evaluation.get("commute_a", evaluation.get("commute_minutes"))
    commute_b = evaluation.get("commute_b")

    return f"""<b>🏠 Match (score {score}/100)</b>

<b>Title:</b> {title}
<b>Price:</b> {listing.get("price", "N/A")} CZK
<b>Size:</b> {listing.get("size_m2", "N/A")} m²
<b>Address:</b> {address}
<b>Source:</b> {source}

<b>Commute {html.escape(POINT_A_NAME)}→flat:</b> {_fmt_commute(commute_a)}
<b>Commute {html.escape(POINT_B_NAME)}→flat:</b> {_fmt_commute(commute_b)}

<b>Why:</b>
{reason}

<a href="{html.escape(url, quote=True)}">View Listing</a>"""

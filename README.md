# Prague Flats Aggregator

Multi-site Prague rental scraper. Scores each flat with a local LLM, measures public-transit commute to two anchors, Telegram-alerts matches.

Inspired by [landomo-scraper](https://github.com/pierre-lecorre/landomo-scraper).

## How it works

1. **Scrape** — České reality, UlovDomov, Realingo, Sreality, Bezrealitky, plus Landomo (Playwright intercept of `/api/explore/search`). Empty/broken sources Telegram-alert.
2. **Evaluate** — each new listing goes to Ollama as JSON + your criteria (including free-text notes). Model returns score 0–100 plus flatshare/auction flags.
3. **Age cut** — listings with a timestamp older than `MAX_LISTING_AGE_HOURS` (default 24h) are stored and skipped.
4. **Commute** — only for score ≥ `MIN_SCORE`. MOTIS public transit (metro/tram/bus + walk) from **A→flat** and **B→flat**. Optional Mapy.cz walking fallback.
5. **Notify** — Telegram message with title, price, size, both commute times, reason, link.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
ollama pull llama3
cp .env.example .env
```

Edit `.env`:

- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
- `COMMUTE_POINT_A` / `COMMUTE_POINT_B` as `lat,lon`
- `CRITERIA_NOTES` — free-text preferences for the LLM
- `MIN_SCORE` (default 60)
- `LANDOMO_SEARCH_URL` — same bounding-box search Landomo uses in the original tool
- `HTTP_SSL_VERIFY=false` only behind a corporate SSL intercept

```bash
cd src
python main.py
```

Cron every 5–10 minutes:

```bash
*/5 * * * * cd /path/to/prague-flats-aggregator/src && python main.py >> /path/to/logs/flats.log 2>&1
```

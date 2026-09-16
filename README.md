# Prague Flats Aggregator

Multi-site Prague rental flats scraper with AI evaluation and Telegram alerts.

## Features

- Scrapes 5 major Czech real-estate sites:
  - České reality
  - UlovDomov
  - Realingo
  - Sreality
  - Bezrealitky
- Filters by:
  - Minimum size (25 m2)
  - Maximum price (20,000 CZK)
  - Maximum commute time to Palmovka (40 min)
- AI-powered evaluation:
  - Detects and ignores flatshares / room rentals
  - Detects and ignores auctions (especially city/municipal auctions)
- Sends Telegram notifications for good matches

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/pierre-lecorre/prague-flats-aggregator.git
   cd prague-flats-aggregator
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and set:
   - `TELEGRAM_BOT_TOKEN` - Your Telegram bot token from BotFather
   - `TELEGRAM_CHAT_ID` - Your chat ID
   - Adjust other settings as needed

4. Run:
   ```bash
   cd src
   python main.py
   ```

## Scheduling

Run every 5-10 minutes via cron:

```bash
*/5 * * * * cd /path/to/prague-flats-aggregator/src && python main.py >> /path/to/logs/flats.log 2>&1
```

## Architecture

- `scraper_*.py` - Individual site scrapers
- `evaluator.py` - Scoring and filtering logic
- `notifier.py` - Telegram notifications
- `db.py` - SQLite database for deduplication
- `config.py` - Configuration and environment variables
- `main.py` - Orchestration

## Notes

- Commute times are calculated using OSRM routing (driving approximation)
- For more accurate public transport times, integrate with PID Litaš or Chaps.cz API

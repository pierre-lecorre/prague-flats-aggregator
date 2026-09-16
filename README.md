# Prague Flats Aggregator

Multi-site Prague rental flats scraper with **LLM-powered evaluation** and Telegram alerts.

## Features

- Scrapes 5 major Czech real-estate sites:
  - České reality
  - UlovDomov
  - Realingo
  - Sreality
  - Bezrealitky
- **LLM evaluation via Ollama** - Each listing is scored 0-100 by a local LLM
- Filters by:
  - Minimum size (25 m2)
  - Maximum price (20,000 CZK)
  - Maximum commute time to Palmovka (40 min)
- **AI-powered content filtering**:
  - Detects and ignores flatshares / room rentals
  - Detects and ignores auctions (especially city/municipal auctions)
- Sends Telegram notifications for good matches (score ≥ 60)

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/pierre-lecorre/prague-flats-aggregator.git
cd prague-flats-aggregator
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up Ollama (LLM)

Install Ollama from https://ollama.ai and pull a model:

```bash
ollama pull llama3
```

Or use any other model you prefer (e.g., `mistral`, `codellama`, etc.).

### 4. Configure environment
```bash
cp .env.example .env
```

Edit `.env` and set:
- `TELEGRAM_BOT_TOKEN` - Your Telegram bot token from BotFather
- `TELEGRAM_CHAT_ID` - Your chat ID
- `OLLAMA_MODEL` - Your Ollama model name (default: `llama3`)
- Adjust other settings as needed

### 5. Run
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
- `evaluator.py` - **LLM-based scoring** (Ollama) with rule-based fallback
- `notifier.py` - Telegram notifications
- `db.py` - SQLite database for deduplication
- `config.py` - Configuration and environment variables
- `commute.py` - Commute time calculation via OSRM
- `main.py` - Orchestration

## How LLM Evaluation Works

1. Each new listing is sent to Ollama as JSON
2. The LLM receives the flat data + your criteria
3. It returns a score (0-100) and a short reason
4. Listings with score ≥ 60 trigger Telegram notifications
5. If Ollama is unavailable, falls back to rule-based scoring

### Example LLM prompt:
```
--- FLAT ---
{
  "title": "2 bedroom flat in Vinohrady",
  "price": 18000,
  "sqm": 45,
  "description": "..."
}

--- CRITERIA ---
{
  "max_price_czk": 20000,
  "min_sqm": 25,
  "max_commute_minutes": 40
}
```

### Example LLM response:
```
SCORE: 85
REASON: Good size and price, but commute time slightly exceeds limit.
```

## Notes

- Commute times are calculated using OSRM driving routes as approximation
- For accurate Prague public transport times, integrate PID Litaš or Chaps.cz API
- The LLM runs locally via Ollama - no API keys needed
- Adjust score threshold (60) in `main.py` if needed

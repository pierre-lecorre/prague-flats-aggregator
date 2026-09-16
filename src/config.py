import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Commute
COMMUTE_TARGET_ADDRESS = os.getenv("COMMUTE_TARGET_ADDRESS", "Palmovka, Prague")
COMMUTE_MAX_MINUTES = int(os.getenv("COMMUTE_MAX_MINUTES", "40"))

# Flat criteria
MIN_SIZE_M2 = int(os.getenv("MIN_SIZE_M2", "25"))
MAX_PRICE_CZK = int(os.getenv("MAX_PRICE_CZK", "20000"))

# Ollama LLM
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")  # or your preferred model

# Run mode
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# Source URLs
SOURCES = {
    "ceskereality": "https://www.ceskereality.cz/mapa/pronajem/byty/do-20000/",
    "ulovdomov": "https://www.ulovdomov.cz/pronajem/bytu/praha?cena-do=20000kc&lokace=Praha",
    "realingo": "https://www.realingo.cz/pronajem_byty/Praha/25-_plocha/-20000_cena/",
    "sreality": "https://www.sreality.cz/hledani/byty/praha?cena-do=20000",
    "bezrealitky": "https://www.bezrealitky.cz/vyhledat?boundaryPoints=%5B%7B%22lat%22%3A50.13007318104701%2C%22lng%22%3A14.53205776150702%7D%2C%7B%22lat%22%3A50.13007318104701%2C%22lng%22%3A14.326692925962533%7D%2C%7B%22lat%22%3A50.04683586656233%2C%22lng%22%3A14.326692925962533%7D%2C%7B%22lat%22%3A50.04683586656233%2C%22lng%22%3A14.53205776150702%7D%2C%7B%22lat%22%3A50.13007318104701%2C%22lng%22%3A14.53205776150702%7D%5D&estateType=BYT&location=exact&offerType=PRONAJEM&osm_value=Praha%2C+%C4%8Cesko&priceTo=20000&regionOsmIds=R435514&currency=CZK",
}

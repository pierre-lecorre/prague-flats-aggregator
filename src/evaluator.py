import re
from typing import Dict, Any, Tuple, Optional, List
from config import MIN_SIZE_M2, COMMUTE_MAX_MINUTES

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

def check_flatshare(description: str, title: str = "") -> bool:
    text = (title + " " + description).lower()
    for keyword in FLATSHARE_KEYWORDS:
        if keyword.lower() in text:
            return True
    return False

def check_auction(description: str, title: str = "") -> Tuple[bool, bool]:
    text = (title + " " + description).lower()
    
    is_auction = any(kw.lower() in text for kw in AUCTION_KEYWORDS)
    if not is_auction:
        return False, False
    
    is_city_auction = any(kw.lower() in text for kw in CITY_AUCTION_KEYWORDS)
    return is_auction, is_city_auction

def calculate_commute_time(latitude: Optional[float], longitude: Optional[float], 
                          target_address: str = "Palmovka, Prague") -> Optional[float]:
    if latitude is None or longitude is None:
        return None
    
    try:
        import httpx
        url = "https://router.project-osrm.org/route/v1/driving"
        
        origin = f"{longitude},{latitude}"
        
        full_url = f"{url}/{origin};14.4639,50.1067?overview=false"
        
        with httpx.Client(timeout=10) as client:
            response = client.get(full_url)
            if response.status_code == 200:
                data = response.json()
                if data.get("routes") and len(data["routes"]) > 0:
                    duration_seconds = data["routes"][0]["duration"]
                    return duration_seconds / 60.0
    except Exception as e:
        print(f"Commute calculation failed: {e}")
    
    return None

def evaluate_listing(listing: Dict[str, Any]) -> Tuple[float, str, bool, bool, Optional[float]]:
    size_m2 = listing.get("size_m2")
    price = listing.get("price")
    description = listing.get("description", "")
    title = listing.get("title", "")
    latitude = listing.get("latitude")
    longitude = listing.get("longitude")
    
    score = 0
    reasons = []
    
    if size_m2 and size_m2 >= MIN_SIZE_M2:
        score += 25
        reasons.append(f"Size {size_m2} m2 meets minimum ({MIN_SIZE_M2} m2)")
    elif size_m2:
        score += max(0, 25 - (MIN_SIZE_M2 - size_m2) * 2)
        reasons.append(f"Size {size_m2} m2 slightly below minimum")
    
    if price and price <= 20000:
        score += 25
        reasons.append(f"Price {price} CZK within budget")
    
    commute_minutes = calculate_commute_time(latitude, longitude)
    if commute_minutes is not None:
        if commute_minutes <= COMMUTE_MAX_MINUTES:
            score += 30
            reasons.append(f"Commute {commute_minutes:.1f} min to Palmovka (max {COMMUTE_MAX_MINUTES})")
        else:
            score += max(0, 30 - (commute_minutes - COMMUTE_MAX_MINUTES) * 2)
            reasons.append(f"Commute {commute_minutes:.1f} min to Palmovka (slightly over)")
    else:
        reasons.append("Commute time could not be calculated")
    
    score += 20
    
    is_flatshare = check_flatshare(description, title)
    is_auction, is_city_auction = check_auction(description, title)
    
    if is_flatshare:
        score -= 50
        reasons.append("WARNING: Appears to be a flatshare/room rental")
    
    if is_auction:
        if is_city_auction:
            score = -100
            reasons.append("REJECT: City/municipal auction - ignoring")
        else:
            score -= 30
            reasons.append("WARNING: Appears to be an auction (non-city)")
    
    return min(100, max(0, score)), "; ".join(reasons), is_flatshare, is_auction, commute_minutes
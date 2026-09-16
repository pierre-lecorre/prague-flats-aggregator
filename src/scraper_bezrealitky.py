import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from scraper_base import BaseScraper

class BezrealitkyScraper(BaseScraper):
    source_name = "bezrealitky"
    base_url = "https://www.bezrealitky.cz/vyhledat?boundaryPoints=%5B%7B%22lat%22%3A50.13007318104701%2C%22lng%22%3A14.53205776150702%7D%2C%7B%22lat%22%3A50.13007318104701%2C%22lng%22%3A14.326692925962533%7D%2C%7B%22lat%22%3A50.04683586656233%2C%22lng%22%3A14.326692925962533%7D%2C%7B%22lat%22%3A50.04683586656233%2C%22lng%22%3A14.53205776150702%7D%2C%7B%22lat%22%3A50.13007318104701%2C%22lng%22%3A14.53205776150702%7D%5D&estateType=BYT&location=exact&offerType=PRONAJEM&osm_value=Praha%2C+%C4%8Cesko&priceTo=20000&regionOsmIds=R435514&currency=CZK"
    
    async def scrape(self) -> List[Dict[str, Any]]:
        listings = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            try:
                response = await client.get(self.base_url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                property_cards = soup.select('.property-card, .listing-item, [class*="property"], [class*="listing"], article')
                
                for card in property_cards[:50]:
                    try:
                        listing = self.parse_card(card)
                        if listing and listing.get("url"):
                            listings.append(listing)
                    except Exception as e:
                        print(f"Error parsing card: {e}")
                        continue
                        
            except Exception as e:
                print(f"Bezrealitky scraper error: {e}")
        
        return listings
    
    def parse_card(self, card) -> Dict[str, Any]:
        try:
            title_el = card.select_one('h2, h3, [class*="title"], [class*="name"]')
            title = title_el.get_text(strip=True) if title_el else ""
            
            price_el = card.select_one('[class*="price"], .price')
            price = self.parse_price(price_el.get_text() if price_el else "")
            
            size_el = card.select_one('[class*="area"], [class*="size"], [class*="m2"]')
            size_m2 = self.parse_size(size_el.get_text() if size_el else "")
            
            address_el = card.select_one('[class*="address"], [class*="location"]')
            address = address_el.get_text(strip=True) if address_el else ""
            
            link_el = card.select_one('a[href*="/pronajem/"], a[href*="/byt/"]')
            url = link_el.get('href') if link_el else ""
            if url and not url.startswith('http'):
                url = "https://www.bezrealitky.cz" + url
            
            description = ""
            desc_el = card.select_one('[class*="description"], [class*="text"]')
            if desc_el:
                description = desc_el.get_text(strip=True)
            
            lat, lon = None, None
            
            return {
                "id": self.generate_listing_id(url),
                "source": self.source_name,
                "title": title,
                "price": price,
                "size_m2": size_m2,
                "address": address,
                "url": url,
                "description": description,
                "images": [],
                "latitude": lat,
                "longitude": lon
            }
        except Exception as e:
            print(f"Error parsing Bezrealitky card: {e}")
            return {}
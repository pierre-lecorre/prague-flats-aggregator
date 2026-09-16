from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import hashlib
import re

class BaseScraper(ABC):
    source_name: str = "base"
    base_url: str = ""
    
    @abstractmethod
    async def scrape(self) -> List[Dict[str, Any]]:
        pass
    
    def generate_listing_id(self, url: str) -> str:
        return f"{self.source_name}_{hashlib.md5(url.encode()).hexdigest()[:12]}"
    
    def parse_price(self, price_str: str) -> Optional[int]:
        if not price_str:
            return None
        match = re.search(r'(\d+[\s,]?\d*)', str(price_str).replace(" ", ""))
        if match:
            return int(match.group(1).replace(",", ""))
        return None
    
    def parse_size(self, size_str: str) -> Optional[float]:
        if not size_str:
            return None
        match = re.search(r'(\d+\.?\d*)', str(size_str))
        if match:
            return float(match.group(1))
        return None
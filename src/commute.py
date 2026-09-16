import httpx
from typing import Optional, Tuple

def calculate_commute_time(origin_lat: float, origin_lon: float, 
                           dest_lat: float = 50.1067, dest_lon: float = 14.4639) -> Optional[float]:
    """
    Calculate commute time using OSRM driving route.
    Default destination is Palmovka, Prague.
    Returns time in minutes, or None if calculation fails.
    """
    try:
        url = "https://router.project-osrm.org/route/v1/driving"
        origin = f"{origin_lon},{origin_lat}"
        dest = f"{dest_lon},{dest_lat}"
        full_url = f"{url}/{origin};{dest}?overview=false"
        
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

def calculate_commute_time_with_address(origin_lat: float, origin_lon: float,
                                        target_address: str = "Palmovka, Prague") -> Optional[float]:
    """
    Wrapper for calculate_commute_time that could be extended to use geocoding.
    For now, uses default Palmovka coordinates.
    """
    # Default Palmovka coordinates
    dest_lat, dest_lon = 50.1067, 14.4639
    
    # Could extend to geocode target_address in the future
    if "palmovka" in target_address.lower():
        dest_lat, dest_lon = 50.1067, 14.4639
    
    return calculate_commute_time(origin_lat, origin_lon, dest_lat, dest_lon)

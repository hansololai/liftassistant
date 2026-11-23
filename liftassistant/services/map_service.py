"""Pluggable Map & Geocoding Service (Decision 5).
Uses OpenStreetMap Nominatim by default for physical location grounding.
Handles:
1. Physical address search & verification (Option 2 map widget).
2. Nearby POI grounding using coordinates (Option 3 on-the-go logging).
3. Reverse geocoding.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

from liftassistant.models.domain import Place
from liftassistant.db.repository import PlaceRepository

logger = logging.getLogger(__name__)


class MapService:
    """Service for grounding physical real-world places."""

    def __init__(
        self,
        place_repo: Optional[PlaceRepository] = None,
        user_agent: str = "LiftAssistant/3.0 (personal_life_os)",
        timeout: int = 5,
    ):
        self.place_repo = place_repo
        self.geolocator = Nominatim(user_agent=user_agent, timeout=timeout)

    def list_places(self, search: Optional[str] = None, limit: int = 50) -> List[Place]:
        """List verified physical places from the places catalog."""
        if not self.place_repo:
            return []
        return self.place_repo.list_places(search=search, limit=limit)

    def create_grounded_place(
        self,
        name: str,
        address: str,
        category: Optional[str] = "venue",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        map_url: Optional[str] = None,
        google_place_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Place:
        """Validate, ground, and persist a verified physical place."""
        if not name or not name.strip():
            raise ValueError("A physical place must have a valid name.")
        if not address or not address.strip():
            raise ValueError("A physical place must have a grounded address.")
        if not self.place_repo:
            raise RuntimeError("PlaceRepository is required to persist places.")

        # Re-use existing place if address matches an already grounded place
        addr_clean = address.strip().lower()
        street_prefix = address.split(",")[0].strip().lower()
        existing_places = self.place_repo.list_places(search=street_prefix, limit=5)
        for ep in existing_places:
            if ep.address and (street_prefix in ep.address.lower() or ep.address.lower() in addr_clean):
                return ep

        resolved_category = category or "venue"
        resolved_lat = latitude
        resolved_lng = longitude

        # Ground real-world category and coordinates from OpenStreetMap Nominatim
        if resolved_category in ("venue", "shopping") or resolved_lat is None:
            disc_cat, disc_lat, disc_lng = self.ground_place_details(name, address)
            if disc_cat and resolved_category in ("venue", "shopping"):
                resolved_category = disc_cat
            if resolved_lat is None and disc_lat is not None:
                resolved_lat = disc_lat
            if resolved_lng is None and disc_lng is not None:
                resolved_lng = disc_lng

        resolved_map_url = map_url
        if not resolved_map_url and resolved_lat is not None and resolved_lng is not None:
            resolved_map_url = f"https://www.google.com/maps/search/?api=1&query={resolved_lat},{resolved_lng}"

        place = Place(
            id=f"pl_{uuid4().hex[:8]}",
            name=name.strip(),
            category=resolved_category,
            address=address.strip(),
            latitude=resolved_lat,
            longitude=resolved_lng,
            map_url=resolved_map_url,
            google_place_id=google_place_id,
            notes=notes,
        )
        return self.place_repo.create_place(place)

    def ground_place_details(
        self,
        name: str,
        address: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[float], Optional[float]]:
        """Query Nominatim POI tags to extract physical category (dining vs shopping) and coordinates."""
        queries: List[str] = []
        if address:
            # Try combining merchant name with locality/city from address
            parts = [p.strip() for p in address.split(",") if p.strip()]
            if len(parts) >= 2:
                queries.append(f"{name}, {parts[-2]}")
            queries.append(f"{name}, {address}")
        queries.append(name)

        dining_types = {
            "restaurant", "fast_food", "cafe", "bar", "pub", "food_court",
            "ice_cream", "bistro", "diner", "pizzeria", "bakery", "eatery"
        }
        shopping_types = {
            "supermarket", "convenience", "wholesale", "department_store",
            "clothes", "hardware", "mall", "chemist", "electronics", "shoes", "variety_store"
        }

        for q in queries:
            try:
                res = self.geolocator.geocode(q, addressdetails=True)
                if res and hasattr(res, "raw"):
                    raw = res.raw
                    osm_class = str(raw.get("class", "")).lower()
                    osm_type = str(raw.get("type", "")).lower()
                    lat = round(float(res.latitude), 6) if res.latitude else None
                    lng = round(float(res.longitude), 6) if res.longitude else None

                    if osm_type in dining_types or (osm_class == "amenity" and osm_type in dining_types):
                        return "dining", lat, lng

                    if osm_class == "shop" or osm_type in shopping_types:
                        return "shopping", lat, lng

                    if lat and lng:
                        return None, lat, lng
            except Exception:
                pass

        return None, None, None

    def search_places(
        self,
        query: str,
        near_lat: Optional[float] = None,
        near_lng: Optional[float] = None,
        limit: int = 5,
    ) -> List[Place]:
        """Option 2: Search physical map places by name or address.
        Returns a list of grounded Place objects with verified coordinates.
        """
        if not query or not query.strip():
            return []

        places: List[Place] = []

        # 1. First check our local SQLite verified places for fast instant match
        if self.place_repo:
            local_matches = self.place_repo.list_places(search=query, limit=limit)
            places.extend(local_matches)

        # 2. Query Nominatim for online geocoding grounding
        try:
            viewbox = None
            if near_lat and near_lng:
                # 0.5 deg bbox (~35 miles around base)
                delta = 0.5
                viewbox = ((near_lat - delta, near_lng - delta), (near_lat + delta, near_lng + delta))

            results = self.geolocator.geocode(
                query,
                exactly_one=False,
                limit=limit,
                addressdetails=True,
                viewbox=viewbox,
            )
            if results:
                for res in results:
                    raw = getattr(res, "raw", {})
                    display_name = raw.get("display_name", str(res))
                    # Extract concise place name
                    name = query.title()
                    addr_dict = raw.get("address", {})
                    if "amenity" in addr_dict:
                        name = addr_dict["amenity"]
                    elif "shop" in addr_dict:
                        name = addr_dict["shop"]
                    elif "building" in addr_dict:
                        name = addr_dict["building"]
                    elif "office" in addr_dict:
                        name = addr_dict["office"]
                    elif "leisure" in addr_dict:
                        name = addr_dict["leisure"]

                    # Deduplicate against local matches
                    if any(p.address == display_name or (abs(p.latitude - res.latitude) < 0.0001 and abs(p.longitude - res.longitude) < 0.0001) for p in places if p.latitude and p.longitude):
                        continue

                    places.append(
                        Place(
                            id=f"pl_{uuid4().hex[:8]}",
                            name=name,
                            category=raw.get("type", "venue"),
                            address=display_name,
                            latitude=round(res.latitude, 6),
                            longitude=round(res.longitude, 6),
                            map_url=f"https://www.openstreetmap.org/?mlat={res.latitude}&mlon={res.longitude}#map=16/{res.latitude}/{res.longitude}",
                            google_place_id=str(raw.get("osm_id", "")),
                            notes="Verified physical location via OpenStreetMap.",
                        )
                    )
        except (GeocoderTimedOut, GeocoderServiceError, Exception) as e:
            logger.warning("Geocoding lookup failed or offline for query '%s': %s", query, e)

        return places[:limit]

    def resolve_nearby_poi(
        self,
        query: str,
        latitude: float,
        longitude: float,
        max_radius_miles: float = 2.0,
    ) -> Place:
        """Option 3: Resolve and ground a place using user GPS coordinates + name hint.
        Searches local database first, then reverse geocodes / nearby searches to ground the physical venue.
        """
        # 1. Check local database for an existing place nearby with matching name
        if self.place_repo:
            existing = self.place_repo.find_nearest(
                latitude=latitude,
                longitude=longitude,
                max_distance_miles=max_radius_miles,
                name_hint=query,
            )
            if existing:
                return existing

        # 2. Online reverse geocode around coordinates to ground physical address
        address = None
        try:
            rev = self.geolocator.reverse((latitude, longitude), exactly_one=True, addressdetails=True)
            if rev:
                address = rev.address
        except Exception as e:
            logger.warning("Reverse geocode failed: %s", e)

        grounded_place = Place(
            id=f"pl_{uuid4().hex[:8]}",
            name=query.title() if query else "Physical Location",
            category="venue",
            address=address or f"Coordinates: {round(latitude, 4)}, {round(longitude, 4)}",
            latitude=round(latitude, 6),
            longitude=round(longitude, 6),
            map_url=f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}",
            notes="Grounded via on-the-go device GPS coordinates.",
        )

        if self.place_repo:
            self.place_repo.upsert_place(grounded_place)

        return grounded_place

"""Trip Service.
Handles inverted geofence evaluation (> 30 miles from Cranberry Township base),
out-of-town trip tracking, and trip budget accounting.
"""

from datetime import date
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from liftassistant.models.domain import Trip, TripStop

logger = logging.getLogger(__name__)

# Default household base: Cranberry Township, PA
DEFAULT_BASE_LAT = 40.6873
DEFAULT_BASE_LNG = -80.1078
DEFAULT_GEOFENCE_RADIUS_MILES = 30.0


def calculate_haversine_distance_miles(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate great-circle distance between two GPS coordinates in miles."""
    earth_radius_miles = 3958.8

    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_miles * c


class TripService:
    """Service to evaluate out-of-town trips and inverted geofence triggers."""

    def __init__(
        self,
        base_lat: float = DEFAULT_BASE_LAT,
        base_lng: float = DEFAULT_BASE_LNG,
        radius_miles: float = DEFAULT_GEOFENCE_RADIUS_MILES,
        conn: Optional[Any] = None,
    ):
        self.base_lat = base_lat
        self.base_lng = base_lng
        self.radius_miles = radius_miles
        self.conn = conn

    def list_trips(self) -> List[Dict[str, Any]]:
        """List all trips with their stops and budget status."""
        if not self.conn:
            return []
        cursor = self.conn.cursor()
        rows = cursor.execute("SELECT * FROM trips ORDER BY start_date DESC").fetchall()
        results = []
        for r in rows:
            trip_data = dict(r)
            stops = cursor.execute(
                "SELECT * FROM trip_stops WHERE trip_id = ? ORDER BY order_index ASC, stop_date ASC",
                (trip_data["id"],),
            ).fetchall()
            trip_data["stops"] = [dict(s) for s in stops]
            results.append(trip_data)
        return results

    def get_trip(self, trip_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific trip with stops."""
        if not self.conn:
            return None
        cursor = self.conn.cursor()
        row = cursor.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if not row:
            return None
        trip_data = dict(row)
        stops = cursor.execute(
            "SELECT * FROM trip_stops WHERE trip_id = ? ORDER BY order_index ASC, stop_date ASC",
            (trip_id,),
        ).fetchall()
        trip_data["stops"] = [dict(s) for s in stops]
        return trip_data

    def create_trip(self, trip: Trip) -> Dict[str, Any]:
        """Create a new trip container."""
        if not self.conn:
            raise RuntimeError("Database connection not provided to TripService")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO trips (
                id, name, start_date, end_date, budget, spent,
                geofence_center_lat, geofence_center_lng, inverted_geofence_radius_miles, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trip.id,
                trip.name,
                trip.start_date.isoformat(),
                trip.end_date.isoformat(),
                trip.budget,
                trip.spent,
                trip.geofence_center_lat,
                trip.geofence_center_lng,
                trip.inverted_geofence_radius_miles,
                trip.notes,
            ),
        )
        self.conn.commit()
        return self.get_trip(trip.id) or trip.model_dump()

    def add_stop(self, stop: TripStop) -> Dict[str, Any]:
        """Add a stop to an existing trip and update trip spent amount."""
        if not self.conn:
            raise RuntimeError("Database connection not provided to TripService")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO trip_stops (id, trip_id, name, stop_date, category, spent, notes, order_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stop.id,
                stop.trip_id,
                stop.name,
                stop.stop_date.isoformat() if stop.stop_date else None,
                stop.category,
                stop.spent,
                stop.notes,
                stop.order_index,
            ),
        )
        # Update total spent on the trip
        cursor.execute(
            "UPDATE trips SET spent = (SELECT COALESCE(SUM(spent), 0.0) FROM trip_stops WHERE trip_id = ?) WHERE id = ?",
            (stop.trip_id, stop.trip_id),
        )
        self.conn.commit()
        row = cursor.execute("SELECT * FROM trip_stops WHERE id = ?", (stop.id,)).fetchone()
        return dict(row) if row else stop.model_dump()

    def is_outside_home_geofence(
        self,
        latitude: float,
        longitude: float,
        radius_override: Optional[float] = None,
    ) -> Tuple[bool, float]:
        """Check if coordinates exceed the 30-mile home radius (Inverted Geofence).
        Returns (is_outside, distance_miles).
        """
        threshold = radius_override or self.radius_miles
        dist = calculate_haversine_distance_miles(
            self.base_lat, self.base_lng, latitude, longitude
        )
        is_outside = dist > threshold
        return is_outside, round(dist, 1)

    def evaluate_event_for_trip(
        self,
        event_title: str,
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> Dict[str, Any]:
        """Evaluate whether a life event belongs to an out-of-town trip."""
        if latitude is None or longitude is None:
            return {
                "trip_mode_triggered": False,
                "distance_from_base_miles": 0.0,
                "reason": "No GPS coordinates provided",
            }

        is_outside, distance = self.is_outside_home_geofence(latitude, longitude)

        return {
            "trip_mode_triggered": is_outside,
            "distance_from_base_miles": distance,
            "threshold_miles": self.radius_miles,
            "status": "OUT_OF_TOWN_TRIP" if is_outside else "LOCAL_CRANBERRY_METRO",
            "message": (
                f"Event is {distance} miles from home base (exceeds {self.radius_miles}mi limit) -> TRIP MODE ACTIVE"
                if is_outside
                else f"Event is {distance} miles from home base (within {self.radius_miles}mi local radius)"
            ),
        }

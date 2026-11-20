"""Trip and travel management API routes.
Validates requests and delegates business logic to TripService.
"""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends

from liftassistant.api.deps import get_trip_service
from liftassistant.services.trip_service import TripService

router = APIRouter(prefix="/trips", tags=["trips"])


@router.get("", response_model=List[Dict[str, Any]])
def list_trips(
    trip_service: TripService = Depends(get_trip_service),
) -> List[Dict[str, Any]]:
    """List all trips and their stops."""
    return trip_service.list_trips()

"""Physical Places & Venues API Router.
Enforces physical address and coordinate grounding (Decision 5 & Decision 7).
All business logic and persistence are delegated to MapService.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from liftassistant.api.deps import get_map_service
from liftassistant.services.map_service import MapService

router = APIRouter(prefix="/places", tags=["Places"])


class CreatePlaceRequest(BaseModel):
    name: str
    category: Optional[str] = "venue"
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    map_url: Optional[str] = None
    google_place_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("", response_model=List[Dict[str, Any]])
def list_places(
    search: Optional[str] = Query(None, description="Filter by name or address substring"),
    map_service: MapService = Depends(get_map_service),
) -> List[Dict[str, Any]]:
    """List verified physical places for frontend autocomplete."""
    places = map_service.list_places(search=search)
    return [p.model_dump() for p in places]


@router.get("/search", response_model=List[Dict[str, Any]])
def search_physical_places(
    q: str = Query(..., min_length=2, description="Place or venue name/address search query"),
    lat: Optional[float] = Query(None, description="User latitude bias"),
    lng: Optional[float] = Query(None, description="User longitude bias"),
    limit: int = Query(5, ge=1, le=20),
    map_service: MapService = Depends(get_map_service),
) -> List[Dict[str, Any]]:
    """Option 2: Physical Map Search Widget endpoint.
    Queries OpenStreetMap Nominatim for real-world grounded venues with verified coordinates.
    """
    results = map_service.search_places(query=q, near_lat=lat, near_lng=lng, limit=limit)
    return [p.model_dump() for p in results]


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_grounded_place(
    payload: CreatePlaceRequest,
    map_service: MapService = Depends(get_map_service),
) -> Dict[str, Any]:
    """Validate payload and delegate place grounding to MapService."""
    try:
        saved = map_service.create_grounded_place(
            name=payload.name,
            address=payload.address,
            category=payload.category,
            latitude=payload.latitude,
            longitude=payload.longitude,
            map_url=payload.map_url,
            google_place_id=payload.google_place_id,
            notes=payload.notes,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    return saved.model_dump()

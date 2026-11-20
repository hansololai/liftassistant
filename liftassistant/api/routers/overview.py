"""Morning Briefing & Daily Status API Router.
Delegates daily summary assembly to EventManager.
"""

from fastapi import APIRouter, Depends
from liftassistant.api.deps import get_event_manager
from liftassistant.services.event_manager import EventManager

router = APIRouter(prefix="/overview", tags=["Overview"])


@router.get("/briefing")
def get_morning_briefing(
    event_manager: EventManager = Depends(get_event_manager),
):
    """Fetch daily contextual overview, weather advisory, and summary counts."""
    return event_manager.get_morning_briefing()

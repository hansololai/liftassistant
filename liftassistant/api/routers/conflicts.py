"""Conflict Triage Center API Router.
Validates requests and delegates conflict evaluation & triage to EventManager.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from liftassistant.api.deps import get_event_manager
from liftassistant.services.event_manager import EventManager

router = APIRouter(prefix="/conflicts", tags=["Conflicts"])


@router.get("")
def list_conflicts(event_manager: EventManager = Depends(get_event_manager)):
    """Fetch all active schedule collisions, travel time violations, and facility mutex conflicts."""
    conflicts = event_manager.evaluate_all_conflicts()
    return [c.model_dump() for c in conflicts]


@router.post("/{conflict_id}/acknowledge")
def acknowledge_conflict(
    conflict_id: str,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Acknowledge conflict and retain conflicting event on schedule via EventManager."""
    result = event_manager.acknowledge_conflict(conflict_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conflict '{conflict_id}' not found or already resolved.",
        )
    return result


@router.post("/{conflict_id}/reschedule")
def reschedule_conflict(
    conflict_id: str,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Reschedule conflicting event to suggested non-colliding time slot via EventManager."""
    result = event_manager.reschedule_conflict(conflict_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conflict '{conflict_id}' not found or already resolved.",
        )
    return result

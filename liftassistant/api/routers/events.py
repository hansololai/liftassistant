"""Universal Life Events API Router with polymorphic details.
Validates incoming requests and delegates all business logic to EventManager.
"""

import json
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from liftassistant.api.deps import get_event_manager
from liftassistant.services.event_manager import EventManager

router = APIRouter(prefix="/events", tags=["Events"])


class EventCreateRequest(BaseModel):
    model_config = {"extra": "allow"}

    title: str
    event_type: str = "CUSTOM"
    scheduled_at: Optional[datetime] = None
    duration_minutes: int = 60
    deadline: Optional[datetime] = None
    place_id: Optional[str] = None
    studio: Optional[str] = None
    place_query: Optional[str] = None
    place_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    completed_at: Optional[datetime] = None
    people_involved: List[str] = []
    total_amount: float = 0.0
    notes: Optional[str] = None
    # Flat optional category metadata for special sub-tables (DINING, MAINTENANCE)
    rating: Optional[int] = None
    service_type: Optional[str] = None


@router.get("")
def list_events(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    status_filter: Optional[str] = Query("all", alias="status", description="upcoming, completed, all"),
    sort_by_deadline: bool = Query(True, description="Order by closest deadline"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_manager: EventManager = Depends(get_event_manager),
):
    """List events from the ledger with pagination envelope (result, total_count, start_index, end_index, has_more)."""
    paged = event_manager.list_events(
        event_type=event_type,
        status=status_filter,
        sort_by_deadline=sort_by_deadline,
        limit=limit,
        offset=offset,
    )
    return {
        "result": [e.model_dump() if hasattr(e, "model_dump") else e for e in paged["result"]],
        "total_count": paged["total_count"],
        "start_index": paged["start_index"],
        "end_index": paged["end_index"],
        "has_more": paged["has_more"],
    }


def _format_event_response(result: Any) -> dict:
    """Normalize EventManager creation output into uniform REST JSON response."""
    if isinstance(result, dict):
        return result
    dumped = result.model_dump()
    return {**dumped, "event": dumped}


def _parse_multipart_create_params(form: Any) -> dict:
    """Validate and extract multipart/form-data fields for EventManager.create_event."""
    title = form.get("title")
    if not title or not str(title).strip():
        raise RequestValidationError(
            [{"loc": ["body", "title"], "msg": "Field 'title' is required", "type": "missing"}]
        )

    sched_dt = None
    sched_raw = form.get("scheduled_at")
    if sched_raw:
        try:
            sched_dt = datetime.fromisoformat(str(sched_raw).replace("Z", "+00:00"))
        except ValueError:
            raise RequestValidationError(
                [{"loc": ["body", "scheduled_at"], "msg": "Invalid ISO datetime format", "type": "datetime_parsing"}]
            )

    dur = form.get("duration_minutes")
    dur_mins = 60
    if dur is not None and str(dur).strip():
        try:
            dur_mins = int(dur)
        except ValueError:
            raise RequestValidationError(
                [{"loc": ["body", "duration_minutes"], "msg": "Must be an integer", "type": "int_parsing"}]
            )

    people_list: List[str] = []
    people_raw = form.get("people_involved")
    if people_raw:
        try:
            parsed = json.loads(str(people_raw))
            people_list = parsed if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            people_list = [str(people_raw)]

    total_amt = 0.0
    total_amt_raw = form.get("total_amount")
    if total_amt_raw is not None and str(total_amt_raw).strip():
        try:
            total_amt = float(total_amt_raw)
        except ValueError:
            raise RequestValidationError(
                [{"loc": ["body", "total_amount"], "msg": "Must be a valid number", "type": "float_parsing"}]
            )

    params: dict = {
        "title": str(title).strip(),
        "event_type": str(form.get("event_type", "CUSTOM")),
        "scheduled_at": sched_dt,
        "duration_minutes": dur_mins,
        "people_involved": people_list,
        "notes": str(form.get("notes") or form.get("description") or "") or None,
        "total_amount": total_amt,
        "place_id": str(form.get("place_id") or "") or None,
    }

    lat = form.get("latitude")
    lng = form.get("longitude")
    if lat is not None and lng is not None:
        try:
            params["latitude"] = float(lat)
            params["longitude"] = float(lng)
        except ValueError:
            raise RequestValidationError(
                [{"loc": ["body", "latitude"], "msg": "Invalid GPS coordinates", "type": "float_parsing"}]
            )
        params["place_query"] = str(form.get("place_query") or form.get("place_name") or params["title"])

    return params


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_event(
    request: Request,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Unified Life Event creation endpoint.
    Validates HTTP multipart/JSON payload and delegates domain orchestration to EventManager.create_event.
    """
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        params = _parse_multipart_create_params(form)
        title = params.pop("title")

        receipt_file = form.get("receipt_file") or form.get("file")
        if receipt_file and hasattr(receipt_file, "read"):
            file_bytes = await receipt_file.read()
            if len(file_bytes) > 0:
                params["receipt_bytes"] = file_bytes
                params["filename"] = getattr(receipt_file, "filename", None) or "receipt.jpg"

        try:
            res = event_manager.create_event(title, **params)
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
        return _format_event_response(res)

    try:
        body = await request.json()
    except Exception:
        raise RequestValidationError([{"loc": ["body"], "msg": "Invalid JSON body", "type": "json_invalid"}])

    try:
        payload = EventCreateRequest.model_validate(body)
    except ValidationError as e:
        raise RequestValidationError(e.errors())

    lat = payload.latitude
    lng = payload.longitude

    params = {
        "event_type": payload.event_type,
        "scheduled_at": payload.scheduled_at,
        "duration_minutes": payload.duration_minutes or (30 if lat is not None else 60),
        "deadline": payload.deadline,
        "place_id": payload.place_id,
        "studio": payload.studio,
        "people_involved": payload.people_involved,
        "notes": payload.notes,
        "total_amount": payload.total_amount,
        "rating": payload.rating,
        "service_type": payload.service_type,
        "completed_at": payload.completed_at,
    }
    if lat is not None and lng is not None:
        params["latitude"] = lat
        params["longitude"] = lng
        params["place_query"] = payload.place_query or payload.place_name or payload.title

    try:
        res = event_manager.create_event(payload.title, **params)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    return _format_event_response(res)


class EventUpdateRequest(BaseModel):
    model_config = {"extra": "allow"}

    title: Optional[str] = None
    event_type: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    deadline: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    place_id: Optional[str] = None
    studio: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    people_involved: Optional[List[str]] = None
    notes: Optional[str] = None
    total_amount: Optional[float] = None


class CompleteEventRequest(BaseModel):
    completed_at: Optional[datetime] = None
    total_amount: Optional[float] = None


class ConflictCheckRequest(BaseModel):
    model_config = {"extra": "allow"}

    scheduled_at: datetime
    duration_minutes: Optional[int] = 60
    title: Optional[str] = "Proposed Event"
    people_involved: Optional[List[str]] = None
    place_id: Optional[str] = None
    studio: Optional[str] = None
    notes: Optional[str] = None
    event_id: Optional[str] = None


@router.post("/check-conflict")
def check_event_conflict(
    payload: ConflictCheckRequest,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Pre-flight conflict check endpoint. Returns any clashes with facility blackouts, travel buffers, or attendees."""
    conflicts = event_manager.check_event_conflict(
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes or 60,
        title=payload.title or "Proposed Event",
        people_involved=payload.people_involved or [],
        place_id=payload.place_id,
        studio=payload.studio,
        notes=payload.notes,
        exclude_event_id=payload.event_id,
    )
    return {
        "has_conflict": len(conflicts) > 0,
        "conflicts": [c.model_dump() for c in conflicts],
    }


class RecheckConflictsRequest(BaseModel):
    force_refresh: bool = True


@router.get("/conflicts")
def get_conflicts(
    event_manager: EventManager = Depends(get_event_manager),
):
    """List all active conflicts detected across upcoming events."""
    conflicts = event_manager.evaluate_all_conflicts(force_refresh_facility=False, persist_sync=True)
    return {
        "conflicts": [c.model_dump() for c in conflicts],
        "total_conflicts": len(conflicts),
    }


@router.post("/recheck-conflicts")
def recheck_all_conflicts(
    payload: Optional[RecheckConflictsRequest] = None,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Re-evaluate all calendar conflicts across the schedule.
    Queries live external facilities (e.g. YMCA API) when force_refresh=True,
    and updates has_conflict/conflict_status flags on the ledger.
    """
    force_refresh = payload.force_refresh if payload else True
    conflicts = event_manager.evaluate_all_conflicts(
        force_refresh_facility=force_refresh,
        persist_sync=True,
    )
    return {
        "conflicts": [c.model_dump() for c in conflicts],
        "total_conflicts": len(conflicts),
        "refreshed_live_facility": force_refresh,
        "message": f"Successfully rechecked schedule. {len(conflicts)} active conflict(s) detected.",
    }


class ConflictActionRequest(BaseModel):
    action: str = "ACKNOWLEDGE"  # "ACKNOWLEDGE" or "RESCHEDULE"


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict_endpoint(
    conflict_id: str,
    payload: Optional[ConflictActionRequest] = None,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Resolve an active conflict via Acknowledge or Reschedule."""
    action = payload.action.upper() if payload and payload.action else "ACKNOWLEDGE"
    if action == "RESCHEDULE":
        res = event_manager.reschedule_conflict(conflict_id)
    else:
        res = event_manager.acknowledge_conflict(conflict_id)

    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conflict '{conflict_id}' not found or already resolved",
        )
    return res


@router.get("/{event_id}")
def get_event(
    event_id: str,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Retrieve details for a single event by ID."""
    evt = event_manager.get_event(event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found")
    return _format_event_response(evt)


@router.put("/{event_id}")
def update_event(
    event_id: str,
    payload: EventUpdateRequest,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Update fields on an existing event."""
    fields = payload.model_dump(exclude_unset=True)
    evt = event_manager.update_event(event_id, **fields)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found")
    return _format_event_response(evt)


@router.post("/{event_id}/complete")
def complete_event_endpoint(
    event_id: str,
    payload: Optional[CompleteEventRequest] = None,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Mark an event as completed."""
    completed_at = payload.completed_at if payload else None
    total_amount = payload.total_amount if payload else None
    evt = event_manager.complete_event(event_id, completed_at=completed_at, total_amount=total_amount)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found")
    return _format_event_response(evt)


@router.post("/{event_id}/uncomplete")
def uncomplete_event_endpoint(
    event_id: str,
    event_manager: EventManager = Depends(get_event_manager),
):
    """Mark an event as incomplete / reopen."""
    evt = event_manager.uncomplete_event(event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found")
    return _format_event_response(evt)


@router.delete("/{event_id}")
def delete_event_endpoint(event_id: str):
    """Deletion of events is strictly disallowed to preserve ledger tractability and auditability."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Event deletion is disallowed to preserve ledger tractability and auditability. Events may be rescheduled or marked completed/cancelled, but not deleted from the ledger.",
    )

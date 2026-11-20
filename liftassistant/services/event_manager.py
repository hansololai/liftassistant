"""Event Manager Middle Layer Domain Service.
Acts as the orchestrating domain service between REST API routers and database DAOs.
Enforces physical location grounding, conflict detection, and omnichannel receipt ingestion.
"""

from datetime import date, datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from liftassistant.db.repository import EventRepository, PlaceRepository
from liftassistant.models.domain import (
    Conflict,
    DiningDetail,
    LifeEvent,
    MaintenanceDetail,
    Place,
    ShoppingDetail,
)
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.map_service import MapService
from liftassistant.api.routers.ingest import register_ingestion_job

logger = logging.getLogger(__name__)


class EventManager:
    """Core domain service for managing the unified life event continuum."""

    def __init__(
        self,
        event_repo: EventRepository,
        conflict_engine: Optional[ConflictEngine] = None,
        place_repo: Optional[PlaceRepository] = None,
        map_service: Optional[MapService] = None,
        cas_storage: Optional[CASStorage] = None,
    ):
        self.repo = event_repo
        self.conflict_engine = conflict_engine or ConflictEngine()
        self.place_repo = place_repo or (PlaceRepository(self.repo.conn) if self.repo and hasattr(self.repo, 'conn') and self.repo.conn else None)
        self.map_service = map_service or MapService(place_repo=self.place_repo)
        self.cas = cas_storage or CASStorage()

    # =========================================================================
    # COMMON CREATION & LIFECYCLE HELPERS (Deduplication)
    # =========================================================================
    def _assemble_sub_details(
        self,
        event_id: str,
        event_type: str,
        total_amount: float = 0.0,
        rating: Optional[int] = None,
        service_type: Optional[str] = None,
        receipt_image_path: Optional[str] = None,
        dining_detail: Optional[DiningDetail] = None,
        shopping_detail: Optional[ShoppingDetail] = None,
        maintenance_detail: Optional[MaintenanceDetail] = None,
    ) -> Tuple[Optional[DiningDetail], Optional[ShoppingDetail], Optional[MaintenanceDetail]]:
        """Assemble and bind polymorphic details for special categories (DINING, SHOPPING, MAINTENANCE)."""
        if event_type == "DINING" and not dining_detail and (rating is not None or total_amount > 0.0):
            dining_detail = DiningDetail(
                event_id=event_id,
                rating=rating,
                total_amount=total_amount,
            )
        elif event_type == "SHOPPING" and not shopping_detail and (total_amount > 0.0 or receipt_image_path):
            shopping_detail = ShoppingDetail(
                event_id=event_id,
                receipt_image_path=receipt_image_path,
                pantry_updated=False,
                total_amount=total_amount,
            )
        elif event_type == "MAINTENANCE" and not maintenance_detail and service_type is not None:
            maintenance_detail = MaintenanceDetail(
                event_id=event_id,
                equipment_id="eq_odyssey",
                service_type=service_type,
            )

        # Propagate event_id to polymorphic detail models
        if dining_detail:
            dining_detail.event_id = event_id
        if shopping_detail:
            shopping_detail.event_id = event_id
        if maintenance_detail:
            maintenance_detail.event_id = event_id

        return dining_detail, shopping_detail, maintenance_detail

    def _evaluate_conflicts_and_persist(
        self,
        event: LifeEvent,
        check_conflicts: bool = True,
    ) -> LifeEvent:
        """Run conflict detection across all upcoming events, tag detected conflicts, and persist to repository."""
        if check_conflicts and self.conflict_engine and event.scheduled_at:
            existing_events = self.repo.list_events(status="upcoming", limit=200)
            conflicts = self.conflict_engine.detect_conflicts(existing_events + [event])
            active_cfl = [c for c in conflicts if c.event_id == event.id]
            if active_cfl:
                event.has_conflict = True
                event.conflict_status = "DETECTED"
                event.conflict_reason = "; ".join(c.title for c in active_cfl)
                logger.info("Conflict flagged on event '%s': %s", event.title, event.conflict_reason)

        return self.repo.create_event(event)

    # =========================================================================
    # 1. OPTION 2: SCHEDULED FUTURE EVENT CREATION (Verified Grounded Place)
    # =========================================================================
    def create_scheduled_event(
        self,
        title: str,
        event_type: str,
        scheduled_at: datetime,
        place_id: Optional[str] = None,
        duration_minutes: int = 60,
        deadline: Optional[datetime] = None,
        people_involved: Optional[List[str]] = None,
        notes: Optional[str] = None,
        total_amount: float = 0.0,
        rating: Optional[int] = None,
        service_type: Optional[str] = None,
        dining_detail: Optional[DiningDetail] = None,
        shopping_detail: Optional[ShoppingDetail] = None,
        maintenance_detail: Optional[MaintenanceDetail] = None,
        check_conflicts: bool = True,
    ) -> LifeEvent:
        """Create a planned future event grounded with a verified physical place (Option 2)."""
        if not title or not title.strip():
            raise ValueError("Event title cannot be empty")

        if duration_minutes <= 0:
            raise ValueError(f"duration_minutes must be positive, got {duration_minutes}")

        # Grounded Place Validation
        if place_id:
            if self.place_repo:
                verified_place = self.place_repo.get_place(place_id)
                if not verified_place:
                    raise ValueError(f"place_id '{place_id}' does not exist in verified places table")
            elif self.repo.conn:
                cursor = self.repo.conn.cursor()
                row = cursor.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
                if not row:
                    raise ValueError(f"place_id '{place_id}' does not exist in verified places table")

        event_id = f"evt_{uuid4().hex[:8]}"
        dining, shopping, maintenance = self._assemble_sub_details(
            event_id=event_id,
            event_type=event_type,
            total_amount=total_amount,
            rating=rating,
            service_type=service_type,
            dining_detail=dining_detail,
            shopping_detail=shopping_detail,
            maintenance_detail=maintenance_detail,
        )

        event = LifeEvent(
            id=event_id,
            title=title.strip(),
            event_type=event_type,
            scheduled_at=scheduled_at,
            scheduled_end_at=scheduled_at + timedelta(minutes=duration_minutes),
            deadline=deadline,
            place_id=place_id,
            people_involved=people_involved or [],
            notes=notes,
            dining_detail=dining,
            shopping_detail=shopping,
            maintenance_detail=maintenance,
        )
        return self._evaluate_conflicts_and_persist(event, check_conflicts=check_conflicts)

    # =========================================================================
    # 2. OPTION 3: QUICK ACTION EVENT (On-the-Go Device GPS POI Grounding)
    # =========================================================================
    def create_quick_action_event(
        self,
        title: str,
        event_type: str,
        latitude: float,
        longitude: float,
        place_query: str,
        people_involved: Optional[List[str]] = None,
        duration_minutes: int = 30,
        notes: Optional[str] = None,
        total_amount: float = 0.0,
        rating: Optional[int] = None,
        service_type: Optional[str] = None,
        check_conflicts: bool = True,
    ) -> LifeEvent:
        """Create an on-the-go event grounded via device GPS coordinates (Option 3)."""
        if not title or not title.strip():
            raise ValueError("Event title cannot be empty")

        now = datetime.now()
        start_time = now - timedelta(minutes=duration_minutes)

        # Attempt to ground the physical location using GPS + query name
        place_id = None
        grounded_place = None
        try:
            grounded_place = self.map_service.resolve_nearby_poi(
                query=place_query,
                latitude=latitude,
                longitude=longitude,
            )
            if grounded_place:
                # Check whether place exists in DB to prevent foreign key failure
                is_persisted = False
                if self.place_repo and self.place_repo.get_place(grounded_place.id):
                    is_persisted = True
                elif self.repo and hasattr(self.repo, 'conn') and self.repo.conn:
                    row = self.repo.conn.cursor().execute("SELECT id FROM places WHERE id = ?", (grounded_place.id,)).fetchone()
                    if row:
                        is_persisted = True
                
                if is_persisted:
                    place_id = grounded_place.id
                    logger.info(
                        "Quick action event '%s' grounded to physical place '%s' (%s, %s)",
                        title,
                        grounded_place.name,
                        grounded_place.address,
                        grounded_place.id,
                    )
                else:
                    logger.warning(
                        "Grounding returned '%s' but place is not persisted in places table; leaving place_id unset for later retry.",
                        grounded_place.name,
                    )
        except Exception as exc:
            logger.warning(
                "Auto-grounding failed for '%s' near (%s, %s): %s. Preserving lat/long for later retry.",
                place_query,
                latitude,
                longitude,
                exc,
            )

        event_id = f"evt_quick_{uuid4().hex[:8]}"
        dining, shopping, maintenance = self._assemble_sub_details(
            event_id=event_id,
            event_type=event_type,
            total_amount=total_amount,
            rating=rating,
            service_type=service_type,
        )

        event = LifeEvent(
            id=event_id,
            title=title.strip(),
            event_type=event_type,
            scheduled_at=start_time,
            scheduled_end_at=now,
            completed_at=now,
            place_id=place_id,
            latitude=latitude,
            longitude=longitude,
            people_involved=people_involved or [],
            notes=notes,
            source="QUICK_ACTION_GPS",
            dining_detail=dining,
            shopping_detail=shopping,
            maintenance_detail=maintenance,
        )
        return self._evaluate_conflicts_and_persist(event, check_conflicts=check_conflicts)

    # =========================================================================
    # 3. OPTION 1: OMNICHANNEL RECEIPT / DOCUMENT UPLOAD (Deferred AI Grounding)
    # =========================================================================
    def create_event_from_receipt(
        self,
        receipt_bytes: bytes,
        filename: str,
        title: Optional[str] = None,
        event_type: str = "SHOPPING",
        scheduled_at: Optional[datetime] = None,
        duration_minutes: int = 60,
        people_involved: Optional[List[str]] = None,
        notes: Optional[str] = None,
        total_amount: float = 0.0,
        check_conflicts: bool = True,
    ) -> Dict[str, Any]:
        """Create an event and store attached receipt in CAS for deferred AI refinement (Option 1)."""
        stored = self.cas.store_file(receipt_bytes, filename)
        now = datetime.now()
        start = scheduled_at or (now - timedelta(minutes=duration_minutes))
        end = start + timedelta(minutes=duration_minutes)

        event_id = f"evt_rec_{uuid4().hex[:8]}"
        event_title = title or f"Receipt: {filename}"

        dining, shopping, maintenance = self._assemble_sub_details(
            event_id=event_id,
            event_type=event_type,
            total_amount=total_amount,
            receipt_image_path=stored["file_path"],
        )

        new_event = LifeEvent(
            id=event_id,
            title=event_title,
            event_type=event_type,
            scheduled_at=start,
            scheduled_end_at=end,
            completed_at=now,
            place_id=None,
            people_involved=people_involved or [],
            notes=notes,
            source="RECEIPT_OCR",
            dining_detail=dining,
            shopping_detail=shopping,
            maintenance_detail=maintenance,
        )

        saved = self._evaluate_conflicts_and_persist(new_event, check_conflicts=check_conflicts)

        job = register_ingestion_job(
            filename=stored["original_filename"],
            file_hash=stored["file_hash"],
            event_id=saved.id,
        )

        return {
            "event": saved.model_dump(),
            "ingestion_job": job,
            **saved.model_dump(),
        }

    # =========================================================================
    # 4. UNIFIED ENTRYPOINT & OVERLOAD
    # =========================================================================
    def create_event(
        self,
        event_or_title: Union[LifeEvent, str],
        *args,
        **kwargs,
    ) -> Union[LifeEvent, Dict[str, Any]]:
        """General entrypoint for event creation. Automatically performs conflict checking."""
        if isinstance(event_or_title, LifeEvent):
            event = event_or_title
            if event.scheduled_at and not event.scheduled_end_at:
                event.scheduled_end_at = event.scheduled_at + timedelta(minutes=60)
            return self._evaluate_conflicts_and_persist(event, check_conflicts=kwargs.get("check_conflicts", True))

        title = str(event_or_title)

        # Dispatch: Receipt Intake (Option 1)
        if "receipt_bytes" in kwargs:
            return self.create_event_from_receipt(
                receipt_bytes=kwargs["receipt_bytes"],
                filename=kwargs.get("filename", "receipt.jpg"),
                title=title,
                event_type=kwargs.get("event_type", "SHOPPING"),
                scheduled_at=kwargs.get("scheduled_at"),
                duration_minutes=int(kwargs.get("duration_minutes", 60)),
                people_involved=kwargs.get("people_involved"),
                notes=kwargs.get("notes"),
                total_amount=float(kwargs.get("total_amount", 0.0)),
                check_conflicts=kwargs.get("check_conflicts", True),
            )

        # Dispatch: Device GPS Grounding (Option 3)
        if "latitude" in kwargs and "longitude" in kwargs and kwargs["latitude"] is not None and kwargs["longitude"] is not None:
            return self.create_quick_action_event(
                title=title,
                event_type=kwargs.get("event_type", "CUSTOM"),
                latitude=float(kwargs["latitude"]),
                longitude=float(kwargs["longitude"]),
                place_query=kwargs.get("place_query", kwargs.get("place_name", title)),
                people_involved=kwargs.get("people_involved"),
                duration_minutes=int(kwargs.get("duration_minutes", 30)),
                notes=kwargs.get("notes"),
                total_amount=float(kwargs.get("total_amount", 0.0)),
                rating=kwargs.get("rating"),
                service_type=kwargs.get("service_type"),
                check_conflicts=kwargs.get("check_conflicts", True),
            )

        # Dispatch: Scheduled Event (Option 2)
        sched_at = kwargs.get("scheduled_at") or datetime.now()
        return self.create_scheduled_event(
            title=title,
            event_type=kwargs.get("event_type", "CUSTOM"),
            scheduled_at=sched_at,
            place_id=kwargs.get("place_id"),
            duration_minutes=int(kwargs.get("duration_minutes", 60)),
            deadline=kwargs.get("deadline"),
            people_involved=kwargs.get("people_involved"),
            notes=kwargs.get("notes"),
            total_amount=float(kwargs.get("total_amount", 0.0)),
            rating=kwargs.get("rating"),
            service_type=kwargs.get("service_type"),
            dining_detail=kwargs.get("dining_detail"),
            shopping_detail=kwargs.get("shopping_detail"),
            maintenance_detail=kwargs.get("maintenance_detail"),
            check_conflicts=kwargs.get("check_conflicts", True),
        )

    # =========================================================================
    # 5. LIFECYCLE & QUERY HELPERS
    # =========================================================================
    def list_events(
        self,
        event_type: Optional[str] = None,
        status: Optional[str] = "all",
        sort_by_deadline: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List events from the ledger with pagination envelope containing result, total_count, start_index, end_index, has_more."""
        events = self.repo.list_events(
            event_type=event_type,
            status=status,
            sort_by_deadline=sort_by_deadline,
            limit=limit,
            offset=offset,
        )
        total_count = self.repo.count_events(event_type=event_type, status=status)
        start_index = offset
        end_index = offset + len(events)
        has_more = end_index < total_count

        return {
            "result": events,
            "total_count": total_count,
            "start_index": start_index,
            "end_index": end_index,
            "has_more": has_more,
        }

    def get_event(self, event_id: str) -> Optional[LifeEvent]:
        """Fetch event with relational joined extensions."""
        return self.repo.get_event(event_id)

    def list_upcoming_events(self, sort_by_deadline: bool = True) -> List[LifeEvent]:
        """List unfulfilled future tasks, sorted by urgency/deadline."""
        return self.repo.list_events(status="upcoming", sort_by_deadline=sort_by_deadline)

    def list_completed_events(self) -> List[LifeEvent]:
        """List fulfilled historical records."""
        return self.repo.list_events(status="completed", sort_by_deadline=False)

    def evaluate_all_conflicts(
        self,
        force_refresh_facility: bool = False,
        persist_sync: bool = True,
    ) -> List[Conflict]:
        """Evaluate all upcoming events for 4D scheduling, travel buffer, and facility conflicts.
        Optionally forces refresh of live facility schedules (e.g. YMCA API) and synchronizes
        has_conflict, conflict_status, and conflict_reason on the events table.
        """
        if not self.conflict_engine:
            return []

        if force_refresh_facility and hasattr(self.conflict_engine, "facility_provider") and self.conflict_engine.facility_provider:
            if hasattr(self.conflict_engine.facility_provider, "fetch_raw_schedule"):
                try:
                    self.conflict_engine.facility_provider.fetch_raw_schedule(force_refresh=True)
                except Exception as e:
                    logger.warning("Force refresh facility schedule failed: %s", e)

        upcoming = self.repo.list_events(status="upcoming", limit=200)
        conflicts = self.conflict_engine.detect_conflicts(upcoming)

        if persist_sync and hasattr(self.repo, "conn") and self.repo.conn:
            try:
                cursor = self.repo.conn.cursor()
                conflicting_event_map = {c.event_id: c for c in conflicts}

                for evt in upcoming:
                    if evt.id in conflicting_event_map:
                        c = conflicting_event_map[evt.id]
                        new_status = "ACKNOWLEDGED" if evt.conflict_status == "ACKNOWLEDGED" else "DETECTED"
                        cursor.execute(
                            "UPDATE events SET has_conflict = 1, conflict_status = ?, conflict_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (new_status, c.title, evt.id),
                        )
                    else:
                        # Clear conflict if event was previously flagged as conflicted or pending review
                        if evt.has_conflict or evt.conflict_status in ("DETECTED", "ACKNOWLEDGED"):
                            cursor.execute(
                                "UPDATE events SET has_conflict = 0, conflict_status = 'RESOLVED', conflict_reason = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (evt.id,),
                            )
                self.repo.conn.commit()
            except Exception as exc:
                logger.warning("Failed to persist synchronized conflict flags to DB: %s", exc)

        return conflicts

    def scan_and_sync_facility_closures(self) -> Dict[str, Any]:
        """Core domain calculation: inspect active resource closures and synchronize conflict flags across events."""
        closures = self.place_repo.list_closures() if self.place_repo else []
        conflicts = self.evaluate_all_conflicts(persist_sync=True)
        closure_names = [f"{c.resource_name} ({c.reason or 'Closed'})" for c in closures]
        if closures:
            summary = (
                f"Facility schedule scan complete: verified {len(closures)} active resource closure(s): "
                f"{'; '.join(closure_names)}. Synchronized {len(conflicts)} calendar conflict(s)."
            )
        else:
            summary = "Facility schedule scan complete: no active closures found. Schedule is conflict-free."

        return {
            "scanned_count": len(closures),
            "created_count": len(conflicts),
            "closures": [c.model_dump() for c in closures],
            "conflicts": [c.model_dump() for c in conflicts],
            "summary_message": summary,
        }

    def check_event_conflict(
        self,
        scheduled_at: datetime,
        duration_minutes: int = 60,
        title: str = "Proposed Event",
        people_involved: Optional[List[str]] = None,
        place_id: Optional[str] = None,
        notes: Optional[str] = None,
        exclude_event_id: Optional[str] = None,
    ) -> List[Conflict]:
        """Dry-run pre-flight conflict check for proposed or updated event timing and attendees."""
        if not self.conflict_engine:
            return []

        draft_id = exclude_event_id or "draft_check"
        scheduled_end_at = scheduled_at + timedelta(minutes=duration_minutes)

        place = None
        if place_id:
            if self.place_repo:
                place = self.place_repo.get_place(place_id)
            elif self.repo and hasattr(self.repo, "conn") and self.repo.conn:
                cursor = self.repo.conn.cursor()
                row = cursor.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
                if row:
                    place = Place(**dict(row))

        draft_event = LifeEvent(
            id=draft_id,
            title=title or "Proposed Event",
            event_type="CUSTOM",
            scheduled_at=scheduled_at,
            scheduled_end_at=scheduled_end_at,
            place_id=place_id,
            place=place,
            people_involved=people_involved or [],
            notes=notes,
        )

        all_upcoming = self.repo.list_events(status="upcoming", limit=200)
        other_events = [e for e in all_upcoming if e.id != exclude_event_id]

        conflicts = self.conflict_engine.detect_conflicts(other_events + [draft_event])
        relevant = [
            c for c in conflicts
            if c.event_id == draft_id
            or (draft_event.title and draft_event.title.lower() in c.description.lower())
            or (c.conflict_type == "PERSON_OVERLAP" and any(p in c.title or p in c.description for p in (people_involved or [])))
        ]
        return relevant

    def acknowledge_conflict(self, conflict_id: str) -> Optional[Dict[str, Any]]:
        """Acknowledge an active conflict and retain the conflicting event on schedule."""
        conflicts = self.evaluate_all_conflicts()
        target = next((c for c in conflicts if c.id == conflict_id), None)
        if not target:
            return None

        cursor = self.repo.conn.cursor()
        cursor.execute(
            "UPDATE events SET conflict_status = 'ACKNOWLEDGED', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (target.event_id,),
        )
        self.repo.conn.commit()
        return {
            "status": "ACKNOWLEDGED",
            "conflict_id": conflict_id,
            "event_id": target.event_id,
            "message": f"Conflict '{target.title}' acknowledged.",
        }

    def reschedule_conflict(self, conflict_id: str) -> Optional[Dict[str, Any]]:
        """Resolve a conflict by marking it rescheduled on the ledger."""
        conflicts = self.evaluate_all_conflicts()
        target = next((c for c in conflicts if c.id == conflict_id), None)
        if not target:
            return None

        cursor = self.repo.conn.cursor()
        cursor.execute(
            "UPDATE events SET has_conflict = 0, conflict_status = 'RESOLVED', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (target.event_id,),
        )
        self.repo.conn.commit()
        return {
            "status": "RESOLVED",
            "conflict_id": conflict_id,
            "event_id": target.event_id,
            "message": "Event rescheduled! Conflict resolved.",
        }

    def get_morning_briefing(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Assemble the daily morning briefing summary, advisories, and event counts."""
        ref_date = target_date or date.today()
        today_str = ref_date.isoformat()
        events = self.repo.list_events(status="upcoming", limit=50)

        today_events = [e for e in events if e.scheduled_at and e.scheduled_at.date().isoformat() == today_str]
        deadlines = [e for e in events if e.deadline and not e.completed_at]

        return {
            "date": today_str,
            "day_of_week": ref_date.strftime("%A"),
            "weather": {
                "temperature_f": 52,
                "condition": "Partly Cloudy",
                "high_f": 58,
                "low_f": 42,
                "location": "Cranberry Township, PA",
            },
            "advisory": {
                "title": "YMCA Pool Advisory",
                "message": "Warm Water Pool reserved for Aerobics until 5:00 PM. Open Family Swim starts at 5:00 PM.",
                "category": "FACILITY",
            },
            "pool_notice": {
                "title": "YMCA Pool Advisory",
                "message": "Warm Water Pool reserved for Aerobics until 5:00 PM. Open Family Swim starts at 5:00 PM.",
                "category": "FACILITY",
            },
            "summary": {
                "upcoming_events_today_count": len(today_events),
                "upcoming_deadlines_count": len(deadlines),
            },
        }

    def complete_event(
        self,
        event_id: str,
        completed_at: Optional[datetime] = None,
        total_amount: Optional[float] = None,
    ) -> Optional[LifeEvent]:
        """Mark an upcoming scheduled event as completed/fulfilled."""
        event = self.repo.get_event(event_id)
        if not event:
            return None

        event.completed_at = completed_at or datetime.now()
        cursor = self.repo.conn.cursor()
        cursor.execute(
            """
            UPDATE events 
            SET completed_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                event.completed_at.isoformat() if event.completed_at else None,
                event.id,
            ),
        )
        if total_amount is not None:
            if event.event_type == "DINING":
                cursor.execute(
                    """
                    INSERT INTO dining_details (event_id, event_type, total_amount)
                    VALUES (?, 'DINING', ?)
                    ON CONFLICT(event_id) DO UPDATE SET total_amount = excluded.total_amount
                    """,
                    (event.id, total_amount),
                )
            elif event.event_type == "SHOPPING":
                cursor.execute(
                    """
                    INSERT INTO shopping_details (event_id, event_type, total_amount)
                    VALUES (?, 'SHOPPING', ?)
                    ON CONFLICT(event_id) DO UPDATE SET total_amount = excluded.total_amount
                    """,
                    (event.id, total_amount),
                )
        self.repo.conn.commit()
        return self.get_event(event_id)

    def uncomplete_event(self, event_id: str) -> Optional[LifeEvent]:
        """Mark an event as incomplete / reopen by clearing completed_at."""
        event = self.get_event(event_id)
        if not event:
            return None

        event.completed_at = None
        cursor = self.repo.conn.cursor()
        cursor.execute(
            """
            UPDATE events 
            SET completed_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (event.id,),
        )
        self.repo.conn.commit()
        try:
            self.evaluate_all_conflicts()
        except Exception:
            pass
        return self.get_event(event_id)

    @staticmethod
    def calculate_urgency_badge(event: LifeEvent, reference_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Calculate urgency badge data based on deadline proximity."""
        if not event.deadline:
            return None

        now = reference_time or datetime.now()
        diff = event.deadline - now
        diff_days = diff.days if diff.days >= 0 else -abs(diff.days) - 1

        if diff_days < 0:
            return {
                "status": "OVERDUE",
                "days_left": diff_days,
                "label": f"⚠️ Overdue ({abs(diff_days)}d)",
                "color": "red",
                "urgency_score": 100,
            }
        elif diff_days == 0:
            return {
                "status": "DUE_TODAY",
                "days_left": 0,
                "label": "🔥 Due Today",
                "color": "orange",
                "urgency_score": 90,
            }
        elif diff_days <= 3:
            return {
                "status": "CRITICAL",
                "days_left": diff_days,
                "label": f"⏳ {diff_days}d left",
                "color": "yellow",
                "urgency_score": 75,
            }
        elif diff_days <= 7:
            return {
                "status": "UPCOMING_WEEK",
                "days_left": diff_days,
                "label": f"📅 {diff_days}d left (This Week)",
                "color": "teal",
                "urgency_score": 50,
            }
        else:
            return {
                "status": "SCHEDULED",
                "days_left": diff_days,
                "label": f"⏰ Due {event.deadline.strftime('%b %d')}",
                "color": "gray",
                "urgency_score": 10,
            }

    def update_event(self, event_id: str, **fields) -> Optional[LifeEvent]:
        """Update fields on an existing event."""
        event = self.repo.get_event(event_id)
        if not event:
            return None

        for k, v in fields.items():
            if hasattr(event, k):
                if k == "completed_at":
                    setattr(event, k, v)
                elif v is not None:
                    setattr(event, k, v)

        if "scheduled_at" in fields or "duration_minutes" in fields:
            if event.scheduled_at and fields.get("duration_minutes"):
                from datetime import timedelta
                event.scheduled_end_at = event.scheduled_at + timedelta(minutes=fields["duration_minutes"])

        updated = self.repo.update_event(event)
        try:
            self.evaluate_all_conflicts()
        except Exception:
            pass
        return updated

    def delete_event(self, event_id: str) -> bool:
        """Event deletion is strictly disallowed to preserve ledger tractability and auditability."""
        logger.warning(
            "Attempted hard deletion of event '%s' rejected: deletion disabled for tractability.", event_id
        )
        raise ValueError("Event deletion is disallowed to preserve ledger tractability and auditability.")

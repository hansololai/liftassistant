"""Conflict Engine Service.
Detects scheduling clashes:
1. Facility Mutex (e.g. YMCA Warm Water Pool occupied / closed)
2. Travel Buffer violations (e.g. drive time exceeds gap between consecutive events)
3. Person Overlap (e.g. double-booking family members)
"""

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from liftassistant.models.domain import Conflict, LifeEvent
from liftassistant.services.facility_provider import (
    BaseFacilityProvider,
    OccupiedWindow,
    YmcaScheduleProvider,
)

logger = logging.getLogger(__name__)


# Standard travel time lookup between known family hubs (in minutes)
KNOWN_DRIVE_TIMES_MINUTES: Dict[Tuple[str, str], int] = {
    ("pediatrician_north_hills", "cranberry_park"): 26,
    ("cranberry_park", "pediatrician_north_hills"): 26,
    ("ymca_cranberry", "seneca_high"): 18,
    ("seneca_high", "ymca_cranberry"): 18,
    ("costco_cranberry", "home_cranberry"): 12,
}

AQUATIC_KEYWORDS = ["swim", "swimming", "pool", "water", "aqua", "open swim", "lap"]


class ConflictEngine:
    """Engine for multi-dimensional calendar conflict detection."""

    def __init__(
        self,
        default_travel_buffer_minutes: int = 15,
        facility_provider: Optional[BaseFacilityProvider] = None,
        place_repo: Optional[Any] = None,
    ):
        self.default_travel_buffer_minutes = default_travel_buffer_minutes
        self.facility_provider = facility_provider or YmcaScheduleProvider()
        self.place_repo = place_repo

    def detect_conflicts(self, events: List[LifeEvent]) -> List[Conflict]:
        """Run all conflict detection strategies on a list of scheduled events."""
        conflicts: List[Conflict] = []

        # 1. Facility Mutex Checks (Resource Closures table + Live API provider)
        conflicts.extend(self._check_facility_mutex(events))

        # 2. Person Overlap Checks
        conflicts.extend(self._check_person_overlap(events))

        # 3. Travel Buffer Checks
        conflicts.extend(self._check_travel_buffers(events))

        return conflicts

    def _check_facility_mutex(self, events: List[LifeEvent]) -> List[Conflict]:
        """Detect events conflicting with persistent resource closures (e.g. YMCA Thanksgiving closure)
        or live external facility reservation schedules (e.g. YMCA pools).
        """
        conflicts: List[Conflict] = []

        # Part A: Check recorded resource closures from database (e.g. YMCA Thanksgiving closure)
        if self.place_repo:
            for evt in events:
                if not evt.scheduled_at:
                    continue
                evt_end = evt.scheduled_end_at or (evt.scheduled_at + timedelta(minutes=getattr(evt, "duration_minutes", None) or 60))
                place_name = (evt.place.name if evt.place else (evt.place_id or "")).lower()

                name_hint = "ymca" if ("ymca" in place_name or "ymca" in evt.title.lower()) else (evt.place.name if evt.place else None)
                try:
                    closures = self.place_repo.find_closures_overlapping(
                        start_time=evt.scheduled_at,
                        end_time=evt_end,
                        resource_id=evt.place_id,
                        resource_name=name_hint,
                    )
                    for cl in closures:
                        cfl = Conflict(
                            id=f"cfl_cls_{uuid4().hex[:6]}",
                            event_id=evt.id,
                            event_title=evt.title,
                            conflict_type="FACILITY_MUTEX",
                            severity="CRITICAL",
                            title=f"{cl.resource_name} Closed: {cl.reason or 'Facility Closure'}",
                            description=f"{cl.resource_name} is closed from {cl.start_time.strftime('%Y-%m-%d %I:%M %p')} to {cl.end_time.strftime('%Y-%m-%d %I:%M %p')} ({cl.reason}).",
                            suggested_action=f"Reschedule event outside the {cl.resource_name} closure period.",
                            status="DETECTED",
                        )
                        conflicts.append(cfl)
                except Exception as ex:
                    logger.warning("Error checking resource closures for %s: %s", evt.title, ex)

        if not self.facility_provider:
            return conflicts

        for evt in events:
            if not evt.scheduled_at:
                continue

            evt_end = evt.scheduled_end_at or (evt.scheduled_at + timedelta(minutes=getattr(evt, "duration_minutes", None) or 60))
            facility_text = f"{evt.title} {evt.notes or ''}".lower()
            place_name = (evt.place.name if evt.place else (evt.place_id or "")).lower()

            is_ymca = "ymca" in place_name or "ymca" in evt.title.lower()
            if not is_ymca:
                continue

            # Ensure we ONLY check pool collisions if the activity is swimming / aquatic
            is_aquatic = any(kw in facility_text for kw in AQUATIC_KEYWORDS)
            if not is_aquatic:
                # Event is at YMCA (e.g. Basketball, Weights, Child Watch) but is NOT swimming.
                # Do not check pool blackout!
                continue

            # Determine specific studio filter if mentioned, else check any pool studio
            if "lap pool" in facility_text:
                studio_filter = "Lap Pool"
            elif "warm water" in facility_text or "warm pool" in facility_text:
                studio_filter = "Warm Water Pool"
            else:
                studio_filter = "Pool"

            try:
                occupied_windows = self.facility_provider.get_occupied_windows(
                    target_date=evt.scheduled_at.date(),
                    studio_filter=studio_filter,
                )
            except Exception as e:
                logger.warning("Failed to query live facility provider for %s: %s", evt.title, e)
                occupied_windows = []

            for w in occupied_windows:
                # Check time intersection: max(start1, start2) < min(end1, end2)
                latest_start = max(evt.scheduled_at, w.start_time)
                earliest_end = min(evt_end, w.end_time)

                if latest_start < earliest_end:
                    instr_str = f" with {w.instructor}" if w.instructor else ""
                    cfl = Conflict(
                        id=f"cfl_fac_{uuid4().hex[:6]}",
                        event_id=evt.id,
                        event_title=evt.title,
                        conflict_type="FACILITY_MUTEX",
                        severity="HIGH",
                        title=f"{w.studio} Occupied: {w.activity_name}",
                        description=f"The {w.studio} at YMCA is reserved for '{w.activity_name}'{instr_str} from {w.start_time.strftime('%I:%M %p')} to {w.end_time.strftime('%I:%M %p')}.",
                        suggested_action=f"Reschedule swimming to an open slot before {w.start_time.strftime('%I:%M %p')} or after {w.end_time.strftime('%I:%M %p')}.",
                        status="DETECTED",
                    )
                    conflicts.append(cfl)

        return conflicts

    def _check_person_overlap(self, events: List[LifeEvent]) -> List[Conflict]:
        """Detect when the same person is scheduled for two events simultaneously."""
        conflicts: List[Conflict] = []
        scheduled = [e for e in events if e.scheduled_at and e.scheduled_end_at]

        for i in range(len(scheduled)):
            for j in range(i + 1, len(scheduled)):
                e1 = scheduled[i]
                e2 = scheduled[j]

                # Check shared people
                shared_people = set(e1.people_involved).intersection(set(e2.people_involved))
                if not shared_people:
                    continue

                # Check time intersection: max(start1, start2) < min(end1, end2)
                latest_start = max(e1.scheduled_at, e2.scheduled_at)
                earliest_end = min(e1.scheduled_end_at, e2.scheduled_end_at)

                if latest_start < earliest_end:
                    people_str = ", ".join(shared_people)
                    cfl = Conflict(
                        id=f"cfl_ovl_{uuid4().hex[:6]}",
                        event_id=e2.id,
                        event_title=e2.title,
                        conflict_type="PERSON_OVERLAP",
                        severity="MEDIUM",
                        title=f"{people_str} Double-Booked",
                        description=f"{people_str} is scheduled for both '{e1.title}' and '{e2.title}' simultaneously.",
                        suggested_action=f"Reassign driver or adjust start time of '{e2.title}'.",
                        status="DETECTED",
                    )
                    conflicts.append(cfl)

        return conflicts

    def _check_travel_buffers(self, events: List[LifeEvent]) -> List[Conflict]:
        """Detect consecutive events where the gap is shorter than the required drive time."""
        conflicts: List[Conflict] = []
        scheduled = sorted([e for e in events if e.scheduled_at and e.scheduled_end_at], key=lambda x: x.scheduled_at)

        for i in range(len(scheduled) - 1):
            e1 = scheduled[i]
            e2 = scheduled[i + 1]

            # Only applies if consecutive events share a participant or driver
            shared = set(e1.people_involved).intersection(set(e2.people_involved))
            if not shared:
                continue

            # Gap between e1 end and e2 start
            gap_minutes = (e2.scheduled_at - e1.scheduled_end_at).total_seconds() / 60.0
            if gap_minutes < 0:
                # Already captured by overlap
                continue

            # Calculate required drive time
            p1_key = (e1.place.category if e1.place else "") or (e1.place_id or "")
            p2_key = (e2.place.category if e2.place else "") or (e2.place_id or "")

            # Check known drive times or check if locations are different
            drive_time = 0
            for (src, dest), minutes in KNOWN_DRIVE_TIMES_MINUTES.items():
                if (src in p1_key.lower() or src in e1.title.lower()) and (dest in p2_key.lower() or dest in e2.title.lower()):
                    drive_time = minutes
                    break

            # If different places and drive time found, compare with gap
            if drive_time > 0 and gap_minutes < drive_time:
                cfl = Conflict(
                    id=f"cfl_trv_{uuid4().hex[:6]}",
                    event_id=e2.id,
                    event_title=e2.title,
                    conflict_type="TRAVEL_BUFFER",
                    severity="HIGH",
                    title="Insufficient Travel Buffer",
                    description=(
                        f"Drive from '{e1.title}' to '{e2.title}' takes approximately {drive_time} mins, "
                        f"but scheduled gap is only {int(gap_minutes)} mins."
                    ),
                    suggested_action=f"Delay arrival of '{e2.title}' by {int(drive_time - gap_minutes)} mins.",
                    status="DETECTED",
                )
                conflicts.append(cfl)

        return conflicts

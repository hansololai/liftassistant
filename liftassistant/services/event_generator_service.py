"""Event Generator Service.
Evaluates recurring annual/monthly calendar rules, determines advance lead times,
and automatically generates events with calculated deadlines.
"""

from datetime import date, datetime, time, timedelta
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from liftassistant.db.repository import EventGeneratorRepository, EventRepository
from liftassistant.models.domain import EventGenerator, LifeEvent

logger = logging.getLogger(__name__)


class EventGeneratorService:
    """Service to process recurring generators and spawn events with automatic deadlines."""

    def __init__(
        self,
        generator_repo: EventGeneratorRepository,
        event_repo: EventRepository,
    ):
        self.generator_repo = generator_repo
        self.event_repo = event_repo

    def get_next_target_date(self, gen: EventGenerator, reference_date: date) -> date:
        """Calculate the next target execution date for a generator relative to reference_date."""
        year = reference_date.year

        if gen.frequency == "YEARLY":
            target_month = gen.by_month or gen.anchor_date.month
            target_day = gen.by_month_day or gen.anchor_date.day

            candidate = date(year, target_month, target_day)
            # If candidate date has already passed for this year, advance to next year
            if candidate < reference_date:
                candidate = date(year + 1, target_month, target_day)
            return candidate

        elif gen.frequency == "MONTHLY":
            target_day = gen.by_month_day or gen.anchor_date.day
            month = reference_date.month
            try:
                candidate = date(year, month, target_day)
            except ValueError:
                # Handle month with fewer days (e.g. Feb 30 -> Feb 28)
                candidate = date(year, month, 28)

            if candidate < reference_date:
                # Advance month
                if month == 12:
                    candidate = date(year + 1, 1, min(target_day, 31))
                else:
                    candidate = date(year, month + 1, min(target_day, 28))
            return candidate

        elif gen.frequency in ("WEEKLY", "BI_WEEKLY"):
            interval_days = 14 if gen.frequency == "BI_WEEKLY" else 7
            if gen.by_weekday:
                weekday_map = {
                    "MO": 0, "MONDAY": 0, "TU": 1, "TUESDAY": 1,
                    "WE": 2, "WEDNESDAY": 2, "TH": 3, "THURSDAY": 3,
                    "FR": 4, "FRIDAY": 4, "SA": 5, "SATURDAY": 5,
                    "SU": 6, "SUNDAY": 6,
                }
                target_w = weekday_map.get(str(gen.by_weekday).upper().strip())
                if target_w is not None:
                    days_ahead = (target_w - reference_date.weekday()) % 7
                    if days_ahead == 0 and gen.last_generated_date == reference_date:
                        days_ahead = interval_days
                    return reference_date + timedelta(days=days_ahead)
            return reference_date + timedelta(days=interval_days)

        # Fallback to anchor date plus interval
        return gen.anchor_date + timedelta(days=gen.interval * 30)

    def should_generate(self, gen: EventGenerator, reference_date: date) -> bool:
        """Determine if a generator should spawn an event based on its lead time window."""
        if not gen.is_active:
            return False

        target_date = self.get_next_target_date(gen, reference_date)
        spawn_threshold_date = target_date - timedelta(days=gen.lead_time_days)

        # In spawn window if reference_date is on or after threshold date
        if reference_date >= spawn_threshold_date:
            # Check if already generated for this target cycle
            if gen.last_generated_date:
                # If generated recently within lead_time_days, avoid duplicate
                if (reference_date - gen.last_generated_date).days < max(gen.lead_time_days, 1):
                    return False
            return True

        return False

    def spawn_event(self, gen: EventGenerator, reference_date: date) -> LifeEvent:
        """Instantiate and persist a new LifeEvent from an EventGenerator with deadline."""
        target_date = self.get_next_target_date(gen, reference_date)

        # Scheduled time: defaults to generator start_time or 09:00 AM on target date
        start_parts = [int(p) for p in (getattr(gen, 'start_time', '09:00') or '09:00').split(':')]
        scheduled_at = datetime.combine(
            target_date,
            time(start_parts[0], start_parts[1], start_parts[2] if len(start_parts) > 2 else 0),
        )
        scheduled_end_at = scheduled_at + timedelta(minutes=gen.duration_minutes)

        # Deadline calculation: target date + deadline_offset_days at deadline_time
        deadline_date = target_date + timedelta(days=gen.deadline_offset_days)
        deadline_time_parts = [int(p) for p in gen.deadline_time.split(":")]
        deadline_dt = datetime.combine(
            deadline_date,
            time(deadline_time_parts[0], deadline_time_parts[1], deadline_time_parts[2]),
        )

        event = LifeEvent(
            id=f"evt_gen_{uuid4().hex[:8]}",
            title=gen.title,
            event_type=gen.event_type,
            scheduled_at=scheduled_at,
            scheduled_end_at=scheduled_end_at,
            deadline=deadline_dt,
            place_id=gen.place_id,
            people_involved=list(gen.people_involved),
            notes=f"Auto-generated from recurring rule '{gen.title}'. {gen.notes or ''}".strip(),
            source="EVENT_GENERATOR",
            source_reference_id=gen.id,
        )

        saved_event = self.event_repo.create_event(event)

        # Update last_generated_date on the generator
        gen.last_generated_date = reference_date
        cursor = self.generator_repo.conn.cursor()
        cursor.execute(
            "UPDATE event_generators SET last_generated_date = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (reference_date.isoformat(), gen.id),
        )
        self.generator_repo.conn.commit()

        logger.info(
            "Spawned event '%s' (due %s) from generator '%s'",
            event.title,
            deadline_dt.isoformat(),
            gen.title,
        )
        return saved_event

    def evaluate_and_spawn_all(self, reference_date: Optional[date] = None) -> List[LifeEvent]:
        """Evaluate all active generators and spawn due events."""
        result = self.evaluate_and_spawn_due_rules(reference_date)
        return result["events"]

    def evaluate_and_spawn_due_rules(
        self, reference_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Core domain calculation: evaluate active recurring rules within lead_time_days and spawn due events."""
        ref = reference_date or date.today()
        generators = self.generator_repo.list_generators(active_only=True)
        spawned: List[LifeEvent] = []

        for gen in generators:
            if self.should_generate(gen, ref):
                event = self.spawn_event(gen, ref)
                spawned.append(event)

        if spawned:
            event_titles = ", ".join([f"'{e.title}'" for e in spawned])
            summary_message = (
                f"Evaluated {len(generators)} recurring calendar rule(s). "
                f"Spawned {len(spawned)} due event(s) ({event_titles}) with advance notice deadlines."
            )
        else:
            summary_message = (
                f"Evaluated {len(generators)} recurring calendar rule(s). "
                f"No upcoming rules due within their lead-time window."
            )

        return {
            "scanned_count": len(generators),
            "created_count": len(spawned),
            "events": spawned,
            "summary_message": summary_message,
        }

    def list_generators(self, active_only: bool = True) -> List[EventGenerator]:
        """List configured recurring event generators."""
        return self.generator_repo.list_generators(active_only=active_only)

    def create_generator(
        self,
        name: str,
        event_type: str = "CUSTOM",
        recurrence_rule: Optional[str] = None,
        recurrence_cycle: Optional[str] = None,
        target_month: Optional[int] = None,
        target_day: Optional[int] = None,
        target_weekday: Optional[int] = None,
        start_time: Optional[str] = None,
        default_start_time: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        default_duration_minutes: Optional[int] = None,
        lead_time_days: int = 14,
        deadline_offset_days: int = 0,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and persist a new recurring event generator rule."""
        if not name or not name.strip():
            raise ValueError("Generator name cannot be empty.")

        frequency = recurrence_cycle or recurrence_rule or "YEARLY"
        resolved_start_time = start_time or default_start_time or "09:00"
        duration = (
            duration_minutes
            if duration_minutes is not None
            else (default_duration_minutes if default_duration_minutes is not None else 60)
        )
        if duration <= 0:
            raise ValueError("Generator duration_minutes must be positive.")

        gen = EventGenerator(
            title=name.strip(),
            event_type=event_type,
            frequency=frequency,
            by_month=target_month,
            by_month_day=target_day,
            by_weekday=str(target_weekday) if target_weekday is not None else None,
            anchor_date=date.today(),
            lead_time_days=lead_time_days,
            deadline_offset_days=deadline_offset_days,
            start_time=resolved_start_time,
            duration_minutes=duration,
            notes=description,
        )
        saved = self.generator_repo.create_generator(gen)
        data = saved.model_dump()
        data["recurrence_cycle"] = saved.frequency
        data["target_weekday"] = int(saved.by_weekday) if saved.by_weekday and saved.by_weekday.isdigit() else None
        return data

    def spawn_event_by_id(
        self, gen_id: str, reference_date: Optional[date] = None
    ) -> Optional[LifeEvent]:
        """Find a generator by ID and force-spawn its next LifeEvent."""
        generators = self.generator_repo.list_generators()
        gen = next((g for g in generators if g.id == gen_id), None)
        if not gen:
            return None
        return self.spawn_event(gen, reference_date=reference_date or date.today())

"""Event Generators API Router for periodic obligations with deadlines
and autonomous Email Event Perception with user review feedback & prompt learning.
"""

from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from liftassistant.api.deps import (
    get_db_connection,
    get_event_gen_service,
    get_event_manager,
    get_event_repo,
    get_gen_run_repo,
    get_place_repo,
)
from liftassistant.db.repository import EventRepository, GeneratorRunRepository, PlaceRepository
from liftassistant.models.domain import GeneratorRun, LearnedPromptRule
from liftassistant.services.event_manager import EventManager
from liftassistant.services.daily_workers import (
    WORKER_TYPE_CALENDAR_RULES,
    WORKER_TYPE_EMAIL_EVENT,
    WORKER_TYPE_FACILITY_CLOSURE,
    WORKER_TYPE_INVENTORY_DEPLETION,
    get_master_daily_worker,
)
from liftassistant.services.email_event_generator import EXTRACTION_SYSTEM_PROMPT
from liftassistant.services.event_generator_service import EventGeneratorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generators", tags=["Generators"])


class GeneratorCreateRequest(BaseModel):
    name: str
    event_type: str = "CUSTOM"
    recurrence_rule: Optional[str] = None
    recurrence_cycle: Optional[str] = None
    target_month: Optional[int] = None
    target_day: Optional[int] = None
    target_weekday: Optional[int] = None
    start_time: Optional[str] = None
    default_start_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    default_duration_minutes: Optional[int] = None
    lead_time_days: int = 14
    deadline_offset_days: int = 0
    description: Optional[str] = None


class FeedbackActionRequest(BaseModel):
    event_id: str
    status: str  # 'ACCEPTED', 'MODIFIED', 'REMOVED'
    user_correction_reason: Optional[str] = None
    modified_title: Optional[str] = None
    modified_scheduled_at: Optional[str] = None
    modified_amount: Optional[float] = None
    run_id: Optional[str] = None
    feedback_id: Optional[str] = None


class RuleCreateRequest(BaseModel):
    user_feedback: str
    prompt_instruction: str
    rule_type: str = "NEGATIVE"  # 'NEGATIVE', 'POSITIVE', 'GENERAL'


@router.get("")
def list_generators(gen_service: EventGeneratorService = Depends(get_event_gen_service)):
    """Fetch all configured recurring event generators."""
    generators = gen_service.list_generators()
    return [g.model_dump() for g in generators]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_generator(
    payload: GeneratorCreateRequest,
    gen_service: EventGeneratorService = Depends(get_event_gen_service),
):
    """Validate payload and delegate recurring generator creation to EventGeneratorService."""
    try:
        return gen_service.create_generator(**payload.model_dump())
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post("/{gen_id}/spawn", status_code=status.HTTP_201_CREATED)
def spawn_from_generator(
    gen_id: str,
    gen_service: EventGeneratorService = Depends(get_event_gen_service),
):
    """Force-spawn a LifeEvent from a generator rule via EventGeneratorService."""
    spawned_event = gen_service.spawn_event_by_id(gen_id)
    if not spawned_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generator '{gen_id}' not found.",
        )
    return spawned_event.model_dump()


# =========================================================================
# EMAIL EVENT GENERATOR: WORKER RUNS, AUDIT, FEEDBACK & PROMPT LEARNING
# =========================================================================

# =========================================================================
# MASTER DAILY ORCHESTRATOR & SUB-WORKER EXECUTION ENDPOINTS
# =========================================================================

@router.get("/master/status")
@router.get("/email/worker")
def get_master_worker_status():
    """Return status and schedule info for the master daily orchestrator and all sub-workers."""
    master = get_master_daily_worker()
    return master.get_status()


@router.post("/master/run")
def trigger_master_daily_run():
    """Trigger the full daily perception pipeline across all 4 sub-workers asynchronously."""
    master = get_master_daily_worker()
    return master.run_all_async(run_type="MANUAL")


@router.post("/master/retry-failed")
def trigger_master_retry_failed():
    """Selectively retry only the sub-workers that failed in their latest run."""
    master = get_master_daily_worker()
    return master.retry_failed()


@router.post("/rules/run")
@router.post("/calendar-rules/run")
def trigger_calendar_rules_worker_run():
    """Trigger thin CalendarRuleWorker to evaluate recurring rules asynchronously."""
    master = get_master_daily_worker()
    run = master.calendar_worker.trigger_run_async(run_type="MANUAL")
    return {
        "run": run.model_dump(),
        "summary_message": "Calendar rules evaluation started in background.",
    }


@router.post("/email/run")
def trigger_email_worker_run(max_results: int = 25):
    """Trigger thin EmailEventWorker to perceive incoming emails asynchronously."""
    master = get_master_daily_worker()
    run = master.email_worker.trigger_run_async(run_type="MANUAL", max_results=max_results)
    return {
        "run": run.model_dump(),
        "summary_message": "Email perception sync started in background.",
    }


@router.post("/facility/run")
def trigger_facility_worker_run():
    """Trigger thin FacilityClosureWorker to check blackout windows asynchronously."""
    master = get_master_daily_worker()
    run = master.facility_worker.trigger_run_async(run_type="MANUAL")
    return {
        "run": run.model_dump(),
        "summary_message": "Facility closure verification started in background.",
        "events": [],
    }


@router.post("/depletion/run")
def trigger_depletion_worker_run():
    """Trigger thin InventoryDepletionWorker to calculate stock runway asynchronously."""
    master = get_master_daily_worker()
    run = master.depletion_worker.trigger_run_async(run_type="MANUAL")
    return {
        "run": run.model_dump(),
        "summary_message": "Pantry depletion analysis started in background.",
        "events": [],
    }


@router.get("/runs")
def list_all_generator_runs(
    generator_type: Optional[str] = None,
    limit: int = 50,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
    event_repo: EventRepository = Depends(get_event_repo),
):
    """Fetch history of generator execution runs across workers with generated event references."""
    # Map legacy aliases
    alias_map = {
        "EMAIL_EVENT_GENERATOR": WORKER_TYPE_EMAIL_EVENT,
        "FACILITY_WORKER": WORKER_TYPE_FACILITY_CLOSURE,
        "DEPLETION_WORKER": WORKER_TYPE_INVENTORY_DEPLETION,
    }
    resolved_type = alias_map.get(generator_type, generator_type) if generator_type else None
    runs = gen_run_repo.list_runs(generator_type=resolved_type, limit=limit)
    # Also fetch legacy types if querying all or specific legacy
    if not runs and generator_type:
        runs = gen_run_repo.list_runs(generator_type=generator_type, limit=limit)

    # Handle direct function invocations in unit tests without FastAPI DI
    if hasattr(event_repo, "dependency") or not hasattr(event_repo, "list_events_by_run_id"):
        event_repo = EventRepository(gen_run_repo.conn) if hasattr(gen_run_repo, "conn") else None

    output = []
    for r in runs:
        item = r.model_dump()
        event_ids: List[str] = []
        generated_events: List[Dict[str, Any]] = []

        if r.details_json:
            try:
                parsed = json.loads(r.details_json)
                event_ids = parsed.get("event_ids") or parsed.get("spawned_events") or []
                generated_events = parsed.get("generated_events") or []
            except Exception:
                pass

        # If not present in details_json, look up directly via event_repo by generator_run_id
        if not event_ids and r.id:
            db_events = event_repo.list_events_by_run_id(r.id)
            if db_events:
                event_ids = [e.id for e in db_events]
                generated_events = [
                    {
                        "id": e.id,
                        "title": e.title,
                        "event_type": e.event_type,
                        "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
                        "deadline": e.deadline.isoformat() if e.deadline else None,
                        "notes": e.notes,
                    }
                    for e in db_events
                ]

        item["event_ids"] = event_ids
        item["generated_events"] = generated_events
        output.append(item)

    return output


@router.get("/runs/{run_id}")
def get_generator_run_result(
    run_id: str,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
    event_repo: EventRepository = Depends(get_event_repo),
):
    """Get detailed outcome of a specific worker execution run:
    - Returns full list of generated events with LLM perception reasoning and direct event link.
    """
    run = gen_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    # Handle direct function invocations in unit tests without FastAPI DI
    if hasattr(event_repo, "dependency") or not hasattr(event_repo, "list_events_by_run_id"):
        event_repo = EventRepository(gen_run_repo.conn) if hasattr(gen_run_repo, "conn") else None

    feedbacks = gen_run_repo.get_run_feedbacks(run_id)
    db_events = event_repo.list_events_by_run_id(run_id) if event_repo else []

    summary_message = ""
    details: Dict[str, Any] = {}
    if run.details_json:
        try:
            details = json.loads(run.details_json)
            summary_message = details.get("summary_message", "")
        except Exception:
            pass

    if not summary_message or (run.generator_type in (WORKER_TYPE_EMAIL_EVENT, "EMAIL_EVENT_GENERATOR") and "pre-filtered" not in summary_message):
        if run.generator_type in (WORKER_TYPE_EMAIL_EVENT, "EMAIL_EVENT_GENERATOR"):
            evaluated_count = len(feedbacks)
            existing_count = sum(1 for fb in feedbacks if fb.llm_category == "EXISTING")
            prefiltered_count = max(0, run.scanned_count - evaluated_count)
            existing_clause = f" ({existing_count} already created in prior run)" if existing_count > 0 else ""
            summary_message = (
                f"Scanned {run.scanned_count} emails from Gmail: "
                f"{prefiltered_count} non-transactional pre-filtered, {evaluated_count} evaluated by AI{existing_clause}. "
                f"Generated {run.created_count} new events into the life ledger."
            )
        elif run.generator_type in (WORKER_TYPE_CALENDAR_RULES, "CALENDAR_RULE_GENERATOR"):
            summary_message = (
                f"Evaluated {run.scanned_count} recurring calendar rule(s). "
                f"Spawned {run.created_count} due event(s) into calendar ledger."
            )
        elif run.generator_type in (WORKER_TYPE_INVENTORY_DEPLETION, "DEPLETION_WORKER"):
            summary_message = details.get("message") or (
                f"Inventory runway evaluation complete: scanned {run.scanned_count} pantry items. "
                f"{run.created_count} items below 7-day runway flagged for restock."
            )
        elif run.generator_type in (WORKER_TYPE_FACILITY_CLOSURE, "FACILITY_WORKER"):
            summary_message = details.get("summary_message") or details.get("message") or (
                f"Facility schedule scan complete: verified active blackout windows. "
                f"{run.created_count} closures recorded; conflict flags synchronized."
            )

    # Format full generated events list for traceability
    generated_events_list = []
    seen_event_ids = set()

    for e in db_events:
        seen_event_ids.add(e.id)
        # Find matching feedback if any
        matching_fb = next((f for f in feedbacks if f.event_id == e.id), None)
        total_amt = None
        if e.shopping_detail:
            total_amt = e.shopping_detail.total_amount
        elif e.dining_detail:
            total_amt = e.dining_detail.total_amount

        generated_events_list.append({
            "id": e.id,
            "title": e.title,
            "event_type": e.event_type,
            "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
            "deadline": e.deadline.isoformat() if e.deadline else None,
            "total_amount": total_amt,
            "source": e.source,
            "source_reference_id": e.source_reference_id,
            "notes": e.notes,
            "llm_category": matching_fb.llm_category if matching_fb else None,
            "llm_reason": matching_fb.llm_reason if matching_fb else None,
            "user_status": matching_fb.user_status if matching_fb else "ACCEPTED",
        })

    # Also include any valid events from feedback that weren't directly captured in db_events (must start with evt_)
    # Strictly exclude skipped non-events, promotional emails, removed items, or events already created in a previous run
    existing_events_list = []
    for fb in feedbacks:
        if fb.llm_category == "EXISTING" and fb.event_id:
            ev = event_repo.get_event(fb.event_id) if event_repo else None
            orig_run_id = ev.generator_run_id if ev and ev.generator_run_id else None
            orig_run_time = None
            if not orig_run_id and gen_run_repo and hasattr(gen_run_repo, "conn") and gen_run_repo.conn:
                orig_fb = gen_run_repo.conn.cursor().execute(
                    "SELECT run_id, created_at FROM generator_event_feedback WHERE event_id = ? AND llm_category != 'EXISTING' ORDER BY created_at ASC LIMIT 1",
                    (fb.event_id,)
                ).fetchone()
                if orig_fb:
                    orig_run_id = orig_fb[0]
                    orig_run_time = str(orig_fb[1])

            if orig_run_id and gen_run_repo:
                orig_run = gen_run_repo.get_run(orig_run_id)
                if orig_run and orig_run.started_at:
                    orig_run_time = orig_run.started_at.isoformat()

            ev_type = (ev.event_type if ev else None) or fb.event_type or "CUSTOM"
            ex_amt = (
                ev.shopping_detail.total_amount
                if ev and ev.shopping_detail
                else (ev.dining_detail.total_amount if ev and ev.dining_detail else (fb.total_amount or 0.0))
            )
            existing_events_list.append({
                "id": fb.event_id,
                "title": (ev.title if ev else None) or fb.event_title or fb.email_subject or "Existing Event",
                "event_type": ev_type,
                "scheduled_at": ev.scheduled_at.isoformat() if ev and ev.scheduled_at else (fb.scheduled_at.isoformat() if hasattr(fb.scheduled_at, 'isoformat') else str(fb.scheduled_at) if fb.scheduled_at else None),
                "completed_at": ev.completed_at.isoformat() if ev and ev.completed_at else None,
                "deadline": ev.deadline.isoformat() if ev and ev.deadline else (fb.deadline.isoformat() if hasattr(fb.deadline, 'isoformat') else str(fb.deadline) if fb.deadline else None),
                "total_amount": ex_amt,
                "dining_details": {"total_amount": ex_amt, "rating": 5} if ev_type == "DINING" else (ev.dining_detail.model_dump() if ev and ev.dining_detail else None),
                "shopping_details": {"total_amount": ex_amt, "pantry_updated": False} if ev_type == "SHOPPING" else (ev.shopping_detail.model_dump() if ev and ev.shopping_detail else None),
                "source": (ev.source if ev else None) or "AGENT_GMAIL",
                "source_reference_id": fb.source_reference_id,
                "originating_run_id": orig_run_id,
                "originating_run_time": orig_run_time,
                "notes": ev.notes if ev else None,
                "llm_category": "EXISTING",
                "llm_reason": fb.llm_reason,
                "user_status": "EXISTING",
            })
        elif (
            fb.event_id
            and fb.event_id not in seen_event_ids
            and fb.event_id.startswith("evt_")
            and fb.user_status not in ("SKIPPED", "REMOVED")
            and fb.llm_category not in ("SKIP", "PROMOTION", "EXISTING")
        ):
            seen_event_ids.add(fb.event_id)
            gen_type = fb.event_type or "CUSTOM"
            gen_amt = fb.total_amount or 0.0
            generated_events_list.append({
                "id": fb.event_id,
                "title": fb.event_title or fb.email_subject or "Generated Event",
                "event_type": gen_type,
                "scheduled_at": fb.scheduled_at.isoformat() if hasattr(fb.scheduled_at, 'isoformat') else str(fb.scheduled_at) if fb.scheduled_at else None,
                "deadline": fb.deadline.isoformat() if hasattr(fb.deadline, 'isoformat') else str(fb.deadline) if fb.deadline else None,
                "total_amount": gen_amt,
                "dining_details": {"total_amount": gen_amt, "rating": 5} if gen_type == "DINING" else None,
                "shopping_details": {"total_amount": gen_amt, "pantry_updated": False} if gen_type == "SHOPPING" else None,
                "source": "AGENT_GMAIL",
                "source_reference_id": fb.source_reference_id,
                "notes": fb.user_correction_reason,
                "llm_category": fb.llm_category,
                "llm_reason": fb.llm_reason,
                "user_status": fb.user_status,
            })

    run_dump = run.model_dump()
    run_dump["event_ids"] = list(seen_event_ids)
    run_dump["generated_events"] = generated_events_list
    run_dump["existing_events"] = existing_events_list

    return {
        "run": run_dump,
        "summary_message": summary_message,
        "events": generated_events_list,
        "existing_events": existing_events_list,
        "feedbacks": [f.model_dump() for f in feedbacks],
    }


@router.get("/email/runs")
def list_email_generator_runs(
    limit: int = 50,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Fetch history of daily background and manual email generator execution runs."""
    runs = gen_run_repo.list_runs(generator_type=WORKER_TYPE_EMAIL_EVENT, limit=limit)
    if not runs:
        runs = gen_run_repo.list_runs(generator_type="EMAIL_EVENT_GENERATOR", limit=limit)
    return [r.model_dump() for r in runs]



@router.post("/email/sync")
def trigger_email_generator_sync(max_results: int = 25):
    """Trigger an immediate manual sync run of the Email Event Generator asynchronously."""
    master = get_master_daily_worker()
    run = master.email_worker.trigger_run_async(run_type="MANUAL", max_results=max_results)
    return {
        "run": run.model_dump(),
        "summary_message": "Email perception sync started in background.",
    }


@router.get("/email/events")
def list_generated_email_events(
    limit: int = 100,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """List events extracted by the Email Event Generator with LLM reasons and review statuses."""
    feedbacks = gen_run_repo.list_feedbacks(limit=limit)
    return [fb.model_dump() for fb in feedbacks]


@router.post("/email/feedback")
def submit_email_event_feedback(
    payload: FeedbackActionRequest,
    event_repo: EventRepository = Depends(get_event_repo),
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Accept user feedback on a generated event or facility closure:
    1. If REMOVED: delete the incorrect event from the ledger (or closure from resource_closures).
    2. If MODIFIED: update the event title, time, or amount.
    3. If user_correction_reason is provided: automatically record a new LearnedPromptRule
       that is injected into the LLM system prompt on all subsequent runs.
    """
    clean_status = payload.status.upper()
    if clean_status not in ["ACCEPTED", "MODIFIED", "REMOVED"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be one of: ACCEPTED, MODIFIED, REMOVED",
        )

    # Share the underlying SQLite connection across repositories to prevent pool starvation
    shared_conn = getattr(event_repo, "conn", None) or getattr(gen_run_repo, "conn", None)
    place_repo = PlaceRepository(shared_conn) if shared_conn else None

    # 1. Handle REMOVAL of incorrect event or facility closure
    if clean_status == "REMOVED":
        event_title = None
        target_run_id = payload.run_id

        if payload.event_id and payload.event_id.startswith("cls_"):
            if place_repo:
                place_repo.delete_closure(payload.event_id)
        elif payload.event_id:
            evt = event_repo.get_event(payload.event_id)
            if evt:
                event_title = evt.title
                if not target_run_id and evt.generator_run_id:
                    target_run_id = evt.generator_run_id
                event_repo.delete_event(payload.event_id)

        # Update run stats if applicable
        if target_run_id:
            run = gen_run_repo.get_run(target_run_id)
            if run:
                run.created_count = max(0, run.created_count - 1)
                if run.details_json:
                    try:
                        d = json.loads(run.details_json)
                        d["created_count"] = run.created_count
                        d["summary_message"] = (
                            f"Scanned {run.scanned_count} incoming emails via Gmail API. "
                            f"Generated {run.created_count} events into the life ledger."
                        )
                        run.details_json = json.dumps(d)
                    except Exception:
                        pass
                gen_run_repo.update_run(run)

        # Append what happened to the previous run's feedback record
        user_reason = (payload.user_correction_reason or "").strip()
        event_label = f"'{event_title}'" if event_title else f"'{payload.event_id}'"
        action_note = f"Deleted event {event_label}" + (f" with prompt reason: '{user_reason}'" if user_reason else " by user.")

        gen_run_repo.update_feedback_status(
            event_id=payload.event_id,
            status="REMOVED",
            user_reason=action_note,
            append_reason=True,
            feedback_id=payload.feedback_id,
            run_id=target_run_id,
        )

    # 2. Handle MODIFICATION of event
    elif clean_status == "MODIFIED":
        if payload.event_id and not payload.event_id.startswith("cls_"):
            evt = event_repo.get_event(payload.event_id)
            if evt:
                if payload.modified_title:
                    evt.title = payload.modified_title
                if payload.modified_scheduled_at:
                    try:
                        evt.scheduled_at = datetime.fromisoformat(payload.modified_scheduled_at)
                        evt.scheduled_end_at = evt.scheduled_at
                    except Exception:
                        pass
                event_repo.update_event(evt)
        gen_run_repo.update_feedback_status(
            event_id=payload.event_id,
            status="MODIFIED",
            user_reason=payload.user_correction_reason,
        )

    # 3. Handle ACCEPTANCE
    elif clean_status == "ACCEPTED":
        gen_run_repo.update_feedback_status(
            event_id=payload.event_id,
            status="ACCEPTED",
            user_reason=payload.user_correction_reason,
        )

    # 4. Iterative Prompt Learning: synthesize new learned prompt rule from user reason
    learned_rule = None
    if payload.user_correction_reason and payload.user_correction_reason.strip():
        user_reason = payload.user_correction_reason.strip()
        if clean_status == "REMOVED":
            instruction = f"USER CORRECTION: '{user_reason}'. Do not generate events or receipts for similar emails or promotions."
            rule_type = "NEGATIVE"
        elif clean_status == "MODIFIED":
            instruction = f"USER CORRECTION: '{user_reason}'. Apply this rule when formatting or extracting similar events."
            rule_type = "GENERAL"
        else:
            instruction = f"USER CONFIRMATION: '{user_reason}'."
            rule_type = "POSITIVE"

        rule = LearnedPromptRule(
            generator_type="EMAIL_EVENT_GENERATOR",
            rule_type=rule_type,
            user_feedback=user_reason,
            prompt_instruction=instruction,
            is_active=True,
        )
        learned_rule = gen_run_repo.add_learned_rule(rule)
        logger.info(f"Synthesized and recorded new LearnedPromptRule: {instruction}")

    updated_feedback = gen_run_repo.get_feedback_by_event(payload.event_id)
    return {
        "success": True,
        "status": clean_status,
        "event_id": payload.event_id,
        "feedback": updated_feedback.model_dump() if updated_feedback else None,
        "learned_rule": learned_rule.model_dump() if learned_rule else None,
    }


@router.get("/email/rules")
def list_learned_prompt_rules(
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """List all iteratively learned prompt rules."""
    rules = gen_run_repo.list_learned_rules(generator_type="EMAIL_EVENT_GENERATOR")
    return [r.model_dump() for r in rules]


@router.post("/email/rules", status_code=status.HTTP_201_CREATED)
def create_learned_prompt_rule(
    payload: RuleCreateRequest,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Manually add a prompt rule to guide the LLM."""
    rule = LearnedPromptRule(
        generator_type="EMAIL_EVENT_GENERATOR",
        rule_type=payload.rule_type,
        user_feedback=payload.user_feedback,
        prompt_instruction=payload.prompt_instruction,
        is_active=True,
    )
    saved = gen_run_repo.add_learned_rule(rule)
    return saved.model_dump()


@router.put("/email/rules/{rule_id}/toggle")
def toggle_learned_prompt_rule(
    rule_id: str,
    is_active: bool,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Enable or disable an iteratively learned prompt rule."""
    success = gen_run_repo.toggle_learned_rule(rule_id, is_active)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return {"success": True, "rule_id": rule_id, "is_active": is_active}


@router.delete("/email/rules/{rule_id}")
def delete_learned_prompt_rule(
    rule_id: str,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Delete a learned prompt rule."""
    success = gen_run_repo.delete_learned_rule(rule_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return {"success": True, "rule_id": rule_id}


@router.get("/email/prompt")
def get_effective_email_prompt(
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Return the base prompt plus all dynamically injected active learned rules."""
    active_rules = gen_run_repo.list_learned_rules(
        generator_type="EMAIL_EVENT_GENERATOR", only_active=True
    )
    full_prompt = EXTRACTION_SYSTEM_PROMPT
    if active_rules:
        rules_text = "\n".join(f"- {r.prompt_instruction}" for r in active_rules)
        full_prompt += f"\n\nADDITIONAL USER CORRECTIONS & LEARNED RULES (MANDATORY TO FOLLOW):\n{rules_text}\n"

    return {
        "base_prompt": EXTRACTION_SYSTEM_PROMPT,
        "active_rules_count": len(active_rules),
        "active_rules": [r.model_dump() for r in active_rules],
        "effective_prompt": full_prompt,
    }



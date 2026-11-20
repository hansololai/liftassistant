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
    get_event_gen_service,
    get_event_manager,
    get_event_repo,
    get_gen_run_repo,
    get_place_repo,
)
from liftassistant.db.repository import EventRepository, GeneratorRunRepository
from liftassistant.models.domain import GeneratorRun, LearnedPromptRule
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
    """Trigger the full daily perception pipeline across all 4 sub-workers."""
    master = get_master_daily_worker()
    return master.run_all(run_type="MANUAL")


@router.post("/master/retry-failed")
def trigger_master_retry_failed():
    """Selectively retry only the sub-workers that failed in their latest run."""
    master = get_master_daily_worker()
    return master.retry_failed()


@router.post("/rules/run")
@router.post("/calendar-rules/run")
def trigger_calendar_rules_worker_run():
    """Trigger thin CalendarRuleWorker to evaluate recurring rules and spawn due events."""
    master = get_master_daily_worker()
    run = master.calendar_worker.trigger_run(run_type="MANUAL")
    summary = ""
    if run.details_json:
        try:
            summary = json.loads(run.details_json).get("summary_message", "")
        except Exception:
            pass
    return {
        "run": run.model_dump(),
        "summary_message": summary or f"Evaluated rules; spawned {run.created_count} events.",
    }


@router.post("/email/run")
def trigger_email_worker_run():
    """Trigger thin EmailEventWorker to perceive incoming emails and extract events."""
    master = get_master_daily_worker()
    run = master.email_worker.trigger_run(run_type="MANUAL")
    summary = ""
    if run.details_json:
        try:
            summary = json.loads(run.details_json).get("summary_message", "")
        except Exception:
            pass
    return {
        "run": run.model_dump(),
        "summary_message": summary or f"Scanned {run.scanned_count} emails; generated {run.created_count} events.",
    }


@router.post("/facility/run")
def trigger_facility_worker_run():
    """Trigger thin FacilityClosureWorker to check blackout windows and sync calendar conflicts."""
    master = get_master_daily_worker()
    run = master.facility_worker.trigger_run(run_type="MANUAL")
    summary = ""
    if run.details_json:
        try:
            summary = json.loads(run.details_json).get("summary_message", "")
        except Exception:
            pass
    return {
        "run": run.model_dump(),
        "summary_message": summary or f"Verified {run.scanned_count} closures; synced {run.created_count} conflicts.",
        "events": [],
    }


@router.post("/depletion/run")
def trigger_depletion_worker_run():
    """Trigger thin InventoryDepletionWorker to calculate rolling stock runway."""
    master = get_master_daily_worker()
    run = master.depletion_worker.trigger_run(run_type="MANUAL")
    summary = ""
    if run.details_json:
        try:
            summary = json.loads(run.details_json).get("summary_message", "")
        except Exception:
            pass
    return {
        "run": run.model_dump(),
        "summary_message": summary or f"Evaluated stock; found {run.created_count} items below runway threshold.",
        "events": [],
    }


@router.get("/runs")
def list_all_generator_runs(
    generator_type: Optional[str] = None,
    limit: int = 50,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Fetch history of generator execution runs across workers."""
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
    return [r.model_dump() for r in runs]


@router.get("/runs/{run_id}")
def get_generator_run_result(
    run_id: str,
    gen_run_repo: GeneratorRunRepository = Depends(get_gen_run_repo),
):
    """Get detailed outcome of a specific worker execution run:
    - If Email / Calendar Rules: returns list of generated events with LLM / rule reasoning.
    - If Depletion / Facility: returns summary message.
    """
    run = gen_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    events = gen_run_repo.get_run_feedbacks(run_id)
    summary_message = ""
    details: Dict[str, Any] = {}
    if run.details_json:
        try:
            details = json.loads(run.details_json)
            summary_message = details.get("summary_message", "")
        except Exception:
            pass

    if not summary_message:
        if run.generator_type in (WORKER_TYPE_EMAIL_EVENT, "EMAIL_EVENT_GENERATOR"):
            summary_message = (
                f"Scanned {run.scanned_count} incoming emails via Gmail API. "
                f"Generated {run.created_count} events into the life ledger."
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
            summary_message = details.get("message") or (
                f"Facility schedule scan complete: verified active blackout windows. "
                f"{run.created_count} closures recorded; conflict flags synchronized."
            )

    return {
        "run": run.model_dump(),
        "summary_message": summary_message,
        "events": [e.model_dump() for e in events],
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



@router.post("/email/run")
def trigger_email_generator_run(max_results: int = 25):
    """Trigger an immediate manual sync run of the Email Event Generator."""
    worker = get_email_worker()
    try:
        run = worker.trigger_sync(run_type="MANUAL", max_results=max_results)
        return run.model_dump()
    except RuntimeError as re:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(re))
    except Exception as e:
        logger.exception("Error executing manual email generator run: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
    """Accept user feedback on a generated event:
    1. If REMOVED: delete the incorrect event from the ledger.
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

    # 1. Handle REMOVAL of incorrect event
    if clean_status == "REMOVED":
        event_repo.delete_event(payload.event_id)
        gen_run_repo.update_feedback_status(
            event_id=payload.event_id,
            status="REMOVED",
            user_reason=payload.user_correction_reason,
        )

    # 2. Handle MODIFICATION of event
    elif clean_status == "MODIFIED":
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



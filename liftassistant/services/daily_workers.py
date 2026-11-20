"""Unified Daily Workers and Master Orchestrator Architecture.
Enforces the 'Thin Worker, Rich Core Engine' design:
1. Core engines (EventGeneratorService, EmailEventGenerator, EventManager, InventoryService) contain 100% domain logic.
2. Workers are thin runners responsible for execution lifecycle, locks, DB run logging, and error isolation.
3. MasterDailyWorker coordinates all 4 sub-workers on a daily schedule with individual retry capabilities.
"""

from datetime import datetime, timedelta
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from liftassistant.db.connection import get_db
from liftassistant.db.repository import (
    EventGeneratorRepository,
    EventRepository,
    GeneratorRunRepository,
    InventoryRepository,
    PlaceRepository,
)
from liftassistant.models.domain import GeneratorEventFeedback, GeneratorRun
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.email_event_generator import EmailEventGenerator
from liftassistant.services.event_generator_service import EventGeneratorService
from liftassistant.services.event_manager import EventManager
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.map_service import MapService
from liftassistant.services.receipt_parser import ReceiptParser
from liftassistant.services.receipt_service import ReceiptService

logger = logging.getLogger(__name__)

# Standardized Worker Types
WORKER_TYPE_CALENDAR_RULES = "CALENDAR_RULE_WORKER"
WORKER_TYPE_EMAIL_EVENT = "EMAIL_EVENT_WORKER"
WORKER_TYPE_FACILITY_CLOSURE = "FACILITY_CLOSURE_WORKER"
WORKER_TYPE_INVENTORY_DEPLETION = "INVENTORY_DEPLETION_WORKER"


class CalendarRuleWorker:
    """Thin execution runner for recurring calendar rule evaluations."""

    def __init__(self):
        self._lock = threading.Lock()
        self.worker_type = WORKER_TYPE_CALENDAR_RULES

    def _execute_run(self, run: GeneratorRun, run_type: str = "MANUAL", reference_date=None) -> GeneratorRun:
        """Internal execution runner for rule evaluation."""
        with self._lock:
            with get_db() as conn:
                gen_repo = EventGeneratorRepository(conn)
                event_repo = EventRepository(conn)
                run_repo = GeneratorRunRepository(conn)
                engine = EventGeneratorService(generator_repo=gen_repo, event_repo=event_repo)

                try:
                    # Delegate 100% of domain math to core engine
                    result = engine.evaluate_and_spawn_due_rules(reference_date=reference_date, run_id=run.id)

                    run.status = "SUCCESS"
                    run.completed_at = datetime.now()
                    run.scanned_count = result["scanned_count"]
                    run.created_count = result["created_count"]
                    run.details_json = json.dumps({
                        "run_type": run_type,
                        "summary_message": result["summary_message"],
                        "event_ids": [e.id for e in result["events"]],
                        "generated_events": [
                            {
                                "id": e.id,
                                "title": e.title,
                                "event_type": e.event_type,
                                "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
                                "deadline": e.deadline.isoformat() if e.deadline else None,
                                "notes": e.notes,
                            }
                            for e in result["events"]
                        ],
                    })

                    # Log feedback rows so spawned events are inspectable in the UI outcome modal
                    for evt in result["events"]:
                        feedback = GeneratorEventFeedback(
                            event_id=evt.id,
                            run_id=run.id,
                            source_reference_id=evt.source_reference_id,
                            email_subject=f"Recurring Rule: {evt.title}",
                            email_from="System Calendar Rules",
                            email_date=datetime.now().isoformat(),
                            llm_category="CALENDAR_RULE",
                            llm_reason=evt.notes or "Spawned by advance lead-time window.",
                            raw_json=json.dumps(evt.model_dump(), default=str),
                            user_status="ACCEPTED",
                        )
                        run_repo.create_or_update_feedback(feedback)

                    run_repo.update_run(run)
                    logger.info("CalendarRuleWorker completed: %s", result["summary_message"])
                    return run

                except Exception as exc:
                    logger.error("CalendarRuleWorker failed: %s", exc, exc_info=True)
                    run.status = "FAILED"
                    run.completed_at = datetime.now()
                    run.error_message = str(exc)
                    run.details_json = json.dumps({"run_type": run_type, "summary_message": f"Execution failed: {exc}"})
                    run_repo.update_run(run)
                    raise

    def trigger_run(self, run_type: str = "MANUAL", reference_date=None) -> GeneratorRun:
        """Execute recurring rule evaluation synchronously and log run lifecycle."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type}),
            )
            run_repo.create_run(run)
        return self._execute_run(run, run_type=run_type, reference_date=reference_date)

    def trigger_run_async(self, run_type: str = "MANUAL", reference_date=None) -> GeneratorRun:
        """Immediately record RUNNING in DB and evaluate recurring rules in a background daemon thread."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type, "summary_message": "Evaluating calendar rules in background..."}),
            )
            run_repo.create_run(run)

        def _bg():
            try:
                self._execute_run(run, run_type=run_type, reference_date=reference_date)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True, name=f"{self.worker_type}_async").start()
        return run


class EmailEventWorker:
    """Thin execution runner for Gmail perception and LLM event extraction."""

    def __init__(self):
        self._lock = threading.Lock()
        self.worker_type = WORKER_TYPE_EMAIL_EVENT

    def _execute_run(self, run: GeneratorRun, run_type: str = "MANUAL", max_results: int = 25) -> GeneratorRun:
        """Internal execution runner for email perception and receipt ingestion."""
        with self._lock:
            with get_db() as conn:
                repo = EventRepository(conn)
                place_repo = PlaceRepository(conn)
                conflict_engine = ConflictEngine(place_repo=place_repo)
                map_service = MapService(place_repo=place_repo)
                event_manager = EventManager(
                    event_repo=repo,
                    conflict_engine=conflict_engine,
                    place_repo=place_repo,
                    map_service=map_service,
                )
                run_repo = GeneratorRunRepository(conn)
                inv_service = InventoryService(InventoryRepository(conn))
                receipt_service = ReceiptService(conn=conn, inventory_service=inv_service)
                receipt_parser = ReceiptParser()

                engine = EmailEventGenerator(
                    event_manager=event_manager,
                    receipt_parser=receipt_parser,
                    place_repo=place_repo,
                    cas_storage=CASStorage(),
                    gen_run_repo=run_repo,
                    receipt_service=receipt_service,
                )

                try:
                    # Delegate 100% of perception & extraction to core engine
                    created_events = engine.sync_recent_emails(
                        max_results=max_results,
                        run_id=run.id,
                    )
                    # Refresh run updated by engine
                    refreshed = run_repo.get_run(run.id)
                    if refreshed:
                        run = refreshed
                    summary = (
                        f"Scanned {run.scanned_count} incoming emails via Gmail API. "
                        f"Generated {run.created_count} events into the life ledger."
                    )
                    details = {}
                    if run.details_json:
                        try:
                            details = json.loads(run.details_json)
                        except Exception:
                            pass
                    details["summary_message"] = summary
                    details["run_type"] = run_type
                    details["event_ids"] = [e.id for e in created_events]
                    details["generated_events"] = [
                        {
                            "id": e.id,
                            "title": e.title,
                            "event_type": e.event_type,
                            "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
                            "deadline": e.deadline.isoformat() if e.deadline else None,
                            "notes": e.notes,
                        }
                        for e in created_events
                    ]
                    run.details_json = json.dumps(details)
                    run_repo.update_run(run)
                    logger.info("EmailEventWorker completed: %s", summary)
                    return run

                except Exception as exc:
                    logger.error("EmailEventWorker failed: %s", exc, exc_info=True)
                    run.status = "FAILED"
                    run.completed_at = datetime.now()
                    run.error_message = str(exc)
                    run.details_json = json.dumps({"run_type": run_type, "summary_message": f"Sync failed: {exc}"})
                    run_repo.update_run(run)
                    raise

    def trigger_run(self, run_type: str = "MANUAL", max_results: int = 25) -> GeneratorRun:
        """Execute email perception sync synchronously and log run lifecycle."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type, "max_results": max_results}),
            )
            run_repo.create_run(run)
        return self._execute_run(run, run_type=run_type, max_results=max_results)

    def trigger_run_async(self, run_type: str = "MANUAL", max_results: int = 25) -> GeneratorRun:
        """Immediately record RUNNING in DB and execute email sync in a background daemon thread."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type, "max_results": max_results, "summary_message": "Scanning emails and extracting events in background..."}),
            )
            run_repo.create_run(run)

        def _bg():
            try:
                self._execute_run(run, run_type=run_type, max_results=max_results)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True, name=f"{self.worker_type}_async").start()
        return run


class FacilityClosureWorker:
    """Thin execution runner for facility closure verification and conflict synchronization."""

    def __init__(self):
        self._lock = threading.Lock()
        self.worker_type = WORKER_TYPE_FACILITY_CLOSURE

    def _execute_run(self, run: GeneratorRun, run_type: str = "MANUAL") -> GeneratorRun:
        """Internal execution runner for facility verification."""
        with self._lock:
            with get_db() as conn:
                repo = EventRepository(conn)
                place_repo = PlaceRepository(conn)
                conflict_engine = ConflictEngine(place_repo=place_repo)
                event_manager = EventManager(
                    event_repo=repo,
                    conflict_engine=conflict_engine,
                    place_repo=place_repo,
                )
                run_repo = GeneratorRunRepository(conn)

                try:
                    # Delegate 100% of closure check & conflict sync to core engine
                    result = event_manager.scan_and_sync_facility_closures()

                    run.status = "SUCCESS"
                    run.completed_at = datetime.now()
                    run.scanned_count = result["scanned_count"]
                    run.created_count = result["created_count"]
                    run.details_json = json.dumps({
                        "run_type": run_type,
                        "summary_message": result["summary_message"],
                        "closures_count": len(result.get("closures", [])),
                        "conflicts_count": result["created_count"],
                        "warm_pool_schedule": result.get("warm_pool_schedule"),
                        "api_status": result.get("api_status"),
                    })
                    run_repo.update_run(run)
                    logger.info("FacilityClosureWorker completed: %s", result["summary_message"])
                    return run

                except Exception as exc:
                    logger.error("FacilityClosureWorker failed: %s", exc, exc_info=True)
                    run.status = "FAILED"
                    run.completed_at = datetime.now()
                    run.error_message = str(exc)
                    run.details_json = json.dumps({"run_type": run_type, "summary_message": f"Facility check failed: {exc}"})
                    run_repo.update_run(run)
                    raise

    def trigger_run(self, run_type: str = "MANUAL") -> GeneratorRun:
        """Execute facility closure verification synchronously and log run lifecycle."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type}),
            )
            run_repo.create_run(run)
        return self._execute_run(run, run_type=run_type)

    def trigger_run_async(self, run_type: str = "MANUAL") -> GeneratorRun:
        """Immediately record RUNNING in DB and execute facility verification in background daemon thread."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type, "summary_message": "Verifying facility closures & schedules in background..."}),
            )
            run_repo.create_run(run)

        def _bg():
            try:
                self._execute_run(run, run_type=run_type)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True, name=f"{self.worker_type}_async").start()
        return run


class InventoryDepletionWorker:
    """Thin execution runner for pantry depletion evaluation and runway restock suggestions."""

    def __init__(self):
        self._lock = threading.Lock()
        self.worker_type = WORKER_TYPE_INVENTORY_DEPLETION

    def _execute_run(self, run: GeneratorRun, run_type: str = "MANUAL", threshold_days: float = 7.0) -> GeneratorRun:
        """Internal execution runner for pantry depletion."""
        with self._lock:
            with get_db() as conn:
                inv_repo = InventoryRepository(conn)
                inv_service = InventoryService(inv_repo)
                run_repo = GeneratorRunRepository(conn)

                try:
                    # Delegate 100% of burn-rate & runway math to core engine
                    result = inv_service.evaluate_depletion_and_runway(threshold_days=threshold_days)

                    run.status = "SUCCESS"
                    run.completed_at = datetime.now()
                    run.scanned_count = result["scanned_count"]
                    run.created_count = result["created_count"]
                    run.details_json = json.dumps({
                        "run_type": run_type,
                        "summary_message": result["summary_message"],
                        "low_stock": result["low_stock_items"],
                    })
                    run_repo.update_run(run)
                    logger.info("InventoryDepletionWorker completed: %s", result["summary_message"])
                    return run

                except Exception as exc:
                    logger.error("InventoryDepletionWorker failed: %s", exc, exc_info=True)
                    run.status = "FAILED"
                    run.completed_at = datetime.now()
                    run.error_message = str(exc)
                    run.details_json = json.dumps({"run_type": run_type, "summary_message": f"Depletion scan failed: {exc}"})
                    run_repo.update_run(run)
                    raise

    def trigger_run(self, run_type: str = "MANUAL", threshold_days: float = 7.0) -> GeneratorRun:
        """Execute pantry burn-rate calculation synchronously and log run lifecycle."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type, "threshold_days": threshold_days}),
            )
            run_repo.create_run(run)
        return self._execute_run(run, run_type=run_type, threshold_days=threshold_days)

    def trigger_run_async(self, run_type: str = "MANUAL", threshold_days: float = 7.0) -> GeneratorRun:
        """Immediately record RUNNING in DB and execute depletion evaluation in background daemon thread."""
        started_at = datetime.now()
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            run = GeneratorRun(
                generator_type=self.worker_type,
                started_at=started_at,
                status="RUNNING",
                details_json=json.dumps({"run_type": run_type, "threshold_days": threshold_days, "summary_message": "Calculating stock runway in background..."}),
            )
            run_repo.create_run(run)

        def _bg():
            try:
                self._execute_run(run, run_type=run_type, threshold_days=threshold_days)
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True, name=f"{self.worker_type}_async").start()
        return run


class MasterDailyWorker:
    """Master Orchestrator that coordinates all daily life workers on schedule.
    Manages scheduling, sequence dispatching, failure isolation, and retry execution.
    """

    def __init__(self, interval_seconds: int = 86400):
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_run_time: Optional[datetime] = None
        self.next_run_time: Optional[datetime] = None

        # Instantiate decoupled thin workers
        self.calendar_worker = CalendarRuleWorker()
        self.email_worker = EmailEventWorker()
        self.facility_worker = FacilityClosureWorker()
        self.depletion_worker = InventoryDepletionWorker()

        self._workers = {
            WORKER_TYPE_CALENDAR_RULES: self.calendar_worker,
            WORKER_TYPE_EMAIL_EVENT: self.email_worker,
            WORKER_TYPE_FACILITY_CLOSURE: self.facility_worker,
            WORKER_TYPE_INVENTORY_DEPLETION: self.depletion_worker,
        }

    def start(self) -> None:
        """Start the background daemon loop."""
        if self._thread and self._thread.is_alive():
            logger.info("MasterDailyWorker is already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="MasterDailyWorkerDaemon", daemon=True
        )
        self._thread.start()
        logger.info("MasterDailyWorker background daemon started (interval=%ds).", self.interval_seconds)

    def stop(self) -> None:
        """Signal background thread to terminate."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("MasterDailyWorker stopped.")

    def _run_loop(self) -> None:
        """Worker loop that executes the daily master pipeline."""
        logger.info("MasterDailyWorker run loop initialized.")
        self.next_run_time = datetime.now() + timedelta(seconds=self.interval_seconds)

        while not self._stop_event.is_set():
            for _ in range(self.interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

            if self._stop_event.is_set():
                break

            logger.info("MasterDailyWorker scheduled trigger firing...")
            try:
                self.run_all(run_type="SCHEDULED")
            except Exception as e:
                logger.error("MasterDailyWorker scheduled execution encountered an error: %s", e)

            self.next_run_time = datetime.now() + timedelta(seconds=self.interval_seconds)

    def run_all(self, run_type: str = "MANUAL") -> Dict[str, Any]:
        """Execute all 4 workers in sequence with complete failure isolation."""
        self.last_run_time = datetime.now()
        results: Dict[str, Any] = {}
        errors: Dict[str, str] = {}

        pipeline = [
            ("Calendar Rules", self.calendar_worker),
            ("Email Perception", self.email_worker),
            ("Facility Closures", self.facility_worker),
            ("Inventory Depletion", self.depletion_worker),
        ]

        for label, worker in pipeline:
            try:
                run = worker.trigger_run(run_type=run_type)
                results[worker.worker_type] = {
                    "status": run.status,
                    "scanned_count": run.scanned_count,
                    "created_count": run.created_count,
                    "run_id": run.id,
                }
            except Exception as exc:
                logger.warning("Stage '%s' failed during master daily run: %s", label, exc)
                results[worker.worker_type] = {
                    "status": "FAILED",
                    "error": str(exc),
                }
                errors[worker.worker_type] = str(exc)

                # Ensure a FAILED run record is recorded in generator_runs
                try:
                    with get_db() as conn:
                        run_repo = GeneratorRunRepository(conn)
                        latest = run_repo.list_runs(generator_type=worker.worker_type, limit=1)
                        if not latest or latest[0].status != "FAILED":
                            fallback_run = GeneratorRun(
                                generator_type=worker.worker_type,
                                started_at=self.last_run_time,
                                completed_at=datetime.now(),
                                status="FAILED",
                                error_message=str(exc),
                                details_json=json.dumps({"summary_message": f"Execution failed: {exc}"}),
                            )
                            run_repo.create_run(fallback_run)
                except Exception as db_err:
                    logger.warning("Could not persist fallback failed run: %s", db_err)

        summary = {
            "timestamp": self.last_run_time.isoformat(),
            "run_type": run_type,
            "success": len(errors) == 0,
            "failed_stages": list(errors.keys()),
            "results": results,
        }
        return summary

    def run_all_async(self, run_type: str = "MANUAL") -> Dict[str, Any]:
        """Trigger master daily pipeline asynchronously across all 4 sub-workers."""
        threading.Thread(
            target=self.run_all,
            kwargs={"run_type": run_type},
            daemon=True,
            name="MasterDailyWorker_all_async",
        ).start()
        return {
            "status": "RUNNING",
            "message": "Master daily pipeline started in background across all 4 workers.",
            "run_type": run_type,
            "success": True,
            "failed_stages": [],
            "results": {},
        }

    def retry_failed(self) -> Dict[str, Any]:
        """Inspect latest run for each worker and retry only the workers that failed."""
        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            retried: Dict[str, Any] = {}

            for worker_type, worker in self._workers.items():
                runs = run_repo.list_runs(generator_type=worker_type, limit=1)
                # Check legacy aliases as well if applicable
                if not runs and worker_type == WORKER_TYPE_EMAIL_EVENT:
                    runs = run_repo.list_runs(generator_type="EMAIL_EVENT_GENERATOR", limit=1)
                elif not runs and worker_type == WORKER_TYPE_FACILITY_CLOSURE:
                    runs = run_repo.list_runs(generator_type="FACILITY_WORKER", limit=1)
                elif not runs and worker_type == WORKER_TYPE_INVENTORY_DEPLETION:
                    runs = run_repo.list_runs(generator_type="DEPLETION_WORKER", limit=1)

                if runs and runs[0].status == "FAILED":
                    logger.info("Retrying failed worker '%s' (previous error: %s)...", worker_type, runs[0].error_message)
                    try:
                        new_run = worker.trigger_run(run_type="RETRY")
                        retried[worker_type] = {
                            "status": new_run.status,
                            "run_id": new_run.id,
                            "scanned_count": new_run.scanned_count,
                            "created_count": new_run.created_count,
                        }
                    except Exception as ex:
                        retried[worker_type] = {
                            "status": "FAILED",
                            "error": str(ex),
                        }

        return {
            "retried_count": len(retried),
            "results": retried,
            "message": (
                f"Retried {len(retried)} failed worker(s)."
                if retried
                else "No failed workers found. All systems healthy."
            ),
        }

    def trigger_worker(self, worker_type: str, **kwargs) -> GeneratorRun:
        """Trigger a specific sub-worker by name/type."""
        # Support aliases
        alias_map = {
            "EMAIL_EVENT_GENERATOR": WORKER_TYPE_EMAIL_EVENT,
            "FACILITY_WORKER": WORKER_TYPE_FACILITY_CLOSURE,
            "DEPLETION_WORKER": WORKER_TYPE_INVENTORY_DEPLETION,
            "CALENDAR_RULE_GENERATOR": WORKER_TYPE_CALENDAR_RULES,
        }
        resolved = alias_map.get(worker_type, worker_type)
        worker = self._workers.get(resolved)
        if not worker:
            raise ValueError(f"Unknown worker type: '{worker_type}'. Available: {list(self._workers.keys())}")
        return worker.trigger_run(**kwargs)

    def get_status(self) -> Dict[str, Any]:
        """Return status and latest execution outcome for master worker and all sub-workers."""
        is_running = bool(self._thread and self._thread.is_alive())
        sub_worker_statuses = {}

        with get_db() as conn:
            run_repo = GeneratorRunRepository(conn)
            for wtype in self._workers.keys():
                runs = run_repo.list_runs(generator_type=wtype, limit=1)
                if not runs and wtype == WORKER_TYPE_EMAIL_EVENT:
                    runs = run_repo.list_runs(generator_type="EMAIL_EVENT_GENERATOR", limit=1)
                elif not runs and wtype == WORKER_TYPE_FACILITY_CLOSURE:
                    runs = run_repo.list_runs(generator_type="FACILITY_WORKER", limit=1)
                elif not runs and wtype == WORKER_TYPE_INVENTORY_DEPLETION:
                    runs = run_repo.list_runs(generator_type="DEPLETION_WORKER", limit=1)

                latest = runs[0] if runs else None
                sub_worker_statuses[wtype] = {
                    "latest_run_id": latest.id if latest else None,
                    "latest_status": latest.status if latest else "IDLE",
                    "latest_run_at": latest.started_at.isoformat() if latest else None,
                    "created_count": latest.created_count if latest else 0,
                    "error_message": latest.error_message if latest else None,
                }

        return {
            "is_running": is_running,
            "interval_seconds": self.interval_seconds,
            "last_run_time": self.last_run_time.isoformat() if self.last_run_time else None,
            "next_run_time": self.next_run_time.isoformat() if self.next_run_time else None,
            "workers": sub_worker_statuses,
        }


# Global Master Worker Singleton
_master_worker_instance: Optional[MasterDailyWorker] = None


def get_master_daily_worker() -> MasterDailyWorker:
    """Singleton provider for MasterDailyWorker."""
    global _master_worker_instance
    if _master_worker_instance is None:
        _master_worker_instance = MasterDailyWorker()
    return _master_worker_instance


def get_email_worker() -> MasterDailyWorker:
    """Backward-compatible provider returning master worker."""
    return get_master_daily_worker()

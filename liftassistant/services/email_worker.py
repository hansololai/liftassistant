"""Daily background worker for email event perception and ingestion."""

from datetime import datetime, timedelta
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

from liftassistant.db.connection import get_db
from liftassistant.db.repository import (
    EventRepository,
    GeneratorRunRepository,
    PlaceRepository,
)
from liftassistant.models.domain import GeneratorRun
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.email_event_generator import EmailEventGenerator
from liftassistant.services.event_manager import EventManager
from liftassistant.services.map_service import MapService
from liftassistant.services.receipt_parser import ReceiptParser

logger = logging.getLogger(__name__)


class EmailWorker:
    """Daily background worker that monitors Gmail and coordinates perception/event generation."""

    def __init__(self, interval_seconds: int = 86400):
        self.interval_seconds = interval_seconds  # Default 24 hours (86400s)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_syncing = False
        self._sync_lock = threading.Lock()
        self.last_run_time: Optional[datetime] = None
        self.next_run_time: Optional[datetime] = None

    def start(self) -> None:
        """Start the background daemon loop."""
        if self._thread and self._thread.is_alive():
            logger.info("EmailWorker is already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="EmailEventGeneratorWorker", daemon=True
        )
        self._thread.start()
        logger.info("EmailWorker background daemon started (interval=%ds).", self.interval_seconds)

    def stop(self) -> None:
        """Signal background thread to terminate."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("EmailWorker stopped.")

    def _run_loop(self) -> None:
        """Worker loop that executes daily."""
        logger.info("EmailWorker run loop initialized.")
        self.next_run_time = datetime.now() + timedelta(seconds=self.interval_seconds)

        while not self._stop_event.is_set():
            # Wait with 1-second chunks for responsive cancellation
            for _ in range(self.interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

            if self._stop_event.is_set():
                break

            logger.info("EmailWorker scheduled daily trigger firing...")
            try:
                self.trigger_sync(run_type="SCHEDULED")
            except Exception as e:
                logger.error("EmailWorker scheduled run failed: %s", e)

            self.next_run_time = datetime.now() + timedelta(seconds=self.interval_seconds)

    def trigger_sync(self, run_type: str = "MANUAL", max_results: int = 25) -> GeneratorRun:
        """Execute a sync operation immediately with run tracking."""
        if self._is_syncing:
            raise RuntimeError("A sync run is already in progress.")

        with self._sync_lock:
            self._is_syncing = True
            started_at = datetime.now()
            run = None
            try:
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
                    gen_run_repo = GeneratorRunRepository(conn)

                    run = GeneratorRun(
                        generator_type="EMAIL_EVENT_GENERATOR",
                        started_at=started_at,
                        status="RUNNING",
                        details_json=json.dumps({"trigger": run_type, "max_results": max_results}),
                    )
                    gen_run_repo.create_run(run)

                    generator = EmailEventGenerator(
                        event_manager=event_manager,
                        receipt_parser=ReceiptParser(),
                        place_repo=place_repo,
                        cas_storage=CASStorage(),
                        gen_run_repo=gen_run_repo,
                    )

                    generator.sync_recent_emails(max_results=max_results, run_id=run.id)
                    self.last_run_time = datetime.now()
                    updated_run = gen_run_repo.get_run(run.id)
                    return updated_run or run
            except Exception as e:
                logger.exception("Failed during email generator sync: %s", e)
                try:
                    with get_db() as conn:
                        gen_run_repo = GeneratorRunRepository(conn)
                        if run:
                            run.status = "FAILED"
                            run.error_message = str(e)
                            run.completed_at = datetime.now()
                            gen_run_repo.update_run(run)
                            return run
                except Exception:
                    pass
                raise
            finally:
                self._is_syncing = False

    def get_status(self) -> Dict[str, Any]:
        """Return status payload for API / UI."""
        return {
            "is_worker_running": self._thread is not None and self._thread.is_alive(),
            "is_syncing": self._is_syncing,
            "last_run_time": self.last_run_time.isoformat() if self.last_run_time else None,
            "next_run_time": self.next_run_time.isoformat() if self.next_run_time else None,
            "interval_seconds": self.interval_seconds,
        }


_email_worker_instance: Optional[EmailWorker] = None


def get_email_worker() -> EmailWorker:
    global _email_worker_instance
    if _email_worker_instance is None:
        _email_worker_instance = EmailWorker()
    return _email_worker_instance

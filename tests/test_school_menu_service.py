"""Comprehensive test suite for SchoolMenuService, SchoolMenuWorker, and MasterDailyWorker extension."""

from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from liftassistant.api.app import create_app
from liftassistant.db.connection import get_db
from liftassistant.db.repository import EventRepository, GeneratorRunRepository, PlaceRepository
from liftassistant.models.domain import GeneratorRun, LifeEvent, Place
from liftassistant.services.daily_workers import (
    MasterDailyWorker,
    SchoolMenuWorker,
    WORKER_TYPE_SCHOOL_MENU,
    get_master_daily_worker,
)
from liftassistant.services.school_menu_service import (
    PRIMROSE_PLACE_ID,
    PRIMROSE_PLACE_NAME,
    SchoolMenuService,
)


def test_db(tmp_path):
    """Set up an isolated SQLite database with liftassistant schema."""
    from liftassistant.db import connection
    db_file = tmp_path / "test_school_menu.db"
    connection.DEFAULT_DB_PATH = db_file
    connection.init_db(db_path=db_file)
    return str(db_file)


def test_html_and_pdf_text_extraction():
    """Verify HTML stripping and PyMuPDF PDF text extraction."""
    # 1. HTML text extraction
    html = "<html><body><h1>Primrose Menu</h1><p>Monday: Meatball sliders</p><script>alert(1);</script></body></html>"
    text = SchoolMenuService.extract_text_from_html(html)
    assert "Primrose Menu" in text
    assert "Meatball sliders" in text
    assert "alert" not in text

    # 2. PDF text extraction with PyMuPDF
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Weekly Menu: Week of Nov 24, 2026\nWednesday: Chicken nuggets")
    pdf_bytes = doc.write()
    doc.close()

    extracted_pdf_text = SchoolMenuService.extract_text_from_pdf_bytes(pdf_bytes)
    assert "Weekly Menu: Week of Nov 24, 2026" in extracted_pdf_text
    assert "Chicken nuggets" in extracted_pdf_text


def test_menu_parsing_and_reminders_creation(test_db):
    """Test menu parsing, place grounding, LifeEvent creation, and deduplication."""
    with get_db() as conn:
        event_repo = EventRepository(conn)
        place_repo = PlaceRepository(conn)
        run_repo = GeneratorRunRepository(conn)

        # Mock LLM caller simulating local Ollama response
        def mock_llm_caller(prompt, system_prompt=None, json_mode=True, timeout=60):
            return json.dumps({
                "events": [
                    {
                        "title": "Primrose Lunch: Switch to Sun Butter and Jelly Sandwich (Meatballs sliders)",
                        "description": "Monday lunch serves Meatballs sliders.",
                        "due_date": "2026-11-23",
                        "priority": "Medium",
                        "source_citation": "Meatballs sliders, cucumbers, banana",
                    },
                    {
                        "title": "Primrose Lunch: Switch to Sun Butter and Jelly Sandwich (Chicken teriyaki)",
                        "description": "Wednesday lunch serves Chicken teriyaki.",
                        "due_date": "2026-11-25",
                        "priority": "Medium",
                        "source_citation": "Chicken teriyaki, peas, apples",
                    },
                ]
            })

        service = SchoolMenuService(
            event_repo=event_repo,
            place_repo=place_repo,
            gen_run_repo=run_repo,
            llm_caller=mock_llm_caller,
        )

        menu_sample = """
        Weekly Menu for Primrose School of Wexford
        Week of Monday, November 23, 2026
        Monday: Meatballs sliders, cucumbers, banana
        Tuesday: Macaroni and cheese, broccoli, pears
        Wednesday: Chicken teriyaki, peas, apples
        Thursday: Cheese pizza, carrot sticks, orange slices
        Friday: Grilled cheese, tomato soup, melon
        """

        # 1. Process raw menu text
        run = GeneratorRun(generator_type=WORKER_TYPE_SCHOOL_MENU, status="RUNNING")
        run_repo.create_run(run)

        events = service.process_raw_menu_text(menu_sample, reference_date="2026-11-23", run_id=run.id)
        assert len(events) == 2

        # Verify first event (Monday Meatball sliders)
        evt_monday = next(e for e in events if "2026-11-23" in e.scheduled_at.isoformat())
        assert "Meatballs sliders" in evt_monday.title
        assert evt_monday.place_id == PRIMROSE_PLACE_ID
        assert evt_monday.event_type == "KID_ACTIVITY"
        assert "Marcus" in evt_monday.people_involved
        assert evt_monday.scheduled_at.hour == 8
        assert evt_monday.deadline.hour == 9
        assert evt_monday.source_reference_id == "primrose_lunch:2026-11-23"

        # Verify second event (Wednesday Chicken teriyaki)
        evt_wednesday = next(e for e in events if "2026-11-25" in e.scheduled_at.isoformat())
        assert "Chicken teriyaki" in evt_wednesday.title
        assert evt_wednesday.scheduled_at.hour == 8

        # Verify place was auto-created and grounded
        place = place_repo.get_place(PRIMROSE_PLACE_ID)
        assert place is not None
        assert place.name == PRIMROSE_PLACE_NAME
        assert place.category == "education"

        # Verify feedback records created with PENDING review status
        feedbacks = run_repo.get_run_feedbacks(run.id)
        assert len(feedbacks) == 2
        for fb in feedbacks:
            assert fb.llm_category == "SCHOOL_LUNCH"
            assert fb.user_status == "PENDING"
            assert "Switch to Sun Butter and Jelly" in fb.event_title

        # 2. Test Deduplication / Idempotency
        # Re-running with the same menu must NOT create duplicate events
        events_run2 = service.process_raw_menu_text(menu_sample, reference_date="2026-11-23", run_id=run.id)
        assert len(events_run2) == 0, "Duplicate reminders must not be created for the same date"

        # Verify database still only has 2 events
        all_events = event_repo.list_events()
        assert len(all_events) == 2


def test_school_menu_worker_execution(test_db):
    """Verify SchoolMenuWorker executes cleanly, creates DB run, and isolates errors."""
    with get_db() as conn:
        run_repo = GeneratorRunRepository(conn)
        worker = SchoolMenuWorker()
        assert worker.worker_type == WORKER_TYPE_SCHOOL_MENU

        # Mock sync_recent_menus on the engine
        def mock_sync(self, max_results=10, run_id=None):
            return [
                LifeEvent(
                    id="evt_mock_lunch_1",
                    title="Primrose Lunch: Switch to Sun Butter and Jelly Sandwich (Chicken Nuggets)",
                    event_type="KID_ACTIVITY",
                    scheduled_at=datetime(2026, 11, 24, 8, 0),
                    deadline=datetime(2026, 11, 24, 9, 0),
                    place_id=PRIMROSE_PLACE_ID,
                    generator_run_id=run_id,
                )
            ]

        SchoolMenuService.sync_recent_menus = mock_sync

        run = worker.trigger_run(run_type="MANUAL")
        assert run.status == "SUCCESS"
        assert run.created_count == 1
        assert "Generated 1 lunch switch reminder(s)" in run.details_json

        # Verify run in repository
        persisted_run = run_repo.get_run(run.id)
        assert persisted_run is not None
        assert persisted_run.status == "SUCCESS"


def test_master_daily_worker_extension_and_registration(test_db):
    """Verify MasterDailyWorker includes SchoolMenuWorker in pipeline and supports dynamic worker registration."""
    master = MasterDailyWorker()
    assert WORKER_TYPE_SCHOOL_MENU in master._workers
    assert any(label == "School Lunch Menu" for label, _ in master._pipeline)

    # Verify status includes school menu worker
    status = master.get_status()
    assert WORKER_TYPE_SCHOOL_MENU in status["workers"]

    # Verify dynamic registration of future generator workers
    class FutureHealthAlertWorker:
        def __init__(self):
            self.worker_type = "FUTURE_HEALTH_ALERT_WORKER"
        def trigger_run(self, run_type="MANUAL", **kwargs):
            return GeneratorRun(generator_type=self.worker_type, status="SUCCESS")

    future_worker = FutureHealthAlertWorker()
    master.register_worker("FUTURE_HEALTH_ALERT_WORKER", future_worker, label="Health Alerts")
    assert "FUTURE_HEALTH_ALERT_WORKER" in master._workers
    assert any(label == "Health Alerts" for label, _ in master._pipeline)


def test_school_menu_api_endpoints(test_db):
    """Test API endpoint functions for School Menu trigger and raw text parsing."""
    from liftassistant.api.routers.generators import (
        MenuTextParseRequest,
        parse_school_menu_text_directly,
        trigger_school_menu_worker_run,
    )

    with get_db() as conn:
        event_repo = EventRepository(conn)
        place_repo = PlaceRepository(conn)
        gen_run_repo = GeneratorRunRepository(conn)

        # 1. Test parse_school_menu_text_directly
        mock_payload = MenuTextParseRequest(
            text="""
            Primrose School of Wexford Menu - Week of Dec 1, 2026
            Monday: Chicken tenders, fries, apple
            Tuesday: Veggie burger, sweet potato
            """,
            reference_date="2026-12-01",
        )

        original_parse = SchoolMenuService.parse_menu_content
        SchoolMenuService.parse_menu_content = lambda self, txt, reference_date=None, **kwargs: [
            {
                "title": "Primrose Lunch: Switch to Sun Butter and Jelly Sandwich (Chicken tenders)",
                "description": "Monday lunch serves Chicken tenders.",
                "due_date": "2026-12-01",
                "priority": "Medium",
                "source_citation": "Chicken tenders, fries, apple",
            }
        ]

        try:
            resp = parse_school_menu_text_directly(
                mock_payload,
                event_repo=event_repo,
                place_repo=place_repo,
                gen_run_repo=gen_run_repo,
            )
            assert resp["created_count"] == 1
            assert "Chicken tenders" in resp["events"][0]["title"]

            # 2. Test trigger endpoint function trigger_school_menu_worker_run
            res_run = trigger_school_menu_worker_run(max_results=5)
            assert res_run["run"]["generator_type"] == WORKER_TYPE_SCHOOL_MENU
            assert "Primrose school lunch menu sync" in res_run["summary_message"]
        finally:
            SchoolMenuService.parse_menu_content = original_parse


if __name__ == "__main__":
    import tempfile
    import shutil

    tmp = Path(tempfile.mkdtemp())
    try:
        db_path = test_db(tmp)
        print("Running test_html_and_pdf_text_extraction...")
        test_html_and_pdf_text_extraction()
        print("✓ test_html_and_pdf_text_extraction passed")

        print("Running test_menu_parsing_and_reminders_creation...")
        test_menu_parsing_and_reminders_creation(db_path)
        print("✓ test_menu_parsing_and_reminders_creation passed")

        print("Running test_school_menu_worker_execution...")
        test_school_menu_worker_execution(db_path)
        print("✓ test_school_menu_worker_execution passed")

        print("Running test_master_daily_worker_extension_and_registration...")
        test_master_daily_worker_extension_and_registration(db_path)
        print("✓ test_master_daily_worker_extension_and_registration passed")

        print("Running test_school_menu_api_endpoints...")
        test_school_menu_api_endpoints(db_path)
        print("✓ test_school_menu_api_endpoints passed")

        print("\nALL 5 SCHOOL MENU SERVICE TESTS PASSED!")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


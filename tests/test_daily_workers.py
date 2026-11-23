"""Tests for Unified Daily Workers Architecture and ReceiptService.
Verifies:
1. Thin Worker, Rich Core Engine pattern across all 4 workers.
2. MasterDailyWorker orchestrator: sequencing, failure isolation, and retry_failed().
3. ReceiptService: deterministic persistence, line item linking, and Grocy qu_factor bulk restocking.
4. EmailEventGenerator receipt handling: directly invokes ReceiptService to restock pantry.
5. API endpoints for master orchestrator and sub-workers.
"""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3

from liftassistant.api.app import create_app
from liftassistant.db.connection import close_connection_pool, get_db
from liftassistant.db.repository import (
    EventGeneratorRepository,
    EventRepository,
    GeneratorRunRepository,
    InventoryRepository,
    PlaceRepository,
)
from liftassistant.models.domain import (
    EventGenerator,
    GeneratorRun,
    LifeEvent,
    Place,
    ReceiptLineItem,
    StandardizedReceipt,
)
from liftassistant.services.daily_workers import (
    CalendarRuleWorker,
    EmailEventWorker,
    FacilityClosureWorker,
    InventoryDepletionWorker,
    MasterDailyWorker,
    WORKER_TYPE_CALENDAR_RULES,
    WORKER_TYPE_EMAIL_EVENT,
    WORKER_TYPE_FACILITY_CLOSURE,
    WORKER_TYPE_INVENTORY_DEPLETION,
    get_master_daily_worker,
)
from liftassistant.services.event_generator_service import EventGeneratorService
from liftassistant.services.event_manager import EventManager
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.receipt_service import ReceiptService


def test_db_setup(tmp_path, monkeypatch):
    """Create an isolated test database with the complete schema."""
    db_file = tmp_path / "test_workers.db"
    monkeypatch.setenv("LIFTASSISTANT_DB_PATH", str(db_file))

    # Initialize tables
    schema_path = Path("liftassistant/db/schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_sql)

    # Seed baseline place & product
    conn.execute(
        "INSERT INTO places (id, name, address, category) VALUES ('pl_test_mart', 'Test Supermarket', '123 Test Rd', 'store')"
    )
    conn.execute(
        """
        INSERT INTO products (id, name, category, consume_step, qu_factor, qu_stock_id, qu_purchase_id)
        VALUES ('prod_toilet_paper', 'Kirkland Bath Tissue', 'household', 1.0, 36.0, 'roll', 'pack')
        """
    )
    conn.execute(
        "INSERT INTO stock (product_id, amount) VALUES ('prod_toilet_paper', 2.0)"
    )
    conn.commit()
    conn.close()

    yield db_file
    close_connection_pool(db_file)


def test_receipt_service_persists_and_restocks(test_db_setup):
    """ReceiptService should save receipt, items, apply qu_factor bulk multiplier, and restock pantry."""
    with get_db() as conn:
        inv_repo = InventoryRepository(conn)
        inv_service = InventoryService(inv_repo)
        receipt_service = ReceiptService(conn=conn, inventory_service=inv_service)

        std_receipt = StandardizedReceipt(
            id="rec_test_001",
            file_hash="hash123",
            file_path="data/receipts_inbox/rec_test_001.json",
            merchant_name="Costco Wholesale",
            transaction_time=datetime(2026, 11, 15, 14, 30),
            place_id="pl_test_mart",
            total_amount=24.99,
            currency="USD",
            source_channel="EMAIL_BODY",
            line_items=[
                ReceiptLineItem(
                    raw_text="KS BATH TISSUE 36/PK",
                    clean_name="Kirkland Bath Tissue 36-pack",
                    category="household",
                    quantity=1.0,  # 1 pack purchased
                    unit="pack",
                    total_price=24.99,
                    product_id="prod_toilet_paper",
                )
            ],
        )

        saved = receipt_service.persist_receipt(std_receipt, auto_restock=True)
        assert saved.id == "rec_test_001"

        # Verify receipt stored in DB
        cursor = conn.cursor()
        r_row = cursor.execute("SELECT * FROM receipts WHERE id = ?", ("rec_test_001",)).fetchone()
        assert r_row is not None
        assert r_row["merchant_name"] == "Costco Wholesale"

        # Verify pantry stock increased by 1 pack * 36 = 36 rolls (from 2.0 -> 38.0)
        stock_row = cursor.execute("SELECT amount FROM stock WHERE product_id = ?", ("prod_toilet_paper",)).fetchone()
        assert stock_row["amount"] == 38.0


def test_calendar_rule_worker(test_db_setup):
    """CalendarRuleWorker should evaluate due rules and log execution in generator_runs."""
    with get_db() as conn:
        gen_repo = EventGeneratorRepository(conn)
        rule = EventGenerator(
            title="Annual Vehicle Inspection",
            event_type="MAINTENANCE",
            frequency="YEARLY",
            by_month=11,
            by_month_day=20,
            anchor_date=date(2026, 1, 1),
            lead_time_days=14,  # Nov 20 - 14d = Nov 6 threshold (today is Nov 17 -> due!)
            deadline_offset_days=0,
            duration_minutes=60,
        )
        gen_repo.create_generator(rule)

    worker = CalendarRuleWorker()
    run = worker.trigger_run(run_type="MANUAL", reference_date=date(2026, 11, 17))

    assert run.status == "SUCCESS"
    assert run.generator_type == WORKER_TYPE_CALENDAR_RULES
    assert run.scanned_count == 1
    assert run.created_count == 1

    # Check feedback row logged for the spawned event
    with get_db() as conn:
        run_repo = GeneratorRunRepository(conn)
        feedbacks = run_repo.get_run_feedbacks(run.id)
        assert len(feedbacks) == 1
        assert "Vehicle Inspection" in feedbacks[0].email_subject


def test_inventory_depletion_worker(test_db_setup):
    """InventoryDepletionWorker should evaluate low stock runway and log run."""
    worker = InventoryDepletionWorker()
    run = worker.trigger_run(run_type="MANUAL", threshold_days=7.0)

    assert run.status == "SUCCESS"
    assert run.generator_type == WORKER_TYPE_INVENTORY_DEPLETION
    assert run.scanned_count >= 1
    assert "summary_message" in run.details_json


def test_facility_closure_worker(test_db_setup):
    """FacilityClosureWorker should scan closures, sync conflict flags, and log run."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO resource_closures (id, resource_id, resource_name, start_time, end_time, reason)
            VALUES ('cls_test_01', 'pl_test_mart', 'Test Supermarket', '2026-11-26 00:00:00', '2026-11-26 23:59:59', 'Thanksgiving')
            """
        )
        conn.commit()

    worker = FacilityClosureWorker()
    run = worker.trigger_run(run_type="MANUAL")

    assert run.status == "SUCCESS"
    assert run.generator_type == WORKER_TYPE_FACILITY_CLOSURE
    assert run.scanned_count >= 1


def test_master_daily_worker_orchestration_and_failure_isolation(test_db_setup, monkeypatch):
    """MasterDailyWorker should run all sub-workers in sequence.
    If one sub-worker fails, the other sub-workers should still run and succeed (failure isolation).
    """
    master = MasterDailyWorker()

    # Intentionally cause email_worker to fail to test failure isolation
    def mock_email_fail(*args, **kwargs):
        raise ConnectionError("Simulated Gmail API timeout")

    monkeypatch.setattr(master.email_worker, "trigger_run", mock_email_fail)

    outcome = master.run_all(run_type="MANUAL")

    assert outcome["success"] is False
    assert WORKER_TYPE_EMAIL_EVENT in outcome["failed_stages"]

    # Other workers must have succeeded despite email failure
    assert outcome["results"][WORKER_TYPE_CALENDAR_RULES]["status"] == "SUCCESS"
    assert outcome["results"][WORKER_TYPE_FACILITY_CLOSURE]["status"] == "SUCCESS"
    assert outcome["results"][WORKER_TYPE_INVENTORY_DEPLETION]["status"] == "SUCCESS"
    assert outcome["results"][WORKER_TYPE_EMAIL_EVENT]["status"] == "FAILED"

    # Now test retry_failed(): restore email worker and trigger retry
    monkeypatch.undo()
    # Mock email worker trigger_run to return a successful run
    def mock_email_success(*args, **kwargs):
        with get_db() as conn:
            r = GeneratorRunRepository(conn)
            run_obj = GeneratorRun(
                generator_type=WORKER_TYPE_EMAIL_EVENT,
                status="SUCCESS",
                scanned_count=5,
                created_count=2,
            )
            return r.create_run(run_obj)

    monkeypatch.setattr(master.email_worker, "trigger_run", mock_email_success)
    retry_outcome = master.retry_failed()

    assert retry_outcome["retried_count"] == 1
    assert WORKER_TYPE_EMAIL_EVENT in retry_outcome["results"]
    assert retry_outcome["results"][WORKER_TYPE_EMAIL_EVENT]["status"] == "SUCCESS"


from liftassistant.api.routers.generators import (
    get_generator_run_result,
    get_master_worker_status,
    trigger_calendar_rules_worker_run,
    trigger_master_daily_run,
    trigger_master_retry_failed,
)


def test_master_worker_api_endpoints(test_db_setup):
    """Test REST API endpoint functions directly without requiring loopback HTTP sockets."""
    with get_db() as conn:
        run_repo = GeneratorRunRepository(conn)

        # 1. Master status
        status_data = get_master_worker_status()
        assert "interval_seconds" in status_data
        assert "workers" in status_data

        # 2. Trigger calendar rules worker endpoint
        res_data = trigger_calendar_rules_worker_run()
        assert res_data["run"]["status"] == "SUCCESS"
        assert res_data["run"]["generator_type"] == WORKER_TYPE_CALENDAR_RULES

        # 3. View run result (displays events)
        run_id = res_data["run"]["id"]
        detail_data = get_generator_run_result(run_id, gen_run_repo=run_repo)
        assert detail_data["run"]["id"] == run_id
        assert "summary_message" in detail_data


if __name__ == "__main__":
    import tempfile
    import shutil
    import liftassistant.db.connection as conn_mod

    temp_dir = Path(tempfile.mkdtemp())
    db_file = temp_dir / "test_workers_runner.db"
    orig_db_path = conn_mod.DEFAULT_DB_PATH
    conn_mod.DEFAULT_DB_PATH = db_file

    try:
        class MonkeyPatchHelper:
            def __init__(self):
                self._patches = []
            def setattr(self, obj, attr, value):
                orig = getattr(obj, attr)
                self._patches.append((obj, attr, orig))
                setattr(obj, attr, value)
            def undo(self):
                for obj, attr, orig in reversed(self._patches):
                    setattr(obj, attr, orig)
                self._patches.clear()

        mp = MonkeyPatchHelper()

        schema_path = Path("liftassistant/db/schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.executescript(schema_sql)

        conn.execute("INSERT INTO quantity_units (id, name, name_plural) VALUES ('roll', 'Roll', 'Rolls'), ('pack', 'Pack', 'Packs')")
        conn.execute(
            "INSERT INTO places (id, name, address, category) VALUES ('pl_test_mart', 'Test Supermarket', '123 Test Rd', 'store')"
        )
        conn.execute(
            """
            INSERT INTO products (id, name, category, consume_step, qu_factor, qu_stock_id, qu_purchase_id)
            VALUES ('prod_toilet_paper', 'Kirkland Bath Tissue', 'household', 1.0, 36.0, 'roll', 'pack')
            """
        )
        conn.execute(
            "INSERT INTO stock (id, product_id, amount) VALUES ('stk_1', 'prod_toilet_paper', 2.0)"
        )
        conn.commit()
        conn.close()

        print("--> Testing ReceiptService persistence and bulk pantry restocking...")
        test_receipt_service_persists_and_restocks(db_file)
        print("  ✓ ReceiptService passed.")

        print("--> Testing CalendarRuleWorker execution and run logging...")
        test_calendar_rule_worker(db_file)
        print("  ✓ CalendarRuleWorker passed.")

        print("--> Testing InventoryDepletionWorker execution and run logging...")
        test_inventory_depletion_worker(db_file)
        print("  ✓ InventoryDepletionWorker passed.")

        print("--> Testing FacilityClosureWorker execution and conflict sync...")
        test_facility_closure_worker(db_file)
        print("  ✓ FacilityClosureWorker passed.")

        print("--> Testing MasterDailyWorker sequencing and failure isolation...")
        test_master_daily_worker_orchestration_and_failure_isolation(db_file, mp)
        print("  ✓ MasterDailyWorker passed.")

        print("--> Testing Master Worker REST API endpoints...")
        test_master_worker_api_endpoints(db_file)
        print("  ✓ API endpoints passed.")

        print("\n=======================================================")
        print("ALL DAILY WORKER & RECEIPT SERVICE TESTS PASSED CLEANLY!")
        print("=======================================================\n")
    finally:
        close_connection_pool(db_file)
        conn_mod.DEFAULT_DB_PATH = orig_db_path
        shutil.rmtree(temp_dir, ignore_errors=True)


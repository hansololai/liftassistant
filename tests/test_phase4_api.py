"""Unit and Integration Tests for Phase 4 REST API.
Verifies standard REST conventions, JSON responses for success and failures.
"""

from datetime import datetime, date
import os
from pathlib import Path
import sqlite3
import unittest
from fastapi.testclient import TestClient

# Configure environment to test for integration tests
os.environ["ENVIRONMENT"] = "test"

from liftassistant.api.app import app
from liftassistant.api.deps import (
    get_db_connection,
    get_event_repo,
    get_gen_repo,
    get_inventory_repo,
    get_place_repo,
    get_map_service,
    get_event_manager,
    get_event_gen_service,
    get_inventory_service,
    get_trip_service,
)
from liftassistant.db.connection import close_connection_pool, init_db
from liftassistant.db.seed import seed_database
from liftassistant.db.repository import (
    EventGeneratorRepository,
    EventRepository,
    InventoryRepository,
    PlaceRepository,
)
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.event_manager import EventManager
from liftassistant.services.event_generator_service import EventGeneratorService
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.trip_service import TripService
from liftassistant.services.map_service import MapService

TEST_API_DB = Path("data") / "test_api.db"


class TestPhase4RestApi(unittest.TestCase):
    """Test suite for LiftAssistant REST API."""

    @classmethod
    def setUpClass(cls):
        close_connection_pool(TEST_API_DB)
        if TEST_API_DB.exists():
            try:
                os.remove(TEST_API_DB)
            except OSError:
                pass
        init_db(TEST_API_DB)
        seed_database(TEST_API_DB)

    @classmethod
    def tearDownClass(cls):
        close_connection_pool(TEST_API_DB)
        if TEST_API_DB.exists():
            try:
                os.remove(TEST_API_DB)
            except OSError:
                pass

    def setUp(self):
        self.conn = sqlite3.connect(str(TEST_API_DB), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")

        # Set up dependency overrides so all endpoints use test database
        def override_get_db():
            yield self.conn

        def override_event_repo():
            yield EventRepository(self.conn)

        def override_inv_repo():
            yield InventoryRepository(self.conn)

        def override_place_repo():
            yield PlaceRepository(self.conn)

        def override_map_service():
            yield MapService(place_repo=PlaceRepository(self.conn))

        def override_event_mgr():
            yield EventManager(
                event_repo=EventRepository(self.conn),
                conflict_engine=ConflictEngine(),
                place_repo=PlaceRepository(self.conn),
                map_service=MapService(place_repo=PlaceRepository(self.conn)),
            )

        def override_gen_repo():
            yield EventGeneratorRepository(self.conn)

        def override_gen_service():
            yield EventGeneratorService(EventGeneratorRepository(self.conn), EventRepository(self.conn))

        def override_inv_service():
            yield InventoryService(InventoryRepository(self.conn))

        def override_trip_service():
            yield TripService(conn=self.conn)

        app.dependency_overrides[get_db_connection] = override_get_db
        app.dependency_overrides[get_event_repo] = override_event_repo
        app.dependency_overrides[get_place_repo] = override_place_repo
        app.dependency_overrides[get_map_service] = override_map_service
        app.dependency_overrides[get_gen_repo] = override_gen_repo
        app.dependency_overrides[get_inventory_repo] = override_inv_repo
        app.dependency_overrides[get_event_manager] = override_event_mgr
        app.dependency_overrides[get_event_gen_service] = override_gen_service
        app.dependency_overrides[get_inventory_service] = override_inv_service
        app.dependency_overrides[get_trip_service] = override_trip_service

        self.client = TestClient(app, headers={"X-Device-Token": "test"})

    def tearDown(self):
        app.dependency_overrides.clear()
        self.conn.close()

    # --- 1. Health & Overview Tests ---
    def test_health_check_json(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "lifeassistant-api")

    def test_overview_briefing_json(self):
        resp = self.client.get("/api/v1/overview/briefing")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        data = resp.json()
        self.assertIn("weather", data)
        self.assertIn("summary", data)
        self.assertIn("pool_notice", data)
        self.assertEqual(data["weather"]["location"], "Cranberry Township, PA")

    # --- 2. Events CRUD & REST Format Tests ---
    def test_list_events(self):
        resp = self.client.get("/api/v1/events")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        data = resp.json()
        self.assertIn("result", data)
        self.assertIsInstance(data["result"], list)
        self.assertIn("total_count", data)
        self.assertIn("start_index", data)
        self.assertIn("end_index", data)
        self.assertIn("has_more", data)
        self.assertGreater(data["total_count"], 0)

    def test_create_and_list_event(self):
        payload = {
            "title": "Pediatric Dentist Checkup",
            "event_type": "KID_ACTIVITY",
            "scheduled_at": "2026-11-20T14:30:00",
            "people_involved": ["Marcus", "Mom"],
            "notes": "Bring fluoride record",
        }
        resp = self.client.post("/api/v1/events", json=payload)
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        created = resp.json()
        self.assertEqual(created["title"], "Pediatric Dentist Checkup")
        self.assertIn("Marcus", created["people_involved"])
        event_id = created["id"]

        # Verify present in events list
        list_resp = self.client.get("/api/v1/events")
        self.assertEqual(list_resp.status_code, 200)
        events_envelope = list_resp.json()
        events = events_envelope["result"]
        self.assertTrue(any(e["id"] == event_id and e["title"] == "Pediatric Dentist Checkup" for e in events))

    def test_create_event_with_receipt_multipart(self):
        """Unified Event & Receipt Intake (Case B): Creates event & attaches receipt in one call."""
        fake_image_bytes = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C\x00"
        files = {
            "receipt_file": ("mad_mex_receipt.jpg", fake_image_bytes, "image/jpeg"),
        }
        data = {
            "title": "Family Dinner at Mad Mex",
            "event_type": "DINING",
            "scheduled_at": "2026-11-09T18:30:00",
            "duration_minutes": "75",
            "people_involved": '["Dad", "Mom", "Marcus"]',
            "notes": "Table 12, great fish tacos",
            "total_amount": "58.50",
        }
        resp = self.client.post("/api/v1/events", data=data, files=files)
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        res = resp.json()

        # Both top-level and "event" wrapper contain event details
        self.assertIn("id", res)
        self.assertEqual(res["title"], "Family Dinner at Mad Mex")
        self.assertIn("ingestion_job", res)
        self.assertIn("job_id", res["ingestion_job"])
        self.assertEqual(res["ingestion_job"]["filename"], "mad_mex_receipt.jpg")
        self.assertEqual(res["ingestion_job"]["status"], "PROCESSING")

    # --- 3. Standard Failure Response Tests (HTTP 404 & 422 JSON Format) ---
    def test_error_response_format_on_404(self):
        """Failure responses must return JSON with error, message, and status_code."""
        resp = self.client.post("/api/v1/conflicts/non_existent_cfl_999/acknowledge")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        error_data = resp.json()
        self.assertIn("error", error_data)
        self.assertIn("message", error_data)
        self.assertIn("status_code", error_data)
        self.assertEqual(error_data["status_code"], 404)
        self.assertIn("non_existent_cfl_999", error_data["message"])

    def test_error_response_format_on_validation_422(self):
        """Unprocessable entity must return standard JSON format with error and message."""
        # Missing required 'title' and 'event_type'
        invalid_payload = {"invalid_key": "some_value"}
        resp = self.client.post("/api/v1/events", json=invalid_payload)
        self.assertEqual(resp.status_code, 422)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        error_data = resp.json()
        self.assertIn("error", error_data)
        self.assertIn("message", error_data)
        self.assertIn("status_code", error_data)
        self.assertEqual(error_data["status_code"], 422)
        self.assertIn("title", error_data["message"])

    def test_error_response_generator_not_found(self):
        resp = self.client.post("/api/v1/generators/unknown_gen_xyz/spawn")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        error_data = resp.json()
        self.assertEqual(error_data["status_code"], 404)
        self.assertIn("unknown_gen_xyz", error_data["message"])

    # --- 4. Event Generators & Recurrence Tests ---
    def test_generators_list_and_create(self):
        list_resp = self.client.get("/api/v1/generators")
        self.assertEqual(list_resp.status_code, 200)
        self.assertTrue(list_resp.headers["content-type"].startswith("application/json"))

        gen_payload = {
            "name": "Marcus Bi-Weekly Piano Lesson",
            "event_type": "KID_ACTIVITY",
            "recurrence_cycle": "BI_WEEKLY",
            "target_weekday": 3,  # Thursday
            "default_start_time": "16:00:00",
            "default_duration_minutes": 45,
            "lead_time_days": 5,
        }
        create_resp = self.client.post("/api/v1/generators", json=gen_payload)
        self.assertEqual(create_resp.status_code, 201)
        created = create_resp.json()
        self.assertEqual(created["recurrence_cycle"], "BI_WEEKLY")
        self.assertEqual(created["target_weekday"], 3)

    # --- 5. Inventory & Shopping Tests ---
    def test_inventory_products(self):
        resp = self.client.get("/api/v1/inventory/products")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        data = resp.json()
        self.assertIn("result", data)
        self.assertIsInstance(data["result"], list)
        self.assertIn("total_count", data)
        self.assertIn("start_index", data)
        self.assertIn("end_index", data)
        self.assertIn("has_more", data)

    def test_inventory_transactions(self):
        resp = self.client.get("/api/v1/inventory/transactions")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        data = resp.json()
        self.assertIn("result", data)
        self.assertIsInstance(data["result"], list)
        self.assertIn("total_count", data)
        self.assertIn("start_index", data)
        self.assertIn("end_index", data)
        self.assertIn("has_more", data)

    def test_shopping_list(self):
        get_resp = self.client.get("/api/v1/shopping/shopping-list")
        self.assertEqual(get_resp.status_code, 200)
        self.assertTrue(get_resp.headers["content-type"].startswith("application/json"))
        self.assertIsInstance(get_resp.json(), list)

    # --- 6. Trips Tests ---
    def test_list_trips(self):
        resp = self.client.get("/api/v1/trips")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        self.assertIsInstance(resp.json(), list)

    # --- 7. Grounded Places & Quick Action GPS Tests ---
    def test_places_api_flow(self):
        """Test listing grounded places (Option 2 Autocomplete) and adding a verified physical place."""
        # 1. List places
        list_resp = self.client.get("/api/v1/places")
        self.assertEqual(list_resp.status_code, 200)
        places = list_resp.json()
        self.assertIsInstance(places, list)
        self.assertGreater(len(places), 0)
        # Verify Costco seeded place
        self.assertTrue(any(p["name"] == "Costco Wholesale" for p in places))

        # 2. Add a new grounded physical place (Option 2 Map search selection)
        new_place_payload = {
            "name": "Cranberry Pediatric Dentistry",
            "category": "medical",
            "address": "200 VIP Dr Suite 100, Wexford, PA 15090",
            "latitude": 40.6234,
            "longitude": -80.0512,
            "notes": "Marcus's primary pediatric dentist",
        }
        create_resp = self.client.post("/api/v1/places", json=new_place_payload)
        self.assertEqual(create_resp.status_code, 201)
        created_place = create_resp.json()
        self.assertEqual(created_place["name"], "Cranberry Pediatric Dentistry")
        self.assertIn("Wexford", created_place["address"])
        place_id = created_place["id"]

        # 3. Create scheduled event referencing this grounded place_id (Option 2)
        event_payload = {
            "title": "Marcus 6-Month Dental Cleaning",
            "event_type": "KID_ACTIVITY",
            "scheduled_at": "2026-12-15T10:00:00",
            "duration_minutes": 45,
            "place_id": place_id,
            "people_involved": ["Marcus", "Mom"],
        }
        event_resp = self.client.post("/api/v1/events", json=event_payload)
        self.assertEqual(event_resp.status_code, 201)
        created_event = event_resp.json()
        self.assertEqual(created_event["place_id"], place_id)

    def test_quick_action_gps_event_api(self):
        """Option 3: Quick action on-the-go event with browser GPS coordinates."""
        payload = {
            "title": "Costco Quick Restock",
            "event_type": "SHOPPING",
            "latitude": 40.6865,
            "longitude": -80.1065,
            "place_query": "Costco",
            "people_involved": ["Dad"],
            "total_amount": 128.50,
            "notes": "Milk and Paper Towels",
        }
        resp = self.client.post("/api/v1/events", json=payload)
        self.assertEqual(resp.status_code, 201)
        res = resp.json()
        self.assertEqual(res["title"], "Costco Quick Restock")
        self.assertIsNotNone(res["place_id"])
        self.assertEqual(res["shopping_detail"]["total_amount"], 128.50)
        self.assertIsNotNone(res["completed_at"])

    def test_place_repull_and_validation_via_service(self):
        """Creating a grounded place makes it immediately available on repull; blank address fails 400."""
        bad_resp = self.client.post(
            "/api/v1/places",
            json={"name": "Ungrounded Place", "address": "   "},
        )
        self.assertEqual(bad_resp.status_code, 400)
        self.assertIn("message", bad_resp.json())

        good_resp = self.client.post(
            "/api/v1/places",
            json={
                "name": "Target Cranberry",
                "category": "department_store",
                "address": "1717 Route 228, Cranberry Twp, PA 16066",
                "latitude": 40.6852,
                "longitude": -80.1041,
            },
        )
        self.assertEqual(good_resp.status_code, 201)
        created_id = good_resp.json()["id"]

        repull_resp = self.client.get("/api/v1/places")
        self.assertEqual(repull_resp.status_code, 200)
        places = repull_resp.json()
        self.assertTrue(any(p["id"] == created_id and p["name"] == "Target Cranberry" for p in places))

    def test_conflicts_and_ingest_via_service(self):
        """Verify conflicts and ingest endpoints route cleanly through domain services."""
        conflicts_resp = self.client.get("/api/v1/conflicts")
        self.assertEqual(conflicts_resp.status_code, 200)
        self.assertIsInstance(conflicts_resp.json(), list)

        jobs_resp = self.client.get("/api/v1/ingest/jobs")
        self.assertEqual(jobs_resp.status_code, 200)
        self.assertIsInstance(jobs_resp.json(), list)

    def test_inventory_consume_undo_and_conversions_via_service(self):
        """Verify inventory router delegates consume, undo, and conversions to InventoryService."""
        conv_resp = self.client.get("/api/v1/inventory/conversions")
        self.assertEqual(conv_resp.status_code, 200)
        self.assertIsInstance(conv_resp.json(), list)

        consume_resp = self.client.post("/api/v1/inventory/products/prod_tp/consume", json={"amount": 1.0})
        self.assertEqual(consume_resp.status_code, 200)
        self.assertEqual(consume_resp.json()["product_id"], "prod_tp")

        undo_resp = self.client.post("/api/v1/inventory/products/prod_tp/undo-consume")
        self.assertEqual(undo_resp.status_code, 200)
        self.assertEqual(undo_resp.json()["product_id"], "prod_tp")

    def test_create_product_endpoint_with_multiplier(self):
        """Verify POST /api/v1/inventory/products creates product in stock with bulk multiplier mapping."""
        payload = {
            "name": "Kirkland Signature Cashews",
            "category": "snacks",
            "qu_stock_id": "oz",
            "qu_purchase_id": "tub",
            "qu_factor": 40.0,
            "initial_stock": 40.0,
            "daily_burn_rate": 1.5,
            "store_name": "Costco",
            "receipt_raw_text": "KS CASHEWS",
            "is_fridge_quick_tile": True,
        }
        resp = self.client.post("/api/v1/inventory/products", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("id", data)
        self.assertEqual(data["name"], "Kirkland Signature Cashews")
        self.assertEqual(data["unit"], "oz")
        self.assertEqual(data["current_stock"], 40.0)


if __name__ == "__main__":
    unittest.main()

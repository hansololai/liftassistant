"""Unit tests for Phase 2: Core Domain Services & Business Rules."""

from datetime import date, datetime, timedelta
from pathlib import Path
import os
import sqlite3
import unittest

from liftassistant.db.connection import close_connection_pool, get_db, init_db
from liftassistant.db.repository import EventGeneratorRepository, EventRepository, InventoryRepository
from liftassistant.db.seed import seed_database
from liftassistant.models.domain import (
    DiningDetail,
    EventGenerator,
    LifeEvent,
    MaintenanceDetail,
    Place,
    Product,
    ShoppingDetail,
)
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.event_generator_service import EventGeneratorService
from liftassistant.services.event_manager import EventManager
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.trip_service import TripService, calculate_haversine_distance_miles

TEST_DB_PATH = Path("data") / "test_phase2.db"


class TestPhase2DomainServices(unittest.TestCase):
    """Test suite for Phase 2 business logic services."""

    def setUp(self):
        close_connection_pool(TEST_DB_PATH)
        if TEST_DB_PATH.exists():
            os.remove(TEST_DB_PATH)

        init_db(TEST_DB_PATH)
        seed_database(TEST_DB_PATH)

        self.conn = sqlite3.connect(str(TEST_DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")

        self.event_repo = EventRepository(self.conn)
        self.inv_repo = InventoryRepository(self.conn)
        self.gen_repo = EventGeneratorRepository(self.conn)

        self.event_manager = EventManager(self.event_repo)
        self.inv_service = InventoryService(self.inv_repo)
        self.gen_service = EventGeneratorService(self.gen_repo, self.event_repo)
        self.conflict_engine = ConflictEngine()
        self.trip_service = TripService()

    def tearDown(self):
        self.conn.close()
        close_connection_pool(TEST_DB_PATH)
        if TEST_DB_PATH.exists():
            os.remove(TEST_DB_PATH)


    # 1. Event Manager Tests
    def test_event_manager_create_and_duration(self):
        start = datetime(2026, 11, 15, 10, 0, 0)
        event = LifeEvent(
            id="evt_test_mgr_01",
            title="Dr. Smith Ortho Checkup",
            event_type="CUSTOM",
            scheduled_at=start,
            people_involved=["Marcus", "Mom"],
        )
        saved = self.event_manager.create_event(event)
        self.assertEqual(saved.id, "evt_test_mgr_01")
        # Automatic duration set to 60 mins
        self.assertEqual(saved.scheduled_end_at, start + timedelta(minutes=60))

    def test_event_manager_complete(self):
        evt = self.event_manager.complete_event("evt_tax_01", completed_at=datetime(2026, 11, 12, 14, 0))
        self.assertIsNotNone(evt)
        self.assertIsNotNone(evt.completed_at)

    def test_event_manager_update(self):
        # Seeded event evt_swim_01
        updated = self.event_manager.update_event(
            "evt_swim_01",
            title="Marcus Swim Team Practice (Extended)",
            notes="Bring goggles and towel",
            duration_minutes=90,
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.title, "Marcus Swim Team Practice (Extended)")
        self.assertEqual(updated.notes, "Bring goggles and towel")
        self.assertEqual(updated.scheduled_end_at - updated.scheduled_at, timedelta(minutes=90))

    def test_event_manager_delete(self):
        """Verify hard deletion of events is strictly disallowed to preserve tractability."""
        evt = LifeEvent(
            id="evt_to_delete",
            title="Temporary Event",
            event_type="CUSTOM",
            scheduled_at=datetime(2026, 11, 25, 9, 0),
        )
        self.event_manager.create_event(evt)
        self.assertIsNotNone(self.event_manager.get_event("evt_to_delete"))

        # Deletion must raise ValueError and event must remain intact
        with self.assertRaises(ValueError):
            self.event_manager.delete_event("evt_to_delete")
        self.assertIsNotNone(self.event_manager.get_event("evt_to_delete"))

    def test_event_api_endpoints_direct(self):
        from fastapi import HTTPException
        from liftassistant.api.routers.events import (
            get_event,
            update_event,
            complete_event_endpoint,
            uncomplete_event_endpoint,
            delete_event_endpoint,
            EventUpdateRequest,
            CompleteEventRequest,
        )
        # 1. get_event
        res = get_event("evt_swim_01", event_manager=self.event_manager)
        self.assertEqual(res["id"], "evt_swim_01")
        self.assertIn("title", res)

        # 2. update_event
        up_req = EventUpdateRequest(title="Updated Title via Endpoint", notes="Updated notes")
        res_up = update_event("evt_swim_01", payload=up_req, event_manager=self.event_manager)
        self.assertEqual(res_up["title"], "Updated Title via Endpoint")

        # 3. complete_event_endpoint
        comp_req = CompleteEventRequest(completed_at=datetime(2026, 11, 10, 18, 0), total_amount=25.50)
        res_comp = complete_event_endpoint("evt_swim_01", payload=comp_req, event_manager=self.event_manager)
        self.assertIsNotNone(res_comp["completed_at"])

        # 3b. uncomplete_event_endpoint marks event incomplete / reopens
        res_uncomp = uncomplete_event_endpoint("evt_swim_01", event_manager=self.event_manager)
        self.assertIsNone(res_uncomp["completed_at"])

        # 4. delete_event_endpoint must raise HTTP 405 Method Not Allowed
        with self.assertRaises(HTTPException) as ctx:
            delete_event_endpoint("evt_swim_01")
        self.assertEqual(ctx.exception.status_code, 405)
        self.assertIsNotNone(self.event_manager.get_event("evt_swim_01"))

    def test_check_event_conflict_dry_run(self):
        from liftassistant.api.routers.events import (
            check_event_conflict,
            ConflictCheckRequest,
        )

        # 1. Test facility mutex collision at YMCA Warm Water Pool (Aqua Zumba at 9:00 AM - 10:00 AM on Nov 14)
        req_fac = ConflictCheckRequest(
            title="Family Open Swim at YMCA",
            scheduled_at=datetime(2026, 11, 14, 9, 15, 0),
            duration_minutes=30,
            notes="Warm Water Pool",
            place_id="pl_ymca",
            people_involved=["Marcus", "Dad"],
        )
        res_fac = check_event_conflict(payload=req_fac, event_manager=self.event_manager)
        self.assertTrue(res_fac["has_conflict"])
        self.assertTrue(any(c["conflict_type"] == "FACILITY_MUTEX" for c in res_fac["conflicts"]))

        # 1b. Non-aquatic event at YMCA (e.g. Basketball) does NOT trigger pool conflict
        req_bball = ConflictCheckRequest(
            title="YMCA Basketball with Marcus",
            scheduled_at=datetime(2026, 11, 14, 9, 15, 0),
            duration_minutes=30,
            place_id="pl_ymca",
            people_involved=["Marcus", "Dad"],
        )
        res_bball = check_event_conflict(payload=req_bball, event_manager=self.event_manager)
        self.assertFalse(res_bball["has_conflict"])

        # 2. Test person overlap with an existing event
        self.event_manager.create_event(
            LifeEvent(
                id="evt_marcus_soccer",
                title="Marcus Soccer Practice",
                event_type="KID_ACTIVITY",
                scheduled_at=datetime(2026, 11, 16, 10, 0, 0),
                scheduled_end_at=datetime(2026, 11, 16, 11, 0, 0),
                people_involved=["Marcus", "Mom"],
            )
        )
        # Check draft event overlapping at 10:30 AM with Marcus
        req_overlap = ConflictCheckRequest(
            title="Marcus Dentist",
            scheduled_at=datetime(2026, 11, 16, 10, 30, 0),
            duration_minutes=45,
            people_involved=["Marcus", "Dad"],
        )
        res_overlap = check_event_conflict(payload=req_overlap, event_manager=self.event_manager)
        self.assertTrue(res_overlap["has_conflict"])
        self.assertTrue(any(c["conflict_type"] == "PERSON_OVERLAP" for c in res_overlap["conflicts"]))

        # 3. Test non-conflicting time slot (at 2:00 PM)
        req_ok = ConflictCheckRequest(
            title="Marcus Dentist Safe",
            scheduled_at=datetime(2026, 11, 16, 14, 0, 0),
            duration_minutes=45,
            people_involved=["Marcus", "Dad"],
        )
        res_ok = check_event_conflict(payload=req_ok, event_manager=self.event_manager)
        self.assertFalse(res_ok["has_conflict"])
        self.assertEqual(len(res_ok["conflicts"]), 0)

    def test_urgency_badge_calculations(self):
        ref = datetime(2026, 11, 10, 12, 0, 0)

        # Due Today
        evt_today = LifeEvent(
            title="Due Today Event",
            event_type="CUSTOM",
            deadline=datetime(2026, 11, 10, 23, 59, 59),
        )
        badge_today = self.event_manager.calculate_urgency_badge(evt_today, reference_time=ref)
        self.assertIsNotNone(badge_today)
        self.assertEqual(badge_today["status"], "DUE_TODAY")

        # Overdue
        evt_overdue = LifeEvent(
            title="Past Due Event",
            event_type="CUSTOM",
            deadline=datetime(2026, 11, 8, 12, 0, 0),
        )
        badge_overdue = self.event_manager.calculate_urgency_badge(evt_overdue, reference_time=ref)
        self.assertIsNotNone(badge_overdue)
        self.assertEqual(badge_overdue["status"], "OVERDUE")

        # 3 days left
        evt_soon = LifeEvent(
            title="Soon Event",
            event_type="CUSTOM",
            deadline=datetime(2026, 11, 13, 12, 0, 0),
        )
        badge_soon = self.event_manager.calculate_urgency_badge(evt_soon, reference_time=ref)
        self.assertIsNotNone(badge_soon)
        self.assertEqual(badge_soon["status"], "CRITICAL")
        self.assertEqual(badge_soon["days_left"], 3)

    # 2. Event Generator Service Tests
    def test_generator_recurrence_and_spawn_with_deadline(self):
        # Butler Property tax generator: Nov 15 target, 30 days lead time
        gen = self.gen_repo.list_generators()[0]
        self.assertEqual(gen.id, "gen_tax")

        # Nov 1, 2026 is 14 days before Nov 15, within 30-day lead time window -> Should generate!
        ref_date = date(2026, 11, 1)
        should_gen = self.gen_service.should_generate(gen, ref_date)
        self.assertTrue(should_gen)

        spawned = self.gen_service.spawn_event(gen, ref_date)
        self.assertIsNotNone(spawned.id)
        self.assertEqual(spawned.title, gen.title)
        self.assertEqual(spawned.event_type, gen.event_type)
        self.assertIsNotNone(spawned.deadline)
        # Deadline matches target date (Nov 15, 2026 at 23:59:59)
        self.assertEqual(spawned.deadline.date(), date(2026, 11, 15))

        # Check duplicate suppression within same lead time window
        should_gen_again = self.gen_service.should_generate(gen, date(2026, 11, 2))
        self.assertFalse(should_gen_again)

    # 3. Conflict Engine Tests
    def test_conflict_facility_mutex(self):
        # YMCA Warm Water Pool occupied 9:00 AM - 10:00 AM on Nov 14 by Aqua Zumba
        pool_event = LifeEvent(
            id="evt_pool_clash",
            title="Marcus Open Swim at YMCA (Warm Water Pool)",
            event_type="KID_ACTIVITY",
            scheduled_at=datetime(2026, 11, 14, 9, 15, 0),
            scheduled_end_at=datetime(2026, 11, 14, 9, 45, 0),
        )
        conflicts = self.conflict_engine.detect_conflicts([pool_event])
        self.assertTrue(any(c.conflict_type == "FACILITY_MUTEX" for c in conflicts))

        # Non-aquatic YMCA event should NOT trigger pool mutex conflict
        gym_event = LifeEvent(
            id="evt_gym_ok",
            title="Dad Basketball at YMCA",
            event_type="CUSTOM",
            scheduled_at=datetime(2026, 11, 14, 9, 15, 0),
            scheduled_end_at=datetime(2026, 11, 14, 9, 45, 0),
        )
        gym_conflicts = self.conflict_engine.detect_conflicts([gym_event])
        self.assertFalse(any(c.conflict_type == "FACILITY_MUTEX" for c in gym_conflicts))

    def test_conflict_person_overlap(self):
        # Dad double-booked at 6:00 PM
        evt1 = LifeEvent(
            id="evt_school_board",
            title="School Board Meeting",
            event_type="CUSTOM",
            scheduled_at=datetime(2026, 11, 12, 18, 0, 0),
            scheduled_end_at=datetime(2026, 11, 12, 19, 30, 0),
            people_involved=["Dad"],
        )
        evt2 = LifeEvent(
            id="evt_bedtime",
            title="Marcus Bedtime Routine",
            event_type="KID_ACTIVITY",
            scheduled_at=datetime(2026, 11, 12, 18, 0, 0),
            scheduled_end_at=datetime(2026, 11, 12, 19, 0, 0),
            people_involved=["Dad", "Marcus"],
        )
        conflicts = self.conflict_engine.detect_conflicts([evt1, evt2])
        self.assertTrue(any(c.conflict_type == "PERSON_OVERLAP" for c in conflicts))

    def test_conflict_travel_buffer(self):
        # Event 1 in North Hills ends at 3:45 PM. Event 2 in Cranberry starts at 4:00 PM (15m gap vs 26m drive)
        evt1 = LifeEvent(
            id="evt_pediatrician",
            title="Marcus Pediatrician North Hills",
            event_type="CUSTOM",
            scheduled_at=datetime(2026, 11, 13, 15, 0, 0),
            scheduled_end_at=datetime(2026, 11, 13, 15, 45, 0),
            place_id="pediatrician_north_hills",
            people_involved=["Mom", "Marcus"],
        )
        evt2 = LifeEvent(
            id="evt_soccer",
            title="Marcus Soccer Practice Cranberry Park",
            event_type="KID_ACTIVITY",
            scheduled_at=datetime(2026, 11, 13, 16, 0, 0),
            scheduled_end_at=datetime(2026, 11, 13, 17, 0, 0),
            place_id="cranberry_park",
            people_involved=["Mom", "Marcus"],
        )
        conflicts = self.conflict_engine.detect_conflicts([evt1, evt2])
        self.assertTrue(any(c.conflict_type == "TRAVEL_BUFFER" for c in conflicts))

    def test_conflict_checking_on_all_creation_paths(self):
        """Verify that conflict detection is executed across all event creation paths."""
        # Option 2: create_scheduled_event flags facility blackout conflict via live YMCA schedule
        event_opt2 = self.event_manager.create_scheduled_event(
            title="Open Swim at YMCA Warm Water Pool",
            event_type="CUSTOM",
            scheduled_at=datetime(2026, 11, 14, 9, 15, 0),  # during YMCA Aqua Zumba (9:00 AM - 10:00 AM)
            duration_minutes=45,
            place_id="pl_ymca",
        )
        self.assertTrue(event_opt2.has_conflict)
        self.assertEqual(event_opt2.conflict_status, "DETECTED")
        self.assertIn("Warm Water Pool", event_opt2.conflict_reason)
        self.assertIsNone(event_opt2.latitude)
        self.assertIsNone(event_opt2.longitude)

    def test_quick_action_stores_lat_long_even_if_grounding_fails(self):
        """Quick action events must preserve user lat/long so we can retry grounding later."""
        # Query for an unknown location in the middle of nowhere: grounding will fail/return ungrounded
        event = self.event_manager.create_quick_action_event(
            title="Random Field Stop",
            event_type="CUSTOM",
            latitude=40.12345,
            longitude=-80.54321,
            place_query="Nowhere Unknown Spot 99999",
            duration_minutes=15,
        )
        self.assertIsNotNone(event.id)
        self.assertEqual(event.latitude, 40.12345)
        self.assertEqual(event.longitude, -80.54321)
        self.assertIsNotNone(event.completed_at)

        # Retrieve from repository to ensure DB persistence of lat/long
        retrieved = self.event_repo.get_event(event.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.latitude, 40.12345)
        self.assertEqual(retrieved.longitude, -80.54321)

    # 4. Inventory Service Tests
    def test_fridge_door_pad_consume(self):
        # Product tp: initial stock 14
        result = self.inv_service.fridge_door_pad_consume("prod_tp", amount=1.0)
        self.assertEqual(result["product_id"], "prod_tp")
        self.assertEqual(result["amount_consumed"], 1.0)
        self.assertEqual(result["new_stock"], 13.0)

    def test_restock_bulk_multiplier(self):
        # 1 Costco pack of TP has qu_factor = 36. 13 + 36 = 49 rolls
        self.inv_service.fridge_door_pad_consume("prod_tp", amount=1.0)  # down to 13
        result = self.inv_service.restock_from_purchase("prod_tp", purchase_quantity=1.0)
        self.assertEqual(result["purchased_qty"], 1.0)
        self.assertEqual(result["multiplier"], 36.0)
        self.assertEqual(result["units_added"], 36.0)
        self.assertEqual(result["total_stock"], 49.0)

    def test_shopping_horizon_and_depletion(self):
        horizon = self.inv_service.get_shopping_horizon(horizon_days=7.0)
        self.assertIn("sufficient_items", horizon)
        self.assertIn("queued_items", horizon)

        dep_res = self.inv_service.confirm_depletion("dep_test_1", "prod_milk", 0.5)
        self.assertEqual(dep_res["status"], "CONFIRMED")
        self.assertEqual(dep_res["amount_deducted"], 0.5)

    def test_create_product_with_unit_multiplier_mapping(self):
        """Verify dynamic creation of products in stock with packaging unit multiplier."""
        new_prod = self.inv_service.create_product(
            name="KS Create-A-Size Paper Towels",
            category="household",
            qu_stock_id="roll",
            qu_purchase_id="pack",
            qu_factor=12.0,
            initial_stock=6.0,
            daily_burn_rate=0.5,
            store_name="Costco",
            receipt_raw_text="KS PAPER TOWELS",
            is_fridge_quick_tile=True,
        )
        self.assertIsNotNone(new_prod["id"])
        self.assertEqual(new_prod["unit"], "roll")
        self.assertEqual(new_prod["current_stock"], 6.0)

        # Restock 2 packs -> should add 2 * 12 = 24 rolls -> total 6 + 24 = 30 rolls
        restock = self.inv_service.restock_from_purchase(new_prod["id"], purchase_quantity=2.0)
        self.assertEqual(restock["units_added"], 24.0)
        self.assertEqual(restock["total_stock"], 30.0)

        # Verify multiplier table contains the product_id link and product_name
        multipliers = self.inv_service.list_item_multipliers(store="Costco")
        matched = next((m for m in multipliers if m["item"] == "KS PAPER TOWELS"), None)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["multiplier"], 12.0)
        self.assertEqual(matched["product_id"], new_prod["id"])
        self.assertEqual(matched["product_name"], "KS Create-A-Size Paper Towels")

    # 5. Trip Service Tests
    def test_trip_inverted_geofence(self):
        # Home Base: Cranberry Twp (40.6873, -80.1078)
        # Wexford, PA: 40.6300, -80.0500 (~5.1 miles) -> Local
        eval_local = self.trip_service.evaluate_event_for_trip("Wexford Giant Eagle", 40.6300, -80.0500)
        self.assertFalse(eval_local["trip_mode_triggered"])
        self.assertEqual(eval_local["status"], "LOCAL_CRANBERRY_METRO")

        # Walt Disney World, Orlando FL: 28.3852, -81.5639 (~860 miles) -> Trip Mode Triggered!
        eval_trip = self.trip_service.evaluate_event_for_trip("Magic Kingdom Dinner", 28.3852, -81.5639)
        self.assertTrue(eval_trip["trip_mode_triggered"])
        self.assertEqual(eval_trip["status"], "OUT_OF_TOWN_TRIP")
        self.assertGreater(eval_trip["distance_from_base_miles"], 800)

    def test_recheck_conflicts_and_auto_resolution(self):
        """Verify recheck-conflicts synchronizes database flags and clears stale conflict status."""
        from liftassistant.api.routers.events import (
            get_conflicts,
            recheck_all_conflicts,
            resolve_conflict_endpoint,
            ConflictActionRequest,
            RecheckConflictsRequest,
        )

        # 1. Create two colliding events
        evt1 = LifeEvent(
            id="evt_sync_clash_1",
            title="Marcus Math Tutoring",
            event_type="CUSTOM",
            scheduled_at=datetime(2026, 11, 20, 15, 0, 0),
            scheduled_end_at=datetime(2026, 11, 20, 16, 0, 0),
            people_involved=["Marcus", "Dad"],
        )
        evt2 = LifeEvent(
            id="evt_sync_clash_2",
            title="Marcus Orthodontist",
            event_type="CUSTOM",
            scheduled_at=datetime(2026, 11, 20, 15, 30, 0),
            scheduled_end_at=datetime(2026, 11, 20, 16, 30, 0),
            people_involved=["Marcus", "Dad"],
        )
        self.event_manager.create_event(evt1)
        self.event_manager.create_event(evt2)

        # 2. Recheck conflicts -> should detect clash and mark in DB
        recheck_res = recheck_all_conflicts(
            payload=RecheckConflictsRequest(force_refresh=False),
            event_manager=self.event_manager,
        )
        self.assertGreaterEqual(recheck_res["total_conflicts"], 1)

        db_evt2 = self.event_manager.get_event("evt_sync_clash_2")
        self.assertIsNotNone(db_evt2)
        self.assertTrue(db_evt2.has_conflict)
        self.assertEqual(db_evt2.conflict_status, "DETECTED")

        # 3. Move evt2 to a non-colliding time slot (7:00 PM)
        self.event_manager.update_event(
            "evt_sync_clash_2",
            scheduled_at=datetime(2026, 11, 20, 19, 0, 0),
            duration_minutes=60,
        )

        # 4. Trigger recheck conflicts again -> conflict clears, DB status transitions to RESOLVED!
        recheck_after = recheck_all_conflicts(
            payload=RecheckConflictsRequest(force_refresh=False),
            event_manager=self.event_manager,
        )
        conflicts_list = recheck_after["conflicts"]
        clash_remaining = [c for c in conflicts_list if c["event_id"] in ("evt_sync_clash_1", "evt_sync_clash_2")]
        self.assertEqual(len(clash_remaining), 0)

        # Event in DB is no longer marked as has_conflict
        db_evt2_cleared = self.event_manager.get_event("evt_sync_clash_2")
        self.assertFalse(db_evt2_cleared.has_conflict)
        self.assertEqual(db_evt2_cleared.conflict_status, "RESOLVED")


if __name__ == "__main__":
    unittest.main()

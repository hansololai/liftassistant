"""Phase 1 Automated Test Suite: SQLite Schema, Relational Polymorphism, and Grocy Engine."""

import os
import sqlite3
import unittest
from pathlib import Path
from liftassistant.db.connection import close_connection_pool, get_db, init_db
from liftassistant.db.seed import seed_database
from liftassistant.db.repository import EventGeneratorRepository, EventRepository, InventoryRepository
from liftassistant.models.domain import DiningDetail, EventGenerator, LifeEvent, MaintenanceDetail


class TestPhase1Schema(unittest.TestCase):
    """Verifies DDL constraints, Approach 2 polymorphism, and Grocy calculations."""

    @classmethod
    def setUpClass(cls):
        cls.test_db_path = Path("data") / "test_phase1.db"
        if cls.test_db_path.exists():
            os.remove(cls.test_db_path)
        
        # 1. Initialize schema
        init_db(cls.test_db_path)
        
        # 2. Seed baseline data
        seed_database(cls.test_db_path)

    @classmethod
    def tearDownClass(cls):
        close_connection_pool(cls.test_db_path)
        if cls.test_db_path.exists():
            try:
                os.remove(cls.test_db_path)
            except Exception:
                pass

    def test_01_seeded_tables_exist_and_populated(self):
        """Verify core tables are present and seeded."""
        with get_db(self.test_db_path) as conn:
            cursor = conn.cursor()
            tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            
            expected_tables = [
                "places", "people", "events", "dining_details", "shopping_details",
                "household_equipment", "maintenance_details",
                "storage_locations", "quantity_units", "products", "product_unit_conversions",
                "stock", "stock_transactions", "depletion_proposals", "receipts",
                "receipt_items", "shopping_list", "trips", "trip_stops"
            ]
            for t in expected_tables:
                self.assertIn(t, tables, f"Expected table '{t}' to exist in schema")

            # Check seeded places count
            places_count = cursor.execute("SELECT COUNT(*) FROM places").fetchone()[0]
            self.assertGreaterEqual(places_count, 5)

            # Check seeded products count
            products_count = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            self.assertGreaterEqual(products_count, 5)

    def test_02_approach_2_relational_polymorphism_mutex(self):
        """CRITICAL: Approach 2 test.
        Guarantees that an event CANNOT have multiple conflicting details.
        """
        with get_db(self.test_db_path) as conn:
            cursor = conn.cursor()

            # Step 1: Insert a DINING event into events
            cursor.execute(
                """
                INSERT INTO events (id, title, event_type, source) 
                VALUES ('evt_test_dining', 'Dinner at Cantina', 'DINING', 'MANUAL')
                """
            )

            # Step 2: Insert into dining_details -> MUST SUCCEED
            cursor.execute(
                """
                INSERT INTO dining_details (event_id, event_type, rating) 
                VALUES ('evt_test_dining', 'DINING', 5)
                """
            )
            self.assertEqual(cursor.rowcount, 1)

            # Step 3: Attempt to insert a second dining_detail row for same event -> MUST FAIL (PK uniqueness)
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO dining_details (event_id, event_type, rating) 
                    VALUES ('evt_test_dining', 'DINING', 4)
                    """
                )

            # Step 4: Attempt to insert the DINING event into maintenance_details -> MUST FAIL (Composite FK violation!)
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO maintenance_details (event_id, event_type, equipment_id, service_type) 
                    VALUES ('evt_test_dining', 'MAINTENANCE', 'eq_odyssey', 'oil_change')
                    """
                )

    def test_03_on_delete_cascade_cleans_details(self):
        """Verify ON DELETE CASCADE automatically removes detail row when event is deleted."""
        with get_db(self.test_db_path) as conn:
            cursor = conn.cursor()

            # Insert test event and dining detail
            cursor.execute(
                "INSERT INTO events (id, title, event_type, source) VALUES ('evt_cascade_test', 'Lunch', 'DINING', 'MANUAL')"
            )
            cursor.execute(
                "INSERT INTO dining_details (event_id, event_type, rating) VALUES ('evt_cascade_test', 'DINING', 4)"
            )

            # Verify row exists
            row = cursor.execute("SELECT * FROM dining_details WHERE event_id = 'evt_cascade_test'").fetchone()
            self.assertIsNotNone(row)

            # Delete parent event
            cursor.execute("DELETE FROM events WHERE id = 'evt_cascade_test'")

            # Verify child detail was automatically deleted via CASCADE
            row_after = cursor.execute("SELECT * FROM dining_details WHERE event_id = 'evt_cascade_test'").fetchone()
            self.assertIsNone(row_after, "dining_details row should be deleted by ON DELETE CASCADE")

    def test_04_costco_bulk_unit_multiplier(self):
        """Test Grocy bulk package multiplier factor: 1 Costco pack of toilet paper = 36 rolls."""
        with get_db(self.test_db_path) as conn:
            repo = InventoryRepository(conn)

            # Initial toilet paper stock was seeded at 14 rolls
            cursor = conn.cursor()
            initial_stock = cursor.execute("SELECT amount FROM stock WHERE product_id = 'prod_tp'").fetchone()[0]
            self.assertEqual(initial_stock, 14.0)

            # Buy 1 pack at Costco -> qu_factor is 36.0 -> adds +36.0 rolls
            added_rolls = repo.restock_with_bulk_multiplier("prod_tp", purchase_quantity=1.0)
            self.assertEqual(added_rolls, 36.0)

            # New stock should be 14 + 36 = 50 rolls
            new_stock = cursor.execute("SELECT amount FROM stock WHERE product_id = 'prod_tp'").fetchone()[0]
            self.assertEqual(new_stock, 50.0)

    def test_05_fridge_pad_1_tap_consume(self):
        """Test Fridge Door Pad 1-tap decrement."""
        with get_db(self.test_db_path) as conn:
            repo = InventoryRepository(conn)

            # Initial bananas stock is 2.0 ea
            cursor = conn.cursor()
            initial = cursor.execute("SELECT amount FROM stock WHERE product_id = 'prod_banana'").fetchone()[0]
            self.assertEqual(initial, 2.0)

            # Tap fridge pad: consume 1 banana
            result = repo.consume_stock("prod_banana", amount=1.0, source="FRIDGE_PAD")
            self.assertEqual(result["current_stock"], 1.0)

            # Verify transaction was logged
            tx = cursor.execute(
                "SELECT * FROM stock_transactions WHERE product_id = 'prod_banana' AND source = 'FRIDGE_PAD' ORDER BY created_at DESC"
            ).fetchone()
            self.assertIsNotNone(tx)
            self.assertEqual(tx["amount"], -1.0)

    def test_06_7_day_rolling_horizon_rule(self):
        """Test 7-Day Horizon Rule: items with runway >= 7 days are suppressed; < 7 days are queued."""
        with get_db(self.test_db_path) as conn:
            repo = InventoryRepository(conn)
            list_data = repo.get_shopping_list(horizon_days=7.0)

            self.assertGreater(list_data["sufficient_count"], 0)
            self.assertGreater(list_data["low_stock_count"], 0)

            # Check that sufficient items have runway >= 7
            for item in list_data["sufficient_items"]:
                self.assertGreaterEqual(item["days_runway"], 7.0)

            # Check that queued low stock items have runway < 7
            for item in list_data["queued_items"]:
                self.assertLess(item["days_runway"], 7.0)

    def test_07_event_deadline_and_urgency_sorting(self):
        """Test that events store deadlines and can be sorted by closest deadline first."""
        with get_db(self.test_db_path) as conn:
            repo = EventRepository(conn)

            # Query upcoming events sorted by deadline
            upcoming = repo.list_events(status="upcoming", sort_by_deadline=True)
            self.assertGreaterEqual(len(upcoming), 2)

            # evt_swim_01 is due Nov 9 16:00, evt_tax_01 deadline is Nov 15 23:59
            # Closest deadline (swim lesson today) should appear before tax deadline!
            deadlines = [e.deadline or e.scheduled_at for e in upcoming if e.deadline or e.scheduled_at]
            for i in range(len(deadlines) - 1):
                self.assertLessEqual(deadlines[i], deadlines[i + 1])

            # Verify specific event has its deadline populated
            tax_event = repo.get_event("evt_tax_01")
            self.assertIsNotNone(tax_event)
            self.assertIsNotNone(tax_event.deadline)
            self.assertIn("2026-11-15", str(tax_event.deadline))

    def test_08_event_generators_recurrence_and_deadlines(self):
        """Test event_generators table and annual recurrence rules with deadline offsets."""
        with get_db(self.test_db_path) as conn:
            gen_repo = EventGeneratorRepository(conn)
            generators = gen_repo.list_generators()

            self.assertGreaterEqual(len(generators), 2)
            gen_titles = [g.title for g in generators]
            self.assertIn("Annual County Property Tax Payment", gen_titles)
            self.assertIn("Honda Odyssey State Inspection & Emissions", gen_titles)

            tax_gen = next(g for g in generators if g.id == "gen_tax")
            self.assertEqual(tax_gen.frequency, "YEARLY")
            self.assertTrue(tax_gen.has_deadline)
            self.assertEqual(tax_gen.lead_time_days, 30)
            self.assertEqual(tax_gen.deadline_time, "23:59:59")


if __name__ == "__main__":
    unittest.main()

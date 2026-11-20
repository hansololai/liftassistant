"""Unit tests for Phase 3: Omnichannel CAS Ingestion & Deferred AI Worker."""

from datetime import datetime
import os
from pathlib import Path
import shutil
import sqlite3
import unittest

from liftassistant.db.connection import close_connection_pool, init_db
from liftassistant.db.repository import EventRepository, InventoryRepository
from liftassistant.db.seed import seed_database
from liftassistant.models.domain import LifeEvent, ShoppingDetail
from liftassistant.services.cas_storage import CASStorage
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.receipt_parser import ReceiptParser
from liftassistant.services.receipt_worker import ReceiptWorker

TEST_DB_PATH = Path("data") / "test_phase3.db"
TEST_CAS_DIR = Path("data") / "test_receipt_store"


class TestPhase3CASAndWorker(unittest.TestCase):
    """Test suite for CAS Storage and Deferred AI Receipt Worker."""

    def setUp(self):
        close_connection_pool(TEST_DB_PATH)
        if TEST_DB_PATH.exists():
            os.remove(TEST_DB_PATH)
        if TEST_CAS_DIR.exists():
            shutil.rmtree(TEST_CAS_DIR)

        init_db(TEST_DB_PATH)
        seed_database(TEST_DB_PATH)

        self.conn = sqlite3.connect(str(TEST_DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")

        self.event_repo = EventRepository(self.conn)
        self.inv_repo = InventoryRepository(self.conn)
        self.inv_service = InventoryService(self.inv_repo)

        self.cas = CASStorage(root_dir=TEST_CAS_DIR)
        self.parser = ReceiptParser()
        self.worker = ReceiptWorker(
            conn=self.conn,
            cas_storage=self.cas,
            receipt_parser=self.parser,
            inventory_service=self.inv_service,
        )

    def tearDown(self):
        self.conn.close()
        close_connection_pool(TEST_DB_PATH)
        if TEST_DB_PATH.exists():
            os.remove(TEST_DB_PATH)
        if TEST_CAS_DIR.exists():
            shutil.rmtree(TEST_CAS_DIR)

    # 1. CAS Storage Tests
    def test_cas_storage_and_deduplication(self):
        sample_bytes = b"MOCK_RECEIPT_IMAGE_DATA_12345"
        res1 = self.cas.store_file(sample_bytes, "costco_receipt.jpg")

        self.assertIsNotNone(res1["file_hash"])
        self.assertFalse(res1["is_duplicate"])
        self.assertTrue(Path(res1["file_path"]).exists())

        # Second store with identical content must detect duplicate without re-writing
        res2 = self.cas.store_file(sample_bytes, "duplicate_copy.jpg")
        self.assertEqual(res1["file_hash"], res2["file_hash"])
        self.assertTrue(res2["is_duplicate"])
        self.assertEqual(res1["file_path"], res2["file_path"])

        # Integrity check
        is_valid = self.cas.verify_integrity(Path(res1["file_path"]), res1["file_hash"])
        self.assertTrue(is_valid)

        # Retrieval check
        read_bytes = self.cas.read_file(res1["file_hash"])
        self.assertEqual(read_bytes, sample_bytes)

    # 2. Receipt Parser Tests
    def test_receipt_parser_costco_and_grocy_matching(self):
        costco_transcript = """
        COSTCO WHOLESALE #1024
        1050 Cranberry Square Dr, Cranberry Twp, PA 16066
        
        KIRKLAND BATH TISSUE 36/PK  1  18.99
        WHOLE MILK ORGANIC 2/PK     1   7.49
        LARGE BROWN EGGS 48/CT      1   9.99
        
        SUBTOTAL                     36.47
        PA TAX                        1.14
        TOTAL                        37.61
        VISA **** 4819
        """
        receipt = self.parser.parse_from_text(
            raw_text=costco_transcript,
            file_hash="test_sha_123",
            file_path="data/receipt_store/test_sha_123.jpg",
            original_filename="costco_nov10.jpg",
        )

        self.assertEqual(receipt.merchant_name, "Costco Wholesale #1024")
        self.assertEqual(receipt.place_id, "pl_costco")
        self.assertEqual(receipt.total_amount, 37.61)
        self.assertEqual(receipt.tax_amount, 1.14)
        self.assertEqual(receipt.subtotal, 36.47)
        self.assertEqual(len(receipt.line_items), 3)

        # Verify Grocy catalog matching
        items_by_prod = {item.product_id: item for item in receipt.line_items}
        self.assertIn("prod_tp", items_by_prod)
        self.assertIn("prod_milk", items_by_prod)
        self.assertIn("prod_eggs", items_by_prod)

    # 3. Receipt Worker Pipeline & Deferred Event Location Patching
    def test_worker_pipeline_with_bulk_multiplier_and_location_patching(self):
        # 1. Create a parent LifeEvent with tentative initial location
        parent_event = LifeEvent(
            id="evt_snap_test_01",
            title="Costco Restock Run",
            event_type="SHOPPING",
            scheduled_at=datetime(2026, 11, 10, 14, 0, 0),
            place_id=None,
            people_involved=["Dad"],
            shopping_detail=ShoppingDetail(
                event_id="evt_snap_test_01",
                payment_method="Costco Visa",
                pantry_updated=False,
            ),
        )
        self.event_repo.create_event(parent_event)

        # 2. Check initial stock of Kirkland bath tissue (initial stock is 14 rolls)
        cursor = self.conn.cursor()
        init_tp = cursor.execute("SELECT amount FROM stock WHERE product_id = 'prod_tp'").fetchone()
        self.assertEqual(init_tp["amount"], 14.0)

        # 3. Store raw receipt text in CAS
        receipt_text = """
        Costco Wholesale #1024
        1050 Cranberry Square Dr, Cranberry Twp, PA
        
        KIRKLAND BATH TISSUE 36/PK  1  18.99
        
        TOTAL   18.99
        """
        stored = self.cas.store_file(receipt_text.encode("utf-8"), "receipt_costco.txt")

        # 4. Enqueue worker job
        progress_events = []
        self.worker.subscribe_progress(lambda job: progress_events.append((job.status, job.progress_pct)))

        job = self.worker.enqueue_job(
            file_hash=stored["file_hash"],
            filename="receipt_costco.txt",
            event_id="evt_snap_test_01",
        )
        self.assertEqual(job.status, "PENDING")

        # 5. Process job
        processed_receipt = self.worker.process_receipt(job.job_id)
        self.assertEqual(processed_receipt.total_amount, 18.99)
        self.assertEqual(processed_receipt.place_id, "pl_costco")

        # Check job completion state
        updated_job = self.worker.get_job(job.job_id)
        self.assertEqual(updated_job.status, "COMPLETED")
        self.assertEqual(updated_job.progress_pct, 100)
        self.assertGreaterEqual(len(progress_events), 4)

        # 6. Verify Grocy Bulk Multiplier: 1 pack * 36 rolls = +36 rolls added!
        # Initial 14.0 + 36.0 = 50.0 rolls!
        after_tp = cursor.execute("SELECT amount FROM stock WHERE product_id = 'prod_tp'").fetchone()
        self.assertEqual(after_tp["amount"], 50.0)

        # Verify stock_transactions recorded PURCHASE_RECEIPT
        tx = cursor.execute(
            "SELECT * FROM stock_transactions WHERE product_id = 'prod_tp' AND transaction_type = 'PURCHASE_RECEIPT'"
        ).fetchone()
        self.assertIsNotNone(tx)
        self.assertEqual(tx["amount"], 36.0)

        # 7. Verify Deferred Location & Financial Patching on Parent Event
        updated_event = self.event_repo.get_event("evt_snap_test_01")
        self.assertEqual(updated_event.place_id, "pl_costco")
        self.assertIsNotNone(updated_event.shopping_detail)
        self.assertEqual(updated_event.shopping_detail.total_amount, 18.99)
        self.assertIsNotNone(updated_event.completed_at)
        self.assertTrue(updated_event.shopping_detail.pantry_updated)

    def test_costco_json_file_parsing(self):
        """Verify that ReceiptParser parses official Costco digital receipt JSON exports."""
        json_file = Path("data") / "costco-receipts-09-30-2026-10-02-2026.json"
        self.assertTrue(json_file.exists(), "Costco JSON sample receipt file must exist")

        receipt = self.parser.parse_from_file(json_file)

        self.assertIn("Costco Wholesale", receipt.merchant_name)
        self.assertIn("328", receipt.merchant_name)
        self.assertEqual(receipt.place_id, "pl_costco")
        self.assertIn("1050 CRANBERRY SQUARE DR", receipt.merchant_address)
        self.assertEqual(receipt.total_amount, 125.27)
        self.assertEqual(receipt.subtotal, 125.27)
        self.assertEqual(receipt.tax_amount, 0.0)
        self.assertEqual(len(receipt.line_items), 9)

        # Check line item details
        items_by_name = {itm.clean_name: itm for itm in receipt.line_items}
        self.assertIn("Kiwi Berries, 1 lb", items_by_name)
        self.assertEqual(items_by_name["Kiwi Berries, 1 lb"].quantity, 2.0)
        self.assertEqual(items_by_name["Kiwi Berries, 1 lb"].total_price, 13.98)

        # Organic A2 Milk catalog link
        milk_item = items_by_name["Kirkland Signature Organic A2 Whole Milk, Half Gallon, 3-count"]
        self.assertEqual(milk_item.product_id, "prod_milk")
        self.assertEqual(milk_item.category, "dairy")
        self.assertEqual(milk_item.total_price, 13.99)

        # Weighted Pork Belly item
        pork_item = items_by_name["Pork Belly Skin On Boneless Sliced Per Lb."]
        self.assertEqual(pork_item.unit, "lb")
        self.assertEqual(pork_item.quantity, 6.78)
        self.assertEqual(pork_item.total_price, 27.05)

        # Discount / Instant Savings Coupon
        discount_items = [itm for itm in receipt.line_items if itm.category == "discount"]
        self.assertEqual(len(discount_items), 1)
        self.assertEqual(discount_items[0].total_price, -4.50)

    def test_costco_json_worker_pipeline_integration(self):
        """End-to-end integration: store Costco JSON in CAS, process with ReceiptWorker, and update pantry."""
        json_file = Path("data") / "costco-receipts-09-30-2026-10-02-2026.json"
        self.assertTrue(json_file.exists())

        raw_bytes = json_file.read_bytes()
        stored = self.cas.store_file(raw_bytes, "costco_app_receipt.json")

        # Initial milk stock in seed database: 1.2 gal
        cursor = self.conn.cursor()
        init_milk = cursor.execute("SELECT amount FROM stock WHERE product_id = 'prod_milk'").fetchone()
        self.assertEqual(init_milk["amount"], 1.2)

        job = self.worker.enqueue_job(
            file_hash=stored["file_hash"],
            filename="costco_app_receipt.json",
        )
        processed = self.worker.process_receipt(job.job_id)

        self.assertEqual(processed.total_amount, 125.27)
        self.assertEqual(processed.place_id, "pl_costco")
        self.assertEqual(len(processed.line_items), 9)

        # Verify Grocy bulk expansion for prod_milk: conv_02 has factor 2.0 gal/pack -> 1.2 + 2.0 = 3.2 gal
        after_milk = cursor.execute("SELECT amount FROM stock WHERE product_id = 'prod_milk'").fetchone()
        self.assertEqual(after_milk["amount"], 3.2)

    def test_image_receipt_parsing_costco_and_asian_market(self):
        """Test OCR and spatial line parsing on binary image receipts."""
        img1 = Path("data") / "image1.jpeg"
        if img1.exists():
            r1 = self.parser.parse_from_file(img1)
            self.assertIn("Costco", r1.merchant_name)
            self.assertEqual(r1.place_id, "pl_costco")
            self.assertEqual(r1.total_amount, 43.97)
            self.assertEqual(len(r1.line_items), 3)
            # Item verification
            names = [itm.clean_name for itm in r1.line_items]
            self.assertTrue(any("SALMON" in n for n in names))
            self.assertTrue(any("CANOLA" in n for n in names))
            self.assertTrue(any("FR 2DZ" in n for n in names))

        img0 = Path("data") / "image0.jpeg"
        if img0.exists():
            r0 = self.parser.parse_from_file(img0)
            self.assertIn("Oriental", r0.merchant_name)
            self.assertEqual(r0.place_id, "pl_oriental")
            self.assertEqual(r0.total_amount, 63.60)
            self.assertGreaterEqual(len(r0.line_items), 6)

    def test_bundled_costco_receipts_deduplication(self):
        """Verify that bundled JSON receipts in one file are all imported and deduplicated by barcode."""
        import json
        json_file = Path("data") / "costco-receipts-09-30-2026-10-02-2026.json"
        raw_receipts = json.loads(json_file.read_text(encoding="utf-8"))
        base_r = raw_receipts[0]

        # Create a second distinct Costco receipt in the same bundle
        second_r = dict(base_r)
        second_r["transactionBarcode"] = "21032899999999999999999"
        second_r["transactionNumber"] = "999"
        second_r["total"] = 43.97
        second_r["subTotal"] = 43.97
        second_r["itemArray"] = [
            {
                "itemActualName": "Kirkland Signature Cashews",
                "itemNumber": "12345",
                "unit": 1,
                "amount": 15.99,
                "itemUnitPriceAmount": 15.99,
            }
        ]

        bundle_bytes = json.dumps([base_r, second_r]).encode("utf-8")
        stored1 = self.cas.store_file(bundle_bytes, "bundle_1.json")

        job1 = self.worker.enqueue_job(
            file_hash=stored1["file_hash"],
            filename="bundle_1.json",
        )
        self.worker.process_receipt(job1.job_id)

        # Verify both receipts are in DB with distinct IDs
        cursor = self.conn.cursor()
        imported = cursor.execute("SELECT id, source_reference_id, total_amount FROM receipts").fetchall()
        self.assertEqual(len(imported), 2)
        ref_ids = {row["source_reference_id"] for row in imported}
        self.assertIn(base_r["transactionBarcode"], ref_ids)
        self.assertIn(second_r["transactionBarcode"], ref_ids)

        # Import a second file that contains the duplicate base_r and a NEW third receipt
        third_r = dict(base_r)
        third_r["transactionBarcode"] = "21032888888888888888888"
        third_r["total"] = 20.00
        third_r["itemArray"] = []

        bundle2_bytes = json.dumps([base_r, third_r]).encode("utf-8")
        stored2 = self.cas.store_file(bundle2_bytes, "bundle_2.json")
        self.assertNotEqual(stored1["file_hash"], stored2["file_hash"])

        job2 = self.worker.enqueue_job(
            file_hash=stored2["file_hash"],
            filename="bundle_2.json",
        )
        self.worker.process_receipt(job2.job_id)

        # Base receipt must NOT be duplicated; total count must be 3, not 4
        after_imported = cursor.execute("SELECT id, source_reference_id FROM receipts").fetchall()
        self.assertEqual(len(after_imported), 3)


if __name__ == "__main__":
    unittest.main()

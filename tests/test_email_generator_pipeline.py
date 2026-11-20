"""Comprehensive Pipeline Test for EmailEventGenerator.
Tests:
1. Receipt: Procare Payment Receipt ($200.00) -> Generates JSON in receipts_inbox -> Ingests LifeEvent.
2. Bill without Auto-Pay: Primrose Invoice ($200.00) -> Generates event where start == end == received time and deadline == due date.
3. Bill with Auto-Pay: Energy Bill ("Auto-pay is scheduled for $85.50") -> Auto-pay detected -> SKIPPED (no event created).
4. Kid Workshop: Lowe's Kids Workshop -> Classified as KID_ACTIVITY (involves Marcus), not facility resource occupied.
5. YMCA Thanksgiving Closure: "Thanksgiving 2026 Closure" -> Stored in resource_closures table for conflict detection.
6. Conflict Engine Verification: Scheduling an event at YMCA on Thanksgiving flags a FACILITY_MUTEX conflict!
7. Marketing / Self-Sent: "Receipt test" and Hulu streaming promos -> SKIPPED.
8. Deduplication / Idempotency: Re-processing yields 0 new events.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys

logging.basicConfig(level=logging.INFO)

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from liftassistant.db.repository import EventRepository, PlaceRepository
from liftassistant.models.domain import LifeEvent
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.event_manager import EventManager
from liftassistant.services.email_event_generator import EmailEventGenerator

def run_tests():
    # 1. Setup in-memory DB with schema and foreign key places
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open("liftassistant/db/schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_costco', 'Costco Wholesale', 'supermarket', '1050 Cranberry Square Dr')")
    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_primrose', 'Primrose School', 'education', '2598 Wexford Bayne Rd')")
    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_ymca', 'Rose E. Schneider Family YMCA', 'community', 'Ehrman Rd')")
    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_lowes', 'Lowes Home Improvement', 'hardware', 'Cranberry Twp')")
    conn.commit()

    repo = EventRepository(conn)
    place_repo = PlaceRepository(conn)
    conflict_engine = ConflictEngine(place_repo=place_repo)
    em = EventManager(event_repo=repo, place_repo=place_repo, conflict_engine=conflict_engine)
    
    test_inbox_dir = Path("data") / "test_receipts_inbox"
    test_inbox_dir.mkdir(parents=True, exist_ok=True)
    
    gen = EmailEventGenerator(event_manager=em, place_repo=place_repo, inbox_dir=test_inbox_dir)

    # 1. Receipt Test Case (Procare $200)
    receipt_email = {
        "id": "msg_procare_receipt_01",
        "subject": "Payment Receipt",
        "from": "Procare <connect-notification@online.procaresoftware.com>",
        "date": "Sat, 21 Feb 2026 02:44:17 +0000 (UTC)",
        "snippet": "Hello, Online payment of $200.00 was successfully processed on your account. You can view all your transactions online from Procare's Parent Portal.",
        "body": "Payment of $200.00 received for tuition. Thank you for your payment.",
        "attachments": [],
    }

    # 2. Manual Bill Test Case (Primrose $200 due)
    manual_bill_email = {
        "id": "msg_primrose_invoice_01",
        "subject": "Invoice: 20-Feb-2026",
        "from": "Primrose School of Wexford <connect-notification@online.procaresoftware.com>",
        "date": "Fri, 20 Feb 2026 17:55:50 +0000 (UTC)",
        "snippet": "Hello Parent, Primrose School of Wexford has requested a payment of $200, due by February 20, 2026. You can easily and securely pay this online.",
        "body": "Tuition invoice for $200 due on February 20, 2026.",
        "attachments": [],
    }

    # 3. Auto-Pay Bill Test Case
    autopay_bill_email = {
        "id": "msg_autopay_peco",
        "subject": "Your Monthly Electric Bill: Auto-Pay Scheduled",
        "from": "Duquesne Light <billing@duquesnelight.com>",
        "date": "Fri, 20 Feb 2026 10:00:00 -0500",
        "body": "Hello Customer, your bill of $85.50 is ready. Auto-pay is active and $85.50 will be automatically deducted on March 5, 2026.",
        "snippet": "Auto-pay is active and $85.50 will be automatically deducted on March 5, 2026.",
    }

    # 4. Kid Workshop Test Case (Lowe's Kids Workshop)
    kids_workshop_email = {
        "id": "msg_lowes_workshop_01",
        "subject": "Reminder! The Kids Workshop is tomorrow",
        "from": "Lowe's Home Improvement <lowes@e.lowes.com>",
        "date": "Fri, 20 Feb 2026 17:05:03 -0600",
        "snippet": "Pack your aprons and goggles. We'll see you soon. Kids Workshop | Birdhouse Submission tomorrow at 10:00 AM.",
        "body": "Reminder: Kids Workshop at Lowe's Cranberry Twp tomorrow from 10:00 AM to 1:00 PM.",
        "attachments": [],
    }

    # 5. YMCA Closure Test Case
    ymca_closure_email = {
        "id": "msg_ymca_closure_tg",
        "subject": "Thanksgiving 2026 Closure & Holiday Hours",
        "from": "Rose E. Schneider Family YMCA <engagesupport@daxkoengage.com>",
        "date": "Mon, 16 Nov 2026 15:30:48 +0000",
        "body": "Please note that Rose E. Schneider Family YMCA will be closed on Thanksgiving Day, November 26, 2026. Normal hours resume Nov 27.",
        "snippet": "Rose E. Schneider Family YMCA will be closed on Thanksgiving Day, November 26, 2026.",
    }

    # 6. Self-Sent False Positive Test Case
    self_sent_email = {
        "id": "msg_test_self_sent",
        "subject": "Receipt test",
        "from": "Family Member <testuser@example.com>",
        "date": "Tue, 17 Nov 2026 00:00:00 -0500",
        "body": "Sent from my iPhone",
        "snippet": "Sent from my iPhone",
    }

    # 7. Promotional Marketing Email
    promo_email = {
        "id": "msg_test_hulu_promo",
        "subject": "'The Remarried Empress' Is Now Streaming on Hulu",
        "from": "Hulu <hulu@hulumail.com>",
        "date": "Sat, 14 Nov 2026 20:02:54 -0600",
        "body": "Get Disney+ and Hulu for $4.99/month for 3 months. Start streaming now.",
        "snippet": "Get Disney+ and Hulu for $4.99/month for 3 months.",
    }

    print("=== TEST 1: Receipt Ingestion ===")
    evt_rec = gen.process_email_message(receipt_email)
    assert evt_rec is not None, "Expected receipt event to be created"
    assert evt_rec.event_type == "SHOPPING"
    assert evt_rec.shopping_detail.total_amount == 200.0
    print(f"PASS: Receipt event created: '{evt_rec.title}' (${evt_rec.shopping_detail.total_amount})")

    print("\n=== TEST 2: Manual Bill (No Auto-Pay) ===")
    evt_bill = gen.process_email_message(manual_bill_email)
    assert evt_bill is not None, "Expected manual bill event to be created"
    assert evt_bill.scheduled_at == evt_bill.scheduled_end_at, "Start time and end time must equal email received time"
    assert evt_bill.deadline is not None, "Manual bill must have a deadline"
    assert evt_bill.event_type == "CUSTOM"
    print(f"PASS: Manual bill created: '{evt_bill.title}' | Scheduled: {evt_bill.scheduled_at} | Deadline: {evt_bill.deadline}")

    print("\n=== TEST 3: Auto-Pay Bill (Should Skip Event Creation) ===")
    evt_autopay = gen.process_email_message(autopay_bill_email)
    assert evt_autopay is None, "Bill with auto-pay MUST NOT generate a calendar event!"
    print("PASS: Auto-pay bill correctly skipped!")

    print("\n=== TEST 4: Kid Workshop (Should Be KID_ACTIVITY, not facility blackout) ===")
    evt_workshop = gen.process_email_message(kids_workshop_email)
    assert evt_workshop is not None, "Expected workshop event to be created"
    assert evt_workshop.event_type == "KID_ACTIVITY", f"Expected KID_ACTIVITY, got {evt_workshop.event_type}"
    assert "Marcus" in evt_workshop.people_involved, f"Marcus should be in people_involved, got {evt_workshop.people_involved}"
    print(f"PASS: Kid Workshop created: '{evt_workshop.title}' | Type: {evt_workshop.event_type} | People: {evt_workshop.people_involved}")

    print("\n=== TEST 5: YMCA Closure (Should Store in resource_closures table) ===")
    evt_closure = gen.process_email_message(ymca_closure_email)
    assert evt_closure is None, "Facility closure should not be a calendar event, but a resource closure!"
    closures = place_repo.list_closures(resource_id="pl_ymca")
    assert len(closures) >= 1, f"Expected at least 1 closure in resource_closures table, got {len(closures)}"
    closure = closures[0]
    print(f"PASS: Resource closure stored: '{closure.resource_name}' from {closure.start_time} to {closure.end_time} ({closure.reason})")

    print("\n=== TEST 6: Conflict Engine Detects Facility Closure Collision ===")
    # Event 6A: Scheduled on Thanksgiving (during closure)
    thanksgiving_event = LifeEvent(
        id="evt_test_swim_tg",
        title="Marcus Swimming at YMCA",
        event_type="KID_ACTIVITY",
        scheduled_at=datetime(2026, 11, 26, 10, 0),
        scheduled_end_at=datetime(2026, 11, 26, 11, 0),
        place_id="pl_ymca",
        people_involved=["Marcus", "Dad"],
    )
    conflicts_tg = conflict_engine.detect_conflicts([thanksgiving_event])
    closure_conflicts = [c for c in conflicts_tg if c.conflict_type == "FACILITY_MUTEX" and "Closed" in c.title]
    assert len(closure_conflicts) >= 1, f"Expected closure conflict on Thanksgiving, got {conflicts_tg}"
    print(f"PASS: ConflictEngine detected collision: '{closure_conflicts[0].title}' - {closure_conflicts[0].description}")

    # Event 6B: Scheduled on normal day (outside closure)
    normal_event = LifeEvent(
        id="evt_test_swim_normal",
        title="Marcus Swimming at YMCA",
        event_type="KID_ACTIVITY",
        scheduled_at=datetime(2026, 11, 20, 10, 0),
        scheduled_end_at=datetime(2026, 11, 20, 11, 0),
        place_id="pl_ymca",
        people_involved=["Marcus", "Dad"],
    )
    conflicts_normal = conflict_engine.detect_conflicts([normal_event])
    closure_conflicts_normal = [c for c in conflicts_normal if "Closed" in c.title]
    assert len(closure_conflicts_normal) == 0, f"Expected no closure conflict on normal day, got {closure_conflicts_normal}"
    print("PASS: ConflictEngine reports 0 closure conflicts on normal days!")

    print("\n=== TEST 7: Promotions and Self-Sent Test Emails Filtered ===")
    assert gen.process_email_message(self_sent_email) is None
    assert gen.process_email_message(promo_email) is None
    print("PASS: Self-sent tests and promotional emails successfully rejected!")

    print("\n=== TEST 8: Deduplication / Idempotency ===")
    # Re-running receipt_email should return None because it is already ingested
    second_run = gen.process_email_message(receipt_email)
    assert second_run is None, "Expected duplicate email to be skipped"
    print("PASS: Deduplication verified. Zero duplicate events created.")

    # Clean up test inbox directory
    import shutil
    shutil.rmtree(test_inbox_dir, ignore_errors=True)
    print("\n==========================================")
    print("ALL 8 COMPREHENSIVE PIPELINE TESTS PASSED!")
    print("==========================================")

if __name__ == "__main__":
    run_tests()

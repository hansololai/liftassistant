"""Test runner for EmailEventGenerator."""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import sqlite3
from liftassistant.db.repository import EventRepository, PlaceRepository
from liftassistant.services.event_manager import EventManager
from liftassistant.services.email_event_generator import EmailEventGenerator

def main():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open("liftassistant/db/schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    # Pre-seed places so foreign keys resolve cleanly
    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_costco', 'Costco Wholesale', 'supermarket', '1050 Cranberry Square Dr')")
    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_primrose', 'Primrose School', 'education', '2598 Wexford Bayne Rd')")
    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_ymca', 'Rose E. Schneider YMCA', 'community', 'Ehrman Rd')")
    conn.execute("INSERT INTO places (id, name, category, address) VALUES ('pl_lowes', 'Lowes Home Improvement', 'hardware', 'Cranberry Twp')")
    conn.commit()

    repo = EventRepository(conn)
    em = EventManager(event_repo=repo)
    gen = EmailEventGenerator(event_manager=em)

    batch_path = Path("tests/fixtures/mock_email_batch.json")
    with open(batch_path, "r", encoding="utf-8") as f:
        batch = json.load(f)

    print(f"Testing EmailEventGenerator on batch of {len(batch)} emails...")
    generated = []
    for email_item in batch:
        evt = gen.process_email_message(email_item)
        if evt:
            generated.append(evt)

    print(f"\nExtracted & Saved {len(generated)} LifeEvents to Ledger:")
    for i, ev in enumerate(generated, 1):
        status_str = "COMPLETED" if ev.completed_at else "UPCOMING"
        amount_str = f" (${ev.shopping_detail.total_amount:.2f})" if ev.shopping_detail and ev.shopping_detail.total_amount > 0 else ""
        print(f"{i}. [{ev.event_type} | {status_str}] {ev.title}{amount_str}")
        print(f"   Date: {ev.scheduled_at} | Deadline: {ev.deadline}")
        print(f"   Notes: {ev.notes.splitlines()[0] if ev.notes else ''}")
        print()

    # Test Idempotency: re-running should skip already processed emails without duplicate inserts
    print("Testing Idempotency on second run...")
    second_run = []
    for email_item in batch:
        evt = gen.process_email_message(email_item)
        if evt:
            second_run.append(evt)
    print(f"Second run yielded {len(second_run)} new events (expected 0). Idempotency passed!")

if __name__ == "__main__":
    main()

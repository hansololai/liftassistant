"""LiftAssistant 3.0 CLI Entrypoint."""

import argparse
import logging
import sys
from pathlib import Path

# Force UTF-8 on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def init_database():
    from liftassistant.db.connection import get_db_path, init_db
    db_path = get_db_path()
    init_db(db_path)
    logger.info("Initialized LifeAssistant 3.0 database at %s", db_path)


def reset_database():
    """Wipe all mock/sample data while keeping clean schema and authorized devices."""
    from liftassistant.db.connection import get_db, get_db_path, init_db
    from liftassistant.services.auth_service import DeviceAuthService
    db_path = get_db_path()
    init_db(db_path)
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        tables = [
            "events", "shopping_details", "dining_details", "maintenance_details",
            "kid_activity_details", "medical_details", "travel_details",
            "receipts", "receipt_items", "stock", "depletion_proposals",
            "conflicts", "inventory_transactions", "products", "item_multipliers",
            "product_unit_conversions", "event_generators", "generator_runs",
            "generator_event_feedback", "trips", "trip_flight_quotes", "trip_hotel_quotes"
        ]
        for t in tables:
            try:
                cursor.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        conn.commit()
    auth_service = DeviceAuthService(db_path)
    auth_service.ensure_default_devices()
    logger.info("Successfully wiped all mock events, products, and receipts from %s. Database is pristine.", db_path)


def seed_db():
    from liftassistant.db.connection import get_db_path, init_db
    from liftassistant.db.seed import seed_database
    db_path = get_db_path()
    init_db(db_path)
    seed_database(db_path)
    logger.info("Seeded LiftAssistant 3.0 baseline data at %s", db_path)


def evaluate_generators():
    import sqlite3
    from datetime import date
    from liftassistant.db.connection import get_db_path
    from liftassistant.db.repository import EventGeneratorRepository, EventRepository
    from liftassistant.services.event_generator_service import EventGeneratorService

    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    gen_repo = EventGeneratorRepository(conn)
    event_repo = EventRepository(conn)
    service = EventGeneratorService(gen_repo, event_repo)

    spawned = service.evaluate_and_spawn_all(date.today())
    logger.info("Evaluated event generators. Spawned %d new event(s).", len(spawned))
    conn.close()


def manage_devices(add_name: str = None):
    from liftassistant.services.auth_service import DeviceAuthService
    auth_service = DeviceAuthService()
    if add_name:
        dev = auth_service.create_device(add_name)
        print(f"\nCreated pending device: '{dev['device_name']}'")
        print(f"  -> Magic Link: /?enroll_token={dev['enroll_token']}\n")
        return

    devices = auth_service.list_devices()
    print("\n" + "=" * 60)
    print("LifeAssistant Authorized Family Devices:")
    print("=" * 60)
    for d in devices:
        status_str = "REVOKED" if d["is_revoked"] else ("ACTIVE" if d["is_enrolled"] else "PENDING")
        print(f"[{status_str:7}] {d['device_name']} (id: {d['id']})")
        if not d["is_enrolled"] and not d["is_revoked"]:
            print(f"          Magic Link: /?enroll_token={d['enroll_token']}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="LifeAssistant 3.0 CLI")
    parser.add_argument(
        "command",
        nargs="?",
        default="init-db",
        choices=["init-db", "seed", "reset-db", "evaluate-generators", "api", "devices"],
        help="Command to run (default: init-db)",
    )
    parser.add_argument(
        "--add",
        dest="add_device",
        help="Create a new device by name and generate its enrollment link",
    )
    args = parser.parse_args()

    if args.command == "init-db":
        init_database()
    elif args.command == "reset-db":
        reset_database()
    elif args.command == "seed":
        seed_db()
    elif args.command == "evaluate-generators":
        evaluate_generators()
    elif args.command == "devices":
        manage_devices(args.add_device)
    elif args.command == "api":
        import uvicorn
        logger.info("Starting LiftAssistant 3.0 API Gateway on port 8000...")
        uvicorn.run("liftassistant.api.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()

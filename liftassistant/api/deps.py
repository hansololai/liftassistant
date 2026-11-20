"""Dependency injection helpers for LiftAssistant FastAPI routes."""

import sqlite3
from typing import Generator
from pathlib import Path
from liftassistant.db.connection import get_db
from liftassistant.db.repository import (
    EventGeneratorRepository,
    EventRepository,
    GeneratorRunRepository,
    InventoryRepository,
    PlaceRepository,
)
from liftassistant.services.conflict_engine import ConflictEngine
from liftassistant.services.event_manager import EventManager
from liftassistant.services.event_generator_service import EventGeneratorService
from liftassistant.services.inventory_service import InventoryService
from liftassistant.services.trip_service import TripService
from liftassistant.services.map_service import MapService
from liftassistant.services.receipt_worker import ReceiptWorker
from liftassistant.services.auth_service import DeviceAuthService


_auth_service_instance = None


def get_auth_service() -> DeviceAuthService:
    global _auth_service_instance
    if _auth_service_instance is None:
        _auth_service_instance = DeviceAuthService()
    return _auth_service_instance


def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """Yield managed SQLite connection with WAL mode and foreign keys enabled."""
    with get_db() as conn:
        yield conn


def get_event_repo() -> Generator[EventRepository, None, None]:
    with get_db() as conn:
        yield EventRepository(conn)


def get_inventory_repo() -> Generator[InventoryRepository, None, None]:
    with get_db() as conn:
        yield InventoryRepository(conn)


def get_conflict_engine() -> ConflictEngine:
    return ConflictEngine()


def get_place_repo() -> Generator[PlaceRepository, None, None]:
    with get_db() as conn:
        yield PlaceRepository(conn)


def get_map_service() -> Generator[MapService, None, None]:
    with get_db() as conn:
        place_repo = PlaceRepository(conn)
        yield MapService(place_repo=place_repo)


def get_event_manager() -> Generator[EventManager, None, None]:
    with get_db() as conn:
        repo = EventRepository(conn)
        place_repo = PlaceRepository(conn)
        engine = ConflictEngine(place_repo=place_repo)
        map_service = MapService(place_repo=place_repo)
        yield EventManager(
            event_repo=repo,
            conflict_engine=engine,
            place_repo=place_repo,
            map_service=map_service,
        )


def get_gen_repo() -> Generator[EventGeneratorRepository, None, None]:
    with get_db() as conn:
        yield EventGeneratorRepository(conn)


def get_event_gen_service() -> Generator[EventGeneratorService, None, None]:
    with get_db() as conn:
        gen_repo = EventGeneratorRepository(conn)
        event_repo = EventRepository(conn)
        yield EventGeneratorService(gen_repo, event_repo)


def get_inventory_service() -> Generator[InventoryService, None, None]:
    with get_db() as conn:
        repo = InventoryRepository(conn)
        yield InventoryService(repo)


def get_trip_service() -> Generator[TripService, None, None]:
    with get_db() as conn:
        yield TripService(conn=conn)


def get_gen_run_repo() -> Generator[GeneratorRunRepository, None, None]:
    with get_db() as conn:
        yield GeneratorRunRepository(conn)


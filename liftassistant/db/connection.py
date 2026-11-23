"""Database connection pool abstraction and schema initialization for LiftAssistant 3.0.
Supports live connection pooling with an abstract interface ready for PostgreSQL migration.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import queue
import sqlite3
import threading
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db_path() -> Path:
    """Return database path based on active environment (hardcoded to test_liftassistant.db in test)."""
    from liftassistant.config import get_settings
    db_path = get_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


# Dynamic default property for backwards compatibility
class _DefaultDbPathProxy(Path):
    def __new__(cls):
        return get_db_path()

DEFAULT_DB_PATH = get_db_path()


# =========================================================================
# 1. ABSTRACT CONNECTION POOL CONTRACT (Database-Agnostic Interface)
# =========================================================================
class BaseConnectionPool(ABC):
    """Abstract connection pool contract supporting SQLite, PostgreSQL, etc."""

    @abstractmethod
    @contextmanager
    def connection(self) -> Generator[Any, None, None]:
        """Acquire a live, transaction-managed connection from the pool."""
        pass

    @abstractmethod
    def close_all(self) -> None:
        """Release and close all pooled connections."""
        pass


# =========================================================================
# 2. CONCRETE SQLITE LIVE CONNECTION POOL
# =========================================================================
class SQLiteConnectionPool(BaseConnectionPool):
    """Thread-safe SQLite connection pool with pre-warmed WAL mode connections."""

    def __init__(self, db_path: Path, max_connections: int = 25, timeout: float = 30.0):
        self.db_path = db_path.resolve()
        self.max_connections = max_connections
        self.timeout = timeout
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._all_conns: List[sqlite3.Connection] = []
        self._closed = False

        self._initialize_pool()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _initialize_pool(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for _ in range(self.max_connections):
                conn = self._create_connection()
                self._all_conns.append(conn)
                self._pool.put(conn)
        logger.debug("Initialized SQLite pool for %s with %d connections", self.db_path, self.max_connections)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._closed:
            raise RuntimeError(f"Connection pool for {self.db_path} is closed.")

        conn = self._pool.get(timeout=self.timeout)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Database transaction error on pool %s: %s", self.db_path, e)
            raise
        finally:
            if not self._closed:
                self._pool.put(conn)

    def close_all(self) -> None:
        with self._lock:
            self._closed = True
            while not self._pool.empty():
                try:
                    self._pool.get_nowait()
                except queue.Empty:
                    break
            for conn in self._all_conns:
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_conns.clear()
        logger.debug("Closed all connections in pool for %s", self.db_path)


# =========================================================================
# 3. FUTURE POSTGRESQL POOL ADAPTER
# =========================================================================
class PostgresConnectionPool(BaseConnectionPool):
    """PostgreSQL pool adapter (ready for psycopg_pool.ConnectionPool or asyncpg)."""

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool = None  # To be instantiated via psycopg_pool when switching to PostgreSQL

    @contextmanager
    def connection(self) -> Generator[Any, None, None]:
        if not self._pool:
            raise NotImplementedError("PostgreSQL pool requires psycopg_pool configured with valid DSN.")
        with self._pool.connection() as conn:
            yield conn

    def close_all(self) -> None:
        if self._pool:
            self._pool.close()


# =========================================================================
# 4. GLOBAL POOL REGISTRY & FACTORY
# =========================================================================
_pools: Dict[Path, SQLiteConnectionPool] = {}
_pools_lock = threading.Lock()


def get_connection_pool(db_path: Optional[Path] = None, max_connections: int = 25) -> BaseConnectionPool:
    """Retrieve or create a live connection pool for the given target database."""
    target_path = (db_path or get_db_path()).resolve()
    with _pools_lock:
        if target_path not in _pools or _pools[target_path]._closed:
            _pools[target_path] = SQLiteConnectionPool(target_path, max_connections=max_connections)
        return _pools[target_path]


def close_connection_pool(db_path: Optional[Path] = None) -> None:
    """Close and release the connection pool for a specific database file."""
    target_path = (db_path or get_db_path()).resolve()
    with _pools_lock:
        pool = _pools.pop(target_path, None)
        if pool:
            pool.close_all()


def close_all_pools() -> None:
    """Close all active connection pools across the process."""
    with _pools_lock:
        for pool in _pools.values():
            pool.close_all()
        _pools.clear()


# =========================================================================
# 5. CONVENIENCE CONTEXT MANAGER & INITIALIZATION
# =========================================================================
@contextmanager
def get_db(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager acquiring a live pooled connection with automatic commit/rollback.
    Fully backwards-compatible with all existing services, routers, and tests.
    """
    pool = get_connection_pool(db_path)
    with pool.connection() as conn:
        yield conn


def init_db(db_path: Optional[Path] = None, schema_path: Optional[Path] = None) -> None:
    """Initialize all SQLite tables matching the LiftAssistant 3.0 schema."""
    target_schema = schema_path or DEFAULT_SCHEMA_PATH
    if not target_schema.exists():
        raise FileNotFoundError(f"Schema file not found at: {target_schema}")

    schema_sql = target_schema.read_text(encoding="utf-8")

    with get_db(db_path) as conn:
        conn.executescript(schema_sql)
        # Idempotent migration for latitude, longitude, and studio columns
        for col, col_type in [("latitude", "REAL"), ("longitude", "REAL"), ("studio", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE events ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Idempotent creation and migration of item_multipliers table with product_id
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS item_multipliers (
                store TEXT NOT NULL,
                item TEXT NOT NULL,
                multiplier REAL NOT NULL DEFAULT 1.0,
                product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
                PRIMARY KEY (store, item)
            )
            """
        )
        try:
            conn.execute("ALTER TABLE item_multipliers ADD COLUMN product_id TEXT REFERENCES products(id) ON DELETE SET NULL")
        except sqlite3.OperationalError:
            pass

        # Idempotent index for receipt source reference deduplication
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_source_ref ON receipts(source_reference_id) WHERE source_reference_id IS NOT NULL")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_receipts_lookup ON receipts(merchant_name, transaction_time, total_amount)")
        except sqlite3.OperationalError:
            pass

        # Idempotent creation of authorized_devices table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS authorized_devices (
                id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                enroll_token TEXT UNIQUE NOT NULL,
                session_token TEXT UNIQUE,
                is_enrolled INTEGER DEFAULT 0,
                enrolled_at TIMESTAMP,
                last_seen_at TIMESTAMP,
                user_agent TEXT,
                ip_address TEXT,
                is_revoked INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_session ON authorized_devices(session_token)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_enroll ON authorized_devices(enroll_token)")

        # Section 12: Generator runs, feedback & prompt learning tables
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generator_runs (
                id TEXT PRIMARY KEY,
                generator_type TEXT NOT NULL DEFAULT 'EMAIL_EVENT_GENERATOR',
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                scanned_count INTEGER DEFAULT 0,
                created_count INTEGER DEFAULT 0,
                error_message TEXT,
                details_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_runs_type ON generator_runs(generator_type, started_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generator_event_feedback (
                id TEXT PRIMARY KEY,
                event_id TEXT,
                run_id TEXT REFERENCES generator_runs(id) ON DELETE SET NULL,
                source_reference_id TEXT,
                email_subject TEXT,
                email_from TEXT,
                email_date TEXT,
                llm_category TEXT,
                llm_reason TEXT,
                raw_json TEXT,
                user_status TEXT DEFAULT 'PENDING',
                user_correction_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_feedback_event ON generator_event_feedback(event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_feedback_run ON generator_event_feedback(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_feedback_source ON generator_event_feedback(source_reference_id)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learned_prompt_rules (
                id TEXT PRIMARY KEY,
                generator_type TEXT NOT NULL DEFAULT 'EMAIL_EVENT_GENERATOR',
                rule_type TEXT NOT NULL DEFAULT 'NEGATIVE',
                user_feedback TEXT NOT NULL,
                prompt_instruction TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_rules_active ON learned_prompt_rules(generator_type, is_active)")

        logger.info("Database initialized successfully at %s", db_path or get_db_path())

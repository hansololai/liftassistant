"""Device Authorization Service for Zero-Friction Family Magic Link Enrollment.
Recognizes physical mobile devices (Mom's phone, Dad's phone) via long-lived
cryptographic session tokens without requiring usernames, passwords, or OAuth.
"""

from datetime import datetime
import logging
from pathlib import Path
import secrets
from typing import Any, Dict, List, Optional
from uuid import uuid4

from liftassistant.db.connection import get_db

logger = logging.getLogger(__name__)


class DeviceAuthService:
    """Service managing authorized physical devices and one-time magic enrollment links."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        self._init_table()
        self.ensure_default_devices()

    def _init_table(self) -> None:
        """Create authorized_devices table if not already created."""
        with get_db(self.db_path) as conn:
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
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_session ON authorized_devices(session_token);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_enroll ON authorized_devices(enroll_token);")

    def ensure_default_devices(self) -> None:
        """Seed default Mom and Dad devices if the table is empty."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            count = cursor.execute("SELECT COUNT(*) FROM authorized_devices").fetchone()[0]
            if count == 0:
                logger.info("Initializing default authorized family devices (Dad's Phone, Mom's Phone)")
                default_devices = [
                    ("dev_dad", "Dad's Phone", f"dad_enroll_{secrets.token_urlsafe(24)}"),
                    ("dev_mom", "Mom's Phone", f"mom_enroll_{secrets.token_urlsafe(24)}"),
                ]
                for dev_id, name, enroll_tok in default_devices:
                    cursor.execute(
                        """
                        INSERT INTO authorized_devices (id, device_name, enroll_token, is_enrolled)
                        VALUES (?, ?, ?, 0)
                        """,
                        (dev_id, name, enroll_tok),
                    )

    def list_devices(self) -> List[Dict[str, Any]]:
        """List all devices with enrollment and last seen status."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, device_name, enroll_token, is_enrolled, enrolled_at, last_seen_at, user_agent, is_revoked, created_at
                FROM authorized_devices
                ORDER BY created_at ASC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "device_name": r[1],
                    "enroll_token": r[2],
                    "is_enrolled": bool(r[3]),
                    "enrolled_at": r[4],
                    "last_seen_at": r[5],
                    "user_agent": r[6],
                    "is_revoked": bool(r[7]),
                    "created_at": r[8],
                }
                for r in rows
            ]

    def create_device(self, device_name: str) -> Dict[str, Any]:
        """Generate a new pending device with an enrollment token."""
        dev_id = f"dev_{uuid4().hex[:8]}"
        clean_name = device_name.strip()
        slug = "".join(c.lower() for c in clean_name if c.isalnum())[:8] or "device"
        enroll_token = f"{slug}_enroll_{secrets.token_urlsafe(24)}"

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO authorized_devices (id, device_name, enroll_token, is_enrolled)
                VALUES (?, ?, ?, 0)
                """,
                (dev_id, clean_name, enroll_token),
            )
        return {
            "id": dev_id,
            "device_name": clean_name,
            "enroll_token": enroll_token,
            "is_enrolled": False,
        }

    def enroll_device(
        self,
        enroll_token: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Exchange a one-time enrollment token for a permanent session token."""
        token_clean = enroll_token.strip()
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                """
                SELECT id, device_name, is_revoked FROM authorized_devices
                WHERE enroll_token = ?
                """,
                (token_clean,),
            ).fetchone()

            if not row or row[2]:  # not found or revoked
                logger.warning("Enrollment attempt rejected: invalid or revoked token '%s'", token_clean)
                return None

            dev_id, dev_name, _ = row
            session_token = f"sess_{secrets.token_urlsafe(40)}"
            now = datetime.now().isoformat()

            cursor.execute(
                """
                UPDATE authorized_devices
                SET session_token = ?,
                    is_enrolled = 1,
                    enrolled_at = COALESCE(enrolled_at, ?),
                    last_seen_at = ?,
                    user_agent = COALESCE(?, user_agent),
                    ip_address = COALESCE(?, ip_address)
                WHERE id = ?
                """,
                (session_token, now, now, user_agent, ip_address, dev_id),
            )

            logger.info("Successfully enrolled device '%s' (%s)", dev_name, dev_id)
            return {
                "device_id": dev_id,
                "device_name": dev_name,
                "session_token": session_token,
            }

    def validate_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """Validate an active device session token and refresh last_seen_at."""
        if not session_token or not session_token.strip():
            return None

        clean_token = session_token.strip()
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                """
                SELECT id, device_name, is_revoked, is_enrolled FROM authorized_devices
                WHERE session_token = ?
                """,
                (clean_token,),
            ).fetchone()

            if not row:
                return None

            dev_id, dev_name, is_revoked, is_enrolled = row
            if is_revoked or not is_enrolled:
                return None

            now = datetime.now().isoformat()
            cursor.execute(
                "UPDATE authorized_devices SET last_seen_at = ? WHERE id = ?",
                (now, dev_id),
            )

            return {
                "id": dev_id,
                "device_name": dev_name,
            }

    def revoke_device(self, device_id: str) -> bool:
        """Revoke a device immediately, invalidating any active session."""
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE authorized_devices
                SET is_revoked = 1, session_token = NULL
                WHERE id = ?
                """,
                (device_id,),
            )
            return cursor.rowcount > 0

"""Unit tests for Device Authentication Service and Middleware (Option 2: Magic Link Auth)."""

from pathlib import Path
import tempfile
import unittest
from liftassistant.db.connection import get_db, init_db
from liftassistant.services.auth_service import DeviceAuthService


class TestDeviceAuthService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_auth.db"
        init_db(self.db_path)
        self.auth_service = DeviceAuthService(self.db_path)

    def tearDown(self):
        from liftassistant.db.connection import close_connection_pool
        close_connection_pool(self.db_path)
        self.temp_dir.cleanup()

    def test_default_devices_seeded(self):
        """Verify default devices for Dad and Mom are seeded automatically."""
        devices = self.auth_service.list_devices()
        self.assertEqual(len(devices), 2)
        names = [d["device_name"] for d in devices]
        self.assertIn("Dad's Phone", names)
        self.assertIn("Mom's Phone", names)
        for d in devices:
            self.assertFalse(d["is_enrolled"])
            self.assertFalse(d["is_revoked"])
            self.assertTrue(d["enroll_token"].startswith(("dad_enroll_", "mom_enroll_")))

    def test_enroll_device_success_and_validation(self):
        """Verify valid enrollment exchanges token for session token and validates."""
        devices = self.auth_service.list_devices()
        dad = next(d for d in devices if d["device_name"] == "Dad's Phone")

        # 1. Enroll Dad's phone
        res = self.auth_service.enroll_device(
            enroll_token=dad["enroll_token"],
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
            ip_address="192.168.1.100",
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["device_name"], "Dad's Phone")
        session_token = res["session_token"]
        self.assertTrue(session_token.startswith("sess_"))

        # 2. Validate session
        validated = self.auth_service.validate_session(session_token)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["id"], "dev_dad")
        self.assertEqual(validated["device_name"], "Dad's Phone")

        # 3. Check device list updated
        updated_devices = self.auth_service.list_devices()
        dad_updated = next(d for d in updated_devices if d["device_name"] == "Dad's Phone")
        self.assertTrue(dad_updated["is_enrolled"])
        self.assertIsNotNone(dad_updated["enrolled_at"])
        self.assertIsNotNone(dad_updated["last_seen_at"])

    def test_enroll_device_invalid_token(self):
        """Verify invalid or fabricated enrollment token is rejected."""
        res = self.auth_service.enroll_device("fake_token_12345")
        self.assertIsNone(res)

    def test_create_and_revoke_device(self):
        """Verify dynamic creation of an iPad device and revoking it."""
        new_dev = self.auth_service.create_device("Dad's iPad")
        self.assertIsNotNone(new_dev["id"])
        self.assertEqual(new_dev["device_name"], "Dad's iPad")

        # Enroll iPad
        enroll_res = self.auth_service.enroll_device(new_dev["enroll_token"])
        self.assertIsNotNone(enroll_res)
        session_tok = enroll_res["session_token"]

        # Valid before revoke
        self.assertIsNotNone(self.auth_service.validate_session(session_tok))

        # Revoke iPad
        revoked = self.auth_service.revoke_device(new_dev["id"])
        self.assertTrue(revoked)

        # Invalid after revoke
        self.assertIsNone(self.auth_service.validate_session(session_tok))

    def test_auth_router_endpoints(self):
        """Verify auth API router endpoints directly."""
        from fastapi import Response
        from fastapi import Request
        from unittest.mock import MagicMock
        from liftassistant.api.routers.auth import (
            enroll_device,
            check_auth_status,
            list_devices,
            create_device,
            revoke_device,
            EnrollRequest,
            CreateDeviceRequest,
        )

        devices = self.auth_service.list_devices()
        dad = next(d for d in devices if d["device_name"] == "Dad's Phone")

        # 1. Enroll via endpoint
        mock_req = MagicMock(spec=Request)
        mock_req.headers = {"user-agent": "iPhone/Safari"}
        mock_req.client = MagicMock(host="192.168.1.100")
        mock_res = Response()

        enroll_payload = EnrollRequest(enroll_token=dad["enroll_token"])
        enroll_out = enroll_device(
            payload=enroll_payload,
            request=mock_req,
            response=mock_res,
            auth_service=self.auth_service,
        )
        self.assertTrue(enroll_out["success"])
        self.assertEqual(enroll_out["device_name"], "Dad's Phone")
        self.assertIn("lift_device_session=", mock_res.headers.get("set-cookie", ""))

        session_tok = enroll_out["session_token"]

        # 2. Check auth status with X-Device-Token header
        status_req = MagicMock(spec=Request)
        status_req.cookies = {}
        status_req.headers = {}
        status_out = check_auth_status(
            request=status_req,
            x_device_token=session_tok,
            auth_service=self.auth_service,
        )
        self.assertTrue(status_out["authenticated"])
        self.assertEqual(status_out["device_name"], "Dad's Phone")

        # 3. Check auth status without any token -> unauthenticated
        status_unauth = check_auth_status(
            request=status_req,
            x_device_token=None,
            auth_service=self.auth_service,
        )
        self.assertFalse(status_unauth["authenticated"])


if __name__ == "__main__":
    unittest.main()

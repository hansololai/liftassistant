"""Authentication & Device Enrollment Router.
Handles one-time magic link enrollment and 10-year persistent cookie authentication.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel

from liftassistant.api.deps import get_auth_service
from liftassistant.services.auth_service import DeviceAuthService

router = APIRouter(prefix="/auth", tags=["Device Authentication"])

COOKIE_NAME = "life_device_session"
FALLBACK_COOKIE_NAME = "lift_device_session"
COOKIE_MAX_AGE_SECONDS = 315360000  # 10 years


class EnrollRequest(BaseModel):
    enroll_token: str


class CreateDeviceRequest(BaseModel):
    device_name: str


def extract_session_token(request: Request, x_device_token: Optional[str] = None) -> Optional[str]:
    """Extract session token from cookie, X-Device-Token header, or Authorization header."""
    cookie_token = request.cookies.get(COOKIE_NAME) or request.cookies.get(FALLBACK_COOKIE_NAME)
    if cookie_token and cookie_token.strip():
        return cookie_token.strip()

    if x_device_token and x_device_token.strip():
        return x_device_token.strip()

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return None


@router.post("/enroll")
def enroll_device(
    payload: EnrollRequest,
    request: Request,
    response: Response,
    auth_service: DeviceAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Exchange a one-time enrollment token for a permanent 10-year session cookie."""
    user_agent = request.headers.get("user-agent")
    ip_addr = request.client.host if request.client else None

    result = auth_service.enroll_device(
        enroll_token=payload.enroll_token,
        user_agent=user_agent,
        ip_address=ip_addr,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked enrollment link. Please request a new link.",
        )

    # Set 10-year HttpOnly cookie
    response.set_cookie(
        key=COOKIE_NAME,
        value=result["session_token"],
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )

    return {
        "success": True,
        "device_id": result["device_id"],
        "device_name": result["device_name"],
        "session_token": result["session_token"],
        "message": f"Device '{result['device_name']}' successfully enrolled! Tap 'Add to Home Screen' for instant access.",
    }


@router.get("/status")
def check_auth_status(
    request: Request,
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
    auth_service: DeviceAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Check whether the calling browser has an active authorized device session."""
    token = extract_session_token(request, x_device_token)
    if not token:
        return {"authenticated": False, "device_name": None, "device_id": None}

    device = auth_service.validate_session(token)
    if not device:
        return {"authenticated": False, "device_name": None, "device_id": None}

    return {
        "authenticated": True,
        "device_id": device["id"],
        "device_name": device["device_name"],
    }


@router.get("/devices")
def list_devices(
    auth_service: DeviceAuthService = Depends(get_auth_service),
) -> List[Dict[str, Any]]:
    """List all authorized devices and their enrollment states."""
    return auth_service.list_devices()


@router.post("/devices")
def create_device(
    payload: CreateDeviceRequest,
    auth_service: DeviceAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Generate a new pending device enrollment link (e.g. for Dad's iPad or Mom's work phone)."""
    if not payload.device_name or not payload.device_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device name cannot be empty.",
        )
    return auth_service.create_device(payload.device_name)


@router.post("/devices/{device_id}/revoke")
def revoke_device(
    device_id: str,
    auth_service: DeviceAuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Revoke an authorized device immediately."""
    revoked = auth_service.revoke_device(device_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device '{device_id}' not found.",
        )
    return {"success": True, "message": f"Device '{device_id}' revoked."}

"""LiftAssistant REST API Application.
Follows standard REST conventions with uniform JSON success and failure responses.
"""

import http
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from liftassistant.api.deps import get_auth_service
from liftassistant.services.daily_workers import get_master_daily_worker
from liftassistant.api.routers import (

    auth,
    conflicts,
    events,
    generators,
    ingest,
    inventory,
    overview,
    places,
    shopping,
    trips,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup, database schema creation, and background services."""
    from liftassistant.db.connection import get_db_path, init_db

    db_path = get_db_path()
    logger.info("Ensuring database schema exists at %s", db_path)
    init_db(db_path)

    master_worker = get_master_daily_worker()
    master_worker.start()
    yield
    master_worker.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="LifeAssistant API",
        description="Unified Personal Life OS REST API backend with family calendar, inventory, and trip tracking.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 1. CORS Middleware configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://.*$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Device Authorization Middleware (Option 2: One-Time Magic Link Device Auth)
    @app.middleware("http")
    async def device_authorization_middleware(request: Request, call_next):
        path = request.url.path
        # Only protect /api/v1 endpoints
        if not path.startswith("/api/v1"):
            return await call_next(request)

        # Allow public / exemption endpoints
        EXEMPT_PATHS = {
            "/api/v1/health",
            "/api/v1/auth/enroll",
            "/api/v1/auth/status",
        }
        if path in EXEMPT_PATHS or path.endswith("/receipt/file"):
            return await call_next(request)

        # Allow OPTIONS pre-flight requests from CORS
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check if auth is disabled via environment configuration (e.g. test environment)
        from liftassistant.config import get_settings
        if not get_settings().is_device_auth_active:
            return await call_next(request)

        # Extract token from Cookie, X-Device-Token Header, or Bearer Header
        token = request.cookies.get("life_device_session") or request.cookies.get("lift_device_session")
        if not token:
            token = request.headers.get("x-device-token")
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()

        # If an enroll_token query parameter is provided on the request, auto-enroll
        enroll_token_param = request.query_params.get("enroll_token")

        auth_service = get_auth_service()
        device = None

        if token:
            device = auth_service.validate_session(token)
        elif enroll_token_param:
            enroll_res = auth_service.enroll_device(
                enroll_token=enroll_token_param,
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host if request.client else None,
            )
            if enroll_res:
                token = enroll_res["session_token"]
                device = auth_service.validate_session(token)

        if not device:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "Unauthorized",
                    "message": "Device not authorized. Open the family enrollment link sent to your phone.",
                    "status_code": 401,
                },
            )

        request.state.device = device
        response = await call_next(request)
        if token and "life_device_session" not in request.cookies and "lift_device_session" not in request.cookies:
            response.set_cookie(
                key="life_device_session",
                value=token,
                max_age=315360000,
                httponly=True,
                samesite="lax",
                path="/",
            )
        return response

    # 2. Standardized Error Handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle standard HTTP exceptions with structured JSON error format."""
        try:
            status_phrase = http.HTTPStatus(exc.status_code).phrase
        except ValueError:
            status_phrase = "HTTP Error"

        detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": status_phrase,
                "message": detail_msg,
                "status_code": exc.status_code,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle request schema validation errors with clean aggregated message."""
        errors = exc.errors()
        messages = []
        for err in errors:
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            msg = err.get("msg", "Invalid value")
            messages.append(f"{loc}: {msg}" if loc else msg)

        summary_msg = "; ".join(messages) if messages else "Invalid request body or parameters"

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "Unprocessable Entity",
                "message": summary_msg,
                "status_code": 422,
                "detail": errors,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all unhandled exceptions guarantee standard JSON error response."""
        logger.exception("Unhandled server exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "message": str(exc) or "An unexpected server error occurred.",
                "status_code": 500,
                "detail": None,
            },
        )

    # 3. Health & Status Endpoints
    @app.get("/api/v1/health", tags=["system"])
    def health_check() -> Dict[str, Any]:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "lifeassistant-api",
            "version": "1.0.0",
        }

    # 4. Mount API Routers
    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(overview.router, prefix=api_prefix)
    app.include_router(conflicts.router, prefix=api_prefix)
    app.include_router(events.router, prefix=api_prefix)
    app.include_router(places.router, prefix=api_prefix)
    app.include_router(generators.router, prefix=api_prefix)
    app.include_router(inventory.router, prefix=api_prefix)
    app.include_router(shopping.router, prefix=api_prefix)
    app.include_router(ingest.router, prefix=api_prefix)
    app.include_router(trips.router, prefix=api_prefix)

    # 5. Serve Frontend Static SPA (Single-Container Production Mode)
    import os
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    frontend_dist = os.environ.get("FRONTEND_DIST", "frontend/dist")
    if os.path.isdir(frontend_dist):
        assets_dir = os.path.join(frontend_dist, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            # Do not hijack API or documentation routes
            if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
                raise HTTPException(status_code=404, detail="Not Found")
            file_path = os.path.join(frontend_dist, full_path)
            if full_path and os.path.isfile(file_path):
                return FileResponse(file_path)
            index_path = os.path.join(frontend_dist, "index.html")
            if os.path.isfile(index_path):
                return FileResponse(index_path)
            raise HTTPException(status_code=404, detail="Frontend index.html not found")

    return app


app = create_app()

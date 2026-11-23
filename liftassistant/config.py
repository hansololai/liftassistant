"""Centralised configuration loaded from environment / .env file."""

from functools import lru_cache
import os
from pathlib import Path
from typing import Literal, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Environment & Auth ──────────────────────────────────────────────────
    environment: Literal["dev", "test", "prod"] = Field("dev", description="dev | test | prod")
    device_auth_enabled: Optional[bool] = Field(
        None,
        alias="lift_device_auth_enabled",
        description="Explicit override for device auth. Defaults to True for dev/prod, False for test.",
    )

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, v: str) -> str:
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in ("development", "dev"):
                return "dev"
            if clean in ("production", "prod"):
                return "prod"
            if clean in ("test", "testing"):
                return "test"
        return v

    @property
    def is_device_auth_active(self) -> bool:
        """Device authentication is active in dev and prod, but disabled in test."""
        if self.device_auth_enabled is not None:
            return self.device_auth_enabled
        return self.environment != "test"

    @property
    def db_path(self) -> Path:
        """Database file path. If test, always hardcoded to test_liftassistant.db."""
        if self.environment == "test":
            return Path("data") / "test_liftassistant.db"

        # Production / Dev: respect LIFTASSISTANT_DB_PATH from .env or default to liftassistant.db
        if "LIFTASSISTANT_DB_PATH" in os.environ:
            return Path(os.environ["LIFTASSISTANT_DB_PATH"])
        return Path("data") / "liftassistant.db"

    @property
    def cas_root(self) -> Path:
        """Receipt and document CAS storage directory."""
        if self.environment == "test":
            return Path("data") / "test_receipt_store"
        return Path(os.environ.get("LIFTASSISTANT_CAS_ROOT", Path("data") / "receipt_store"))

    # ── LLM ────────────────────────────────────────────────────────────────
    llm_provider: str = Field("ollama", description="ollama | deepseek | openai | gemini")
    llm_model: str = Field("ollama/deepseek-r1:14b", description="LiteLLM model string")
    llm_api_key: str = Field("", description="API key (not needed for Ollama)")
    llm_base_url: str = Field("http://127.0.0.1:11434", description="Ollama base URL")

    # ── Gmail ───────────────────────────────────────────────────────────────
    gmail_credentials_file: str = Field("credentials.json")
    gmail_token_file: str = Field("token.json")
    gmail_scan_labels: list[str] = Field(["INBOX"], description="Gmail labels to scan")
    gmail_max_results: int = Field(20, description="Max emails to fetch per run")
    gmail_newer_than_days: int = Field(2, description="Only fetch emails newer than N days")
    gmail_scan_unread_only: bool = Field(False, description="Scan unread emails only (default: False)")
    gmail_filter_junk_categories: bool = Field(
        True, description="Filter out promotions, social, forums, and spam"
    )

    # ── iCloud CalDAV ───────────────────────────────────────────────────────
    icloud_username: str = Field("", description="Apple ID email")
    icloud_app_password: str = Field("", description="iCloud app-specific password")
    icloud_calendar_name: str = Field("LiftAssistant", description="Calendar display name")
    icloud_reminders_list: str = Field("LiftAssistant", description="Reminders list name")

    # ── Google Calendar (optional alternative) ──────────────────────────────
    google_calendar_id: str = Field("primary")
    google_credentials_file: str = Field("google_calendar_credentials.json")

    # ── Price Tracker ────────────────────────────────────────────────────────
    serpapi_key: str = Field("", description="SerpAPI key for Google Flights scraping")
    price_check_interval_hours: int = Field(6)

    # ── Agent schedule ───────────────────────────────────────────────────────
    email_scan_interval_minutes: int = Field(60)
    home_agent_run_hour: int = Field(7, description="Hour of day (24h) to run home agent")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Return Settings initialized from current environment."""
    return Settings()


class _SettingsProxy:
    """Dynamic settings accessor that respects environment changes at runtime."""

    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()

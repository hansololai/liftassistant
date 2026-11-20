"""Centralised configuration loaded from environment / .env file."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM ────────────────────────────────────────────────────────────────
    llm_provider: str = Field("ollama", description="ollama | deepseek | openai | gemini")
    llm_model: str = Field("ollama/deepseek-r1:14b", description="LiteLLM model string")
    llm_api_key: str = Field("", description="API key (not needed for Ollama)")
    llm_base_url: str = Field("http://localhost:11434", description="Ollama base URL")

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


settings = Settings()

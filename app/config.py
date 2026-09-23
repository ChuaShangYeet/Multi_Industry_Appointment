"""
Centralized application settings, loaded from environment variables / .env.

Nothing else in the app should call `os.environ` directly - import `settings`
from here instead, so every configurable value lives in one place.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    APP_NAME: str = "Appointment Backend"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Database ---
    # Defaults to a local SQLite file so the project runs with zero external
    # setup. Point DATABASE_URL at Postgres for anything beyond local dev -
    # the relational, highly-normalized schema here is a great fit for it.
    DATABASE_URL: str = "sqlite:///./dev.db"

    # --- Auth / JWT ---
    JWT_SECRET_KEY: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # --- CORS ---
    # Covers the bundled frontend/ (Vite's default port, 5173) out of the box on
    # a fresh clone with no .env file, on both "localhost" and "127.0.0.1" -
    # browsers treat those as different origins even though they're the same
    # machine, so both are listed for whichever one a dev server happens to bind.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # --- Google Calendar sync ---
    # Kept OFF by default: the booking workflow works fully without it, sync
    # calls just become logged no-ops until real credentials are supplied.
    GOOGLE_CALENDAR_ENABLED: bool = False
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    # Path to a service-account JSON keyfile used to write into each
    # business's `google_calendar_id` (that calendar must be shared with the
    # service account's email). The customer side instead uses each user's
    # own `google_calendar_token` - see app/services/google_calendar.py.
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""

    # --- Admin bootstrap ---
    FIRST_ADMIN_EMAIL: str = "admin@example.com"
    FIRST_ADMIN_PASSWORD: str = "ChangeThis123!"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

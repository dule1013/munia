import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", enable_decoding=False)

    environment: str = "development"
    database_url: str
    clerk_secret_key: str = ""
    clerk_jwt_key: str = ""
    clerk_authorized_parties: list[str] = ["http://localhost:3000"]
    cors_origins: list[str] = ["http://localhost:3000"]
    career_ops_code_root: Path = Path(__file__).resolve().parents[2]
    career_ops_workspace_root: Path = Path(__file__).resolve().parents[2] / ".career-ops-data" / "users"
    artifact_storage: str = "filesystem"
    auth_test_mode: bool = False

    # Candidate integrations (Gmail/LinkedIn alert ingestion, Phase 5 Checkpoint C).
    # All optional at the Settings level — endpoints that need them return 503
    # ("not configured") rather than failing app startup, since a candidate may
    # simply not have connected Gmail yet. See app/core/crypto.py for why the
    # encryption key is never persisted anywhere but this env var.
    integration_encryption_key: str = ""
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # Must exactly match a redirect URI registered on the Google OAuth client
    # (e.g. https://api.example.com/api/v1/integrations/gmail/callback).
    google_oauth_redirect_uri: str = ""
    # Where to send the browser back to after the OAuth callback finishes.
    web_app_url: str = "http://localhost:3000"

    # Nightly morning sweep, run inside this api process (no separate service
    # needed — the api owns the /data volume the workspace root lives on).
    # "HH:MM" 24h UTC; empty disables the scheduler entirely.
    morning_sweep_schedule_utc: str = ""
    # False → morning_run(disable_ai=True): the sweep is zero-token by default.
    morning_sweep_ai: bool = False

    @field_validator("database_url")
    @classmethod
    def async_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+asyncpg://")):
            return value
        url = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        parsed = urlsplit(url)
        query = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))

    @field_validator("clerk_authorized_parties", "cors_origins", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def secure_auth_configuration(self) -> "Settings":
        if self.environment == "production" and self.auth_test_mode:
            raise ValueError("AUTH_TEST_MODE cannot be enabled in production")
        if self.environment == "production" and not self.clerk_secret_key:
            raise ValueError("CLERK_SECRET_KEY is required in production")
        return self

    @property
    def production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

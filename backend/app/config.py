from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root, one level above backend/
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """One place for configuration. Names match .env.example (case-insensitive)."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    env: str = "development"

    database_url: str = "postgresql+psycopg://integrity:integrity@localhost:5433/integrity"
    test_database_url: str = (
        "postgresql+psycopg://integrity:integrity@localhost:5433/integrity_test"
    )

    # The URL the browser sees. SEB's request hash covers the exact URL (D3).
    public_base_url: str = "http://localhost:5173"
    session_secret: str = "change-me-dev-only"

    seb_mode: str = "off"  # off | log | enforce
    seb_allowed_keys: str = ""  # comma-separated Config Key / Browser Exam Key values

    # Wrong invitation codes allowed per client in the window before /session/start answers 429.
    start_max_failures: int = 20
    start_window_s: int = 300
    # Wrong staff passwords allowed per client address, and per email, in the window before
    # /review/login answers 429. Only failures count. A short window keeps a mistyped password from
    # costing a reviewer much time, and 10 tries a minute is still too slow to guess a 12+
    # character password.
    login_max_failures: int = 10
    login_window_s: int = 60
    # How long a staff token is good for, as the master plan says: one working day.
    staff_token_ttl_s: int = 8 * 3600
    # Behind a trusted reverse proxy (nginx in compose), the real client is the last address in
    # X-Forwarded-For. Leave false when the API is reached directly.
    trust_forwarded_for: bool = False

    video_root: str = "./data/video"
    retention_days: int = 30
    chunk_fail_rate: float = 0.0

    ai_provider: str = "rules"  # rules | ollama | claude
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:latest"
    claude_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str = ""

    @property
    def seb_keys(self) -> list[str]:
        return [k.strip() for k in self.seb_allowed_keys.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

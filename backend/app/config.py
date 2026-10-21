from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repository root, one level above backend/. .env lives there, and so do relative data paths.
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    """One place for configuration. Names match .env.example (case-insensitive)."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    env: str = "development"

    database_url: str = "postgresql+psycopg://integrity:integrity@localhost:5433/integrity"
    test_database_url: str = (
        "postgresql+psycopg://integrity:integrity@localhost:5433/integrity_test"
    )

    # The address candidates open. Used to build the invitation links in the CSV the seed writes.
    public_base_url: str = "http://localhost:5173"
    session_secret: str = "change-me-dev-only"

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

    # What `begin` requires before the timer can start. The camera and microphone gate is the
    # proposal's one automatic outcome, so a production server must use "recording":
    #   off        nothing (development, while the pre-check and upload screens run on fixtures)
    #   precheck   a passing result from POST /api/precheck/result
    #   recording  also a real chunk with a video and an audio track already on the server
    precheck_gate: Literal["off", "precheck", "recording"] = "off"

    # Relative paths are read from the repository root, not from wherever uvicorn was started.
    video_root: str = "./data/video"
    retention_days: int = 30
    # A video chunk is about 10 s; the limit leaves room for a busy scene at the low bitrate.
    chunk_max_bytes: int = 5 * 1024 * 1024
    chunk_seconds: int = 10
    # How long after finishing a candidate can still upload (the proposal's 48 hours).
    resume_window_s: int = 48 * 3600
    # A finished session with video and no decision this long is listed for a person to decide.
    undecided_report_days: int = 60
    # Dev only: fraction of chunk uploads to refuse on purpose. Ignored when ENV=production.
    chunk_fail_rate: float = 0.0

    # Server scan of the saved audio for muted or silent stretches (master plan 7.8).
    mic_silence_db: float = -65.0
    mic_server_min_silence_s: int = 60

    ai_provider: Literal["rules", "ollama", "claude"] = "rules"
    ollama_base_url: str = "http://localhost:11434"
    # Chosen by measurement, see docs/spikes/ollama-benchmark.md
    ollama_model: str = "gemma4:e2b"
    ai_timeout_s: float = 150.0  # one packet through Ollama; the plan's limit is under 2 minutes
    claude_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str = ""

    @model_validator(mode="after")
    def _production_keeps_the_gate(self) -> "Settings":
        if self.env == "production" and self.precheck_gate != "recording":
            raise ValueError("PRECHECK_GATE must be 'recording' when ENV=production")
        return self

    @property
    def effective_chunk_fail_rate(self) -> float:
        return 0.0 if self.env == "production" else self.chunk_fail_rate

    @property
    def video_root_path(self) -> Path:
        path = Path(self.video_root)
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()

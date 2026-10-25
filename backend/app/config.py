import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repository root, one level above backend/. .env lives there, and so do relative data paths.
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """One place for configuration. Names match .env.example (case-insensitive)."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    env: str = "development"

    database_url: str = "postgresql+psycopg://integrity:integrity@localhost:5433/integrity"
    test_database_url: str = (
        "postgresql+psycopg://integrity:integrity@localhost:5433/integrity_test"
    )

    # The address candidates open. Used to build the invitation links.
    public_base_url: str = "http://localhost:5173"
    # Signs every token. Empty in development gives a fresh random one on each start (staff sign in
    # again after a restart); production must set its own, long and secret.
    session_secret: str = ""

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

    # Full path to ffmpeg(.exe), read from .env like every other setting. Empty: the one on PATH.
    ffmpeg_bin: str = ""

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

    # Who writes the questions of an AI sitting (one paper per candidate). Ollama uses its own model
    # setting below, falling back to OLLAMA_MODEL; Claude uses CLAUDE_MODEL and ANTHROPIC_API_KEY.
    question_provider: Literal["ollama", "claude"] = "ollama"
    # Chosen by trying the models installed on the dev laptop (24 Oct): qwen3:8b wrote numerical
    # questions that passed the checks more often than qwen2.5:7b; gemma4:e2b was slower and mostly
    # failed them. Logic puzzles often fail the independent check on any local model.
    question_ollama_model: str = "qwen3:8b"
    # One call writes a handful of questions, or solves them; a local model on a CPU is slow.
    question_timeout_s: float = 300.0
    # How many candidates' papers are written at the same time.
    question_workers: int = 2
    # A candidate waiting this long for their questions is offered a way to ask again.
    question_wait_limit_s: int = 600
    # Writing a paper stops with an error after this long, so nothing runs for ever. Anything
    # already written is kept, and the candidate can ask again.
    question_paper_timeout_s: int = 1800
    # How many times each written question is answered again, without its key and with the options
    # in a different order, and must come out as its key says. More is stricter and slower.
    question_solves: int = Field(2, ge=1, le=3)

    # Outgoing mail (invitations and results), over SMTP with STARTTLS. An empty host means mail is
    # not set up: emails wait in the outbox and the admin page says so. docs/plan/email-setup.md.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""  # the address candidates see; most providers insist it is the account's own
    mail_from_name: str = "Cytonn Aptitude Test"

    # Cytonn's read-only aptitude API, used only by the fetch_cytonn_bank job. The key is a shared
    # secret: it stays in .env and is never printed or logged.
    aptitude_api_base_url: str = "https://hr.cytonn.com/api/aptitude"
    # X-API-KEY is named for the header it fills; APTITUDE_API_KEY is the same key under a name that
    # Compose and shells can carry (they cannot interpolate a name with dashes).
    aptitude_api_key: str = Field(
        "", validation_alias=AliasChoices("X-API-KEY", "APTITUDE_API_KEY")
    )

    @model_validator(mode="after")
    def _production_keeps_the_gate(self) -> "Settings":
        if self.env == "production" and self.precheck_gate != "recording":
            raise ValueError("PRECHECK_GATE must be 'recording' when ENV=production")
        return self

    @model_validator(mode="after")
    def _a_secret_to_sign_with(self) -> "Settings":
        if self.env != "production":
            if not self.session_secret:
                self.session_secret = secrets.token_urlsafe(32)
            return self
        weak = len(self.session_secret) < MIN_SECRET_LENGTH
        if weak or self.session_secret.startswith("change-me"):
            raise ValueError(
                f"SESSION_SECRET must be a long random value ({MIN_SECRET_LENGTH}+ characters) "
                "when ENV=production"
            )
        if not self.public_base_url.startswith("https://"):
            raise ValueError("PUBLIC_BASE_URL must be an https:// address when ENV=production")
        return self

    @property
    def question_model(self) -> str:
        """The model that writes questions, whichever provider is chosen."""
        if self.question_provider == "claude":
            return self.claude_model
        return self.question_ollama_model or self.ollama_model

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

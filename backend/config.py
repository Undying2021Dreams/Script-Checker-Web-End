"""
Application configuration — all settings via environment variables / .env file.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database (Postgres — see docker-compose.yml for local dev)
    DATABASE_URL: str = "postgresql+psycopg2://webend:webend_dev_only@localhost:5434/webend"

    # Background job queue (arq)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Public URLs / browser access
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    FRONTEND_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Microsoft Entra ID (Azure AD) — "Sign in with Microsoft".
    # Single app registration used for both the SPA and the API (its
    # "Expose an API" scope), per the app's "Any Entra ID Tenant + Personal
    # Microsoft accounts" setting.
    AZURE_TENANT_ID: str = "common"
    AZURE_CLIENT_ID: str = ""
    AZURE_OPENAPI_CLIENT_ID: str = ""  # frontend SPA app registration's client ID (for Swagger UI login only)

    # Comma-separated emails auto-assigned role="teacher" on first sign-in.
    # Everyone else who signs in becomes role="student". No admin UI for
    # this yet — deliberately simple for a small, few-teacher deployment.
    TEACHER_EMAILS: str = ""

    # LLM providers — server-side keys the deployer configures once, not
    # per-teacher. A teacher just picks a provider from a dropdown.
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    SELF_HOSTED_LLM_URL: str = ""  # e.g. "https://xxxx.ngrok.io/v1"

    # ArUco / fiducial marker config
    ARUCO_DICT: str = "DICT_4X4_50"
    MARKER_SIZE_PX: int = 60   # ~1 cm at 150 DPI
    MARKER_MARGIN_PX: int = 40

    # Canvas defaults
    DEFAULT_DPI: int = 150
    DEFAULT_PHYSICAL_PAGE: str = "A4"

    # Quality knobs for images that get shown to a teacher / fed to an LLM
    # (question-segment images, ground-truth-solution images). Deliberately
    # separate from DEFAULT_DPI / MARKER_SIZE_PX above — those are load-
    # bearing for the printed page's physical marker geometry, these aren't.
    LLM_IMAGE_SCALE_FACTOR: int = 2  # Playwright device_scale_factor — supersamples text without changing layout
    SUBMISSION_PDF_DPI: int = 300    # rasterization DPI for tablet-answered PDF submissions before cropping

    # Off by default — carried over from Component-1 (see its Key-Decisions.txt,
    # 2026-08-19 entry). Global page homography measured more accurate on
    # clean photos; local QR registration's real-world benefit under paper
    # curl/lens distortion is still unvalidated.
    USE_LOCAL_QR_REGISTRATION: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator(
        "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SELF_HOSTED_LLM_URL",
        "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_OPENAPI_CLIENT_ID",
        mode="before",
    )
    @classmethod
    def _strip_whitespace(cls, v):
        return v.strip() if isinstance(v, str) else v

    @property
    def public_base_url(self) -> str:
        return self.PUBLIC_BASE_URL.rstrip("/")

    @property
    def frontend_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.FRONTEND_ORIGINS.split(",") if origin.strip()]

    @property
    def teacher_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.TEACHER_EMAILS.split(",") if e.strip()}


settings = Settings()

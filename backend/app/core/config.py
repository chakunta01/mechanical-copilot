"""Application settings loaded from environment / .env (12-factor)."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
PROJECT_ROOT = BACKEND_ROOT.parent  # repo root

# Read the repo-root .env (documented location) and backend/.env. With a tuple,
# pydantic-settings applies files in order and the LAST one wins on conflicts.
ENV_FILES: tuple[str, ...] = (
    str(PROJECT_ROOT / ".env"),
    str(BACKEND_ROOT / ".env"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "dev"
    log_level: str = "INFO"
    secret_key: str = Field(default="dev-secret-change-me", min_length=8)
    admin_bootstrap_token: str = ""
    access_token_expire_min: int = 30
    refresh_token_expire_days: int = 7
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Database / files
    database_url: str = "sqlite:///./data/copilot.db"
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 25

    # LLM
    llm_provider: str = "fake"  # openai | openai_compatible | fake
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    llm_model: str = "gpt-6-luna"
    llm_vision_model: str = ""
    llm_timeout_s: int = 120
    llm_temperature: float = 0.2

    # Media generation (direct OpenAI Images API; independent of chat gateway)
    image_api_key: str = ""
    image_api_base_url: str = "https://api.openai.com/v1"
    image_generation_model: str = "gpt-image-2.5-flare"

    # Embeddings
    embeddings_provider: str = "hashing"  # openai_compatible | hashing
    embeddings_base_url: str = "https://api.openai.com/v1"
    embeddings_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("EMBEDDINGS_API_KEY", "OPENAI_API_KEY"),
    )
    embeddings_model: str = "text-embedding-3-small"
    embeddings_dim: int = 256
    # Offline hashing fallback is calibrated (score rescaling, QA refusal band) at
    # 256 dims. It must NOT follow EMBEDDINGS_DIM, which describes the real model.
    hashing_dim: int = 256

    # Vector store
    vector_store: str = "numpy"  # numpy | chroma
    chroma_dir: str = "./data/chroma"

    # Retrieval
    retrieval_top_k: int = 6
    retrieval_min_score: float = 0.15
    citation_required: bool = True
    unsupported_claim_guard: bool = True
    qa_refusal_threshold: float = 0.12  # calibrated absolute floor
    # Self-calibrated refusal margin: a question's top retrieval score must beat
    # the off-topic baseline (probe questions embedded with the same model) by
    # this factor, else the assistant refuses instead of guessing.
    qa_baseline_margin: float = 1.15

    # Vision thresholds
    defect_confidence_threshold: float = 0.60
    img_min_width: int = 320
    img_min_height: int = 240
    img_max_brightness_mean: float = 245.0
    img_min_brightness_mean: float = 25.0
    img_max_blur_laplacian_var: float = 35.0
    img_max_glare_ratio: float = 0.25

    # Security
    rate_limit_per_min: int = 120

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.is_prod:
            if self.secret_key == "dev-secret-change-me" or len(self.secret_key) < 32:
                raise ValueError("Production requires a random SECRET_KEY with at least 32 characters")
            if len(self.admin_bootstrap_token) < 32:
                raise ValueError("Production requires an ADMIN_BOOTSTRAP_TOKEN with at least 32 characters")
            if not self.database_url.startswith(("postgresql://", "postgresql+")):
                raise ValueError("Production requires PostgreSQL; SQLite is not suitable for public deployment")
            if self.llm_provider == "fake" or not self.llm_api_key:
                raise ValueError("Production requires a configured LLM_PROVIDER and LLM_API_KEY")
            if self.embeddings_provider == "hashing" or not self.embeddings_api_key:
                raise ValueError("Production requires a configured embeddings provider and API key")
        return self

    @field_validator("log_level", "app_env")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

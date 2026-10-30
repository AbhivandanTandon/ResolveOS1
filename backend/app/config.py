from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SQLite works out of the box; point at PostgreSQL (see docker-compose.yml) for the full stack:
    # postgresql+psycopg://resolveos:resolveos@localhost:5432/resolveos
    database_url: str = "sqlite:///./resolveos.db"
    jwt_secret: str = "dev-only-secret-change-me-in-production-0001"
    token_ttl_minutes: int = 12 * 60
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # NVIDIA API (OpenAI-compatible). Without a key the deterministic fallback diagnoser is used
    # and every output is labelled as such in the audit trail.
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Defaults are the models the ML notebook evaluated (metrics.json -> models_used).
    model_ultra: str = "nvidia/nemotron-3-ultra-550b-a55b"
    model_super: str = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    model_nano: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    llm_timeout_seconds: float = 45.0

    # ML/RAG notebook export: resolveos_kb.pkl, triage/action/risk .joblib, cases.parquet, metrics.json.
    ml_enabled: bool = True
    ml_artifacts_dir: str = str(BACKEND_DIR / "ml_artifacts")

    # Optional token prices (USD per million tokens) for cost-per-case estimates. Left unset, tokens are
    # still metered but no cost is invented. Example: LLM_PRICE_PER_MTOK='{"nvidia/llama-3.3-nemotron-super-49b-v1": 0.4}'
    llm_price_per_mtok: dict[str, float] = {}

    # Redis fans live updates out across API workers. Without it, updates stay in-process.
    redis_url: str | None = None

    # Run Alembic migrations on start. Tests turn this off and use create_all.
    migrate_on_start: bool = True

    # Seed demo cases on first start.
    seed_demo: bool = True
    # Multiplier for simulator pacing (0 = instant, useful in tests).
    sim_delay_scale: float = 1.0


settings = Settings()

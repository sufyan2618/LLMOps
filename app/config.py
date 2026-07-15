"""Application settings loaded from environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "llmops-chat"
    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    model_path: str = "/models/qwen3-4b-q4_k_m.gguf"
    model_n_ctx: int = 2048
    model_n_threads: int = 4
    lazy_load_model: bool = True

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_enabled: bool = True

    otel_enabled: bool = True
    otel_service_name: str = "llmops-chat"
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    otel_exporter_otlp_protocol: str = "grpc"

    metrics_enabled: bool = True

    eval_min_avg_score: float = 0.9
    eval_max_p95_latency_ms: float = 2000.0


@lru_cache
def get_settings() -> Settings:
    return Settings()

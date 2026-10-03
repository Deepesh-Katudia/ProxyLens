"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongodb_uri: SecretStr = SecretStr("")
    mongodb_db: str = "proxylens"
    mongodb_timeout_ms: int = Field(default=3000, gt=0)

    embedding_provider: Literal["local", "vertex"] = "local"
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = Field(default=768, gt=0)

    gcp_project_id: str = ""
    gcp_region: str = "asia-south1"
    teacher_provider: Literal["openrouter", "vertex"] = "openrouter"
    teacher_model: str = ""
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    teacher_max_output_tokens: int = Field(default=2048, gt=0)
    teacher_structured_output: bool = True  # strict json_schema; False -> json_object
    teacher_reasoning_effort: Literal["", "minimal", "low", "medium", "high"] = "low"

    student_provider: Literal["local_gguf", "vertex", "base_hf"] = "local_gguf"
    student_gguf_repo: str = "deepesh/proxylens-qwen3b-gguf-v1"
    student_gguf_file: str = "proxylens-q4_k_m.gguf"
    student_gguf_path: str = ""  # local GGUF; overrides the HF Hub download when set
    student_n_threads: int | None = None  # llama.cpp threads; None = library default
    student_constrained_json: bool = True  # grammar-constrained decoding to the schema

    hf_token: SecretStr = SecretStr("")
    api_key: SecretStr = SecretStr("")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

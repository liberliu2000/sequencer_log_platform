from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Sequencer Log Platform"
    app_env: Literal["dev", "test", "prod"] = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'sequencer_log_platform.db').as_posix()}"
    data_dir: str = str(BASE_DIR / "data")
    upload_dir: str = str(BASE_DIR / "data" / "uploads")
    export_dir: str = str(BASE_DIR / "data" / "exports")
    log_dir: str = str(BASE_DIR / "data" / "runtime_logs")

    max_upload_mb: int = 512
    chunk_size: int = 65536

    default_time_rounding: Literal["truncate", "round"] = "truncate"
    default_timezone: str = "Asia/Shanghai"

    llm_enabled: bool = False
    llm_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    llm_api_key: str = ""
    llm_model: str = "ep-xxx"
    llm_timeout_seconds: int = 45
    llm_max_retries: int = 3

    llm_context_pre_lines: int = 8
    llm_context_post_lines: int = 8
    llm_context_time_window_seconds: int = 90
    llm_context_related_component_limit: int = 30
    llm_context_related_cycle_limit: int = 30
    llm_context_max_stack_frames: int = 8
    llm_context_max_token_budget: int = 2200
    llm_context_stage1_token_budget: int = 1200

    api_prefix: str = "/api/v1"
    cors_allow_origins: str = "*"
    task_queue_workers: int = 2


    @property
    def thresholds_path(self) -> Path:
        return BASE_DIR / "config" / "thresholds.yaml"

    @property
    def parser_rules_path(self) -> Path:
        return BASE_DIR / "config" / "parser_rules.yaml"

    @property
    def error_rules_path(self) -> Path:
        return BASE_DIR / "config" / "error_rules.yaml"

    @property
    def prompt_templates_path(self) -> Path:
        return BASE_DIR / "config" / "prompt_templates.yaml"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.export_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    return settings

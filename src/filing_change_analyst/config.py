"""Runtime configuration.

All secrets and identity come from the environment (or a local ``.env``).
Nothing sensitive is ever defaulted into source.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent

# SEC's stated fair-access ceiling is 10 requests/second. We stay far below it.
SEC_MIN_REQUEST_INTERVAL_S = 0.15


class Settings(BaseSettings):
    """Environment-driven settings."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SEC identity. SEC rejects (403) clients that do not identify themselves.
    sec_user_agent: str = Field(
        default="filing-change-analyst (contact configured via SEC_USER_AGENT)",
        alias="SEC_USER_AGENT",
    )

    # `API_KEY` is the documented name. `ANTHROPIC_API_KEY` is also accepted
    # because it is the SDK's own convention and is often already set in the
    # environment — silently ignoring a correctly-set key is a bad failure mode,
    # since the app degrades to deterministic mode and looks like it is working.
    api_key: str = Field(
        default="",
        validation_alias=AliasChoices("API_KEY", "ANTHROPIC_API_KEY"),
    )
    llm_model: str = Field(default="claude-opus-5", alias="FCA_LLM_MODEL")
    llm_max_tokens: int = Field(default=8000, alias="FCA_LLM_MAX_TOKENS")
    # Current Claude models reject `temperature`; reproducibility is controlled
    # with a fixed effort level and a versioned prompt instead.
    llm_effort: str = Field(default="medium", alias="FCA_LLM_EFFORT")
    llm_timeout: float = Field(default=120.0, alias="FCA_LLM_TIMEOUT")
    llm_max_retries: int = Field(default=2, alias="FCA_LLM_MAX_RETRIES")

    default_ticker: str = Field(default="MSFT", alias="FCA_DEFAULT_TICKER")
    cache_dir: str = Field(default=".cache", alias="FCA_CACHE_DIR")
    http_timeout: float = Field(default=30.0, alias="FCA_HTTP_TIMEOUT")
    http_max_retries: int = Field(default=3, alias="FCA_HTTP_MAX_RETRIES")
    offline: bool = Field(default=False, alias="FCA_OFFLINE")
    log_level: str = Field(default="INFO", alias="FCA_LOG_LEVEL")

    @property
    def cache_path(self) -> Path:
        p = Path(self.cache_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def llm_available(self) -> bool:
        return bool(self.api_key.strip())

    def sec_identity_configured(self) -> bool:
        """True when SEC_USER_AGENT looks like a real ``Name email`` identity."""
        ua = self.sec_user_agent
        return "@" in ua and "configured via" not in ua


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


_LOGGING_READY = False


def configure_logging() -> None:
    """Idempotent logging setup. Never logs secrets."""
    global _LOGGING_READY
    if _LOGGING_READY:
        return
    level = os.environ.get("FCA_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _LOGGING_READY = True

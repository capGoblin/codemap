"""Settings: init args > env > config.toml > defaults."""

import os
from pathlib import Path
from typing import Literal

import platformdirs
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

Provider = Literal["openai", "anthropic"]
DEFAULT_MODELS: dict[str, str] = {"openai": "gpt-5-nano", "anthropic": "claude-haiku-5-5"}
FALLBACK_KEY_VARS: dict[str, str] = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def config_path() -> Path:
    override = os.environ.get("CODEMAP_CONFIG_FILE")
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir("codemap")) / "config.toml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True, env_prefix="CODEMAP_")

    provider: Provider = "openai"
    api_key: SecretStr = SecretStr("")
    model: str | None = None
    base_url: str | None = None
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None
    max_wall_seconds: int = 900
    max_tokens_total: int = 2_000_000
    max_cost_usd: float = Field(
        5.0, validation_alias=AliasChoices("CODEMAP_MAX_COST", "max_cost_usd")
    )
    max_tool_calls: int = 400
    max_hops: int = 200
    skeleton_hops: int = 40
    deepen_hops: int = 160
    deepen_max_depth: int = 5  # thin wrappers eat levels, so 3 stops short of the real work
    deepen_max_points: int = 80
    build_max_tokens: int = 1_500_000
    build_max_tool_calls: int = 300
    split_concurrency: int = 4
    request_timeout_s: float = 120

    @property
    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODELS[self.provider]

    @property
    def model_id(self) -> str:
        """Provider and model, for cache keys."""
        return f"{self.provider}/{self.resolved_model}"

    def resolved_api_key(self) -> str:
        """The configured key, else the provider's own env var, else empty."""
        return self.api_key.get_secret_value() or os.environ.get(
            FALLBACK_KEY_VARS[self.provider], ""
        )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml = TomlConfigSettingsSource(settings_cls, toml_file=config_path())
        return (init_settings, env_settings, toml)


def load_settings() -> Settings:
    return Settings.model_validate({})

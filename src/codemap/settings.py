"""Settings: init args > env > config.toml > defaults."""

import os
from pathlib import Path

import platformdirs
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

DEFAULT_MODEL = "MiniMax-M3"


def config_path() -> Path:
    override = os.environ.get("CODEMAP_CONFIG_FILE")
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir("codemap")) / "config.toml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    anthropic_base_url: str = "https://api.minimax.io/anthropic"
    anthropic_auth_token: SecretStr = SecretStr("")
    model: str = Field(DEFAULT_MODEL, validation_alias=AliasChoices("CODEMAP_MODEL", "model"))
    price_in_per_mtok: float = 0.30
    price_out_per_mtok: float = 1.20
    max_wall_seconds: int = 900
    max_tokens_total: int = 2_000_000
    max_cost_usd: float = 5.0
    max_tool_calls: int = 400
    max_hops: int = 200
    skeleton_hops: int = 40
    deepen_hops: int = 160
    split_concurrency: int = 4
    request_timeout_s: float = 120

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

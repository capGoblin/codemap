from pathlib import Path

import pytest

from codemap.settings import Settings, load_settings

ENV_VARS = (
    "CODEMAP_PROVIDER",
    "CODEMAP_MODEL",
    "CODEMAP_API_KEY",
    "CODEMAP_BASE_URL",
    "CODEMAP_MAX_COST",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.toml"
    monkeypatch.setenv("CODEMAP_CONFIG_FILE", str(path))
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return path


def test_env_overrides_config_file(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file.write_text('model = "a"\n')
    assert load_settings().model == "a"
    monkeypatch.setenv("CODEMAP_MODEL", "b")
    assert load_settings().model == "b"


def test_init_args_beat_env(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEMAP_MODEL", "from-env")
    monkeypatch.setenv("CODEMAP_PROVIDER", "anthropic")
    settings = Settings(model="from-flag", provider="openai")
    assert settings.model == "from-flag"
    assert settings.provider == "openai"


def test_key_is_secret(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEMAP_API_KEY", "s3cr3t-value")
    settings = load_settings()
    assert "s3cr3t-value" not in repr(settings)
    assert settings.resolved_api_key() == "s3cr3t-value"


def test_default_model_per_provider(config_file: Path) -> None:
    assert load_settings().resolved_model == "gpt-5-nano"
    assert Settings(provider="anthropic").resolved_model == "claude-haiku-5-5"
    assert Settings(model="x").resolved_model == "x"


def test_key_falls_back_to_provider_env(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an")
    assert load_settings().resolved_api_key() == "oa"
    assert Settings(provider="anthropic").resolved_api_key() == "an"
    monkeypatch.setenv("CODEMAP_API_KEY", "own")
    assert load_settings().resolved_api_key() == "own"


def test_max_cost_env(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_settings().max_cost_usd == 5.0
    monkeypatch.setenv("CODEMAP_MAX_COST", "1.5")
    assert load_settings().max_cost_usd == 1.5


def test_defaults(config_file: Path) -> None:
    settings = load_settings()
    assert settings.max_hops == 200
    assert settings.request_timeout_s == 120
    assert settings.provider == "openai"
    assert settings.base_url is None

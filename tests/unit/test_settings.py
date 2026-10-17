from pathlib import Path

import pytest

from codemap.settings import load_settings


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.toml"
    monkeypatch.setenv("CODEMAP_CONFIG_FILE", str(path))
    for var in ("CODEMAP_MODEL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return path


def test_env_overrides_config_file(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file.write_text('model = "a"\n')
    assert load_settings().model == "a"
    monkeypatch.setenv("CODEMAP_MODEL", "b")
    assert load_settings().model == "b"


def test_token_is_secret(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "s3cr3t-value")
    settings = load_settings()
    assert "s3cr3t-value" not in repr(settings)
    assert settings.anthropic_auth_token.get_secret_value() == "s3cr3t-value"


def test_defaults(config_file: Path) -> None:
    settings = load_settings()
    assert settings.max_hops == 200
    assert settings.request_timeout_s == 120

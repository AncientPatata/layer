import os

import pytest

from layer import ConfigPipeline, field, layerclass
from layer.providers import EnvProvider


@layerclass
class LLMConfig:
    primary_model: str = field(str, default="gpt-3")
    secondary_model: str = field(str, default="gpt-4")


@layerclass
class AppConfig:
    port: int = field(int, default=8080)
    db_password: str = field(str, env="DB_PASS", default="default_pass")
    llm: LLMConfig = field(LLMConfig)


def test_unified_env_provider_system_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_PORT=8000\nAPP_LLM_PRIMARY_MODEL=claude\n")

    # System env overrides
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.delenv("APP_LLM_PRIMARY_MODEL", raising=False)

    pipeline = ConfigPipeline(AppConfig).add_provider(
        EnvProvider(prefix="APP_", env_file=str(env_file))
    )

    config = pipeline.load()

    # System env (9000) overrides .env (8000)
    assert config.port == 9000
    # Pulled from .env file since it wasn't in system env
    assert config.llm.primary_model == "claude"


def test_unified_env_provider_missing_file_ignored(monkeypatch):
    monkeypatch.setenv("APP_PORT", "7777")

    # ignore_missing=True is default
    pipeline = ConfigPipeline(AppConfig).add_provider(
        EnvProvider(prefix="APP_", env_file="does_not_exist.env")
    )
    config = pipeline.load()
    assert config.port == 7777


def test_unified_env_provider_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        ConfigPipeline(AppConfig).add_provider(
            EnvProvider(prefix="APP_", env_file="does_not_exist.env", ignore_missing=False)
        ).load()


def test_unified_env_provider_explicit_override_ignores_prefix(monkeypatch):
    # db_password is bound to DB_PASS
    monkeypatch.setenv("DB_PASS", "super_secret")

    pipeline = ConfigPipeline(AppConfig).add_provider(EnvProvider(prefix="APP_"))
    config = pipeline.load()
    assert config.db_password == "super_secret"


def test_unified_env_provider_no_side_effects(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_PORT=1234\nNEW_VAR=hello\n")

    monkeypatch.delenv("NEW_VAR", raising=False)

    pipeline = ConfigPipeline(AppConfig).add_provider(
        EnvProvider(prefix="APP_", env_file=str(env_file))
    )
    pipeline.load()

    # Global os.environ should NOT be mutated
    assert "NEW_VAR" not in os.environ

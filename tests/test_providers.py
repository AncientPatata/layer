"""Tests for BaseProvider and built-in providers."""

import json
import os

import pytest

from layer import MissingDependencyError
from layer.providers import BaseProvider, DotEnvProvider, EnvProvider, FileProvider

# ---------------------------------------------------------------------------
# Test helper: DictProvider
# ---------------------------------------------------------------------------


class DictProvider(BaseProvider):
    """Simple in-memory provider for testing."""

    def __init__(self, data: dict, name: str = "dict"):
        self._data = data
        self._name = name

    def read(self) -> dict:
        return self._data

    @property
    def source_name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# BaseProvider
# ---------------------------------------------------------------------------


class TestBaseProvider:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseProvider()

    def test_default_source_name(self):
        p = DictProvider({"a": 1})
        assert p.source_name == "dict"

    def test_default_watchable_is_false(self):
        p = DictProvider({})
        assert p.watchable is False


# ---------------------------------------------------------------------------
# FileProvider
# ---------------------------------------------------------------------------


class TestFileProvider:
    def test_reads_yaml(self, tmp_path):
        import yaml

        path = str(tmp_path / "config.yml")
        with open(path, "w") as f:
            yaml.dump({"host": "example.com", "port": 8080}, f)

        p = FileProvider(path)
        data = p.read()
        assert data["host"] == "example.com"
        assert data["port"] == 8080

    def test_reads_json(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w") as f:
            json.dump({"host": "json.example.com"}, f)

        p = FileProvider(path)
        data = p.read()
        assert data["host"] == "json.example.com"

    def test_source_name(self):
        p = FileProvider("/etc/app/config.yml")
        assert p.source_name == "file:/etc/app/config.yml"

    def test_watchable_false_by_default(self):
        p = FileProvider("config.yml")
        assert p.watchable is False

    def test_watchable_true_when_set(self):
        p = FileProvider("config.yml", watch=True)
        assert p.watchable is True

    def test_file_not_found_raises(self, tmp_path):
        p = FileProvider(str(tmp_path / "nonexistent.yml"))
        with pytest.raises(FileNotFoundError):
            p.read()

    def test_file_not_found_ignored_when_required_false(self, tmp_path):
        p = FileProvider(str(tmp_path / "nonexistent.yml"), required=False)
        assert p.read() == {}


# ---------------------------------------------------------------------------
# EnvProvider
# ---------------------------------------------------------------------------


class TestEnvProvider:
    def test_reads_prefixed_vars(self, monkeypatch):
        monkeypatch.setenv("MYAPP_HOST", "env.example.com")
        monkeypatch.setenv("MYAPP_PORT", "9090")
        monkeypatch.setenv("OTHER_KEY", "ignored")

        p = EnvProvider(prefix="MYAPP")
        data = p.read()
        assert data["host"] == "env.example.com"
        assert data["port"] == "9090"
        assert "key" not in data

    def test_strips_prefix_and_lowercases(self, monkeypatch):
        monkeypatch.setenv("APP_DATABASE_HOST", "db.local")
        p = EnvProvider(prefix="APP")
        data = p.read()
        assert "database_host" in data

    def test_source_name(self):
        p = EnvProvider(prefix="APP")
        assert p.source_name == "env:APP_*"

    def test_custom_separator(self, monkeypatch):
        monkeypatch.setenv("APP--HOST", "sep.example.com")
        p = EnvProvider(prefix="APP", separator="--")
        data = p.read()
        assert data["host"] == "sep.example.com"

    def test_empty_when_no_matching_vars(self, monkeypatch):
        # Clear any APP_ vars that might exist
        for key in list(os.environ.keys()):
            if key.startswith("ZZZTESTPREFIX_"):
                monkeypatch.delenv(key)
        p = EnvProvider(prefix="ZZZTESTPREFIX")
        assert p.read() == {}


# ---------------------------------------------------------------------------
# DotEnvProvider
# ---------------------------------------------------------------------------


class TestDotEnvProvider:
    def test_injects_into_environ(self, tmp_path, monkeypatch):
        env_path = str(tmp_path / ".env")
        with open(env_path, "w") as f:
            f.write("MYAPP_HOST=injected.example.com\nMYAPP_PORT=9999\n")

        # Ensure keys are absent before read
        monkeypatch.delenv("MYAPP_HOST", raising=False)
        monkeypatch.delenv("MYAPP_PORT", raising=False)

        p = DotEnvProvider(path=env_path)
        try:
            p.read()
        except (ImportError, MissingDependencyError):
            pytest.skip("python-dotenv not installed")

        import os

        assert os.environ.get("MYAPP_HOST") == "injected.example.com"
        assert os.environ.get("MYAPP_PORT") == "9999"

    def test_returns_empty_dict(self, tmp_path, monkeypatch):
        env_path = str(tmp_path / ".env")
        with open(env_path, "w") as f:
            f.write("KEY=value\n")

        monkeypatch.delenv("KEY", raising=False)
        p = DotEnvProvider(path=env_path)
        try:
            result = p.read()
        except (ImportError, MissingDependencyError):
            pytest.skip("python-dotenv not installed")

        assert result == {}

    def test_does_not_override_existing_env_vars(self, tmp_path, monkeypatch):
        env_path = str(tmp_path / ".env")
        with open(env_path, "w") as f:
            f.write("PROTECTED_KEY=from_dotenv\n")

        monkeypatch.setenv("PROTECTED_KEY", "already_set")
        p = DotEnvProvider(path=env_path)
        try:
            p.read()
        except (ImportError, MissingDependencyError):
            pytest.skip("python-dotenv not installed")

        import os

        assert os.environ["PROTECTED_KEY"] == "already_set"

    def test_pipeline_dotenv_with_env_provider(self, tmp_path, monkeypatch):
        """Integration: DotEnvProvider injects, EnvProvider strips prefix."""
        from conftest import FileConfig

        from layer import ConfigPipeline
        from layer.providers import EnvProvider

        env_path = str(tmp_path / ".env")
        with open(env_path, "w") as f:
            f.write("APP_HOST=dotenv.example.com\nAPP_PORT=7777\n")

        monkeypatch.delenv("APP_HOST", raising=False)
        monkeypatch.delenv("APP_PORT", raising=False)

        try:
            pipeline = (
                ConfigPipeline(FileConfig)
                .add_provider(DotEnvProvider(path=env_path))
                .add_provider(EnvProvider(prefix="APP"))
            )
            config = pipeline.load()
        except (ImportError, MissingDependencyError):
            pytest.skip("python-dotenv not installed")

        assert config.host == "dotenv.example.com"
        assert config.port == 7777

    def test_source_name(self):
        p = DotEnvProvider("/app/.env")
        assert p.source_name == "dotenv:/app/.env"

    def test_import_error_without_dotenv(self, monkeypatch):
        # Temporarily hide dotenv module
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("No module named 'dotenv'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        p = DotEnvProvider()
        with pytest.raises((ImportError, MissingDependencyError), match="python-dotenv"):
            p.read()


# ---------------------------------------------------------------------------
# SSMProvider
# ---------------------------------------------------------------------------


class TestSSMProvider:
    def test_import_error_without_boto3(self, monkeypatch):
        from layer.providers.ssm import SSMProvider

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        p = SSMProvider("/prod/app/")
        with pytest.raises((ImportError, MissingDependencyError), match="boto3"):
            p.read()

    def test_source_name(self):
        from layer.providers.ssm import SSMProvider

        p = SSMProvider("/prod/app/")
        assert p.source_name == "ssm:/prod/app/"

    def test_schema_bound_unflattening(self):
        from layer import field, layerclass
        from layer.providers.ssm import SSMProvider

        @layerclass
        class DBConfig:
            port: int = field(int, default=5432)
            host: str = field(str, default="localhost")

        @layerclass
        class AppConfig:
            database: DBConfig = field(DBConfig)

        p = SSMProvider("/myapp/")
        p.bind_schema(AppConfig)

        pool = {
            "database/port": "9999",
            "database_host": "db.internal",  # Test legacy fallback mapping
        }

        result = p._resolve_schema(p._schema, "", pool)
        assert result == {"database": {"port": "9999", "host": "db.internal"}}

    def test_unbound_flat_resolution(self):
        from layer.providers.ssm import SSMProvider

        p = SSMProvider("/myapp/")

        pool = {
            "database/port": "9999",
            "database_host": "db.internal",
        }

        result = p._resolve_flat(pool)
        assert result == {"database_port": "9999", "database_host": "db.internal"}


# ---------------------------------------------------------------------------
# VaultProvider (import-error only — no real Vault in tests)
# ---------------------------------------------------------------------------


class TestVaultProvider:
    def test_import_error_without_hvac(self, monkeypatch):
        from layer.providers.vault import VaultProvider

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "hvac":
                raise ImportError("No module named 'hvac'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        p = VaultProvider("myapp/config")
        with pytest.raises((ImportError, MissingDependencyError), match="hvac"):
            p.read()

    def test_source_name(self):
        from layer.providers.vault import VaultProvider

        p = VaultProvider("myapp/config", mount_point="kv")
        assert p.source_name == "vault:kv/myapp/config"


# ---------------------------------------------------------------------------
# EtcdProvider
# ---------------------------------------------------------------------------


class TestEtcdProvider:
    def test_schema_bound_unflattening(self):
        from layer import field, layerclass
        from layer.providers.etcd import EtcdProvider

        @layerclass
        class SubConfig:
            value: str = field(str, default="a")

        @layerclass
        class RootConfig:
            sub: SubConfig = field(SubConfig)

        p = EtcdProvider("/prefix/")
        p.bind_schema(RootConfig)

        pool = {"sub/value": "b"}
        result = p._resolve_schema(p._schema, "", pool)
        assert result == {"sub": {"value": "b"}}

    def test_unbound_flat_resolution(self):
        from layer.providers.etcd import EtcdProvider

        p = EtcdProvider("/prefix/")

        pool = {"sub/value": "b"}
        result = p._resolve_flat(pool)
        assert result == {"sub_value": "b"}

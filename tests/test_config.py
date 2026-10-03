import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_DB", "proxylens_test")
    monkeypatch.setenv("EMBEDDING_DIM", "384")

    settings = Settings(_env_file=None)

    assert settings.mongodb_db == "proxylens_test"
    assert settings.embedding_dim == 384


def test_secrets_are_masked_in_repr() -> None:
    settings = Settings(_env_file=None, api_key="super-secret")

    assert "super-secret" not in repr(settings)
    assert settings.api_key.get_secret_value() == "super-secret"


def test_invalid_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, student_provider="openai")

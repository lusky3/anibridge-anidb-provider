"""Tests for AniDB UDP response models and config."""
import pytest
import msgspec
from anibridge.providers.anidb.config import AnidbProviderConfig


def test_config_requires_username():
    with pytest.raises((msgspec.ValidationError, TypeError)):
        msgspec.convert({"password": "pass", "client": "c", "client_version": 1}, type=AnidbProviderConfig)


def test_config_requires_password():
    with pytest.raises((msgspec.ValidationError, TypeError)):
        msgspec.convert({"username": "user", "client": "c", "client_version": 1}, type=AnidbProviderConfig)


def test_config_defaults():
    cfg = msgspec.convert(
        {"username": "user", "password": "pass", "client": "myclient", "client_version": 1},
        type=AnidbProviderConfig,
    )
    assert cfg.username == "user"
    assert cfg.password == "pass"
    assert cfg.client == "myclient"
    assert cfg.client_version == 1
    assert cfg.encrypt is None
    assert cfg.nat is False
    assert cfg.rate_limit == 0.5


def test_config_with_encrypt():
    cfg = msgspec.convert(
        {"username": "u", "password": "p", "client": "c", "client_version": 2, "encrypt": "apikey123"},
        type=AnidbProviderConfig,
    )
    assert cfg.encrypt == "apikey123"

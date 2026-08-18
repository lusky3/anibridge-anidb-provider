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

from anibridge.providers.anidb.models import (
    AnidbResponse,
    AnimeInfo,
    MylistEntry,
    MylistStatus,
    parse_response,
)


# --- parse_response ---

def test_parse_response_200_login():
    resp = parse_response(b"200 s3ss10n LOGIN ACCEPTED\n")
    assert resp.code == 200
    assert "s3ss10n" in resp.body


def test_parse_response_321_no_entry():
    resp = parse_response(b"321 NO SUCH ENTRY\n")
    assert resp.code == 321
    assert resp.body == "NO SUCH ENTRY"


def test_parse_response_invalid_raises():
    with pytest.raises(ValueError):
        parse_response(b"NOT A RESPONSE")


def test_parse_response_empty_body():
    resp = parse_response(b"211")
    assert resp.code == 211
    assert resp.body == ""


# --- MylistStatus ---

def test_mylist_status_from_int_known():
    assert MylistStatus.from_int(0) == MylistStatus.UNKNOWN
    assert MylistStatus.from_int(1) == MylistStatus.HDD
    assert MylistStatus.from_int(2) == MylistStatus.CD
    assert MylistStatus.from_int(3) == MylistStatus.DELETED


def test_mylist_status_from_int_unknown_value():
    # Any unrecognised int should map to UNKNOWN
    assert MylistStatus.from_int(99) == MylistStatus.UNKNOWN


# --- MylistEntry ---

def test_mylist_entry_from_response_viewed():
    line = b"221 42|0|0|1234|0|0|1|1700000000|||\n"
    resp = parse_response(line)
    entry = MylistEntry.from_response(resp)
    assert entry.lid == 42
    assert entry.fid == 0
    assert entry.eid == 0
    assert entry.aid == 1234
    assert entry.gid == 0
    assert entry.state == MylistStatus.HDD
    assert entry.viewdate == 1700000000


def test_mylist_entry_from_response_not_viewed():
    line = b"221 7|0|0|5678|0|0|1|0|||\n"
    resp = parse_response(line)
    entry = MylistEntry.from_response(resp)
    assert entry.lid == 7
    assert entry.aid == 5678
    assert entry.viewdate == 0


def test_mylist_entry_from_response_deleted_state():
    line = b"221 99|0|0|1111|0|0|3|0|||\n"
    resp = parse_response(line)
    entry = MylistEntry.from_response(resp)
    assert entry.state == MylistStatus.DELETED


def test_mylist_entry_from_response_too_few_fields():
    resp = AnidbResponse(code=221, body="42|0|0")
    with pytest.raises(ValueError):
        MylistEntry.from_response(resp)


# --- AnimeInfo ---

def test_anime_info_from_response_romaji_title():
    line = b"243 1234|0|2023|TV Series|Cowboy Bebop|||26\n"
    resp = parse_response(line)
    info = AnimeInfo.from_response(resp)
    assert info.aid == 1234
    assert info.title == "Cowboy Bebop"
    assert info.total_episodes == 26


def test_anime_info_from_response_no_episodes():
    line = b"243 9999|0|2020|OVA|Some OVA|||\n"
    resp = parse_response(line)
    info = AnimeInfo.from_response(resp)
    assert info.aid == 9999
    assert info.title == "Some OVA"
    assert info.total_episodes is None


def test_anime_info_falls_back_to_aid_when_no_title():
    # romaji and english both empty
    resp = AnidbResponse(code=243, body="4242|0|2020|TV|||")
    info = AnimeInfo.from_response(resp)
    assert info.title == "AID:4242"


def test_anime_info_from_response_too_few_fields():
    resp = AnidbResponse(code=243, body="1234|0|2023")
    with pytest.raises(ValueError):
        AnimeInfo.from_response(resp)

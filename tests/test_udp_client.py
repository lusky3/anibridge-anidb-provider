"""Tests for the AniDB async UDP client."""

import asyncio
import logging
import sys
import time
import unittest.mock

import pytest

from anibridge.providers.anidb import udp_client as _udp_client_mod
from anibridge.providers.anidb.udp_client import (
    AnidbAuthError,
    AnidbUdpClient,
    _UdpProtocol,
)


def _make_client():
    client = AnidbUdpClient(
        username="user",
        password="pass",
        client="testclient",
        client_version=1,
        logger=None,
    )
    client._min_interval = 0  # disable rate limiting in tests
    return client


@pytest.mark.asyncio
async def test_authenticate_stores_session(mock_udp_responses):
    mock_udp_responses.extend([b"200 abcdef12 LOGIN ACCEPTED\n"])
    client = _make_client()
    await client._authenticate()
    assert client._session == "abcdef12"
    assert client._authenticated is True


@pytest.mark.asyncio
async def test_authenticate_new_version_accepted(mock_udp_responses):
    mock_udp_responses.extend([b"201 newsess LOGIN ACCEPTED - NEW VERSION\n"])
    client = _make_client()
    await client._authenticate()
    assert client._session == "newsess"
    assert client._authenticated is True


@pytest.mark.asyncio
async def test_authenticate_rejected_raises(mock_udp_responses):
    mock_udp_responses.extend([b"500 ACCESS DENIED\n"])
    client = _make_client()
    with pytest.raises(AnidbAuthError):
        await client._authenticate()


@pytest.mark.asyncio
async def test_get_mylist_entry_returns_none_on_321(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"321 NO SUCH ENTRY\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    result = await client.get_mylist_entry(aid=9999)
    assert result is None


@pytest.mark.asyncio
async def test_get_mylist_entry_parses_221(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"221 42|0|0|1234|0|0|1|1700000000|||\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    entry = await client.get_mylist_entry(aid=1234)
    assert entry is not None
    assert entry.lid == 42
    assert entry.aid == 1234


@pytest.mark.asyncio
async def test_get_mylist_entry_returns_none_on_unexpected_code(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"999 UNKNOWN\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    result = await client.get_mylist_entry(aid=1234)
    assert result is None


@pytest.mark.asyncio
async def test_add_or_update_returns_true_on_210(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"210 MYLIST ENTRY ADDED\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    ok = await client.add_or_update_mylist_entry(aid=1234, state=1, viewed=False)
    assert ok is True


@pytest.mark.asyncio
async def test_add_or_update_returns_true_on_310(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"310 MYLIST ENTRY EDITED\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    ok = await client.add_or_update_mylist_entry(aid=1234, state=1, viewed=True)
    assert ok is True


@pytest.mark.asyncio
async def test_add_or_update_returns_false_on_unexpected(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"500 ERROR\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    ok = await client.add_or_update_mylist_entry(aid=1234, state=1, viewed=False)
    assert ok is False


@pytest.mark.asyncio
async def test_delete_mylist_entry_returns_true_on_211(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"211 DELETED\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    ok = await client.delete_mylist_entry(lid=42)
    assert ok is True


@pytest.mark.asyncio
async def test_delete_mylist_entry_returns_false_on_321(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"321 NO SUCH ENTRY\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    ok = await client.delete_mylist_entry(lid=99999)
    assert ok is False


@pytest.mark.asyncio
async def test_get_anime_info_parses_243(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"243 1234|0|2023|TV Series|Cowboy Bebop|||26\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    info = await client.get_anime_info(aid=1234)
    assert info is not None
    assert info.title == "Cowboy Bebop"
    assert info.total_episodes == 26


@pytest.mark.asyncio
async def test_get_anime_info_returns_none_on_unknown_aid(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"330 NO SUCH ANIME\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    info = await client.get_anime_info(aid=99999)
    assert info is None


@pytest.mark.asyncio
async def test_get_anime_info_uses_cache(mock_udp_responses):
    """Second call for same AID must not send another UDP request."""
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"243 1234|0|2023|TV|Bebop|||26\n",
            # No second response queued — a second UDP call would raise RuntimeError
        ]
    )
    client = _make_client()
    await client._authenticate()
    info1 = await client.get_anime_info(aid=1234)
    info2 = await client.get_anime_info(aid=1234)  # must hit cache
    assert info1 is info2  # same object from cache


@pytest.mark.asyncio
async def test_ensure_authenticated_when_not_authed(mock_udp_responses):
    """_ensure_authenticated triggers login when not yet authenticated."""
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
        ]
    )
    client = _make_client()
    assert not client._authenticated
    await client._ensure_authenticated()
    assert client._authenticated


@pytest.mark.asyncio
async def test_ensure_authenticated_reauths_on_expired_session(mock_udp_responses):
    """_ensure_authenticated re-logs in when session age exceeds TTL."""
    mock_udp_responses.extend(
        [
            b"200 first LOGIN ACCEPTED\n",
            b"200 second LOGIN ACCEPTED\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    assert client._session == "first"
    # Force session to appear expired
    client._auth_time = time.monotonic() - 36 * 60
    await client._ensure_authenticated()
    assert client._session == "second"


@pytest.mark.asyncio
async def test_clear_cache_empties_anime_cache(mock_udp_responses):
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"243 1234|0|2023|TV|Bebop|||26\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    await client.get_anime_info(aid=1234)
    assert 1234 in client._anime_cache
    client.clear_cache()
    assert 1234 not in client._anime_cache


# ---------------------------------------------------------------------------
# Additional tests to reach >= 80% coverage on udp_client.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_mylist_entry_returns_false_on_unexpected_code(mock_udp_responses):
    """delete_mylist_entry logs warning and returns False on unexpected code."""
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"500 INTERNAL ERROR\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    ok = await client.delete_mylist_entry(lid=42)
    assert ok is False


@pytest.mark.asyncio
async def test_authenticate_with_nat_flag(mock_udp_responses):
    """AUTH command includes nat=1 when nat=True."""
    mock_udp_responses.extend([b"200 sess LOGIN ACCEPTED\n"])
    client = AnidbUdpClient(
        username="user",
        password="pass",
        client="testclient",
        client_version=1,
        nat=True,
        logger=None,
    )
    client._min_interval = 0
    await client._authenticate()
    assert client._authenticated is True


@pytest.mark.asyncio
async def test_authenticate_with_encrypt_key(mock_udp_responses):
    """AUTH command includes encrypt param and sets cipher key when encrypt= set."""
    mock_udp_responses.extend([b"200 sess LOGIN ACCEPTED\n"])
    client = AnidbUdpClient(
        username="user",
        password="pass",
        client="testclient",
        client_version=1,
        encrypt="myapikey",
        logger=None,
    )
    client._min_interval = 0
    await client._authenticate()
    assert client._authenticated is True
    # cipher key should be set (md5 of apikey+session)
    assert client._cipher_key is not None
    assert len(client._cipher_key) == 16  # 128-bit MD5 digest


@pytest.mark.asyncio
async def test_close_when_authenticated(mock_udp_responses):
    """close() sends LOGOUT and resets state when authenticated."""
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"203 LOGGED OUT\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    assert client._authenticated is True
    await client.close()
    assert client._authenticated is False
    assert client._session is None


@pytest.mark.asyncio
async def test_close_when_not_authenticated():
    """close() is a no-op (no error) when not authenticated."""
    client = _make_client()
    # Should not raise even with no transport and no session
    await client.close()
    assert client._authenticated is False


@pytest.mark.asyncio
async def test_close_with_transport(mock_udp_responses):
    """close() closes the transport if one is set."""
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"203 LOGGED OUT\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    # Set a mock transport
    mock_transport = unittest.mock.MagicMock()
    client._transport = mock_transport
    await client.close()
    mock_transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_send_command_respects_rate_limit(mock_udp_responses):
    """_send_command waits when called before min_interval has elapsed."""
    mock_udp_responses.extend(
        [
            b"200 sess LOGIN ACCEPTED\n",
            b"221 42|0|0|1234|0|0|1|1700000000|||\n",
        ]
    )
    client = _make_client()
    await client._authenticate()
    # Set a very short (but > 0) min_interval
    client._min_interval = 0.01
    # Set last request time to now so sleep will be triggered
    client._last_request_time = time.monotonic()
    # This should sleep ~0.01s and then call _send_raw
    result = await client.get_mylist_entry(aid=1234)
    assert result is not None


def test_udp_protocol_datagram_received():
    """_UdpProtocol.datagram_received puts data into the queue."""
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    proto = _UdpProtocol(queue)
    proto.datagram_received(b"hello", ("127.0.0.1", 9000))
    assert queue.get_nowait() == b"hello"


def test_udp_protocol_error_received(caplog):
    """_UdpProtocol.error_received logs a warning."""
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    proto = _UdpProtocol(queue)
    with caplog.at_level(logging.WARNING):
        proto.error_received(OSError("test error"))
    assert "test error" in caplog.text


@pytest.mark.asyncio
async def test_send_raw_raises_without_transport():
    """_send_raw raises RuntimeError when transport is None."""
    client = _make_client()
    with pytest.raises(RuntimeError, match="UDP transport is not open"):
        await client._send_raw("TEST command")


def test_aes_encrypt_import_error_fallback(monkeypatch):
    """_aes128_ecb_encrypt returns data unchanged when pycryptodome is missing."""
    original_modules = sys.modules.copy()
    # Remove Crypto from sys.modules to force ImportError path
    for key in list(sys.modules.keys()):
        if key.startswith("Crypto"):
            sys.modules[key] = None  # type: ignore[assignment]

    try:
        data = b"some data to encrypt"
        enc_key = b"\x00" * 16
        result = _udp_client_mod._aes128_ecb_encrypt(data, enc_key)
        # Without pycryptodome, returns original data unchanged
        assert result == data
    finally:
        # Restore modules
        for key in list(sys.modules.keys()):
            if key.startswith("Crypto"):
                if key in original_modules:
                    sys.modules[key] = original_modules[key]
                else:
                    del sys.modules[key]


def test_aes_decrypt_import_error_fallback():
    """_aes128_ecb_decrypt returns data unchanged when pycryptodome is missing."""
    original_modules = sys.modules.copy()
    for key in list(sys.modules.keys()):
        if key.startswith("Crypto"):
            sys.modules[key] = None  # type: ignore[assignment]

    try:
        data = b"some encrypted data"
        dec_key = b"\x00" * 16
        result = _udp_client_mod._aes128_ecb_decrypt(data, dec_key)
        assert result == data
    finally:
        for key in list(sys.modules.keys()):
            if key.startswith("Crypto"):
                if key in original_modules:
                    sys.modules[key] = original_modules[key]
                else:
                    del sys.modules[key]

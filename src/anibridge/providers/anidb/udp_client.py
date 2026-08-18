"""Async AniDB UDP API client."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time

from Crypto.Cipher import AES

from anibridge.providers.anidb.models import (
    AnidbResponse,
    AnimeInfo,
    MylistEntry,
    parse_response,
)

_ANIDB_HOST = "api.anidb.net"
_ANIDB_PORT = 9000
_PROTO_VER = 3
_SESSION_TTL = 35 * 60  # seconds


class AnidbAuthError(Exception):
    """Raised when AniDB authentication is rejected."""


class _UdpProtocol(asyncio.DatagramProtocol):
    """asyncio DatagramProtocol that routes received packets to a queue."""

    def __init__(self, recv_queue: asyncio.Queue[bytes]) -> None:
        """Initialise with a queue to receive incoming packets."""
        self._queue = recv_queue

    def datagram_received(self, data: bytes, addr: object) -> None:
        """Route a received datagram to the receive queue."""
        self._queue.put_nowait(data)

    def error_received(self, exc: Exception) -> None:
        """Log transport-level errors."""
        logging.getLogger(__name__).warning("UDP transport error: %s", exc)


class AnidbUdpClient:
    """Async client for the AniDB UDP API.

    Handles authentication, optional AES-128-ECB encryption,
    rate-limiting (min 2 s between requests), and session renewal.

    Args:
        username: AniDB account username.
        password: AniDB account password.
        client: Registered AniDB client name.
        client_version: Registered AniDB client version.
        encrypt: AniDB API key for UDP encryption (optional).
        nat: Enable NAT mode in AUTH command.
        rate_limit: Max requests per second (default 0.5).
        logger: Logger instance (uses module logger if None).
    """

    def __init__(
        self,
        *,
        username: str,
        password: str,
        client: str,
        client_version: int,
        encrypt: str | None = None,
        nat: bool = False,
        rate_limit: float = 0.5,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialise the UDP client."""
        self._username = username
        self._password = password
        self._client = client
        self._client_version = client_version
        self._encrypt_key = encrypt
        self._nat = nat
        self._min_interval = max(2.0, 1.0 / rate_limit) if rate_limit > 0 else 2.0
        self.log = logger or logging.getLogger(__name__)

        self._session: str | None = None
        self._authenticated = False
        self._last_request_time: float = 0.0
        self._auth_time: float = 0.0
        self._cipher_key: bytes | None = None

        self._transport: asyncio.DatagramTransport | None = None
        self._recv_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._anime_cache: dict[int, AnimeInfo] = {}
        self._auth_lock: asyncio.Lock = asyncio.Lock()
        self._send_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def open(self) -> None:
        """Open the UDP socket and authenticate. Call before any other method."""
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self._recv_queue),
            remote_addr=(_ANIDB_HOST, _ANIDB_PORT),
        )
        await self._authenticate()

    async def close(self) -> None:
        """Log out and close the UDP socket."""
        if self._authenticated and self._session:
            with contextlib.suppress(Exception):
                await self._send_command(f"LOGOUT s={self._session}")
        self._session = None
        self._authenticated = False
        if self._transport:
            self._transport.close()
            self._transport = None

    async def get_mylist_entry(self, *, aid: int) -> MylistEntry | None:
        """Fetch the MyList entry for the given AID (generic file).

        Args:
            aid: AniDB anime ID.

        Returns:
            MylistEntry if found, None if not in list (code 321).
        """
        await self._ensure_authenticated()
        resp = await self._send_command(f"MYLIST s={self._session}&aid={aid}&generic=1")
        if resp.code == 321:
            return None
        if resp.code == 221:
            return MylistEntry.from_response(resp)
        self.log.warning("Unexpected MYLIST code %d: %s", resp.code, resp.body)
        return None

    async def add_or_update_mylist_entry(
        self,
        *,
        aid: int,
        state: int,
        viewed: bool,
        viewdate: int = 0,
    ) -> bool:
        """Add or update the MyList entry for the given AID.

        Args:
            aid: AniDB anime ID.
            state: AniDB file state integer (0=unknown,1=hdd,2=cd,3=deleted).
            viewed: Whether the anime has been watched.
            viewdate: Unix timestamp of last watch (0 for unknown).

        Returns:
            True if added (210) or edited (310), False otherwise.
        """
        await self._ensure_authenticated()
        view_val = 1 if viewed else 0
        cmd = (
            f"MYLISTADD s={self._session}"
            f"&aid={aid}&generic=1&state={state}"
            f"&viewed={view_val}&viewdate={viewdate}"
        )
        resp = await self._send_command(cmd)
        if resp.code in {210, 310}:
            return True
        self.log.warning("Unexpected MYLISTADD code %d: %s", resp.code, resp.body)
        return False

    async def delete_mylist_entry(self, *, lid: int) -> bool:
        """Delete a MyList entry by its list ID.

        Args:
            lid: AniDB MyList entry ID.

        Returns:
            True if deleted (211), False if not found (321).
        """
        await self._ensure_authenticated()
        resp = await self._send_command(f"MYLISTDEL s={self._session}&lid={lid}")
        if resp.code == 211:
            return True
        if resp.code == 321:
            return False
        self.log.warning("Unexpected MYLISTDEL code %d: %s", resp.code, resp.body)
        return False

    async def get_anime_info(self, *, aid: int) -> AnimeInfo | None:
        """Fetch minimal anime info (title, episode count) for an AID.

        Results are cached in-process for the client lifetime.

        Args:
            aid: AniDB anime ID.

        Returns:
            AnimeInfo if found, None otherwise.
        """
        if aid in self._anime_cache:
            return self._anime_cache[aid]
        await self._ensure_authenticated()
        resp = await self._send_command(
            f"ANIME s={self._session}&aid={aid}&acode=0x0982"
        )
        if resp.code == 243:
            info = AnimeInfo.from_response(resp)
            self._anime_cache[aid] = info
            return info
        return None

    def clear_cache(self) -> None:
        """Clear the in-process anime info cache."""
        self._anime_cache.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _authenticate(self) -> None:
        """Negotiate encryption (if configured), then AUTH and store the session.

        Raises:
            AnidbAuthError: If ENCRYPT or AUTH is rejected by AniDB.
        """
        self._cipher_key = None
        if self._encrypt_key:
            await self._negotiate_encryption()

        cmd = (
            f"AUTH user={self._username}&pass={self._password}"
            f"&protover={_PROTO_VER}&client={self._client}"
            f"&clientver={self._client_version}&enc=UTF8"
        )
        if self._nat:
            cmd += "&nat=1"
        raw = await self._send_rate_limited(cmd)
        parsed = parse_response(raw)
        if parsed.code not in {200, 201}:
            raise AnidbAuthError(
                f"AniDB auth failed (code {parsed.code}): {parsed.body}"
            )
        self._session = parsed.body.split()[0]
        self._authenticated = True
        self._auth_time = time.monotonic()
        self.log.debug("AniDB session established: %s", self._session)

    async def _negotiate_encryption(self) -> None:
        """Send ENCRYPT and derive the AES-128-ECB session key from its salt.

        No-op if no encryption API key was configured.

        Raises:
            AnidbAuthError: If AniDB rejects the ENCRYPT request (non-209 code).
        """
        encrypt_key = self._encrypt_key
        if encrypt_key is None:
            return
        cmd = f"ENCRYPT user={self._username}&type=1"
        raw = await self._send_rate_limited(cmd)
        parsed = parse_response(raw)
        if parsed.code != 209:
            raise AnidbAuthError(
                f"AniDB ENCRYPT failed (code {parsed.code}): {parsed.body}"
            )
        salt = parsed.body.split()[0]
        self._cipher_key = hashlib.md5(encrypt_key.encode() + salt.encode()).digest()
        self.log.debug("AniDB UDP encryption negotiated")

    async def _ensure_authenticated(self) -> None:
        """Re-authenticate if the session has expired or was never started."""
        async with self._auth_lock:
            if not self._authenticated:
                await self._authenticate()
                return
            if time.monotonic() - self._auth_time > _SESSION_TTL:
                self.log.debug("AniDB session expired, re-authenticating")
                self._authenticated = False
                self._session = None
                await self._authenticate()

    async def _send_command(self, command: str) -> AnidbResponse:
        """Rate-limit, send a command, and return the parsed response.

        Args:
            command: Full AniDB UDP command string.

        Returns:
            Parsed AnidbResponse.
        """
        raw = await self._send_rate_limited(command)
        return parse_response(raw)

    async def _send_rate_limited(self, command: str) -> bytes:
        """Serialize and rate-limit sends so concurrent callers can't flood.

        AniDB enforces a hard minimum interval between UDP requests; without
        serializing here, two commands issued concurrently (e.g. via
        ``asyncio.gather``) would both observe the same last-request time and
        send back-to-back, violating the limit.

        Args:
            command: Full AniDB UDP command string.

        Returns:
            Raw (decrypted, if applicable) response bytes.
        """
        async with self._send_lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request_time)
            if wait > 0:
                await asyncio.sleep(wait)
            raw = await self._send_raw(command)
            self._last_request_time = time.monotonic()
            return raw

    async def _send_raw(self, command: str) -> bytes:
        """Send a raw command string over UDP and wait for a response.

        If encryption is active, applies AES-128-ECB before sending
        and decrypts the response.

        Args:
            command: Command string to send (UTF-8).

        Returns:
            Raw response bytes.

        Raises:
            RuntimeError: If the transport is not open.
            asyncio.TimeoutError: If no response arrives within 30 s.
        """
        if self._transport is None:
            raise RuntimeError("UDP transport is not open; call open() first")
        data = command.encode("utf-8")
        if self._cipher_key:
            data = _aes128_ecb_encrypt(data, self._cipher_key)
        self._transport.sendto(data)
        try:
            raw = await asyncio.wait_for(self._recv_queue.get(), timeout=30.0)
        except TimeoutError as exc:
            raise TimeoutError(
                f"No response from AniDB within 30 s for: {command[:40]!r}"
            ) from exc
        if self._cipher_key:
            raw = _aes128_ecb_decrypt(raw, self._cipher_key)
        return raw


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    """Pad data to a block boundary using PKCS#7."""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def _pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
    """Strip PKCS#7 padding, returning the input unchanged if it looks invalid."""
    if not data:
        return data
    pad_len = data[-1]
    if (
        pad_len < 1
        or pad_len > block_size
        or data[-pad_len:] != bytes([pad_len]) * pad_len
    ):
        return data
    return data[:-pad_len]


def _aes128_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """Encrypt data with AES-128-ECB, PKCS#7-padded to a 16-byte boundary."""
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(_pkcs7_pad(data))


def _aes128_ecb_decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt AES-128-ECB data and strip PKCS#7 padding."""
    cipher = AES.new(key, AES.MODE_ECB)
    return _pkcs7_unpad(cipher.decrypt(data))

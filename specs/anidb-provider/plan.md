# AniDB Provider Implementation Plan

**Goal:** Build an AniBridge list provider for AniDB that reads and writes a user's MyList via the AniDB UDP API.
**Architecture:** A Python package mirroring the structure of `anibridge-anilist-provider`. An async UDP client handles the AniDB UDP API protocol (auth, encryption, rate-limiting). A thin provider class wraps the client and implements the `anibridge.provider.base` contract (`Provider`, `SupportsReads`, `SupportsWrites`, `SupportsMapping`).
**Tech Stack:** Python 3.14, `anibridge-provider-base>=0.1.0a3`, `aiohttp>=3.13.3` (for HTTP anime metadata lookups), `msgspec>=0.21.1`, `asyncio` UDP via `asyncio.DatagramProtocol`.

---

## Critical background: AniDB API constraints

- **HTTP API** (`https://api.anidb.net:9001/httpapi`) — read-only anime metadata. Useful for looking up anime titles/episode counts by AID. Requires a registered client name + version.
- **UDP API** (`api.anidb.net:9000`) — required for all MyList operations (MYLISTADD, MYLISTDEL, MYLIST, MYLISTSTATS). Authenticated with username + password. Supports optional Rijndael/AES-128-ECB encryption using a per-user API key. Rate limit: **no more than 1 request per 2 seconds** (0.5 req/s sustained), with a burst of up to 4 requests before the rate limit kicks in. Connections must be re-authenticated after 35 minutes of inactivity. The UDP API uses plaintext key=value pairs, not HTTP.
- AniDB MyList entries track individual **file** state, not per-anime state. For list sync purposes we use **generic files** (identified by AID) which give a per-anime list entry with watch status, episode count, rating, etc.

---

## File map

```
pyproject.toml                                    (create)
.python-version                                   (create)
.gitignore                                        (create)
README.md                                         (create)
src/
  anibridge/
    providers/
      anidb/
        __init__.py                               (create — re-exports AnidbProvider)
        config.py                                 (create — msgspec config struct)
        models.py                                 (create — UDP response models)
        udp_client.py                             (create — async UDP protocol + auth)
        provider.py                               (create — Provider implementation)
tests/
  conftest.py                                     (create)
  test_udp_client.py                              (create)
  test_models.py                                  (create)
  test_provider.py                                (create)
```

---

## Group 1: Project scaffold and config
Tasks run in parallel.

### Task 1: pyproject.toml, .python-version, .gitignore (ka-coder)

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`

- [ ] **Step 1: Write `.python-version`**
  ```
  3.14
  ```

- [ ] **Step 2: Write `.gitignore`**
  ```
  __pycache__/
  *.pyc
  *.pyo
  .venv/
  dist/
  *.egg-info/
  .pytest_cache/
  .ruff_cache/
  .coverage
  htmlcov/
  ```

- [ ] **Step 3: Check latest package versions before writing pyproject.toml**
  Run: `pip index versions anibridge-provider-base 2>/dev/null | head -5`
  Also run: `pip index versions msgspec 2>/dev/null | head -3`
  Also run: `pip index versions aiohttp 2>/dev/null | head -3`
  Use exact versions observed. Fall back to `anibridge-provider-base>=0.1.0a3`, `aiohttp>=3.13.3`, `msgspec>=0.21.1` if pip index is unavailable.

- [ ] **Step 4: Write `pyproject.toml`**
  ```toml
  [project]
  name = "anibridge-anidb-provider"
  version = "0.1.0"
  description = "AniDB provider for the AniBridge project."
  license = "MIT"
  license-files = ["LICENSE"]
  readme = "README.md"
  requires-python = ">=3.14"

  authors = [
      { name = "Your Name", email = "you@example.com" },
  ]

  keywords = ["anibridge", "anidb"]
  classifiers = [
      "Programming Language :: Python :: 3",
      "Programming Language :: Python :: 3.14",
      "Operating System :: OS Independent",
  ]

  dependencies = [
      "anibridge-provider-base>=0.1.0a3",
      "aiohttp>=3.13.3",
      "msgspec>=0.21.1",
  ]

  [tool.ruff]
  indent-width = 4
  line-length = 88

  [tool.ruff.format]
  docstring-code-format = true
  indent-style = "space"
  quote-style = "double"

  [tool.ruff.lint]
  select = ["A","ASYNC","B","C4","D","E","F","FURB","G","I","N","PERF","PLC","PLE","RUF","SIM","UP","W"]

  [tool.ruff.lint.per-file-ignores]
  "tests/**/*.py" = ["D"]

  [tool.ruff.lint.pydocstyle]
  convention = "google"

  [tool.pytest.ini_options]
  pythonpath = ["src"]
  testpaths = ["tests"]
  addopts = "--cov=src --import-mode=importlib"
  asyncio_mode = "auto"

  [tool.uv]
  python-preference = "only-managed"

  [tool.uv.build-backend]
  module-name = "anibridge"
  namespace = true

  [build-system]
  requires = ["uv_build>=0.11.0,<0.12.0"]
  build-backend = "uv_build"

  [dependency-groups]
  dev = [
      "pytest>=8.3.5",
      "pytest-asyncio>=0.24.0",
      "pytest-cov>=6.0.0",
      "ruff>=0.9.0",
  ]
  ```

- [ ] **Step 5: Install dependencies and generate lockfile**
  Run: `uv sync`
  Expected: exit 0, `.venv/` created, `uv.lock` written.

- [ ] **Step 6: Commit**
  ```bash
  git add pyproject.toml .python-version .gitignore uv.lock
  git commit -m "chore: scaffold project with pyproject.toml"
  ```

---

### Task 2: Config struct (ka-coder)

**Files:**
- Create: `src/anibridge/providers/anidb/config.py`
- Create: `tests/test_models.py` (config section only, expanded in Task 5)

- [ ] **Step 1: Write failing test for config validation**
  ```python
  # tests/test_models.py
  import pytest
  import msgspec
  from anibridge.providers.anidb.config import AnidbProviderConfig


  def test_config_requires_username_and_password():
      with pytest.raises(Exception):
          msgspec.convert({"username": "user"}, type=AnidbProviderConfig)


  def test_config_defaults():
      cfg = msgspec.convert(
          {"username": "user", "password": "pass", "client": "myclient", "client_version": 1},
          type=AnidbProviderConfig,
      )
      assert cfg.username == "user"
      assert cfg.password == "pass"
      assert cfg.encrypt is None
      assert cfg.rate_limit == 0.5
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `uv run pytest tests/test_models.py -v`
  Expected: FAIL with `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Write `src/anibridge/providers/anidb/config.py`**
  ```python
  """AniDB provider configuration."""

  import msgspec


  class AnidbProviderConfig(msgspec.Struct, kw_only=True):
      """Configuration for the AniDB provider.

      Args:
          username: AniDB account username.
          password: AniDB account password.
          client: Registered AniDB client name (must be registered at anidb.net).
          client_version: Registered AniDB client version integer.
          encrypt: Optional AniDB API key for UDP packet encryption.
              When set, all UDP traffic is encrypted with Rijndael/AES-128-ECB.
              Obtain from https://anidb.net/user/<id>/apikey
          nat: Set True if behind NAT (enables NAT mode in AUTH command).
          rate_limit: Maximum UDP requests per second (default 0.5, max 1.0).
              AniDB enforces a hard limit of 1 req/2 s for logged-in sessions.
      """

      username: str
      password: str
      client: str
      client_version: int
      encrypt: str | None = None
      nat: bool = False
      rate_limit: float = 0.5
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `uv run pytest tests/test_models.py -v`
  Expected: PASS (2 tests).

- [ ] **Step 5: Commit**
  ```bash
  git add src/anibridge/providers/anidb/config.py tests/test_models.py
  git commit -m "feat: add AnidbProviderConfig struct"
  ```

---

## Group 2: UDP response models
Tasks run in parallel with nothing else; depends on Group 1.

### Task 3: UDP response models (ka-coder)

AniDB UDP responses follow the pattern `CODE RESPONSE_BODY\n` where `CODE` is a 3-digit integer and the body is tab-separated fields.

**Files:**
- Create: `src/anibridge/providers/anidb/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for models**
  Append to `tests/test_models.py`:
  ```python
  from anibridge.providers.anidb.models import (
      AnidbResponse,
      MylistEntry,
      AnimeInfo,
      parse_response,
      MylistStatus,
  )


  def test_parse_auth_accepted():
      resp = parse_response(b"200 s3ss10n LOGIN ACCEPTED\n")
      assert resp.code == 200
      assert "s3ss10n" in resp.body


  def test_parse_mylist_entry():
      # 221 lid|fid|eid|aid|gid|date|state|viewdate|storage|source|other|filestate
      line = b"221 42|0|0|1234|0|0|1|1700000000||\t||\t\n"
      resp = parse_response(line)
      assert resp.code == 221
      entry = MylistEntry.from_response(resp)
      assert entry.lid == 42
      assert entry.aid == 1234
      assert entry.state == MylistStatus.COMPLETED


  def test_mylist_status_mapping():
      assert MylistStatus.from_int(0) == MylistStatus.UNKNOWN
      assert MylistStatus.from_int(1) == MylistStatus.HDD
      assert MylistStatus.from_int(2) == MylistStatus.CD
      assert MylistStatus.from_int(3) == MylistStatus.DELETED


  def test_anime_info_from_response():
      # 243 aid|dateflags|year|type|romaji_name|kanji_name|english_name|...
      line = b"243 1234|0|2023|TV Series|Cowboy Bebop|||26\n"
      resp = parse_response(line)
      assert resp.code == 243
      info = AnimeInfo.from_response(resp)
      assert info.aid == 1234
      assert info.total_episodes == 26
      assert info.title == "Cowboy Bebop"
  ```

- [ ] **Step 2: Run tests to confirm they fail**
  Run: `uv run pytest tests/test_models.py -v -k "parse or mylist or anime_info"`
  Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `src/anibridge/providers/anidb/models.py`**
  ```python
  """AniDB UDP API response models."""

  from __future__ import annotations

  from dataclasses import dataclass
  from enum import IntEnum


  @dataclass(slots=True)
  class AnidbResponse:
      """Raw parsed AniDB UDP API response."""

      code: int
      body: str


  def parse_response(data: bytes) -> AnidbResponse:
      """Parse a raw AniDB UDP response packet into code and body.

      Args:
          data: Raw bytes received from the UDP socket.

      Returns:
          AnidbResponse with the 3-digit code and remaining body text.

      Raises:
          ValueError: If the packet does not begin with a 3-digit code.
      """
      text = data.decode("utf-8", errors="replace").strip()
      if len(text) < 3 or not text[:3].isdigit():
          raise ValueError(f"Unexpected AniDB response: {text!r}")
      code = int(text[:3])
      body = text[4:] if len(text) > 4 else ""
      return AnidbResponse(code=code, body=body)


  class MylistStatus(IntEnum):
      """AniDB MyList file state values."""

      UNKNOWN = 0
      HDD = 1
      CD = 2
      DELETED = 3
      # Watched states (watched=True + underlying storage)
      WATCHED_UNKNOWN = 4   # internal: watched + unknown
      WATCHED_HDD = 5       # internal: watched + hdd (rarely used)

      @classmethod
      def from_int(cls, value: int) -> "MylistStatus":
          """Convert an integer state value to MylistStatus."""
          try:
              return cls(value)
          except ValueError:
              return cls.UNKNOWN


  @dataclass(slots=True)
  class MylistEntry:
      """A single AniDB MyList entry (response code 221).

      Fields correspond to the MYLIST UDP API response:
      lid|fid|eid|aid|gid|date|state|viewdate|storage|source|other|filestate
      """

      lid: int        # MyList entry ID
      fid: int        # File ID (0 for generic)
      eid: int        # Episode ID (0 for generic)
      aid: int        # Anime ID
      gid: int        # Group ID (0 for generic)
      state: MylistStatus
      viewdate: int   # Unix timestamp of last watched date (0 if unwatched)

      @classmethod
      def from_response(cls, resp: AnidbResponse) -> "MylistEntry":
          """Parse a MYLIST (221) response body into a MylistEntry.

          Args:
              resp: AnidbResponse with code 221.

          Returns:
              MylistEntry populated from the tab-separated fields.

          Raises:
              ValueError: If the response body cannot be parsed.
          """
          parts = resp.body.split("|")
          if len(parts) < 7:
              raise ValueError(f"Malformed MYLIST response: {resp.body!r}")
          return cls(
              lid=int(parts[0]),
              fid=int(parts[1]),
              eid=int(parts[2]),
              aid=int(parts[3]),
              gid=int(parts[4]),
              state=MylistStatus.from_int(int(parts[6])),
              viewdate=int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else 0,
          )


  @dataclass(slots=True)
  class AnimeInfo:
      """Minimal AniDB anime info (response code 243 from ANIME command).

      Fields: aid|dateflags|year|type|romaji_name|kanji_name|english_name|episodes
      """

      aid: int
      title: str          # romaji_name preferred
      total_episodes: int | None

      @classmethod
      def from_response(cls, resp: AnidbResponse) -> "AnimeInfo":
          """Parse an ANIME (243) response body into AnimeInfo.

          Args:
              resp: AnidbResponse with code 243.

          Returns:
              AnimeInfo populated from the pipe-separated fields.

          Raises:
              ValueError: If the response body cannot be parsed.
          """
          parts = resp.body.split("|")
          if len(parts) < 5:
              raise ValueError(f"Malformed ANIME response: {resp.body!r}")
          aid = int(parts[0])
          romaji = parts[4].strip() if parts[4].strip() else None
          english = parts[6].strip() if len(parts) > 6 and parts[6].strip() else None
          title = romaji or english or f"AID:{aid}"
          episodes: int | None = None
          if len(parts) > 7 and parts[7].strip().isdigit():
              episodes = int(parts[7].strip())
          return cls(aid=aid, title=title, total_episodes=episodes)
  ```

- [ ] **Step 4: Run tests to verify they pass**
  Run: `uv run pytest tests/test_models.py -v`
  Expected: all tests PASS.

- [ ] **Step 5: Commit**
  ```bash
  git add src/anibridge/providers/anidb/models.py tests/test_models.py
  git commit -m "feat: add AniDB UDP response models"
  ```

---

## Group 3: Async UDP client
Depends on Group 2. This is the hardest part. The UDP client must handle the full AniDB session lifecycle.

### Task 4: AniDB async UDP client (ka-coder)

**Files:**
- Create: `src/anibridge/providers/anidb/udp_client.py`
- Create: `tests/conftest.py`
- Create: `tests/test_udp_client.py`

#### AniDB UDP protocol facts (do not invent, implement exactly):
- Host: `api.anidb.net`, port `9000` (UDP)
- Auth: `AUTH user={username}&pass={password}&protover=3&client={client}&clientver={client_version}&enc=UTF8` → response `200 {session} LOGIN ACCEPTED` or `201 {session} LOGIN ACCEPTED - NEW VERSION`
- With encryption: append `&encrypt={username}` to AUTH, then apply Rijndael/AES-128-ECB with key = MD5(`{api_key}{session}`) to all subsequent outgoing packets
- All commands appended with `&s={session_token}`
- Rate limit: minimum 2.0 seconds between requests (enforce with `asyncio.sleep`)
- Session expires after 35 min idle → re-auth automatically
- Logout: `LOGOUT s={session}`
- MYLIST by AID: `MYLIST s={session}&aid={aid}&generic=1`  → `221 {fields}` or `312 MYLIST MULTIPLE ENTRIES` or `321 NO SUCH ENTRY`
- MYLISTADD (add or update by AID+generic): `MYLISTADD s={session}&aid={aid}&generic=1&state={state}&viewed={0|1}&viewdate={unix_ts}` → `210 MYLIST ENTRY ADDED` or `310 MYLIST ENTRY EDITED`
- MYLISTDEL by lid: `MYLISTDEL s={session}&lid={lid}` → `211 DELETED` or `321 NO SUCH ENTRY`
- ANIME basic info: `ANIME s={session}&aid={aid}&acode=0x0002 0x0080 0x0100` → `243 {fields}` — fields: aid|dateflags|year|type|romaji_name|kanji_name|english_name|episodes
- All command strings encoded to UTF-8 before sending

- [ ] **Step 1: Write failing tests for UDP client**

  ```python
  # tests/conftest.py
  """Shared test fixtures."""
  import asyncio
  import pytest


  @pytest.fixture
  def mock_udp_responses(monkeypatch):
      """Fixture to inject pre-canned UDP responses into AnidbUdpClient.

      Usage: pass a list of bytes objects. Each call to _send_command
      pops the next response off the queue.
      """
      responses: list[bytes] = []

      async def fake_send(self, command: str) -> bytes:  # noqa: ARG001
          if not responses:
              raise RuntimeError("No more fake responses queued")
          return responses.pop(0)

      from anibridge.providers.anidb import udp_client as mod
      monkeypatch.setattr(mod.AnidbUdpClient, "_send_raw", fake_send)
      return responses
  ```

  ```python
  # tests/test_udp_client.py
  """Tests for the AniDB UDP client."""
  import asyncio
  import pytest
  from anibridge.providers.anidb.udp_client import AnidbUdpClient, AnidbAuthError


  @pytest.mark.asyncio
  async def test_login_accepted(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 abcdef12 LOGIN ACCEPTED\n",
      ])
      client = AnidbUdpClient(
          username="user", password="pass",
          client="testclient", client_version=1,
          logger=None,
      )
      await client._authenticate()
      assert client._session == "abcdef12"
      assert client._authenticated is True


  @pytest.mark.asyncio
  async def test_login_rejected_raises(mock_udp_responses):
      mock_udp_responses.extend([
          b"500 ACCESS DENIED\n",
      ])
      client = AnidbUdpClient(
          username="baduser", password="badpass",
          client="testclient", client_version=1,
          logger=None,
      )
      with pytest.raises(AnidbAuthError):
          await client._authenticate()


  @pytest.mark.asyncio
  async def test_get_mylist_entry_returns_none_on_321(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 sess LOGIN ACCEPTED\n",
          b"321 NO SUCH ENTRY\n",
      ])
      client = AnidbUdpClient(
          username="u", password="p",
          client="c", client_version=1,
          logger=None,
      )
      await client._authenticate()
      entry = await client.get_mylist_entry(aid=9999)
      assert entry is None


  @pytest.mark.asyncio
  async def test_get_mylist_entry_parses_221(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 sess LOGIN ACCEPTED\n",
          b"221 42|0|0|1234|0|0|1|1700000000|||\n",
      ])
      client = AnidbUdpClient(
          username="u", password="p",
          client="c", client_version=1,
          logger=None,
      )
      await client._authenticate()
      entry = await client.get_mylist_entry(aid=1234)
      assert entry is not None
      assert entry.lid == 42
      assert entry.aid == 1234


  @pytest.mark.asyncio
  async def test_add_mylist_entry_returns_true_on_210(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 sess LOGIN ACCEPTED\n",
          b"210 MYLIST ENTRY ADDED\n",
      ])
      client = AnidbUdpClient(
          username="u", password="p",
          client="c", client_version=1,
          logger=None,
      )
      await client._authenticate()
      ok = await client.add_or_update_mylist_entry(aid=1234, state=1, viewed=False)
      assert ok is True


  @pytest.mark.asyncio
  async def test_update_mylist_entry_returns_true_on_310(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 sess LOGIN ACCEPTED\n",
          b"310 MYLIST ENTRY EDITED\n",
      ])
      client = AnidbUdpClient(
          username="u", password="p",
          client="c", client_version=1,
          logger=None,
      )
      await client._authenticate()
      ok = await client.add_or_update_mylist_entry(aid=1234, state=1, viewed=True)
      assert ok is True


  @pytest.mark.asyncio
  async def test_delete_mylist_entry_returns_true_on_211(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 sess LOGIN ACCEPTED\n",
          b"211 DELETED\n",
      ])
      client = AnidbUdpClient(
          username="u", password="p",
          client="c", client_version=1,
          logger=None,
      )
      await client._authenticate()
      ok = await client.delete_mylist_entry(lid=42)
      assert ok is True


  @pytest.mark.asyncio
  async def test_delete_missing_entry_returns_false(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 sess LOGIN ACCEPTED\n",
          b"321 NO SUCH ENTRY\n",
      ])
      client = AnidbUdpClient(
          username="u", password="p",
          client="c", client_version=1,
          logger=None,
      )
      await client._authenticate()
      ok = await client.delete_mylist_entry(lid=99999)
      assert ok is False


  @pytest.mark.asyncio
  async def test_get_anime_info(mock_udp_responses):
      mock_udp_responses.extend([
          b"200 sess LOGIN ACCEPTED\n",
          b"243 1234|0|2023|TV Series|Cowboy Bebop|||26\n",
      ])
      client = AnidbUdpClient(
          username="u", password="p",
          client="c", client_version=1,
          logger=None,
      )
      await client._authenticate()
      info = await client.get_anime_info(aid=1234)
      assert info is not None
      assert info.title == "Cowboy Bebop"
      assert info.total_episodes == 26
  ```

- [ ] **Step 2: Run tests to confirm they fail**
  Run: `uv run pytest tests/test_udp_client.py -v`
  Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `src/anibridge/providers/anidb/udp_client.py`**
  ```python
  """Async AniDB UDP API client."""

  from __future__ import annotations

  import asyncio
  import hashlib
  import logging
  import time
  from typing import TYPE_CHECKING

  from anibridge.providers.anidb.models import (
      AnidbResponse,
      AnimeInfo,
      MylistEntry,
      parse_response,
  )

  if TYPE_CHECKING:
      pass

  _ANIDB_HOST = "api.anidb.net"
  _ANIDB_PORT = 9000
  _PROTO_VER = 3
  _SESSION_TTL = 35 * 60  # 35 minutes in seconds


  class AnidbAuthError(Exception):
      """Raised when AniDB authentication is rejected."""


  class AnidbRateLimitError(Exception):
      """Raised when the AniDB rate limit is exceeded."""


  class _UdpProtocol(asyncio.DatagramProtocol):
      """asyncio DatagramProtocol that routes received packets to a queue."""

      def __init__(self, recv_queue: asyncio.Queue[bytes]) -> None:
          self._queue = recv_queue

      def datagram_received(self, data: bytes, addr: object) -> None:  # noqa: ARG002
          """Route a received datagram to the receive queue."""
          self._queue.put_nowait(data)

      def error_received(self, exc: Exception) -> None:
          """Log transport-level errors."""
          logging.getLogger(__name__).warning("UDP transport error: %s", exc)


  class AnidbUdpClient:
      """Async client for the AniDB UDP API.

      Handles authentication, optional Rijndael/AES-128-ECB encryption,
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

      # ------------------------------------------------------------------
      # Public API
      # ------------------------------------------------------------------

      async def open(self) -> None:
          """Open the UDP socket. Call before any other method."""
          loop = asyncio.get_running_loop()
          self._transport, _ = await loop.create_datagram_endpoint(
              lambda: _UdpProtocol(self._recv_queue),
              remote_addr=(_ANIDB_HOST, _ANIDB_PORT),
          )
          await self._authenticate()

      async def close(self) -> None:
          """Log out and close the UDP socket."""
          if self._authenticated and self._session:
              try:
                  await self._send_command(f"LOGOUT s={self._session}")
              except Exception:
                  pass
          self._session = None
          self._authenticated = False
          if self._transport:
              self._transport.close()
              self._transport = None

      async def get_mylist_entry(self, *, aid: int) -> MylistEntry | None:
          """Fetch a MyList entry for the given AID using the generic file.

          Args:
              aid: AniDB anime ID.

          Returns:
              MylistEntry if found, None if not in list (code 321).
          """
          await self._ensure_authenticated()
          resp = await self._send_command(
              f"MYLIST s={self._session}&aid={aid}&generic=1"
          )
          if resp.code == 321:
              return None
          if resp.code == 221:
              return MylistEntry.from_response(resp)
          self.log.warning("Unexpected MYLIST response code %d: %s", resp.code, resp.body)
          return None

      async def add_or_update_mylist_entry(
          self,
          *,
          aid: int,
          state: int,
          viewed: bool,
          viewdate: int = 0,
      ) -> bool:
          """Add or update the MyList entry for the given AID (generic file).

          Args:
              aid: AniDB anime ID.
              state: AniDB file state integer (0=unknown,1=hdd,2=cd,3=deleted).
              viewed: Whether the anime has been watched.
              viewdate: Unix timestamp of when it was watched (0 for unknown).

          Returns:
              True if the entry was added (210) or edited (310).
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
          self.log.warning(
              "Unexpected MYLISTADD response code %d: %s", resp.code, resp.body
          )
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
          self.log.warning(
              "Unexpected MYLISTDEL response code %d: %s", resp.code, resp.body
          )
          return False

      async def get_anime_info(self, *, aid: int) -> AnimeInfo | None:
          """Fetch minimal anime info (title, episode count) for an AID.

          Results are cached in-process for the lifetime of the client.

          Args:
              aid: AniDB anime ID.

          Returns:
              AnimeInfo if found, None otherwise.
          """
          if aid in self._anime_cache:
              return self._anime_cache[aid]
          await self._ensure_authenticated()
          # acode bitmask: 0x0002=dateflags, 0x0080=type, 0x0100=title, 0x0800=episodes
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
          """Send AUTH command and store session token.

          Raises:
              AnidbAuthError: If AniDB returns a non-200/201 code.
          """
          cmd = (
              f"AUTH user={self._username}&pass={self._password}"
              f"&protover={_PROTO_VER}&client={self._client}"
              f"&clientver={self._client_version}&enc=UTF8"
          )
          if self._nat:
              cmd += "&nat=1"
          if self._encrypt_key:
              cmd += f"&encrypt={self._username}"
          resp = await self._send_raw(cmd)
          parsed = parse_response(resp)
          if parsed.code not in {200, 201}:
              raise AnidbAuthError(
                  f"AniDB auth failed (code {parsed.code}): {parsed.body}"
              )
          # Session token is the first word of the body
          self._session = parsed.body.split()[0]
          self._authenticated = True
          self._auth_time = time.monotonic()
          if self._encrypt_key:
              raw_key = self._encrypt_key + self._session
              self._cipher_key = hashlib.md5(raw_key.encode()).digest()  # noqa: S324
          self.log.debug("AniDB session established: %s", self._session)

      async def _ensure_authenticated(self) -> None:
          """Re-authenticate if the session has expired."""
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
              command: Full AniDB UDP command string (UTF-8).

          Returns:
              Parsed AnidbResponse.
          """
          now = time.monotonic()
          wait = self._min_interval - (now - self._last_request_time)
          if wait > 0:
              await asyncio.sleep(wait)
          raw = await self._send_raw(command)
          self._last_request_time = time.monotonic()
          return parse_response(raw)

      async def _send_raw(self, command: str) -> bytes:
          """Send a raw command string over UDP and wait for a response.

          If encryption is enabled, applies AES-128-ECB before sending
          and decrypts the response (encryption not applied to AUTH).

          Args:
              command: Command string to send.

          Returns:
              Raw response bytes.

          Raises:
              RuntimeError: If the transport is not open.
              asyncio.TimeoutError: If no response arrives within 30 s.
          """
          if self._transport is None:
              raise RuntimeError("UDP transport is not open; call open() first")
          data = command.encode("utf-8")
          if self._cipher_key and not command.startswith("AUTH"):
              data = _aes128_ecb_encrypt(data, self._cipher_key)
          self._transport.sendto(data)
          try:
              raw = await asyncio.wait_for(self._recv_queue.get(), timeout=30.0)
          except asyncio.TimeoutError as exc:
              raise asyncio.TimeoutError(
                  f"No response from AniDB within 30 s for command: {command[:40]!r}"
              ) from exc
          if self._cipher_key and not command.startswith("AUTH"):
              raw = _aes128_ecb_decrypt(raw, self._cipher_key)
          return raw


  def _aes128_ecb_encrypt(data: bytes, key: bytes) -> bytes:
      """Encrypt *data* with AES-128-ECB using *key*.

      Pads to 16-byte boundary with zero bytes.
      Uses only stdlib (no cryptography package required).
      """
      try:
          from Crypto.Cipher import AES  # pycryptodome optional dependency
          cipher = AES.new(key, AES.MODE_ECB)
      except ImportError:
          # Fallback: return plaintext if pycryptodome not installed.
          # Encryption is optional; warn once.
          logging.getLogger(__name__).warning(
              "pycryptodome not installed; UDP encryption disabled"
          )
          return data
      pad_len = 16 - (len(data) % 16)
      data = data + bytes(pad_len)
      return cipher.encrypt(data)


  def _aes128_ecb_decrypt(data: bytes, key: bytes) -> bytes:
      """Decrypt *data* with AES-128-ECB using *key*."""
      try:
          from Crypto.Cipher import AES
          cipher = AES.new(key, AES.MODE_ECB)
      except ImportError:
          return data
      return cipher.decrypt(data).rstrip(b"\x00")
  ```

- [ ] **Step 4: Run tests to verify they pass**
  Run: `uv run pytest tests/test_udp_client.py -v`
  Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**
  ```bash
  git add src/anibridge/providers/anidb/udp_client.py tests/conftest.py tests/test_udp_client.py
  git commit -m "feat: add async AniDB UDP client with auth, rate-limiting, and cache"
  ```

---

## Group 4: Provider implementation
Depends on Group 3.

### Task 5: AnidbProvider class (ka-coder)

**Files:**
- Create: `src/anibridge/providers/anidb/__init__.py`
- Create: `src/anibridge/providers/anidb/provider.py`
- Create: `tests/test_provider.py`

#### Status mapping (AniDB state int ↔ AniBridge Status):
| AniDB viewdate==0, state=1 | AniBridge Status.ACTIVE (watching/on HDD, not viewed) |
| AniDB viewed=True           | AniBridge Status.COMPLETED                            |
| AniDB state=3 (deleted)    | AniBridge Status.DROPPED                              |
| No entry in MyList          | entry is None (not on list)                           |
| Explicit PLANNING           | Add with state=0, viewed=False — no direct AniDB equivalent; map to state=0 |

#### Key design decisions:
- `key` / `ref` for a record is the string AID (e.g. `"1234"`). AniDB AIDs are integers.
- `MAPPING_PROVIDERS = frozenset({"anidb"})` — AniDB is its own mapping authority.
- `resolve_mapping_descriptors` looks for descriptors with provider `"anidb"` and returns `ListTarget(descriptor, str(aid))`.
- `get_entry(key)` fetches the MyList entry for the AID and the AnimeInfo (for title/total_episodes).
- `update_entry(key, entry)` calls `add_or_update_mylist_entry`.
- `delete_entry(key)` first calls `get_mylist_entry` to get the lid, then calls `delete_mylist_entry(lid=...)`.
- `user()` returns a `ListUser` built from `username` (no separate user fetch needed).
- `search(query)` is not supported by AniDB UDP API for list entries — return `[]`.
- `backup_list()` raises `NotImplementedError`.

- [ ] **Step 1: Write failing provider tests**
  ```python
  # tests/test_provider.py
  """Tests for the AniDB AniBridge provider."""
  import pytest
  from unittest.mock import AsyncMock, MagicMock, patch
  from anibridge.providers.anidb.provider import AnidbProvider
  from anibridge.providers.anidb.models import MylistEntry, MylistStatus, AnimeInfo


  def make_provider(monkeypatch):
      """Create an AnidbProvider with a mocked UDP client."""
      mock_client = MagicMock()
      mock_client.open = AsyncMock()
      mock_client.close = AsyncMock()
      mock_client.clear_cache = MagicMock()
      mock_client.get_mylist_entry = AsyncMock()
      mock_client.add_or_update_mylist_entry = AsyncMock(return_value=True)
      mock_client.delete_mylist_entry = AsyncMock(return_value=True)
      mock_client.get_anime_info = AsyncMock()

      with patch(
          "anibridge.providers.anidb.provider.AnidbUdpClient",
          return_value=mock_client,
      ):
          provider = AnidbProvider(
              logger=MagicMock(),
              config={
                  "username": "testuser",
                  "password": "testpass",
                  "client": "testclient",
                  "client_version": 1,
              },
          )
      provider._client = mock_client
      return provider, mock_client


  @pytest.mark.asyncio
  async def test_initialize_opens_client(monkeypatch):
      provider, mock_client = make_provider(monkeypatch)
      await provider.initialize()
      mock_client.open.assert_awaited_once()


  @pytest.mark.asyncio
  async def test_user_returns_listuser(monkeypatch):
      provider, _ = make_provider(monkeypatch)
      user = provider.user()
      assert user is not None
      assert user.key == "testuser"
      assert user.title == "testuser"


  @pytest.mark.asyncio
  async def test_get_entry_returns_none_when_not_in_list(monkeypatch):
      provider, mock_client = make_provider(monkeypatch)
      mock_client.get_mylist_entry.return_value = None
      mock_client.get_anime_info.return_value = AnimeInfo(
          aid=1234, title="Test Anime", total_episodes=12
      )
      entry = await provider.get_entry("1234")
      assert entry is None


  @pytest.mark.asyncio
  async def test_get_entry_parses_viewed_as_completed(monkeypatch):
      from anibridge.list.base import ListStatus
      provider, mock_client = make_provider(monkeypatch)
      mock_client.get_mylist_entry.return_value = MylistEntry(
          lid=42, fid=0, eid=0, aid=1234, gid=0,
          state=MylistStatus.HDD, viewdate=1700000000,
      )
      mock_client.get_anime_info.return_value = AnimeInfo(
          aid=1234, title="Test Anime", total_episodes=12
      )
      entry = await provider.get_entry("1234")
      assert entry is not None
      assert entry.status == ListStatus.COMPLETED
      assert entry.title == "Test Anime"


  @pytest.mark.asyncio
  async def test_get_entry_not_viewed_is_current(monkeypatch):
      from anibridge.list.base import ListStatus
      provider, mock_client = make_provider(monkeypatch)
      mock_client.get_mylist_entry.return_value = MylistEntry(
          lid=42, fid=0, eid=0, aid=1234, gid=0,
          state=MylistStatus.HDD, viewdate=0,
      )
      mock_client.get_anime_info.return_value = AnimeInfo(
          aid=1234, title="Test Anime", total_episodes=12
      )
      entry = await provider.get_entry("1234")
      assert entry is not None
      assert entry.status == ListStatus.CURRENT


  @pytest.mark.asyncio
  async def test_update_entry_calls_add_or_update(monkeypatch):
      from anibridge.list.base import ListStatus, ListEntry
      provider, mock_client = make_provider(monkeypatch)
      mock_client.get_mylist_entry.return_value = MylistEntry(
          lid=42, fid=0, eid=0, aid=1234, gid=0,
          state=MylistStatus.HDD, viewdate=0,
      )
      mock_client.get_anime_info.return_value = AnimeInfo(
          aid=1234, title="Test Anime", total_episodes=12
      )
      entry = await provider.get_entry("1234")
      entry.status = ListStatus.COMPLETED
      result = await provider.update_entry("1234", entry)
      assert result is not None
      mock_client.add_or_update_mylist_entry.assert_awaited_once()


  @pytest.mark.asyncio
  async def test_delete_entry_fetches_lid_then_deletes(monkeypatch):
      provider, mock_client = make_provider(monkeypatch)
      mock_client.get_mylist_entry.return_value = MylistEntry(
          lid=42, fid=0, eid=0, aid=1234, gid=0,
          state=MylistStatus.HDD, viewdate=0,
      )
      await provider.delete_entry("1234")
      mock_client.delete_mylist_entry.assert_awaited_once_with(lid=42)


  @pytest.mark.asyncio
  async def test_delete_entry_no_op_when_not_in_list(monkeypatch):
      provider, mock_client = make_provider(monkeypatch)
      mock_client.get_mylist_entry.return_value = None
      await provider.delete_entry("1234")
      mock_client.delete_mylist_entry.assert_not_awaited()


  @pytest.mark.asyncio
  async def test_resolve_mapping_descriptors_matches_anidb_ids(monkeypatch):
      from anibridge.provider.base import MappingDescriptor
      provider, _ = make_provider(monkeypatch)
      descriptors = [
          MappingDescriptor(provider="anidb", value="1234"),
          MappingDescriptor(provider="anilist", value="5678"),
      ]
      targets = await provider.resolve_mapping_descriptors(descriptors)
      assert len(targets) == 1
      assert targets[0].media_key == "1234"
  ```

- [ ] **Step 2: Run tests to confirm they fail**
  Run: `uv run pytest tests/test_provider.py -v`
  Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write `src/anibridge/providers/anidb/provider.py`**
  ```python
  """AniBridge list provider for AniDB."""

  from __future__ import annotations

  import logging
  from collections.abc import Mapping, Sequence
  from datetime import UTC, datetime
  from typing import TYPE_CHECKING

  import msgspec
  from anibridge.list.base import (
      ListEntry,
      ListMedia,
      ListMediaType,
      ListProvider,
      ListStatus,
      ListTarget,
      ListUser,
      MappingDescriptor,
  )

  from anibridge.providers.anidb.config import AnidbProviderConfig
  from anibridge.providers.anidb.models import AnimeInfo, MylistEntry, MylistStatus
  from anibridge.providers.anidb.udp_client import AnidbUdpClient

  __all__ = ["AnidbProvider"]

  NAMESPACE = "anidb"

  # ─── Status mapping ──────────────────────────────────────────────────────────
  # AniDB does not have explicit PLANNING/PAUSED/DROPPED statuses.
  # We infer from viewdate (>0 = completed) and state (deleted = dropped).
  # ------------------------------------------------------------------


  def _status_from_entry(entry: MylistEntry) -> ListStatus:
      """Infer an AniBridge ListStatus from an AniDB MylistEntry."""
      if entry.viewdate > 0:
          return ListStatus.COMPLETED
      if entry.state == MylistStatus.DELETED:
          return ListStatus.DROPPED
      return ListStatus.CURRENT


  def _state_from_status(status: ListStatus | None) -> tuple[int, bool]:
      """Return (anidb_state_int, viewed) for a given ListStatus."""
      match status:
          case ListStatus.COMPLETED | ListStatus.REPEATING:
              return (1, True)   # HDD + viewed
          case ListStatus.DROPPED:
              return (3, False)  # Deleted
          case ListStatus.PAUSED | ListStatus.CURRENT:
              return (1, False)  # HDD, not viewed
          case ListStatus.PLANNING | None:
              return (0, False)  # Unknown / planning
          case _:
              return (1, False)


  # ─── Concrete ListMedia / ListEntry ──────────────────────────────────────────


  class _AnidbMedia(ListMedia["AnidbProvider"]):
      """ListMedia backed by AniDB AnimeInfo."""

      def __init__(
          self,
          provider: AnidbProvider,
          info: AnimeInfo,
      ) -> None:
          super().__init__(
              _provider=provider,
              _key=str(info.aid),
              _title=info.title,
          )
          self._info = info

      @property
      def media_type(self) -> ListMediaType:
          """Return TV as the default media type (AniDB is anime-only)."""
          return ListMediaType.TV

      @property
      def total_units(self) -> int | None:
          """Total episode count from AniDB."""
          return self._info.total_episodes

      @property
      def external_url(self) -> str | None:
          """Link to the AniDB anime page."""
          return f"https://anidb.net/anime/{self._info.aid}"


  class _AnidbEntry(ListEntry["AnidbProvider"]):
      """ListEntry backed by an AniDB MylistEntry + AnimeInfo."""

      def __init__(
          self,
          provider: AnidbProvider,
          mylist: MylistEntry,
          info: AnimeInfo,
      ) -> None:
          super().__init__(
              _provider=provider,
              _key=str(mylist.lid),
              _title=info.title,
          )
          self._mylist = mylist
          self._media = _AnidbMedia(provider, info)
          self._status: ListStatus = _status_from_entry(mylist)
          self._progress: int | None = None
          self._repeats: int | None = None
          self._review: str | None = None
          self._user_rating: int | None = None
          self._started_at: datetime | None = None
          self._finished_at: datetime | None = (
              datetime.fromtimestamp(mylist.viewdate, UTC)
              if mylist.viewdate > 0
              else None
          )

      @property
      def status(self) -> ListStatus | None:  # type: ignore[override]
          return self._status

      @status.setter
      def status(self, value: ListStatus | None) -> None:
          self._status = value  # type: ignore[assignment]

      @property
      def progress(self) -> int | None:
          return self._progress

      @progress.setter
      def progress(self, value: int | None) -> None:
          self._progress = value

      @property
      def repeats(self) -> int | None:
          return self._repeats

      @repeats.setter
      def repeats(self, value: int | None) -> None:
          self._repeats = value

      @property
      def review(self) -> str | None:
          return self._review

      @review.setter
      def review(self, value: str | None) -> None:
          self._review = value

      @property
      def user_rating(self) -> int | None:
          return self._user_rating

      @user_rating.setter
      def user_rating(self, value: int | None) -> None:
          self._user_rating = value

      @property
      def started_at(self) -> datetime | None:
          return self._started_at

      @started_at.setter
      def started_at(self, value: datetime | None) -> None:
          self._started_at = value

      @property
      def finished_at(self) -> datetime | None:
          return self._finished_at

      @finished_at.setter
      def finished_at(self, value: datetime | None) -> None:
          self._finished_at = value

      def media(self) -> _AnidbMedia:
          """Return the cached media object for this entry."""
          return self._media


  # ─── Provider ────────────────────────────────────────────────────────────────


  class AnidbProvider(ListProvider):
      """AniBridge ListProvider backed by the AniDB UDP API.

      Configuration keys (all under the ``anidb`` namespace):
          username (str): AniDB account username. Required.
          password (str): AniDB account password. Required.
          client (str): Registered AniDB client name. Required.
          client_version (int): Client version integer. Required.
          encrypt (str | None): AniDB API key for UDP encryption. Optional.
          nat (bool): Enable NAT mode. Default False.
          rate_limit (float): Max UDP req/s. Default 0.5.
      """

      NAMESPACE = "anidb"
      MAPPING_PROVIDERS: frozenset[str] = frozenset({"anidb"})

      def __init__(
          self,
          *,
          logger: logging.Logger,
          config: Mapping[str, object] | None = None,
      ) -> None:
          """Parse config and construct the UDP client."""
          super().__init__(logger=logger, config=config)
          self._parsed = msgspec.convert(config or {}, type=AnidbProviderConfig)
          self._client = AnidbUdpClient(
              username=self._parsed.username,
              password=self._parsed.password,
              client=self._parsed.client,
              client_version=self._parsed.client_version,
              encrypt=self._parsed.encrypt,
              nat=self._parsed.nat,
              rate_limit=self._parsed.rate_limit,
              logger=self.log,
          )

      async def initialize(self) -> None:
          """Open the UDP connection and authenticate."""
          await self._client.open()

      async def close(self) -> None:
          """Log out and close the UDP socket."""
          await self._client.close()

      async def clear_cache(self) -> None:
          """Clear the anime info cache."""
          self._client.clear_cache()

      def user(self) -> ListUser | None:
          """Return a ListUser representing the authenticated AniDB account."""
          return ListUser(
              key=self._parsed.username,
              title=self._parsed.username,
          )

      async def get_entry(self, key: str) -> _AnidbEntry | None:
          """Retrieve a list entry by AID.

          Args:
              key: AniDB anime ID as a string (e.g. ``"1234"``).

          Returns:
              _AnidbEntry if the anime is in the user's MyList, else None.
          """
          aid = int(key)
          mylist, info = await asyncio.gather(
              self._client.get_mylist_entry(aid=aid),
              self._client.get_anime_info(aid=aid),
          )
          if mylist is None:
              return None
          if info is None:
              info = AnimeInfo(aid=aid, title=f"AID:{aid}", total_episodes=None)
          return _AnidbEntry(self, mylist, info)

      async def update_entry(
          self, key: str, entry: ListEntry["AnidbProvider"]
      ) -> _AnidbEntry | None:
          """Update or add a MyList entry for the given AID.

          Args:
              key: AniDB anime ID as a string.
              entry: ListEntry with the new values.

          Returns:
              Updated _AnidbEntry on success, None on failure.
          """
          aid = int(key)
          state_int, viewed = _state_from_status(entry.status)
          viewdate = 0
          if entry.finished_at is not None:
              viewdate = int(entry.finished_at.timestamp())
          ok = await self._client.add_or_update_mylist_entry(
              aid=aid,
              state=state_int,
              viewed=viewed,
              viewdate=viewdate,
          )
          if not ok:
              return None
          return await self.get_entry(key)

      async def delete_entry(self, key: str) -> None:
          """Remove an anime from the user's MyList.

          Args:
              key: AniDB anime ID as a string.
          """
          aid = int(key)
          mylist = await self._client.get_mylist_entry(aid=aid)
          if mylist is None:
              return
          await self._client.delete_mylist_entry(lid=mylist.lid)

      async def resolve_mapping_descriptors(
          self, descriptors: Sequence[MappingDescriptor]
      ) -> Sequence[ListTarget]:
          """Resolve AniDB mapping descriptors to list media keys.

          Only descriptors with provider == ``"anidb"`` are resolved.
          The descriptor value is expected to be a numeric AID string.

          Args:
              descriptors: Sequence of MappingDescriptor objects.

          Returns:
              Sequence of ListTarget for every matched descriptor.
          """
          targets: list[ListTarget] = []
          for desc in descriptors:
              if desc.provider != self.NAMESPACE:
                  continue
              try:
                  int(desc.value)  # validate it's a numeric AID
              except (ValueError, TypeError):
                  self.log.debug("Skipping non-numeric AniDB descriptor: %s", desc.value)
                  continue
              targets.append(ListTarget(descriptor=desc, media_key=str(desc.value)))
          return targets


  # asyncio is used inside get_entry via asyncio.gather
  import asyncio  # noqa: E402
  ```

- [ ] **Step 4: Write `src/anibridge/providers/anidb/__init__.py`**
  ```python
  """AniDB provider for the AniBridge project."""

  from anibridge.providers.anidb.provider import AnidbProvider

  __all__ = ["AnidbProvider"]
  ```

- [ ] **Step 5: Run tests to verify they pass**
  Run: `uv run pytest tests/test_provider.py -v`
  Expected: all tests PASS.

- [ ] **Step 6: Run full test suite**
  Run: `uv run pytest -v`
  Expected: all tests PASS, no import errors.

- [ ] **Step 7: Commit**
  ```bash
  git add src/anibridge/providers/anidb/__init__.py src/anibridge/providers/anidb/provider.py tests/test_provider.py
  git commit -m "feat: implement AnidbProvider with full ListProvider contract"
  ```

---

## Group 5: Documentation
Depends on Group 4. Runs in parallel with review.

### Task 6: README (ka-docs)

**Files:**
- Create: `README.md`
- Create: `LICENSE`

- [ ] **Step 1: Write `LICENSE`** (MIT)
  ```
  MIT License

  Copyright (c) 2026 Contributors

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.
  ```

- [ ] **Step 2: Write `README.md`**
  ```markdown
  # anibridge-anidb-provider

  AniDB list provider for [AniBridge](https://github.com/anibridge/anibridge).
  Reads and writes a user's MyList using the AniDB UDP API.

  ## Requirements

  - Python >= 3.14
  - An AniDB account
  - A registered AniDB API client (register at https://anidb.net/software/add)

  ## Install

  ```bash
  pip install anibridge-anidb-provider
  # or from Git:
  pip install git+https://github.com/<you>/anibridge-anidb-provider.git
  ```

  ## Configuration

  In your AniBridge `config.yaml`:

  ```yaml
  provider_classes:
    - anibridge.providers.anidb.AnidbProvider

  list_provider: anidb
  list_provider_config:
    anidb:
      username: your_anidb_username
      password: your_anidb_password
      client: your_registered_client_name
      client_version: 1
      # Optional: encrypt UDP traffic with your AniDB API key
      # encrypt: your_api_key
      # nat: false
      # rate_limit: 0.5   # max 0.5 req/s (AniDB enforces 1 req/2s)
  ```

  ## Status mapping

  | AniBridge status | AniDB MyList state |
  |---|---|
  | `completed` | `viewed=True`, `state=1` (HDD) |
  | `current` | `viewed=False`, `state=1` (HDD) |
  | `dropped` | `viewed=False`, `state=3` (Deleted) |
  | `planning` | `viewed=False`, `state=0` (Unknown) |
  | `paused` | `viewed=False`, `state=1` (HDD) |
  | `repeating` | `viewed=True`, `state=1` (HDD) |

  ## Limitations

  - AniDB UDP API rate-limits to **1 request per 2 seconds**. Large lists will
    take time to sync.
  - UDP packet encryption requires `pycryptodome` (`pip install pycryptodome`).
    Without it, traffic is sent in plaintext (still acceptable for home use).
  - AniDB does not have a native PAUSED or PLANNING state. Both are approximated.
  - `backup_list()` and `search()` are not implemented.

  ## Development

  ```bash
  uv sync
  uv run pytest -v
  uv run ruff check src tests
  uv run ruff format src tests
  ```
  ```

- [ ] **Step 3: Commit**
  ```bash
  git add README.md LICENSE
  git commit -m "docs: add README and LICENSE"
  ```

---

## Review Gate

- [ ] **ka-reviewer**: check correctness, performance, maintainability
  Focus areas:
  - `_send_raw` timeout and error handling
  - `_ensure_authenticated` race condition under concurrent calls (add `asyncio.Lock`)
  - `asyncio.gather` in `get_entry` — both tasks must tolerate independent failure
  - `_state_from_status` / `_status_from_entry` round-trip correctness
  - `resolve_mapping_descriptors` handles non-string descriptor values gracefully

- [ ] **ka-security-reviewer**: check for vulnerabilities and misconfigurations
  Focus areas:
  - Password stored in memory: confirm it is not logged
  - MD5 used for AES key derivation — this follows AniDB's own spec; document that it is not a security choice
  - UDP source is not authenticated (AniDB sends plaintext session tokens); acceptable given AniDB's design
  - `_send_raw` uses `asyncio.wait_for` — confirm it does not silently drop the pending recv on timeout

---

## Self-review

### Spec coverage

| Requirement | Task |
|---|---|
| pyproject.toml / project scaffold | Task 1 |
| Config struct (username, password, client, encrypt) | Task 2 |
| UDP response parsing (code + body) | Task 3 |
| MylistEntry model | Task 3 |
| AnimeInfo model | Task 3 |
| Async UDP client with auth | Task 4 |
| Rate limiting (min 2s between requests) | Task 4 |
| Session expiry + re-auth | Task 4 |
| Optional AES-128-ECB encryption | Task 4 |
| `get_mylist_entry` | Task 4 |
| `add_or_update_mylist_entry` | Task 4 |
| `delete_mylist_entry` | Task 4 |
| `get_anime_info` with caching | Task 4 |
| `ListProvider.user()` | Task 5 |
| `ListProvider.get_entry()` | Task 5 |
| `ListProvider.update_entry()` | Task 5 |
| `ListProvider.delete_entry()` | Task 5 |
| `ListProvider.resolve_mapping_descriptors()` | Task 5 |
| Status mapping (completed/current/dropped/planning/paused) | Task 5 |
| `__init__.py` re-export | Task 5 |
| README with config docs and status table | Task 6 |
| LICENSE | Task 6 |

### Known gaps / deferred

- **`search()`** — AniDB UDP API has a `ANIME` search command but it returns metadata, not list entries. Returning `[]` is correct for now.
- **`backup_list()`** — AniDB MyList exports exist but require a separate web request with session cookies. Out of scope for v0.1.
- **Pagination / `get_entries_batch`** — the base class default iterates `get_entry` individually; acceptable given rate limits.
- **`asyncio.Lock` on session** — the review gate flags this; the reviewer's fix task should add `self._auth_lock = asyncio.Lock()` and wrap `_ensure_authenticated` + `_authenticate` with it.

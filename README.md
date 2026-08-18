# anibridge-anidb-provider

AniDB provider for the [AniBridge](https://github.com/anibridge) project. Implements the `anibridge-provider-base` interface using the AniDB UDP API to sync watch history, list status, and anime metadata.

[![CI](https://github.com/anibridge/anibridge-anidb-provider/actions/workflows/ci.yml/badge.svg)](https://github.com/anibridge/anibridge-anidb-provider/actions/workflows/ci.yml)

## Installation

From PyPI:

```bash
pip install anibridge-anidb-provider
```

From source:

```bash
pip install git+https://github.com/anibridge/anibridge-anidb-provider.git
```

## Configuration

Add an `anidb` block to your AniBridge `config.yaml`:

```yaml
providers:
  anidb:
    username: your_username        # AniDB account username
    password: your_password        # AniDB account password
    client: your_client_name       # Registered AniDB client name (anidb.net/software)
    client_version: 1              # Registered client version integer
    encrypt: null                  # Optional AniDB API key for UDP encryption (Rijndael/AES-128-ECB)
                                   # Obtain from https://anidb.net/user/<id>/apikey
                                   # Requires pycryptodome to be installed
    nat: false                     # Set true if running behind NAT
    rate_limit: 0.5                # Max UDP requests per second (default 0.5, hard max 1.0)
```

`client` and `client_version` must correspond to a client registered at [anidb.net/software](https://anidb.net/software/add) — AniDB bans unregistered clients.

## Status Mapping

AniDB MyList state values map to AniBridge statuses as follows:

| AniDB `state` | `MylistStatus` | AniBridge status |
|---------------|---------------|-----------------|
| `0` | `UNKNOWN` | `plan_to_watch` |
| `1` | `HDD` | `completed` |
| `2` | `CD` | `completed` |
| `3` | `DELETED` | `dropped` |

`viewdate > 0` (non-zero watch timestamp) is used to confirm a completed entry regardless of state.

## Limitations

- **Rate limiting**: AniDB enforces a hard limit of one request per two seconds for logged-in sessions. The `rate_limit` config key defaults to 0.5 req/s. Exceeding 1.0 req/s will result in a temporary ban.
- **No episode progress**: The AniDB UDP API does not return per-episode progress counters. Episode-level sync is not supported.
- **No backup_list**: The `backup_list` operation is not implemented — AniDB has no bulk export via UDP.
- **Encryption requires pycryptodome**: Setting `encrypt` requires `pycryptodome` (`pip install pycryptodome`). It is not a declared dependency because encryption is optional.

## Development

```bash
# Install dependencies (including dev group)
uv sync

# Run tests
uv run pytest

# Lint
uv run ruff check src tests

# Format check
uv run ruff format --check src tests

# Auto-fix formatting
uv run ruff format src tests
```

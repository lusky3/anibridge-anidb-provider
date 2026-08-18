# anibridge-anidb-provider

AniDB provider for the [AniBridge](https://github.com/anibridge) project. Implements the `anibridge-provider-base` interface using the AniDB UDP API to sync watch history, list status, and anime metadata.

[![CI](https://github.com/lusky3/anibridge-anidb-provider/actions/workflows/ci.yml/badge.svg)](https://github.com/lusky3/anibridge-anidb-provider/actions/workflows/ci.yml)

## Installation

From PyPI:

```bash
pip install anibridge-anidb-provider
```

From source:

```bash
pip install git+https://github.com/lusky3/anibridge-anidb-provider.git
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
    encrypt: null                  # Optional AniDB API key for UDP encryption (AES-128-ECB)
                                   # Obtain from https://anidb.net/user/<id>/apikey
    nat: false                     # Set true if running behind NAT
    rate_limit: 0.5                # Max UDP requests per second (default 0.5, hard max 1.0)
```

`client` and `client_version` must correspond to a client registered at [anidb.net/software](https://anidb.net/software/add) — AniDB bans unregistered clients.

## Status Mapping

AniDB's MyList only has a `state` (0=unknown, 1=hdd, 2=cd, 3=deleted) plus a
`viewdate` timestamp — it has no direct concept of "active", "paused",
"planning", or "repeating". Reads and writes are therefore mapped
independently, and the mapping is lossy in one direction.

**Reading** an entry (checked in this order):

| Condition | AniBridge status |
|-----------|-------------------|
| `viewdate > 0` | `COMPLETED` |
| `state == DELETED` | `DROPPED` |
| anything else | `ACTIVE` |

**Writing** a status (best available approximation):

| AniBridge status | AniDB `state` | `viewed` | Reads back as |
|-------------------|:--:|:--:|-----------------|
| `COMPLETED` / `REPEATING` | `1` (hdd) | `true` | `COMPLETED` |
| `DROPPED` | `3` (deleted) | `false` | `DROPPED` |
| `ACTIVE` / `PAUSED` | `1` (hdd) | `false` | `ACTIVE` |
| `PLANNED` / unset | `0` (unknown) | `false` | `ACTIVE` |

`REPEATING` and `PAUSED` don't round-trip: writing either produces a value
that reads back as `COMPLETED` or `ACTIVE` respectively. This is intentional
— returning a write error for these statuses would break sync pipelines that
legitimately set them. See the `anibridge.providers.anidb.provider` module
docstring for the full rationale.

## Limitations

- **Rate limiting**: AniDB enforces a hard limit of one request per two seconds for logged-in sessions. The `rate_limit` config key defaults to 0.5 req/s. Exceeding 1.0 req/s will result in a temporary ban.
- **No episode progress**: The AniDB UDP API does not return per-episode progress counters. Episode-level sync is not supported.
- **No backup_list**: The `backup_list` operation is not implemented — AniDB has no bulk export via UDP.

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

## Releasing

Publishing to PyPI is fully automated by [`.github/workflows/publish.yml`](.github/workflows/publish.yml)
via [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) —
no API token is stored in the repo.

1. Bump `version` in `pyproject.toml`.
2. Commit, then tag the commit `vX.Y.Z` and push the tag:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
3. The `Publish` workflow builds the package with `uv build` and publishes it
   to PyPI on any push of a `v*` tag. No manual `twine upload`/token step is
   needed.

`.github/dependabot.yml` keeps dependencies (including the `uv.lock` file)
current on a weekly cadence; review and merge those PRs as they come in.

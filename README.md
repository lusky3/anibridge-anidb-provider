# anibridge-anidb-provider

AniDB provider for the AniBridge project.

## Overview

This package implements an AniDB data provider for AniBridge, using the AniDB UDP API.

## Installation

```bash
pip install anibridge-anidb-provider
```

## Configuration

```python
from anibridge.providers.anidb.config import AnidbProviderConfig

config = AnidbProviderConfig(
    username="your_username",
    password="your_password",
    client="your_client_name",
    client_version=1,
)
```

## Development

```bash
uv sync
uv run pytest
```

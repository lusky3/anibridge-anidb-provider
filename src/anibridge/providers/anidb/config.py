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

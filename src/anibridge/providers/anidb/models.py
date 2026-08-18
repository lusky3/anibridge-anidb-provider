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

    @classmethod
    def from_int(cls, value: int) -> MylistStatus:
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

    lid: int
    fid: int
    eid: int
    aid: int
    gid: int
    state: MylistStatus
    viewdate: int

    @classmethod
    def from_response(cls, resp: AnidbResponse) -> MylistEntry:
        """Parse a MYLIST (221) response body into a MylistEntry.

        Args:
            resp: AnidbResponse with code 221.

        Returns:
            MylistEntry populated from the pipe-separated fields.

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
            viewdate=int(parts[7]) if len(parts) > 7 and parts[7].strip().isdigit() else 0,
        )


@dataclass(slots=True)
class AnimeInfo:
    """Minimal AniDB anime info (response code 243 from ANIME command).

    Fields: aid|dateflags|year|type|romaji_name|kanji_name|english_name|episodes
    """

    aid: int
    title: str
    total_episodes: int | None

    @classmethod
    def from_response(cls, resp: AnidbResponse) -> AnimeInfo:
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

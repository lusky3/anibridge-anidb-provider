"""Tests for AnidbProvider — the AniBridge AniDB provider implementation."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anibridge.provider.base import (
    Account,
    DeleteRecord,
    ExternalId,
    Match,
    RecordField,
    Ref,
    State,
    Status,
    SupportsMapping,
    SupportsNodeReads,
    SupportsRecordReads,
    SupportsRecordWrites,
    SupportsScan,
    UpsertRecord,
    WriteError,
    WriteOp,
)
from anibridge.providers.anidb.models import AnimeInfo, MylistEntry, MylistStatus
from anibridge.providers.anidb.provider import (
    AnidbProvider,
    _SURFACE,
    _mylist_to_status,
    _status_to_mylist,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "username": "testuser",
    "password": "testpass",
    "client": "testclient",
    "client_version": 1,
}


def _make_provider() -> tuple[AnidbProvider, MagicMock]:
    """Create an AnidbProvider with a mocked UDP client."""
    logger = logging.getLogger("test")
    with patch(
        "anibridge.providers.anidb.provider.AnidbUdpClient",
        autospec=True,
    ) as MockClient:
        provider = AnidbProvider(logger=logger, config=_BASE_CONFIG)
        mock_client = MockClient.return_value
        # Make async methods return sensible defaults
        mock_client.open = AsyncMock()
        mock_client.close = AsyncMock()
        mock_client.get_mylist_entry = AsyncMock(return_value=None)
        mock_client.get_anime_info = AsyncMock(return_value=None)
        mock_client.add_or_update_mylist_entry = AsyncMock(return_value=True)
        mock_client.delete_mylist_entry = AsyncMock(return_value=True)
        mock_client.clear_cache = MagicMock()
        provider._client = mock_client
    return provider, mock_client


def _make_mylist_entry(
    *,
    lid: int = 10,
    aid: int = 1234,
    state: MylistStatus = MylistStatus.HDD,
    viewdate: int = 0,
) -> MylistEntry:
    """Construct a minimal MylistEntry for test use."""
    return MylistEntry(
        lid=lid,
        fid=0,
        eid=0,
        aid=aid,
        gid=0,
        state=state,
        viewdate=viewdate,
    )


def _make_anime_info(aid: int = 1234, title: str = "Test Anime") -> AnimeInfo:
    """Construct a minimal AnimeInfo for test use."""
    return AnimeInfo(aid=aid, title=title, total_episodes=12)


# ---------------------------------------------------------------------------
# Status mapping helpers
# ---------------------------------------------------------------------------


def test_mylist_to_status_viewdate_nonzero_gives_completed():
    entry = _make_mylist_entry(viewdate=1_700_000_000)
    assert _mylist_to_status(entry) == Status.COMPLETED


def test_mylist_to_status_viewdate_zero_deleted_gives_dropped():
    entry = _make_mylist_entry(state=MylistStatus.DELETED, viewdate=0)
    assert _mylist_to_status(entry) == Status.DROPPED


def test_mylist_to_status_viewdate_zero_hdd_gives_active():
    entry = _make_mylist_entry(state=MylistStatus.HDD, viewdate=0)
    assert _mylist_to_status(entry) == Status.ACTIVE


def test_mylist_to_status_viewdate_zero_cd_gives_active():
    entry = _make_mylist_entry(state=MylistStatus.CD, viewdate=0)
    assert _mylist_to_status(entry) == Status.ACTIVE


def test_mylist_to_status_unknown_state_gives_active():
    entry = _make_mylist_entry(state=MylistStatus.UNKNOWN, viewdate=0)
    assert _mylist_to_status(entry) == Status.ACTIVE


def test_status_to_mylist_completed():
    assert _status_to_mylist(Status.COMPLETED) == (1, True)


def test_status_to_mylist_repeating():
    assert _status_to_mylist(Status.REPEATING) == (1, True)


def test_status_to_mylist_dropped():
    assert _status_to_mylist(Status.DROPPED) == (3, False)


def test_status_to_mylist_active():
    assert _status_to_mylist(Status.ACTIVE) == (1, False)


def test_status_to_mylist_paused():
    assert _status_to_mylist(Status.PAUSED) == (1, False)


def test_status_to_mylist_planned():
    assert _status_to_mylist(Status.PLANNED) == (0, False)


def test_status_to_mylist_none():
    assert _status_to_mylist(None) == (0, False)


# ---------------------------------------------------------------------------
# Provider interface conformance
# ---------------------------------------------------------------------------


def test_provider_implements_required_mixins():
    provider, _ = _make_provider()
    assert isinstance(provider, SupportsMapping)
    assert isinstance(provider, SupportsNodeReads)
    assert isinstance(provider, SupportsRecordReads)
    assert isinstance(provider, SupportsRecordWrites)
    assert isinstance(provider, SupportsScan)


def test_provider_namespace_and_display_name():
    assert AnidbProvider.NAMESPACE == "anidb"
    assert AnidbProvider.DISPLAY_NAME == "AniDB"


# ---------------------------------------------------------------------------
# initialize() / close() / clear_cache()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_calls_client_open():
    """initialize() must call client.open() to establish the UDP session."""
    provider, mock_client = _make_provider()
    await provider.initialize()
    mock_client.open.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_calls_client_close():
    """close() must call client.close() to log out and release the socket."""
    provider, mock_client = _make_provider()
    await provider.close()
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_cache_calls_client_clear_cache():
    """clear_cache() must call client.clear_cache() to drop the anime cache."""
    provider, mock_client = _make_provider()
    await provider.clear_cache()
    mock_client.clear_cache.assert_called_once()


# ---------------------------------------------------------------------------
# account()
# ---------------------------------------------------------------------------


def test_account_returns_none_before_initialize():
    provider, _ = _make_provider()
    assert provider.account() is None


@pytest.mark.asyncio
async def test_account_returns_correct_account_after_initialize():
    """user() equivalent: account() returns Account with username as key and title."""
    provider, mock_client = _make_provider()
    await provider.initialize()
    acc = provider.account()
    assert acc is not None
    assert isinstance(acc, Account)
    assert acc.key == "testuser"
    assert acc.title == "testuser"


# ---------------------------------------------------------------------------
# fetch_records() (get_entry equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_records_returns_empty_when_not_in_mylist():
    """fetch_records() returns no records when get_mylist_entry returns None."""
    provider, mock_client = _make_provider()
    mock_client.get_mylist_entry.return_value = None
    mock_client.get_anime_info.return_value = None

    from anibridge.provider.base import RecordQuery

    result = await provider.fetch_records(RecordQuery(keys=("1234",)))
    assert result.items == ()


@pytest.mark.asyncio
async def test_fetch_records_maps_viewdate_to_completed():
    """fetch_records() returns COMPLETED status when viewdate > 0."""
    provider, mock_client = _make_provider()
    entry = _make_mylist_entry(viewdate=1_700_000_000)
    mock_client.get_mylist_entry.return_value = entry
    mock_client.get_anime_info.return_value = _make_anime_info()

    from anibridge.provider.base import RecordQuery

    result = await provider.fetch_records(RecordQuery(keys=("1234",)))
    assert len(result.items) == 1
    record = result.items[0]
    state = record.values[RecordField.STATUS]
    assert isinstance(state, State)
    assert state.status == Status.COMPLETED


@pytest.mark.asyncio
async def test_fetch_records_maps_hdd_no_viewdate_to_active():
    """fetch_records() returns ACTIVE status when state=HDD and viewdate=0."""
    provider, mock_client = _make_provider()
    entry = _make_mylist_entry(state=MylistStatus.HDD, viewdate=0)
    mock_client.get_mylist_entry.return_value = entry
    mock_client.get_anime_info.return_value = _make_anime_info()

    from anibridge.provider.base import RecordQuery

    result = await provider.fetch_records(RecordQuery(keys=("1234",)))
    assert len(result.items) == 1
    state = result.items[0].values[RecordField.STATUS]
    assert isinstance(state, State)
    assert state.status == Status.ACTIVE


@pytest.mark.asyncio
async def test_fetch_records_maps_deleted_to_dropped():
    """fetch_records() returns DROPPED status when state=DELETED."""
    provider, mock_client = _make_provider()
    entry = _make_mylist_entry(state=MylistStatus.DELETED, viewdate=0)
    mock_client.get_mylist_entry.return_value = entry
    mock_client.get_anime_info.return_value = _make_anime_info()

    from anibridge.provider.base import RecordQuery

    result = await provider.fetch_records(RecordQuery(keys=("1234",)))
    assert len(result.items) == 1
    state = result.items[0].values[RecordField.STATUS]
    assert isinstance(state, State)
    assert state.status == Status.DROPPED


@pytest.mark.asyncio
async def test_fetch_records_uses_concurrent_gather():
    """fetch_records() fetches mylist and anime info concurrently via asyncio.gather."""
    provider, mock_client = _make_provider()
    call_order: list[str] = []

    async def fake_mylist(*, aid: int) -> MylistEntry:
        call_order.append("mylist")
        return _make_mylist_entry(aid=aid, viewdate=0)

    async def fake_anime(*, aid: int) -> AnimeInfo:
        call_order.append("anime")
        return _make_anime_info(aid=aid)

    mock_client.get_mylist_entry.side_effect = fake_mylist
    mock_client.get_anime_info.side_effect = fake_anime

    from anibridge.provider.base import RecordQuery

    result = await provider.fetch_records(RecordQuery(keys=("1234",)))
    assert len(result.items) == 1
    # Both methods must have been called
    assert "mylist" in call_order
    assert "anime" in call_order


@pytest.mark.asyncio
async def test_fetch_records_record_has_correct_surface():
    """Records returned from fetch_records() use the expected surface name."""
    provider, mock_client = _make_provider()
    mock_client.get_mylist_entry.return_value = _make_mylist_entry()
    mock_client.get_anime_info.return_value = _make_anime_info()

    from anibridge.provider.base import RecordQuery

    result = await provider.fetch_records(RecordQuery(keys=("1234",)))
    assert result.items[0].surface == _SURFACE


@pytest.mark.asyncio
async def test_fetch_records_record_key_is_lid():
    """Records returned from fetch_records() use the lid as the record key."""
    provider, mock_client = _make_provider()
    mock_client.get_mylist_entry.return_value = _make_mylist_entry(lid=42)
    mock_client.get_anime_info.return_value = _make_anime_info()

    from anibridge.provider.base import RecordQuery

    result = await provider.fetch_records(RecordQuery(keys=("1234",)))
    assert result.items[0].key == "42"


# ---------------------------------------------------------------------------
# write_records() — UpsertRecord (update_entry equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_records_upsert_completed_calls_viewed_true():
    """UpsertRecord with COMPLETED status calls add_or_update with viewed=True."""
    provider, mock_client = _make_provider()

    write = UpsertRecord(
        ref=Ref.anchor("1234"),
        surface=_SURFACE,
        set={RecordField.STATUS: State(native="completed", status=Status.COMPLETED)},
    )
    results = await provider.write_records([write])

    assert len(results) == 1
    assert results[0].ok is True
    mock_client.add_or_update_mylist_entry.assert_awaited_once_with(
        aid=1234, state=1, viewed=True
    )


@pytest.mark.asyncio
async def test_write_records_upsert_planned_calls_state_0_viewed_false():
    """UpsertRecord with PLANNED status calls add_or_update with state=0, viewed=False."""
    provider, mock_client = _make_provider()

    write = UpsertRecord(
        ref=Ref.anchor("5678"),
        surface=_SURFACE,
        set={RecordField.STATUS: State(native="planned", status=Status.PLANNED)},
    )
    results = await provider.write_records([write])

    assert len(results) == 1
    assert results[0].ok is True
    mock_client.add_or_update_mylist_entry.assert_awaited_once_with(
        aid=5678, state=0, viewed=False
    )


@pytest.mark.asyncio
async def test_write_records_upsert_dropped_calls_state_3():
    """UpsertRecord with DROPPED status calls add_or_update with state=3."""
    provider, mock_client = _make_provider()

    write = UpsertRecord(
        ref=Ref.anchor("9999"),
        surface=_SURFACE,
        set={RecordField.STATUS: State(native="dropped", status=Status.DROPPED)},
    )
    results = await provider.write_records([write])

    assert results[0].ok is True
    mock_client.add_or_update_mylist_entry.assert_awaited_once_with(
        aid=9999, state=3, viewed=False
    )


@pytest.mark.asyncio
async def test_write_records_upsert_repeating_calls_viewed_true():
    """UpsertRecord with REPEATING status calls add_or_update with viewed=True."""
    provider, mock_client = _make_provider()

    write = UpsertRecord(
        ref=Ref.anchor("111"),
        surface=_SURFACE,
        set={RecordField.STATUS: State(native="repeating", status=Status.REPEATING)},
    )
    results = await provider.write_records([write])
    assert results[0].ok is True
    mock_client.add_or_update_mylist_entry.assert_awaited_once_with(
        aid=111, state=1, viewed=True
    )


@pytest.mark.asyncio
async def test_write_records_upsert_returns_transient_on_client_false():
    """UpsertRecord returns failed WriteResult when add_or_update returns False."""
    provider, mock_client = _make_provider()
    mock_client.add_or_update_mylist_entry.return_value = False

    write = UpsertRecord(
        ref=Ref.anchor("1234"),
        surface=_SURFACE,
        set={RecordField.STATUS: State(native="completed", status=Status.COMPLETED)},
    )
    results = await provider.write_records([write])
    assert results[0].ok is False
    assert results[0].code == WriteError.TRANSIENT


@pytest.mark.asyncio
async def test_write_records_upsert_op_is_upsert_record():
    """UpsertRecord result carries the UPSERT_RECORD op."""
    provider, mock_client = _make_provider()
    write = UpsertRecord(
        ref=Ref.anchor("1234"),
        surface=_SURFACE,
        set={RecordField.STATUS: State(native="completed", status=Status.COMPLETED)},
    )
    results = await provider.write_records([write])
    assert results[0].op == WriteOp.UPSERT_RECORD


# ---------------------------------------------------------------------------
# write_records() — DeleteRecord (delete_entry equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_records_delete_by_ref_looks_up_lid_and_deletes():
    """DeleteRecord by ref fetches the lid from MyList then calls delete_mylist_entry."""
    provider, mock_client = _make_provider()
    entry = _make_mylist_entry(lid=99)
    mock_client.get_mylist_entry.return_value = entry

    write = DeleteRecord(ref=Ref.anchor("1234"), surface=_SURFACE)
    results = await provider.write_records([write])

    assert results[0].ok is True
    mock_client.get_mylist_entry.assert_awaited_once_with(aid=1234)
    mock_client.delete_mylist_entry.assert_awaited_once_with(lid=99)


@pytest.mark.asyncio
async def test_write_records_delete_by_ref_noop_when_not_in_list():
    """DeleteRecord by ref is a no-op success when the entry is not in MyList."""
    provider, mock_client = _make_provider()
    mock_client.get_mylist_entry.return_value = None

    write = DeleteRecord(ref=Ref.anchor("1234"), surface=_SURFACE)
    results = await provider.write_records([write])

    assert results[0].ok is True
    mock_client.delete_mylist_entry.assert_not_called()


@pytest.mark.asyncio
async def test_write_records_delete_by_key_uses_lid_directly():
    """DeleteRecord by key (lid) calls delete_mylist_entry with that lid directly."""
    provider, mock_client = _make_provider()

    write = DeleteRecord(key="42")
    results = await provider.write_records([write])

    assert results[0].ok is True
    mock_client.delete_mylist_entry.assert_awaited_once_with(lid=42)
    mock_client.get_mylist_entry.assert_not_called()


@pytest.mark.asyncio
async def test_write_records_delete_op_is_delete_record():
    """DeleteRecord result carries the DELETE_RECORD op."""
    provider, mock_client = _make_provider()
    mock_client.get_mylist_entry.return_value = _make_mylist_entry(lid=1)

    write = DeleteRecord(ref=Ref.anchor("1234"), surface=_SURFACE)
    results = await provider.write_records([write])
    assert results[0].op == WriteOp.DELETE_RECORD


# ---------------------------------------------------------------------------
# resolve() (resolve_mapping_descriptors equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_returns_match_for_anidb_numeric_ids():
    """resolve() returns a Match for each descriptor with authority=anidb and numeric value."""
    provider, _ = _make_provider()

    ids = [
        ExternalId(authority="anidb", value="1234"),
        ExternalId(authority="anidb", value="5678"),
    ]
    matches = await provider.resolve(ids)
    assert len(matches) == 2
    assert all(isinstance(m, Match) for m in matches)
    keys = {m.ref.key for m in matches}
    assert keys == {"1234", "5678"}


@pytest.mark.asyncio
async def test_resolve_skips_non_anidb_authorities():
    """resolve() ignores descriptors from other authorities."""
    provider, _ = _make_provider()

    ids = [
        ExternalId(authority="anidb", value="1234"),
        ExternalId(authority="mal", value="56"),
        ExternalId(authority="tvdb", value="789"),
    ]
    matches = await provider.resolve(ids)
    assert len(matches) == 1
    assert matches[0].ref.key == "1234"


@pytest.mark.asyncio
async def test_resolve_skips_non_numeric_anidb_values():
    """resolve() ignores anidb descriptors with non-numeric values."""
    provider, _ = _make_provider()

    ids = [
        ExternalId(authority="anidb", value="abc"),
        ExternalId(authority="anidb", value="1234"),
    ]
    matches = await provider.resolve(ids)
    assert len(matches) == 1
    assert matches[0].ref.key == "1234"


@pytest.mark.asyncio
async def test_resolve_empty_list_returns_empty():
    """resolve() with no ids returns an empty sequence."""
    provider, _ = _make_provider()
    matches = await provider.resolve([])
    assert list(matches) == []


@pytest.mark.asyncio
async def test_resolve_match_has_full_confidence():
    """resolve() returns confidence=1.0 for resolved AniDB IDs."""
    provider, _ = _make_provider()
    ids = [ExternalId(authority="anidb", value="42")]
    matches = await provider.resolve(ids)
    assert matches[0].confidence == 1.0


# ---------------------------------------------------------------------------
# scan() (backup_list equivalent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_returns_empty_page():
    """scan() returns an empty Page (AniDB UDP has no bulk export)."""
    from anibridge.provider.base import ScanQuery

    provider, _ = _make_provider()
    result = await provider.scan(ScanQuery())
    assert result.items == ()


# ---------------------------------------------------------------------------
# fetch_nodes()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_nodes_returns_node_with_anime_title():
    """fetch_nodes() returns a Node with the anime title when AnimeInfo is available."""
    provider, mock_client = _make_provider()
    mock_client.get_anime_info.return_value = _make_anime_info(title="Neon Genesis Evangelion")

    from anibridge.provider.base import NodeQuery

    result = await provider.fetch_nodes(NodeQuery(keys=("1234",)))
    assert len(result.items) == 1
    node = result.items[0]
    assert node.title == "Neon Genesis Evangelion"
    assert node.ref.key == "1234"


@pytest.mark.asyncio
async def test_fetch_nodes_fallback_title_when_no_anime_info():
    """fetch_nodes() returns AID:key as title when AnimeInfo is None."""
    provider, mock_client = _make_provider()
    mock_client.get_anime_info.return_value = None

    from anibridge.provider.base import NodeQuery

    result = await provider.fetch_nodes(NodeQuery(keys=("9999",)))
    assert len(result.items) == 1
    assert result.items[0].title == "AID:9999"


# ---------------------------------------------------------------------------
# capabilities()
# ---------------------------------------------------------------------------


def test_capabilities_advertises_anidb_external_authority():
    provider, _ = _make_provider()
    caps = provider.capabilities()
    assert "anidb" in caps.external_authorities


def test_capabilities_advertises_record_surface():
    provider, _ = _make_provider()
    caps = provider.capabilities()
    surfaces = [spec.surface for spec in caps.records]
    assert _SURFACE in surfaces


def test_capabilities_has_both_roles():
    from anibridge.provider.base import Role

    provider, _ = _make_provider()
    caps = provider.capabilities()
    assert Role.SOURCE in caps.roles
    assert Role.TARGET in caps.roles


def test_capabilities_record_spec_has_status_field():
    provider, _ = _make_provider()
    caps = provider.capabilities()
    mylist_spec = next(s for s in caps.records if s.surface == _SURFACE)
    assert RecordField.STATUS in mylist_spec.fields

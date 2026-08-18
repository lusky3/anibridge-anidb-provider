"""AniDB provider implementation for AniBridge."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence

from anibridge.provider.base import (
    Account,
    Capabilities,
    DeleteRecord,
    Descriptor,
    ExternalId,
    FacetName,
    FieldSpec,
    Identifiers,
    Match,
    Node,
    NodeFlag,
    NodeKind,
    NodeSpec,
    NodeQuery,
    Page,
    Provider,
    Record,
    RecordField,
    RecordQuery,
    RecordSpec,
    RecordWrite,
    Ref,
    Role,
    State,
    Status,
    SupportsMapping,
    SupportsNodeReads,
    SupportsRecordReads,
    SupportsRecordWrites,
    ScanItem,
    ScanQuery,
    SupportsScan,
    Titles,
    UpsertRecord,
    WriteError,
    WriteOp,
    WriteResult,
)
from anibridge.providers.anidb.config import AnidbProviderConfig
from anibridge.providers.anidb.models import AnimeInfo, MylistEntry, MylistStatus
from anibridge.providers.anidb.udp_client import AnidbUdpClient

#: The AniDB MyList record surface name used in all Record objects.
_SURFACE = "mylist"

#: Status descriptors mapping AniDB native states to normalized Status values.
_STATUS_DESCRIPTORS: tuple[Descriptor[Status], ...] = (
    Descriptor(native="completed", semantic=Status.COMPLETED),
    Descriptor(native="dropped", semantic=Status.DROPPED),
    Descriptor(native="current", semantic=Status.ACTIVE),
    Descriptor(native="planned", semantic=Status.PLANNED),
    Descriptor(native="repeating", semantic=Status.REPEATING),
    Descriptor(native="paused", semantic=Status.PAUSED),
)


def _mylist_to_status(entry: MylistEntry) -> Status:
    """Map a MylistEntry to a normalized Status.

    Rules (in priority order):
    1. viewdate > 0 → COMPLETED
    2. state == DELETED → DROPPED
    3. anything else → ACTIVE
    """
    if entry.viewdate > 0:
        return Status.COMPLETED
    if entry.state == MylistStatus.DELETED:
        return Status.DROPPED
    return Status.ACTIVE


def _status_to_mylist(status: Status | None) -> tuple[int, bool]:
    """Map a normalized Status to an AniDB (state, viewed) pair.

    Returns:
        Tuple of (state_int, viewed_bool) suitable for MYLISTADD.
    """
    if status in (Status.COMPLETED, Status.REPEATING):
        return (1, True)
    if status == Status.DROPPED:
        return (3, False)
    if status in (Status.PAUSED, Status.ACTIVE):
        return (1, False)
    # PLANNED or None
    return (0, False)


def _build_record(
    key: str,
    entry: MylistEntry,
    anime: AnimeInfo | None,
) -> Record:
    """Build a normalized Record from a MylistEntry and optional AnimeInfo."""
    status = _mylist_to_status(entry)
    return Record(
        ref=Ref.anchor(key),
        surface=_SURFACE,
        key=str(entry.lid),
        values={RecordField.STATUS: State(native=status.value, status=status)},
    )


def _build_node(key: str, anime: AnimeInfo | None) -> Node:
    """Build a normalized Node from optional AnimeInfo."""
    title = anime.title if anime else f"AID:{key}"
    facets: dict[FacetName, object] = {}
    if anime:
        facets[FacetName.TITLES] = Titles(primary=anime.title)
        facets[FacetName.IDS] = Identifiers(
            ids=(ExternalId(authority="anidb", value=key),)
        )
    return Node(
        ref=Ref.anchor(key),
        kind="anime",
        title=title,
        flags=frozenset({NodeFlag.ANCHOR, NodeFlag.TRACKABLE, NodeFlag.SCAN_ROOT}),
        facets=facets,
    )


class AnidbProvider(
    Provider,
    SupportsMapping,
    SupportsNodeReads,
    SupportsRecordReads,
    SupportsRecordWrites,
    SupportsScan,
):
    """AniBridge provider for the AniDB anime database.

    Implements the full Provider contract using the AniDB UDP API.
    Supports reading and writing MyList entries (watch status, completion state),
    and resolving AniDB IDs from external mapping descriptors.
    """

    DISPLAY_NAME = "AniDB"
    NAMESPACE = "anidb"

    def __init__(
        self,
        *,
        logger: logging.Logger,
        config: Mapping[str, object] | None = None,
    ) -> None:
        """Construct the provider from a config mapping.

        Args:
            logger: Logger instance.
            config: Config dict with keys matching AnidbProviderConfig fields.
        """
        super().__init__(logger=logger, config=config)
        cfg_dict = dict(config or {})
        import msgspec  # noqa: PLC0415

        self._cfg: AnidbProviderConfig = msgspec.convert(
            cfg_dict, AnidbProviderConfig
        )
        self._client = AnidbUdpClient(
            username=self._cfg.username,
            password=self._cfg.password,
            client=self._cfg.client,
            client_version=self._cfg.client_version,
            encrypt=self._cfg.encrypt,
            nat=self._cfg.nat,
            rate_limit=self._cfg.rate_limit,
            logger=logger,
        )
        self._initialized = False

    # ------------------------------------------------------------------
    # Provider lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open the UDP socket and authenticate with AniDB."""
        await self._client.open()
        self._initialized = True

    async def close(self) -> None:
        """Log out and close the UDP socket."""
        await self._client.close()

    async def clear_cache(self) -> None:
        """Clear the in-process anime info cache."""
        self._client.clear_cache()

    def account(self) -> Account | None:
        """Return the authenticated account, or None before initialize."""
        if not self._initialized:
            return None
        return Account(
            key=self._cfg.username,
            title=self._cfg.username,
        )

    def capabilities(self) -> Capabilities:
        """Advertise AniDB provider capabilities."""
        return Capabilities(
            roles=frozenset({Role.SOURCE, Role.TARGET}),
            facets=frozenset({FacetName.TITLES, FacetName.IDS}),
            nodes=(
                NodeSpec(
                    kind=Descriptor(native="anime", semantic=NodeKind.SERIES),
                    flags=frozenset(
                        {NodeFlag.ANCHOR, NodeFlag.TRACKABLE, NodeFlag.SCAN_ROOT}
                    ),
                ),
            ),
            records=(
                RecordSpec(
                    surface=_SURFACE,
                    fields={
                        RecordField.STATUS: FieldSpec(
                            field=RecordField.STATUS,
                            readable=True,
                            writable=True,
                            values=_STATUS_DESCRIPTORS,
                        ),
                    },
                    write_ops=frozenset({WriteOp.UPSERT_RECORD, WriteOp.DELETE_RECORD}),
                ),
            ),
            external_authorities=frozenset({"anidb"}),
        )

    # ------------------------------------------------------------------
    # SupportsMapping
    # ------------------------------------------------------------------

    async def resolve(self, ids: Sequence[ExternalId]) -> Sequence[Match]:
        """Resolve AniDB external IDs onto Refs.

        Only descriptors with authority="anidb" and a numeric value are resolved.

        Args:
            ids: External ID descriptors to resolve.

        Returns:
            Sequence of Match objects for resolved descriptors.
        """
        matches: list[Match] = []
        for eid in ids:
            if eid.authority == "anidb" and eid.value.isdigit():
                matches.append(
                    Match(external_id=eid, ref=Ref.anchor(eid.value), confidence=1.0)
                )
        return matches

    # ------------------------------------------------------------------
    # SupportsNodeReads
    # ------------------------------------------------------------------

    async def fetch_nodes(self, query: NodeQuery) -> Page[Node]:
        """Fetch anime nodes by AID key or ref.

        Args:
            query: NodeQuery with refs or keys to fetch.

        Returns:
            Page of Node objects.
        """
        keys = list(query.keys)
        for ref in query.refs:
            if ref.key not in keys:
                keys.append(ref.key)

        nodes: list[Node] = []
        for key in keys:
            try:
                aid = int(key)
            except ValueError:
                continue
            anime = await self._client.get_anime_info(aid=aid)
            nodes.append(_build_node(key, anime))

        return Page(items=tuple(nodes))

    # ------------------------------------------------------------------
    # SupportsRecordReads
    # ------------------------------------------------------------------

    async def fetch_records(self, query: RecordQuery) -> Page[Record]:
        """Fetch MyList records for the given refs or keys.

        Fetches mylist entry and anime info concurrently for each requested key.
        Returns only entries that exist in MyList (None mylist → omitted).

        Args:
            query: RecordQuery with refs or keys to fetch.

        Returns:
            Page of Record objects for entries found in MyList.
        """
        keys = list(query.keys)
        for ref in query.refs:
            if ref.key not in keys:
                keys.append(ref.key)

        records: list[Record] = []
        for key in keys:
            record = await self._fetch_single_record(key)
            if record is not None:
                records.append(record)

        return Page(items=tuple(records))

    async def _fetch_single_record(self, key: str) -> Record | None:
        """Fetch one MyList record by AID key, returning None if not in list.

        Fetches mylist entry and anime info concurrently.

        Args:
            key: AID string (e.g. "1234").

        Returns:
            Record if the entry exists in MyList, None otherwise.
        """
        try:
            aid = int(key)
        except ValueError:
            return None

        mylist_entry, _anime = await asyncio.gather(
            self._client.get_mylist_entry(aid=aid),
            self._client.get_anime_info(aid=aid),
        )

        if mylist_entry is None:
            return None

        return _build_record(key, mylist_entry, _anime)

    # ------------------------------------------------------------------
    # SupportsRecordWrites
    # ------------------------------------------------------------------

    async def write_records(
        self, writes: Sequence[RecordWrite]
    ) -> Sequence[WriteResult]:
        """Apply record writes to AniDB MyList.

        For UpsertRecord: maps STATUS field to (state, viewed) and calls
        add_or_update_mylist_entry.

        For DeleteRecord: looks up the lid from MyList and deletes it.
        No-op (success) if the entry does not exist.

        Args:
            writes: Sequence of RecordWrite (UpsertRecord or DeleteRecord).

        Returns:
            Sequence of WriteResult, one per input write.
        """
        results: list[WriteResult] = []
        for write in writes:
            if isinstance(write, UpsertRecord):
                result = await self._upsert_record(write)
            elif isinstance(write, DeleteRecord):
                result = await self._delete_record(write)
            else:
                result = WriteResult(
                    ok=False,
                    op=WriteOp.UPSERT_RECORD,
                    code=WriteError.UNSUPPORTED,
                    error=f"Unsupported write type: {type(write).__name__}",
                    token=getattr(write, "token", None),
                )
            results.append(result)
        return results

    async def _upsert_record(self, write: UpsertRecord) -> WriteResult:
        """Handle a single UpsertRecord by updating AniDB MyList.

        Args:
            write: The upsert request.

        Returns:
            WriteResult indicating success or failure.
        """
        try:
            aid = int(write.ref.key)
        except (ValueError, AttributeError):
            return WriteResult(
                ok=False,
                op=WriteOp.UPSERT_RECORD,
                code=WriteError.INVALID,
                error=f"Invalid AID key: {write.ref!r}",
                token=write.token,
            )

        # Extract status from the write values
        status_value = write.set.get(RecordField.STATUS)
        status: Status | None = None
        if isinstance(status_value, State):
            status = status_value.status
        elif isinstance(status_value, str):
            try:
                status = Status(status_value)
            except ValueError:
                pass

        state_int, viewed = _status_to_mylist(status)
        ok = await self._client.add_or_update_mylist_entry(
            aid=aid,
            state=state_int,
            viewed=viewed,
        )
        if ok:
            return WriteResult(ok=True, op=WriteOp.UPSERT_RECORD, token=write.token)
        return WriteResult(
            ok=False,
            op=WriteOp.UPSERT_RECORD,
            code=WriteError.TRANSIENT,
            error="add_or_update_mylist_entry returned False",
            token=write.token,
        )

    async def _delete_record(self, write: DeleteRecord) -> WriteResult:
        """Handle a single DeleteRecord by removing from AniDB MyList.

        Looks up the lid from the current MyList entry before deleting.
        No-op (success) when the entry is not in the list.

        Args:
            write: The delete request.

        Returns:
            WriteResult indicating success or failure.
        """
        # Resolve the AID — prefer write.key (a lid) then write.ref
        if write.key is not None:
            # key is a lid directly
            try:
                lid = int(write.key)
            except ValueError:
                return WriteResult(
                    ok=False,
                    op=WriteOp.DELETE_RECORD,
                    code=WriteError.INVALID,
                    error=f"Invalid lid key: {write.key!r}",
                    token=write.token,
                )
            await self._client.delete_mylist_entry(lid=lid)
            return WriteResult(ok=True, op=WriteOp.DELETE_RECORD, token=write.token)

        if write.ref is not None:
            try:
                aid = int(write.ref.key)
            except (ValueError, AttributeError):
                return WriteResult(
                    ok=False,
                    op=WriteOp.DELETE_RECORD,
                    code=WriteError.INVALID,
                    error=f"Invalid AID ref: {write.ref!r}",
                    token=write.token,
                )
            entry = await self._client.get_mylist_entry(aid=aid)
            if entry is None:
                # Not in list — treat as no-op success
                return WriteResult(
                    ok=True, op=WriteOp.DELETE_RECORD, token=write.token
                )
            await self._client.delete_mylist_entry(lid=entry.lid)
            return WriteResult(ok=True, op=WriteOp.DELETE_RECORD, token=write.token)

        return WriteResult(
            ok=False,
            op=WriteOp.DELETE_RECORD,
            code=WriteError.INVALID,
            error="DeleteRecord requires key or ref",
            token=write.token,
        )

    # ------------------------------------------------------------------
    # SupportsScan
    # ------------------------------------------------------------------

    async def scan(self, query: ScanQuery) -> Page[ScanItem]:
        """Scan the AniDB MyList.

        Note: AniDB UDP API does not support bulk list export, so this
        always returns an empty page.

        Args:
            query: ScanQuery (unused).

        Returns:
            Empty Page.
        """
        return Page(items=())

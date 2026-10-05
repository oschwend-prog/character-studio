"""Credit budget: reserve before spending, settle with the real cost, release on failure.

The ledger (``studio.ledger``) is append-only. Per clip and month, ``committed`` counts what
was really spent plus what is still reserved:

* ``reserve`` adds an open reservation (refused past the monthly cap or with the kill switch on),
* ``settle`` closes the clip's open reservations and books the *actual* cost instead,
* ``release`` closes them and books nothing (the generation failed).

An open reservation is one with no later ``settle`` / ``release`` for the same clip. A clip can
be reserved again after it was settled (the one allowed re-roll); two reserves in a row simply
add up until the next settle or release closes them.

Months are Europe/London calendar months. A settle or release lands in the month of the
reservation it closes, even when it happens after midnight: the credits were committed when the
job was submitted, so every month's rows are self-contained and ``committed`` for a closed
month never changes.

Concurrency: ``reserve``, ``settle`` and ``release`` each run in ``store.transaction()`` and
read the settings first. ``PostgresStore.get_settings()`` locks the settings row ``FOR UPDATE``
inside a transaction, so concurrent ledger writers queue up and each sees the previous one's
rows; two parallel reserves can never both squeeze under the cap. ``MemoryStore`` has no
transaction semantics (single-threaded tests only).

Ordering: ``committed`` replays each clip's rows in ``created_at`` order, so a new row is
stamped no earlier than the clip's last row (clock skew between machines, or two calls with the
same ``now``, cannot reorder a reservation behind the settle that closes it).

``open_reservations`` / ``studio budget open`` is the read-only list of clips that still hold credits
(any month of the last 12), so a crashed run's reservation can be found and settled or released.

CLI (``studio budget ...``) prints JSON on stdout. Exit codes: 0 ok, 3 refused by the budget
(cap or kill switch), 2 anything the caller must fix (no ``DATABASE_URL``, unknown clip, no open
reservation, bad number); an unexpected crash exits 1, so it is never mistaken for a refusal.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

import typer

from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, now_london
from studio.models import LedgerEntry
from studio.store import Store, require_aware

RefusalReason = Literal["kill_switch", "over_cap"]

# How far back settle/release look for the reservation they close (it normally sits in the
# current month; this only matters for a job that finishes after a month boundary or a
# reservation that was left open for a long time).
LOOKBACK_MONTHS = 12

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


class BudgetRefused(Exception):
    """A reservation was refused: the kill switch is on, or it would pass the monthly cap."""

    def __init__(
        self,
        reason: RefusalReason,
        message: str | None = None,
        *,
        month: str | None = None,
        cap: int | None = None,
        committed: int | None = None,
        requested: int | None = None,
    ) -> None:
        super().__init__(message or f"budget refused: {reason}")
        self.reason: RefusalReason = reason
        self.month = month
        self.cap = cap
        self.committed = committed
        self.requested = requested


class NoOpenReservation(LookupError):
    """``settle`` / ``release`` found no open reservation for the clip."""


@dataclass(frozen=True)
class Spend:
    settled: int
    reserved: int

    @property
    def committed(self) -> int:
        return self.settled + self.reserved


@dataclass
class _ClipTotals:
    settled: int = 0
    open: int = 0


def month_key(dt: datetime) -> str:
    """The Europe/London calendar month of ``dt`` as ``'YYYY-MM'``. ``dt`` must be aware."""
    require_aware(dt, "month_key(dt)")
    return dt.astimezone(LONDON).strftime("%Y-%m")


def _check_credits(value: object, what: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{what} must be an integer >= {minimum}, got {value!r}")
    return value


def _totals(entries: list[LedgerEntry]) -> dict[str, _ClipTotals]:
    """Replay one month's rows (oldest first) into per-clip settled / still-open credits."""
    clips: dict[str, _ClipTotals] = {}
    for e in entries:
        t = clips.setdefault(e.clip_id, _ClipTotals())
        if e.kind == "reserve":
            t.open += e.credits
        elif e.kind == "settle":
            t.settled += e.credits
            t.open = 0
        else:  # release
            t.open = 0
    return clips


def spend(store: Store, month: str) -> Spend:
    """Settled and still-reserved credits for ``month``."""
    clips = _totals(store.ledger_month(month)).values()
    return Spend(settled=sum(t.settled for t in clips), reserved=sum(t.open for t in clips))


def committed(store: Store, month: str) -> int:
    """Credits spent (settled) plus credits held by open reservations in ``month``."""
    return spend(store, month).committed


def _stamp(clip_entries: list[LedgerEntry], now: datetime) -> datetime:
    """``now``, or just after the clip's latest row if that is later (keeps replay order)."""
    latest = max((e.created_at for e in clip_entries if e.created_at is not None), default=None)
    if latest is not None and now <= latest:
        return latest + timedelta(microseconds=1)
    return now


def reserve(store: Store, clip_id: str, credits: int, now: datetime) -> LedgerEntry:
    """Hold ``credits`` for ``clip_id`` or raise ``BudgetRefused`` (nothing is written then)."""
    _check_credits(credits, "credits", minimum=1)
    month = month_key(now)
    with store.transaction():
        settings = store.get_settings()  # the row lock on PostgresStore: serialises writers
        if settings.kill_switch:
            raise BudgetRefused("kill_switch", "kill switch is on: no new reservations", month=month)
        entries = store.ledger_month(month)
        held = sum(t.settled + t.open for t in _totals(entries).values())
        cap = settings.monthly_cap_credits
        if held + credits > cap:
            raise BudgetRefused(
                "over_cap",
                f"over cap: {held} committed + {credits} requested > {cap} for {month}",
                month=month,
                cap=cap,
                committed=held,
                requested=credits,
            )
        mine = [e for e in entries if e.clip_id == clip_id]
        return store.ledger_add(
            LedgerEntry(
                clip_id=clip_id, month=month, kind="reserve", credits=credits,
                created_at=_stamp(mine, now),
            )
        )


def _months_back(now: datetime, count: int) -> Iterator[str]:
    year, month = (int(p) for p in month_key(now).split("-"))
    for _ in range(count):
        yield f"{year:04d}-{month:02d}"
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)


def _close(
    store: Store, clip_id: str, now: datetime, kind: Literal["settle", "release"], actual: int | None
) -> LedgerEntry:
    month_key(now)  # reject a naive ``now`` before touching the database
    with store.transaction():
        store.get_settings()  # row lock: a second settle of the same clip must wait and then fail
        for month in _months_back(now, LOOKBACK_MONTHS):
            mine = [e for e in store.ledger_month(month) if e.clip_id == clip_id]
            held = _totals(mine).get(clip_id, _ClipTotals()).open
            if held > 0:
                return store.ledger_add(
                    LedgerEntry(
                        clip_id=clip_id, month=month, kind=kind,
                        credits=held if actual is None else actual,
                        created_at=_stamp(mine, now),
                    )
                )
    raise NoOpenReservation(f"no open reservation for clip {clip_id}; reserve first")


def settle(store: Store, clip_id: str, actual: int, now: datetime) -> LedgerEntry:
    """Close the clip's open reservation(s) and book ``actual`` credits instead.

    Never refused, even past the cap or with the kill switch on: the credits are already spent.
    """
    _check_credits(actual, "actual", minimum=0)
    return _close(store, clip_id, now, "settle", actual)


def release(store: Store, clip_id: str, now: datetime) -> LedgerEntry:
    """Close the clip's open reservation(s) without booking any spend (generation failed)."""
    return _close(store, clip_id, now, "release", None)


def _open_in(entries: list[LedgerEntry]) -> dict[str, tuple[int, datetime | None]]:
    """Per clip of one month's rows: (credits still held, when the oldest still-open reserve was made)."""
    out: dict[str, tuple[int, datetime | None]] = {}
    for e in entries:
        held, since = out.get(e.clip_id, (0, None))
        if e.kind == "reserve":
            out[e.clip_id] = (held + e.credits, since or e.created_at)
        else:  # settle / release close everything open for the clip
            out[e.clip_id] = (0, None)
    return {clip: (held, since) for clip, (held, since) in out.items() if held > 0}


def open_reservations(store: Store, now: datetime) -> list[dict[str, Any]]:
    """Clips that still hold credits, over the last ``LOOKBACK_MONTHS`` months, oldest reservation first.

    Read-only. One row per clip: ``clip_id``, the clip's ``state`` / ``character`` / ``clip_created_at``
    (``None`` for a ledger row whose clip is gone), ``held`` credits (summed over months), ``months`` that
    hold some, ``oldest_reserved_at`` and ``age_hours`` of that reserve against ``now``. This is what
    crash recovery iterates: a reservation that nothing settled or released is in this list however the
    run died (including between ``budget reserve`` and ``clip set --credits-reserved``).
    """
    month_key(now)  # reject a naive ``now``
    held: dict[str, int] = {}
    oldest: dict[str, datetime] = {}
    months: dict[str, list[str]] = {}
    for month in sorted(_months_back(now, LOOKBACK_MONTHS)):  # oldest month first
        for clip_id, (credits, since) in _open_in(store.ledger_month(month)).items():
            held[clip_id] = held.get(clip_id, 0) + credits
            months.setdefault(clip_id, []).append(month)
            if since is not None and (clip_id not in oldest or since < oldest[clip_id]):
                oldest[clip_id] = since
    rows = []
    for clip_id, credits in held.items():
        clip = store.get_clip(clip_id)
        since = oldest.get(clip_id)
        rows.append(
            {
                "clip_id": clip_id,
                "state": clip.state.value if clip else None,
                "character": clip.character_slug if clip else None,
                "clip_created_at": clip.created_at.isoformat() if clip and clip.created_at else None,
                "held": credits,
                "months": months[clip_id],
                "oldest_reserved_at": since.isoformat() if since else None,
                "age_hours": round((now - since).total_seconds() / 3600, 1) if since else None,
            }
        )
    # by the real instants (the isoformat strings carry BST/GMT offsets that do not sort as text)
    rows.sort(key=lambda r: (r["clip_id"] not in oldest, oldest.get(r["clip_id"], now), r["clip_id"]))
    return rows


# ---- CLI -----------------------------------------------------------------------------------

EXIT_REFUSED = 3

app = typer.Typer(
    help="Credit budget: reserve, settle, release, cap, kill switch. "
    "Prints JSON; exit 3 = refused (cap / kill switch), 2 = caller error.",
    no_args_is_help=True,
)


def _entry_json(e: LedgerEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "clip_id": e.clip_id,
        "month": e.month,
        "kind": e.kind,
        "credits": e.credits,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@app.command("status")
def status_command(
    month: Annotated[
        str | None, typer.Option(help="YYYY-MM (Europe/London); default: the current month.")
    ] = None,
) -> None:
    """Cap, committed credits (settled + reserved) and kill switch for a month."""
    if month is not None and not _MONTH.fullmatch(month):
        raise typer.BadParameter(f"expected YYYY-MM, got {month!r}", param_hint="--month")
    store = open_store()
    month = month or month_key(now_london())
    settings = store.get_settings()
    held = spend(store, month)
    emit(
        {
            "month": month,
            "cap": settings.monthly_cap_credits,
            "committed": held.committed,
            "settled": held.settled,
            "reserved": held.reserved,
            "remaining": max(settings.monthly_cap_credits - held.committed, 0),
            "kill_switch": settings.kill_switch,
        }
    )


@app.command("reserve")
def reserve_command(
    credits: Annotated[int, typer.Argument(min=1, help="Credits to hold.")],
    clip: Annotated[str, typer.Option("--clip", help="Clip id.")],
) -> None:
    """Hold credits for a clip before generating. Exit 3 if the cap or kill switch refuses."""
    store = open_store()
    if store.get_clip(clip) is None:
        fail(f"unknown clip {clip}")
    try:
        entry = reserve(store, clip, credits, now_london())
    except BudgetRefused as e:
        emit(
            {
                "ok": False,
                "refused": e.reason,
                "message": str(e),
                "month": e.month,
                "cap": e.cap,
                "committed": e.committed,
                "requested": e.requested,
            }
        )
        raise typer.Exit(EXIT_REFUSED) from e
    emit(_entry_json(entry))


@app.command("settle")
def settle_command(
    clip: Annotated[str, typer.Argument(help="Clip id.")],
    actual: Annotated[int, typer.Argument(min=0, help="Real cost in credits.")],
) -> None:
    """Replace the clip's reservation with the real cost."""
    try:
        entry = settle(open_store(), clip, actual, now_london())
    except NoOpenReservation as e:
        fail(str(e))
    emit(_entry_json(entry))


@app.command("release")
def release_command(clip: Annotated[str, typer.Argument(help="Clip id.")]) -> None:
    """Free the clip's reservation (generation failed; nothing was spent)."""
    try:
        entry = release(open_store(), clip, now_london())
    except NoOpenReservation as e:
        fail(str(e))
    emit(_entry_json(entry))


@app.command("open")
def open_command() -> None:
    """List clips that still hold credits (read-only JSON): id, state, held, oldest reserve time, age.

    Crash recovery walks this list: a clip here that is over 2 h old was left by a run that died.
    """
    emit(open_reservations(open_store(), now_london()))

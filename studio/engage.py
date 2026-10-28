"""``studio engage``: the daily comment drafts (owner 2026-10-28; no migration, no money).

**Why.** The three live Instagram characters need reach and the studio has no video credits. Every day the daily run drafts about
5 in-character comments per character for big accounts in that character's niche; the owner posts them BY HAND from the
character's own account (about 10 minutes). **We never reply ourselves**: nothing here, and nothing in the skill that calls it,
posts, likes, follows or sends anything. The drafts are text in the database and a card on the terminal's Today page.

**Targets** (``engage targets``). Two sources, merged: the stored hits first, then the curated list. The **hits** are
``studio.hits`` rows (the cloud hits job) of platform ``instagram`` with that character's ``character_slug`` and a
``creator_handle``, one per distinct handle (case and a leading ``@`` do not matter). Their order is the handle's followers, highest
first (the largest number any of its hits carries). **Instagram's search gives no follower count** (verified 2026-10-28: all 42
stored Instagram hits have ``followers`` null), so the handles that tie on it, which today is all of them, are ordered by their best
hit's score (``studio.hits.hit_score``: likes, freshness), then by handle, so the same day always gives the same list. The ``url``
and ``caption`` of a hit target come from the handle's best-known hit (highest score, then newest). The **curated list**
(``config/engage.json``, owner 2026-10-28: the hits job ran dry and Franz had 4 handles) follows in the file's order: real Instagram
creators per character, each with a one-line note on why it fits. A curated target has ``followers``, ``url`` and ``caption`` null
(the daily run looks its post up); a handle that is in both lists is a hit target only. ``load_curated`` validates the file (a
character that is not in ``characters/``, a handle with ``@``, a space or any character Instagram does not allow, a duplicate, a
missing note: refused with every problem listed, and ``engage targets`` exits 2); an absent file is an empty list. A handle drafted
for that character on any of the 7 days BEFORE today is skipped, whichever list it comes from, so an account is not commented on
again within a week. Today's own drafts do not count: a second run on the same day picks the same targets and its ``save`` replaces
the first.

**Drafts** (``engage save FILE``). ``{"drafts": [{"character", "handle", "post_url", "comment"}]}``, written by the skill from
``keyword_posts`` (the post the comment reacts to), the hit's url or, for a curated account with no post found, its profile link. The whole file is refused (exit 2, nothing
written, every problem listed) when a character is not live, a handle or ``post_url`` is not usable, a comment is empty or longer
than 200 characters, carries a link, a hashtag or one of OUR accounts' handles (with or without ``@``), or promotes anything
("follow", "check my page", "link in bio", ...). That is the mechanical part of the rules; the voice and kindness are the skill's.

**Storage.** One ``studio.runs`` row of kind ``comment_drafts`` per London day (``started_at`` = noon London of that day, like
``account_daily``), ``details = {"day": "YYYY-MM-DD", "drafts": [{character, handle, post_url, comment}]}``, updated in place.
Saving again the same day replaces that day's drafts of the characters in the file and keeps the other characters' drafts. Health
and the weekly review ignore it; the terminal's Today card "Comments to post today" reads it.

CLI (``studio engage ...``) prints JSON on stdout; exit 0 normally, exit 2 for anything the caller must fix.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import typer

from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, now_london
from studio.models import Platform, Run, RunKind, RunStatus
from studio.store import Store

ROOT = Path(__file__).resolve().parents[1]
ENGAGE_PATH = ROOT / "config" / "engage.json"  # read at call time: tests point it elsewhere (conftest)
CHARACTERS_DIR = ROOT / "characters"

DEFAULT_TARGETS = 5  # targets per character per day
SKIP_DAYS = 7  # a handle drafted on any of the 7 days before today is not a target again
MAX_COMMENT_CHARS = 200
DRAFT_FIELDS = ("character", "handle", "post_url", "comment")

_INSTAGRAM_HANDLE = re.compile(r"[A-Za-z0-9._]{1,30}")  # what Instagram allows in a username
_LINK = re.compile(
    r"(?i)(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|co|uk|me|ly|app|tv|gg|xyz|link|bio|shop|store|page|site|online|info|dev)\b)"
)
_HASHTAG = re.compile(r"(?<!\w)#\w")
_SELF_PROMOTION = re.compile(
    r"(?i)\bfollow|\blink in (?:my |the )?bio\b|\bcheck (?:out )?(?:my|our|the) (?:page|profile|account|bio|channel|reels?|videos?)\b"
    r"|\b(?:visit|see) my (?:page|profile|account|bio|channel)\b|\b(?:dm|message) me\b|\bsubscribe\b"
)


def _key(handle: str) -> str:
    """A handle for comparing: no ``@``, no spaces, lower case."""
    return handle.strip().lstrip("@").strip().lower()


def _day_rows(store: Store) -> dict[str, Run]:
    """The ``comment_drafts`` rows by their London day; the oldest row of a day is its row."""
    rows: dict[str, Run] = {}
    for r in store.list_runs(kind=RunKind.comment_drafts):
        if isinstance(r.details, dict) and isinstance(r.details.get("day"), str):
            rows.setdefault(r.details["day"], r)
    return rows


def _drafts_of(row: Run | None) -> list[dict[str, Any]]:
    held = row.details.get("drafts") if row is not None and isinstance(row.details, dict) else None
    return [d for d in held if isinstance(d, dict)] if isinstance(held, list) else []


def live_characters(store: Store) -> set[str]:
    return {c.slug for c in store.characters() if c.status == "live"}


def drafted_recently(store: Store, character: str, today: date) -> set[str]:
    """The handle keys drafted for ``character`` on the ``SKIP_DAYS`` London days before ``today`` (today itself is not included)."""
    first = today - timedelta(days=SKIP_DAYS)
    out: set[str] = set()
    for day, row in _day_rows(store).items():
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        if first <= d < today:
            out.update(_key(str(x.get("handle") or "")) for x in _drafts_of(row) if x.get("character") == character)
    out.discard("")
    return out


def handle_problem(handle: Any) -> str | None:
    """Why ``handle`` cannot be in ``config/engage.json`` (``None`` = fine): a bare Instagram username, no ``@``, no spaces."""
    if not isinstance(handle, str) or not handle:
        return "handle is missing or empty"
    if "@" in handle:
        return f"handle {handle!r} must be written without @ (as {handle.replace('@', '').strip()!r})"
    if any(c.isspace() for c in handle):
        return f"handle {handle!r} must not contain spaces"
    if not _INSTAGRAM_HANDLE.fullmatch(handle):
        return f"handle {handle!r} is not an Instagram username (letters, digits, . and _ only, 1 to 30 characters)"
    return None


def load_curated(path: Path | str | None = None, characters_dir: Path | str | None = None) -> dict[str, list[dict[str, str]]]:
    """The curated target list ``{character: [{"handle", "note"}, ...]}`` in the file's order, from ``config/engage.json`` (an
    absent file: ``{}``; keys starting with ``_``, like ``_doc``, are comments). ``ValueError`` listing every problem for a file that
    is not JSON, a character that is not in ``characters/``, a handle with ``@``, a space or any character Instagram does not allow,
    a duplicate handle for one character (case does not matter), a missing note, an unknown key or a list that is not one of
    objects."""
    where = Path(path or ENGAGE_PATH)
    try:
        raw = json.loads(where.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:  # ValueError: invalid JSON and UnicodeDecodeError
        raise ValueError(f"config/engage.json: cannot read it: {getattr(e, 'strerror', None) or e}") from None
    if not isinstance(raw, Mapping):
        raise ValueError(f'config/engage.json must be an object {{"franz": [{{"handle", "note"}}, ...], ...}}, got {type(raw).__name__}')
    known = {p.parent.name for p in Path(characters_dir or CHARACTERS_DIR).glob("*/refs.json")}
    problems: list[str] = []
    curated: dict[str, list[dict[str, str]]] = {}
    for slug, entries in raw.items():
        if slug.startswith("_"):
            continue
        if slug not in known:
            problems.append(f"{slug!r} is not a character (known: {', '.join(sorted(known))})")
            continue
        if not isinstance(entries, list):
            problems.append(f'{slug}: must be a list of {{"handle", "note"}} objects')
            continue
        first: dict[str, int] = {}  # handle key -> the number of its first entry
        clean: list[dict[str, str]] = []
        for i, entry in enumerate(entries, start=1):
            label = f"{slug} #{i}"
            if not isinstance(entry, Mapping):
                problems.append(f'{label}: must be an object {{"handle", "note"}}')
                continue
            if extra := sorted(str(k) for k in entry if k not in ("handle", "note")):
                problems.append(f"{label}: unknown key {', '.join(extra)} (only handle and note)")
            handle, note = entry.get("handle"), entry.get("note")
            ok = True
            if found := handle_problem(handle):
                problems.append(f"{label}: {found}")
                ok = False
            elif (key := _key(handle)) in first:
                problems.append(f"{label}: {handle!r} is a duplicate of {slug} #{first[key]}")
                ok = False
            else:
                first[key] = i
            if not isinstance(note, str) or not note.strip():
                problems.append(f"{label}: note is missing (one line on why the account fits)")
                ok = False
            if ok:
                clean.append({"handle": handle, "note": note.strip()})
        curated[slug] = clean
    if problems:
        raise ValueError("config/engage.json: " + "; ".join(problems))
    return curated


def pick_targets(
    store: Store, character: str, n: int = DEFAULT_TARGETS, *, today: date, curated: dict[str, list[dict[str, str]]] | None = None
) -> list[dict[str, Any]]:
    """Today's target accounts for ``character``: ``[{handle, followers, url, caption}]``, at most ``n``: the stored hits first, then
    the curated list (see the module docstring). ``curated`` defaults to ``load_curated()`` (``ValueError`` for a broken file)."""
    if curated is None:
        curated = load_curated()
    skip = drafted_recently(store, character, today)
    by_handle: dict[str, list[Any]] = {}
    for hit in store.list_hits(character_slug=character):
        key = _key(hit.creator_handle or "")
        if hit.platform is Platform.instagram and key and key not in skip:
            by_handle.setdefault(key, []).append(hit)
    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for key, rows in by_handle.items():
        best = max(rows, key=lambda h: (h.score, h.posted_at.timestamp() if h.posted_at else 0.0))
        followers = max((h.followers for h in rows if h.followers), default=None)
        target = {"handle": best.creator_handle, "followers": followers, "url": best.url, "caption": best.caption}
        ranked.append(((followers is None, -(followers or 0), -best.score, key), target))
    targets = [t for _, t in sorted(ranked, key=lambda x: x[0])]
    taken = set(by_handle) | skip  # a hit is not listed twice, and a handle drafted this week is not listed at all
    for entry in curated.get(character, []):
        if (key := _key(entry["handle"])) not in taken:
            taken.add(key)
            targets.append({"handle": f"@{entry['handle']}", "followers": None, "url": None, "caption": None})
    return targets[:n]


def draft_problems(draft: Any, live: set[str], own: set[str]) -> list[str]:
    """Why one draft is refused (an empty list = fine). ``own`` = the handle keys of our own accounts."""
    if not isinstance(draft, dict):
        return ["is not an object"]
    problems: list[str] = []
    values = {f: draft.get(f) for f in DRAFT_FIELDS}
    for field, value in values.items():
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{field} is missing or empty")
    if problems:
        return problems
    character, handle, post_url, comment = (values[f].strip() for f in DRAFT_FIELDS)  # type: ignore[union-attr]
    if character not in live:
        problems.append(f"character {character!r} is not live")
    if not _key(handle):
        problems.append("handle is empty")
    parts = urlparse(post_url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host == "instagram.com" or host.endswith(".instagram.com")):
        problems.append(f"post_url must be an https://instagram.com link, got {post_url!r}")
    if len(comment) > MAX_COMMENT_CHARS:
        problems.append(f"comment is {len(comment)} characters, the limit is {MAX_COMMENT_CHARS}")
    if _LINK.search(comment):
        problems.append("comment contains a link")
    if _HASHTAG.search(comment):
        problems.append("comment contains a hashtag")
    lowered = comment.lower()
    if mine := sorted(h for h in own if h and h in lowered):
        problems.append(f"comment names our own account ({', '.join('@' + h for h in mine)})")
    if promo := _SELF_PROMOTION.search(comment):
        problems.append(f"comment is self-promotion ({promo.group(0).strip()!r})")
    return problems


def save_drafts(store: Store, drafts: Any, now: datetime) -> dict[str, Any]:
    """Validate ``drafts`` (every one, nothing is written when any is refused: ``ValueError`` listing every problem), then write
    today's row: the characters in ``drafts`` are replaced, the other characters' drafts of the day are kept."""
    if not isinstance(drafts, list) or not drafts:
        raise ValueError('expected {"drafts": [{"character", "handle", "post_url", "comment"}, ...]} with at least one draft')
    live = live_characters(store)
    own = {k for a in store.accounts() if (k := _key(a.handle))}
    problems: list[str] = []
    clean: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i, draft in enumerate(drafts, start=1):
        label = f"draft {i}" + (f" ({draft.get('character')} {draft.get('handle')})" if isinstance(draft, dict) else "")
        found = draft_problems(draft, live, own)
        if not found:
            who = (draft["character"].strip(), _key(draft["handle"]))
            if who in seen:
                found = ["a second draft for the same account (one comment per account a day)"]
            seen.add(who)
        problems += [f"{label}: {p}" for p in found]
        if not found:
            handle = draft["handle"].strip()
            clean.append({
                "character": draft["character"].strip(), "handle": handle if handle.startswith("@") else f"@{handle}",
                "post_url": draft["post_url"].strip(), "comment": draft["comment"].strip(),
            })  # fmt: skip
    if problems:
        raise ValueError("; ".join(problems))
    today = now.astimezone(LONDON).date()
    day = today.isoformat()
    row = _day_rows(store).get(day)
    replaced = {d["character"] for d in clean}
    kept = [d for d in _drafts_of(row) if d.get("character") not in replaced]
    all_drafts = [*kept, *clean]
    totals: dict[str, int] = {}
    for d in all_drafts:
        totals[str(d.get("character"))] = totals.get(str(d.get("character")), 0) + 1
    details = {"day": day, "drafts": all_drafts}
    summary = f"Comment drafts for {day}: " + ", ".join(f"{c} {n}" for c, n in totals.items())
    if row is not None:
        store.update_run(row.id, details=details, finished_at=now, summary=summary)
    else:
        store.add_run(
            Run(
                kind=RunKind.comment_drafts, status=RunStatus.ok, started_at=datetime.combine(today, time(12, 0), tzinfo=LONDON),
                finished_at=now, summary=summary, details=details,
            )
        )
    saved: dict[str, int] = {}
    for d in clean:
        saved[d["character"]] = saved.get(d["character"], 0) + 1
    return {"day": day, "saved": saved, "kept": {c: n for c, n in totals.items() if c not in saved}, "total": len(all_drafts)}


# ---- CLI ------------------------------------------------------------------------------------------

app = typer.Typer(
    help="Daily comment drafts: the accounts to comment on, the drafts the daily run writes, today's list. The owner posts them by "
    "hand; nothing here posts. Prints JSON; exit 2 = something to fix.",
    no_args_is_help=True,
)


@app.command("targets")
def targets_command(
    character: Annotated[str, typer.Option("--character", help="A live character's slug (franz, reginald, lenny).")],
    n: Annotated[int, typer.Option("-n", "--n", min=1, help="At most this many accounts.")] = DEFAULT_TARGETS,
) -> None:
    """Today's target Instagram accounts for CHARACTER: the stored hits first, then the curated list in config/engage.json (see the
    module docstring). A JSON list of {handle, followers, url, caption}: followers is null when Instagram gave none, and url and
    caption are null for a curated account. Accounts drafted for him in the last 7 days are left out. Exit 2 for a character that is
    not live or a config/engage.json that is broken."""
    store = open_store()
    if character not in live_characters(store):
        fail(f"character {character!r} is not live")
    try:
        emit(pick_targets(store, character, n, today=now_london().astimezone(LONDON).date()))
    except ValueError as e:
        fail(str(e))


@app.command("save")
def save_command(
    file: Annotated[Path, typer.Argument(metavar="FILE", help='JSON {"drafts": [{"character", "handle", "post_url", "comment"}]}.')],
) -> None:
    """Store today's drafts from FILE (written with the Write tool). Refused with exit 2, and nothing written, when a character is
    not live, a comment is empty, over 200 characters, has a link, a hashtag, one of our own handles or self-promotion."""
    try:
        payload = json.loads(file.expanduser().read_text(encoding="utf-8"))
    except OSError as e:
        fail(f"cannot read {str(file)!r}: {e.strerror or e}")
    except ValueError as e:  # includes UnicodeDecodeError
        fail(f"not valid JSON: {e}")
    drafts = payload.get("drafts") if isinstance(payload, dict) else None
    store = open_store()
    try:
        emit(save_drafts(store, drafts, now_london()))
    except ValueError as e:
        fail(str(e))


@app.command("show")
def show_command(
    day: Annotated[str | None, typer.Option("--day", help="A London day, YYYY-MM-DD (default: today).")] = None,
) -> None:
    """The drafts of a day: {"day", "drafts": [...]} (an empty list when none were saved)."""
    if day is None:
        wanted = now_london().astimezone(LONDON).date().isoformat()
    else:
        try:
            wanted = date.fromisoformat(day).isoformat()
        except ValueError:
            fail(f"--day must be a date like 2026-10-28, got {day!r}")
    emit({"day": wanted, "drafts": _drafts_of(_day_rows(open_store()).get(wanted))})

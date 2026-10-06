"""``studio seed``: put the characters, their accounts and the batch-1 Viral Picks into the database.

**Characters and accounts** (``studio seed``) come from ``characters/<slug>/refs.json``:

* ``seed_characters`` validates every file first (all or nothing), then upserts each character
  (``slug``, ``name``, ``status``, ``bodies``) and its accounts in one transaction.
* ``status`` (``designing`` | ``live`` | ``paused``, default ``designing``) is read from the file, so going
  live is one edit plus a re-seed. The daily run skips every character that is not ``live``.
* An account with no ``handle`` yet is **skipped** (``accounts.handle`` is NOT NULL) and reported. One with a
  handle is upserted on ``(character_slug, platform)``: a new row gets ``dropin_share`` explicitly (the file's
  value, else the platform default, TikTok 0.70 / Instagram 0.40: the database default would be 0.7 for
  both); an existing row only has its identity (``handle``, ``postiz_integration_id``) refreshed, so a
  re-seed never undoes what the Instagram guard or the autopilot toggle set (``dropin_share``, ``mode``).
  An account with no ``postiz_integration_id`` is seeded but planning treats it as not connected.
* ``setup`` (``characters.setup``, migration 0007) is what the terminal's Characters page shows beside the
  accounts: ``{"closeup": <the close-up shot exists>, "planned_handles": {"tiktok": .., "instagram": ..}}``.
  A planned handle is the account's real ``handle`` once it exists, else the file's optional
  ``planned_handle`` (the first choice of ``docs/launch/social-pages.md``), else null.
* ``traits`` (optional) is the character's trait card: ``energy`` and ``comedy`` and ``music`` (one short phrase
  each) and the lists ``best_formats``, ``settings``, ``moves``, ``props`` and ``never`` (short phrases). Every
  key is required once a card is given and no other key is allowed. The seed copies it into
  ``characters.setup.traits`` (no migration: ``setup`` is jsonb): the terminal shows it as the Traits card, the
  ``props`` become the Make-it sheet's "Gadgets & jewellery" chips (each is a phrase or ``{"name", "job"}``, the
  job being what the gadget does for virality, shown as the chip's hint), and the daily run scores a pick's ``fit``
  against it. A re-seed replaces the card.
* ``sheets`` (optional) maps a body (``biped`` / ``quadruped``, one of the character's ``bodies``) to the Higgsfield job
  id of its character sheet: the daily run passes the matching sheet to Genjutsu as a reference image together with the
  master (Higgsfield best practice). The seed copies it into ``characters.setup.sheets``; ``masters`` and ``closeup``
  are the owner's and are not touched by it.
* ``reference_urls`` (optional, "Drop a video", plan 2026-10-06) are the public Higgsfield CDN URLs of the character's
  images, the ``image_urls`` the cloud Object swap is given: ``master_<body>`` and ``sheet_<body>`` for any of the
  character's ``bodies`` and ``closeup``, each an https URL (validated here, never fetched by the CLI). ``reference_images``
  picks the set for a swap: the master and the sheet of the star's body, then the close-up.
* ``swap`` (optional) is the like-for-like rule of the Object swap: ``noun`` (what the prompt calls him: "butler", "dog") and
  ``stars`` (the kinds of star he may replace: ``person``, ``dog``, ``animal``). Reginald replaces a person, Biscuit a dog or a
  small animal, never a dog for a person (Genjutsu then inserts the dog and keeps the people).
* ``dropin_share`` is the first-insert value of a new account row (owner decision 2026-10-05: ``characters/*/refs.json``
  ships 1.00 for every account, Drop-in is the default for every video); the controller updates live rows.
* ``studio seed status`` prints every character with its status, traits and accounts (what the daily run reads).

**Picks** (``studio seed picks FILE``) loads ``docs/launch/viral-picks-2026-10-04.md``. The document is
the single source: its tables are parsed, nothing is duplicated into code, and the parse is checked rather
than trusted. ``parse_picks`` raises ``ValueError``, before anything is written, when

* a pick lacks a row in any of the three tables (picks, scores, decisions), or a table row is garbled,
* a scored total is not the one the rubric (``favorites.score_pick``) computes from the row's own numbers,
* a decision is unknown, an ``(auto)`` / ``(analyst)`` marker disagrees with the total, a rule approval
  would not pass the standing rule (feasibility under 7), or a hold and the pick's ``needs`` disagree.

How a row becomes a pick: ``url``, ``platform`` and ``creator`` (the handle in the note, else the TikTok
URL's), ``views`` and ``outlier_x`` (``43.4M · 1,393×``), the four judged sub-scores and the total, and a
``proposal`` with ``mode`` (``dropin`` | ``recreate``; the talking-lane table has none and none is
invented), ``mode_note``, ``hook``, ``prop`` (``—`` means none), ``concept`` (the "Our version" cell),
``button_line`` (Outsider), ``enhancement`` (only for a pick with a row of its own in the decisions table;
a shared row holds an order note, not an enhancement) and ``needs``: ``multi_body`` when the Mode cell
names 2+ bodies, ``talking_lane`` for the talking-lane table.

Decisions as recorded in the document: approved picks are ``approved`` with the document's "Why" as the
reason, ``by='rule'`` for a total of 80 or more and ``by='analyst'`` below. Held picks stay ``new`` with
``proposal['hold_reason']`` (the rule holds anything with a ``needs``).

**Idempotent.** A URL already in the list is left as it is, and a decision is recorded only on a pick that is
still ``new`` and has none, so a re-run changes nothing: an owner's skip or a later approval is never undone.
Picks are filed in the document's rank order, one transaction each: the database stamps ``created_at`` per
transaction, so the production queue (oldest first) then follows the rank (each character starts with its
best pick), and a run that dies half way is simply re-run. A pick whose character is not seeded (the
Outsider) is stored with no ``character_slug`` and ``proposal['intended_character']``.

CLI prints JSON on stdout; exit 2 for anything the caller must fix.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import typer

from studio.cli_support import emit, fail, open_store
from studio.favorites import add_pick, decide, parse_video_url, score_pick
from studio.models import DEFAULT_DROPIN_SHARE, Account, Body, Character, Platform
from studio.store import Store

# The characters folder is resolved from the package location, never from the working directory.
DEFAULT_CHARACTERS_DIR = Path(__file__).resolve().parents[1] / "characters"
CHARACTER_STATUSES = ("designing", "live", "paused")
TRAIT_TEXT_KEYS = ("energy", "comedy", "music")
TRAIT_LIST_KEYS = ("best_formats", "settings", "moves", "props", "never")
TRAIT_TEXT_MAX = 160
TRAIT_ITEM_MAX = 80
TRAIT_PROP_MAX = 40  # a prop becomes a Make-it chip, and an owner prop is at most 40 characters
TRAIT_JOB_MAX = 120
TRAIT_LIST_MAX = 8
TRAIT_PROPS_MAX = 12
REFERENCE_URL_MAX = 2048
SWAP_STARS = ("person", "dog", "animal")  # the kinds of star a drop can name (studio.drop reads the clip's star into one)
SWAP_NOUN_MAX = 40

RULE_MIN_TOTAL = 80  # `by` is the rule from this total up (spec 4.4b), the analyst below
RULE_MIN_FEASIBILITY = 7


# ---- characters and accounts -------------------------------------------------------------------


def _require(cond: bool, path: Path, message: str) -> None:
    if not cond:
        raise ValueError(f"{path}: {message}")


def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_https_url(value: Any) -> bool:
    """An https URL with a host, no whitespace, at most ``REFERENCE_URL_MAX`` characters (only stored and handed on)."""
    if not isinstance(value, str) or not value or len(value) > REFERENCE_URL_MAX or re.search(r"\s", value):
        return False
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.hostname)


def reference_images(ref: dict[str, Any], body: Body | str) -> list[str]:
    """The ``image_urls`` of an Object swap for this star's ``body``: the master and the sheet of that body, then the
    close-up (those present, in that order). ``ValueError`` when the character has no master URL for the body."""
    body = Body(body).value
    urls = ref.get("reference_urls") or {}
    if body not in ref.get("bodies", []):
        raise ValueError(f"{ref.get('slug')} has no {body} body (bodies: {', '.join(ref.get('bodies', []))})")
    master = urls.get(f"master_{body}")
    if not master:
        raise ValueError(f"characters/{ref.get('slug')}/refs.json has no reference_urls.master_{body}")
    return [u for u in (master, urls.get(f"sheet_{body}"), urls.get("closeup")) if u]


def _is_prop(item: Any) -> bool:
    """A prop is a phrase, or ``{"name", "job"}``: the name is the Make-it chip, the job says what it is for (viral job)."""
    if _is_str(item):
        return True
    return (
        isinstance(item, dict) and set(item) == {"name", "job"}
        and _is_str(item["name"]) and _is_str(item["job"]) and len(item["job"]) <= TRAIT_JOB_MAX
    )


def _item_fits(item: Any, limit: int) -> bool:
    return len(item["name"] if isinstance(item, dict) else item) <= limit


def prop_names(traits: dict[str, Any]) -> list[str]:
    """The names of a traits card's props, whichever shape each one has (the Make-it chips)."""
    return [p["name"] if isinstance(p, dict) else p for p in traits.get("props", [])]


def _validate_traits(traits: Any, path: Path) -> None:
    _require(isinstance(traits, dict), path, "traits must be an object")
    keys = (*TRAIT_TEXT_KEYS, *TRAIT_LIST_KEYS)
    unknown = sorted(set(traits) - set(keys))
    _require(not unknown, path, f"traits has unknown key(s) {', '.join(unknown)}; allowed: {', '.join(keys)}")
    for key in TRAIT_TEXT_KEYS:
        value = traits.get(key)
        _require(
            _is_str(value) and len(value) <= TRAIT_TEXT_MAX, path,
            f"traits.{key} must be a short phrase (1-{TRAIT_TEXT_MAX} characters), got {value!r:.60}",
        )
    for key in TRAIT_LIST_KEYS:
        items = traits.get(key)
        limit = TRAIT_PROP_MAX if key == "props" else TRAIT_ITEM_MAX
        most = TRAIT_PROPS_MAX if key == "props" else TRAIT_LIST_MAX
        ok = (
            isinstance(items, list) and 1 <= len(items) <= most
            and all((_is_prop(i) if key == "props" else _is_str(i)) and _item_fits(i, limit) for i in items)
        )
        extra = " or {name, job} objects" if key == "props" else ""
        _require(
            ok, path,
            f"traits.{key} must be a list of 1-{most} short phrases{extra} (at most {limit} characters each"
            f"{f', a job at most {TRAIT_JOB_MAX}' if key == 'props' else ''}), got {items!r:.60}",
        )


def _validate_ref(ref: Any, path: Path) -> dict[str, Any]:
    _require(isinstance(ref, dict), path, "must be a JSON object")
    ref = dict(ref)
    folder = path.parent.name
    _require(ref.get("slug") == folder, path, f"slug {ref.get('slug')!r} must match the folder name {folder!r}")
    _require(_is_str(ref.get("name")), path, "name must be a non-empty string")
    ref["status"] = ref.get("status", "designing")
    _require(ref["status"] in CHARACTER_STATUSES, path, f"status must be one of {CHARACTER_STATUSES}, got {ref['status']!r}")

    bodies = ref.get("bodies")
    allowed = [b.value for b in Body]
    _require(
        isinstance(bodies, list) and bool(bodies) and len(set(bodies)) == len(bodies)
        and all(b in allowed for b in bodies),
        path, f"bodies must be a non-empty list without repeats from {allowed}, got {bodies!r}",
    )
    masters = ref.get("masters")
    _require(isinstance(masters, dict), path, "masters must be an object of body -> Higgsfield job id")
    for body in bodies:
        _require(_is_str(masters.get(body)), path, f"the {body} master (masters.{body}) is missing")
    _require(ref.get("closeup") is None or _is_str(ref["closeup"]), path, "closeup must be a job id or null")
    for key in ("closeup_center", "blue_eye_xy"):
        value = ref.get(key)
        _require(
            value is None
            or (isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)),
            path, f"{key} must be [x, y] or null, got {value!r}",
        )

    if ref.get("traits") is not None:
        _validate_traits(ref["traits"], path)
    sheets = ref.get("sheets")
    if sheets is not None:
        _require(isinstance(sheets, dict), path, "sheets must be an object of body -> Higgsfield job id")
        for body, job in sheets.items():
            _require(body in bodies, path, f"sheets.{body}: not one of this character's bodies {bodies}")
            _require(_is_str(job), path, f"sheets.{body} must be a Higgsfield job id")

    urls = ref.get("reference_urls")
    if urls is not None:
        _require(isinstance(urls, dict), path, "reference_urls must be an object of image name -> https URL")
        allowed = {"closeup", *(f"{kind}_{body}" for kind in ("master", "sheet") for body in bodies)}
        for name, url in urls.items():
            _require(
                name in allowed, path,
                f"reference_urls.{name}: not one of {', '.join(sorted(allowed))} (master_<body> / sheet_<body> of this "
                "character's bodies, closeup)",
            )
            _require(is_https_url(url), path, f"reference_urls.{name} must be an https URL, got {url!r:.80}")
    swap = ref.get("swap")
    if swap is not None:
        ok = (
            isinstance(swap, dict) and set(swap) == {"noun", "stars"}
            and _is_str(swap["noun"]) and len(swap["noun"]) <= SWAP_NOUN_MAX
            and isinstance(swap["stars"], list) and bool(swap["stars"])
            and len(set(swap["stars"])) == len(swap["stars"]) and all(s in SWAP_STARS for s in swap["stars"])
        )
        _require(
            ok, path,
            f"swap must be {{noun: 1-{SWAP_NOUN_MAX} characters, stars: a list from {', '.join(SWAP_STARS)}}}, got {swap!r:.80}",
        )

    accounts = ref.get("accounts", [])
    _require(isinstance(accounts, list), path, "accounts must be a list")
    seen: set[str] = set()
    for a in accounts:
        _require(isinstance(a, dict), path, "every account must be an object")
        platform = a.get("platform")
        _require(platform in [p.value for p in Platform], path, f"account platform must be tiktok or instagram, got {platform!r}")
        _require(platform not in seen, path, f"platform {platform} is listed twice (one account per platform)")
        seen.add(platform)
        _require(a.get("handle") is None or _is_str(a["handle"]), path, f"{platform} handle must be a string or null")
        _require(
            a.get("planned_handle") is None or _is_str(a["planned_handle"]),
            path, f"{platform} planned_handle must be a string or null",
        )
        _require(
            a.get("postiz_integration_id") is None or _is_str(a["postiz_integration_id"]),
            path, f"{platform} postiz_integration_id must be a string or null",
        )
        share = a.get("dropin_share")
        _require(
            share is None or (isinstance(share, (int, float)) and not isinstance(share, bool) and 0 <= share <= 1),
            path, f"{platform} dropin_share must be between 0 and 1 or null, got {share!r}",
        )
    return ref


def load_refs(characters_dir: Path | str = DEFAULT_CHARACTERS_DIR) -> list[dict[str, Any]]:
    """Every ``<dir>/<slug>/refs.json``, validated, sorted by slug. ``ValueError`` names the file."""
    base = Path(characters_dir)
    found = sorted(base.glob("*/refs.json"))
    if not found:
        raise ValueError(f"no refs.json found under {base}/<slug>/")
    loaded = []
    for path in found:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"{path}: cannot read refs.json: {e}") from None
        loaded.append(_validate_ref(raw, path))
    return loaded


def character_setup(ref: dict[str, Any]) -> dict[str, Any]:
    """``characters.setup`` for a validated refs.json: the close-up flag, the planned handle per platform and the traits card."""
    planned: dict[str, str | None] = {p.value: None for p in Platform}
    for a in ref.get("accounts", []):
        planned[a["platform"]] = a.get("handle") or a.get("planned_handle")
    setup: dict[str, Any] = {"closeup": bool(ref.get("closeup")), "planned_handles": planned}
    if ref.get("traits") is not None:
        setup["traits"] = {k: ref["traits"][k] for k in (*TRAIT_TEXT_KEYS, *TRAIT_LIST_KEYS)}
    if ref.get("sheets") is not None:
        setup["sheets"] = dict(ref["sheets"])
    return setup


@dataclass
class SeedReport:
    characters: list[Character] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def seed_characters(store: Store, characters_dir: Path | str = DEFAULT_CHARACTERS_DIR) -> SeedReport:
    """Upsert every character and account of ``characters_dir`` (all or nothing). See the module doc."""
    refs = load_refs(characters_dir)  # validates every file before the first write
    report = SeedReport()
    with store.transaction():
        for ref in refs:
            slug = ref["slug"]
            report.characters.append(
                store.upsert_character(
                    Character(
                        slug=slug, name=ref["name"], status=ref["status"], bodies=ref["bodies"],
                        setup=character_setup(ref),
                    )
                )
            )
            for a in ref.get("accounts", []):
                if a.get("handle") is None:
                    report.skipped.append(
                        {
                            "character": slug,
                            "platform": a["platform"],
                            "reason": "no handle yet (fill it in refs.json once the account exists)",
                        }
                    )
                    continue
                platform = Platform(a["platform"])
                share = a.get("dropin_share")
                report.accounts.append(
                    store.upsert_account(
                        Account(
                            character_slug=slug,
                            platform=platform,
                            handle=a["handle"],
                            postiz_integration_id=a.get("postiz_integration_id"),
                            dropin_share=DEFAULT_DROPIN_SHARE[platform] if share is None else float(share),
                        )
                    )
                )
    return report


def _account_json(a: Account) -> dict[str, Any]:
    return {
        "platform": a.platform.value,
        "handle": a.handle,
        "connected": bool(a.postiz_integration_id),
        "mode": a.mode,
        "dropin_share": a.dropin_share,
    }


# ---- batch-1 picks: reading the document ---------------------------------------------------------


@dataclass(frozen=True)
class PickRow:
    id: str  # the document's id (D1, B1, O1 ...), not stored
    rank: int
    url: str  # canonical
    platform: str
    creator: str | None
    views: int
    outlier_x: float
    character: str  # as named in the document (it may not be seeded)
    judged: dict[str, float]
    total: int
    proposal: dict[str, Any]
    decision: str  # approve | hold
    by: str  # rule | analyst (approve); rule (hold)
    reason: str


_ID = re.compile(r"[A-Z]\d+")
_SEPARATOR = re.compile(r"\|[\s:\-|]+\|")
_UNITS = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
_VIEWS = re.compile(r"([\d.,]+)\s*([KMB]?)\s*·\s*([\d.,]+)\s*×")
_ORIGINAL = re.compile(r"(https?://\S+?)(?:\s*\((.*)\))?")
_HANDLE = re.compile(r"@[A-Za-z0-9_.]+")
_BODIES = re.compile(r"(\d+)(?:\s*[–-]\s*\d+)?\s+bodies")
_MODE = re.compile(r"(drop-?in|recreate)\b", re.I)
_NONE_CELLS = {"", "—", "-"}


def _clean(cell: str) -> str:
    return cell.replace("**", "").replace("`", "").strip()


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tables(text: str) -> list[tuple[list[str], list[dict[str, str]]]]:
    """Every markdown table of ``text`` as ``(header, rows)``, each row a header -> cell dict."""
    out: list[tuple[list[str], list[dict[str, str]]]] = []
    block: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2 and _SEPARATOR.fullmatch(block[1].strip()):
            header = [_clean(c) for c in _cells(block[0])]  # '**Total**' is the column Total
            rows = []
            for raw in block[2:]:
                cells = _cells(raw)
                if len(cells) != len(header):
                    raise ValueError(
                        f"table row {cells[0] if cells else '?'!r} has {len(cells)} cells, expected {len(header)}"
                    )
                rows.append(dict(zip(header, cells, strict=True)))
            out.append((header, rows))
        block = []
    return out


def _views_and_outlier(cell: str, pick_id: str) -> tuple[int, float]:
    m = _VIEWS.fullmatch(_clean(cell))
    if m is None:
        raise ValueError(f"{pick_id}: cannot read views and outlier from {cell!r} (expected '43.4M · 1,393×')")
    views = round(float(m[1].replace(",", "")) * _UNITS[m[2]])
    return views, float(m[3].replace(",", ""))


def _original(cell: str, pick_id: str) -> tuple[str, str, str | None]:
    """``(platform, canonical_url, creator)``: the creator is the handle in the note, else the TikTok URL's."""
    m = _ORIGINAL.fullmatch(_clean(cell))
    if m is None:
        raise ValueError(f"{pick_id}: cannot find a video URL in {cell!r}")
    try:
        platform, url = parse_video_url(m[1])
    except ValueError as e:
        raise ValueError(f"{pick_id}: {e}") from None
    creator = None
    if m[2] and (h := _HANDLE.search(m[2])):
        creator = h[0].rstrip(".")
    elif platform == "tiktok" and (h := re.search(r"/(@[^/]+)/video/", url)):
        creator = h[1]
    return platform, url, creator


def _column(row: dict[str, str], prefix: str) -> str:
    """The cell of the column whose header starts with ``prefix`` (a header may carry a gloss)."""
    for name, cell in row.items():
        if name.startswith(prefix):
            return cell
    raise ValueError(f"no {prefix!r} column in the table of row {next(iter(row.values()))!r}")


def _optional(cell: str) -> str | None:
    value = _clean(cell)
    return None if value in _NONE_CELLS else value


def _pick_proposal(row: dict[str, str], pick_id: str) -> dict[str, Any]:
    proposal: dict[str, Any] = {}
    if "Mode" in row:
        cell = _clean(row["Mode"])
        m = _MODE.match(cell)
        if m is None:
            raise ValueError(f"{pick_id}: cannot read the mode from {cell!r}")
        proposal["mode"] = "dropin" if m[1].lower().startswith("drop") else "recreate"
        if cell.lower() not in ("recreate", "drop-in", "dropin"):
            proposal["mode_note"] = cell
        bodies = _BODIES.search(cell)
        if bodies and int(bodies[1]) >= 2:
            proposal["needs"] = "multi_body"
    if "Button line" in row:  # the talking-lane table
        proposal["needs"] = "talking_lane"
        if line := _optional(row["Button line"]):
            proposal["button_line"] = line.strip('"“”')
    proposal["hook"] = _clean(row["Hook"])
    proposal["concept"] = _clean(row["Our version"])
    if "Prop" in row and (prop := _optional(row["Prop"])):
        proposal["prop"] = prop
    return proposal


def _hold_reason(why: str, decision_cell: str) -> str:
    """The "Why" plus whatever the decision cell says beyond a plain hold ("hold → approve if ...")."""
    text = _clean(decision_cell).lstrip("⏸").strip()
    rest = re.sub(r"^hold\s*(→\s*)?", "", text, flags=re.I).strip()
    return f"{why}; {rest}" if rest and not rest.startswith("(") else why


def parse_picks(text: str) -> list[PickRow]:
    """The 17 picks of the batch document, checked (see the module doc), in the document's rank order."""
    tables = _tables(text)
    pick_rows: dict[str, dict[str, str]] = {}
    score_rows: dict[str, dict[str, str]] = {}
    decision_rows: dict[str, tuple[dict[str, str], bool]] = {}  # id -> (row, row has the id to itself)
    for header, rows in tables:
        if header[:2] == ["ID", "Original"]:
            for r in rows:
                pid = _clean(r["ID"])
                if not _ID.fullmatch(pid) or pid in pick_rows:
                    raise ValueError(f"bad or repeated pick id {pid!r} in the picks tables")
                pick_rows[pid] = r
        elif header[0] == "Rank":
            score_rows.update({_clean(r["ID"]): r for r in rows})
        elif header[:2] == ["ID", "Decision"]:
            for r in rows:
                ids = _ID.findall(_clean(r["ID"]))
                if not ids:
                    raise ValueError(f"no pick id in the decision row {r['ID']!r}")
                for pid in ids:
                    decision_rows[pid] = (r, len(ids) == 1)
    if not pick_rows:
        raise ValueError("no pick tables found (expected tables headed 'ID | Original | ...')")
    for what, found in (("scores", score_rows), ("decisions", decision_rows)):
        missing = sorted(set(pick_rows) - set(found))
        extra = sorted(set(found) - set(pick_rows))
        if missing or extra:
            raise ValueError(
                f"{what} table and picks tables disagree: no {what} row for {missing}, no pick for {extra}"
            )

    picks: list[PickRow] = []
    for pid, r in pick_rows.items():
        s = score_rows[pid]
        platform, url, creator = _original(r["Original"], pid)
        views, outlier_x = _views_and_outlier(r["Views · ×"], pid)
        judged = {
            "freshness": float(_clean(s["Fresh"])),
            "fit": float(_clean(s["Fit"])),
            "feasibility": float(_clean(s["Feasible"])),
            "saturation": float(_clean(s["Unsaturated"])),
        }
        total = int(float(_clean(s["Total"])))
        computed = score_pick(outlier_x, views, **judged)["total"]
        if computed != total:
            raise ValueError(f"{pid}: total {total} in the document, but the rubric gives {computed}")
        proposal = _pick_proposal(r, pid)

        d, alone = decision_rows[pid]
        cell = _clean(d["Decision"])
        why = _clean(d["Why"])
        needs = proposal.get("needs")
        if cell.startswith("✅"):
            if needs:
                raise ValueError(f"{pid}: approved in the decisions table but needs {needs}")
            by = "rule" if total >= RULE_MIN_TOTAL else "analyst"
            marker = re.search(r"\((auto|analyst)\)", cell)
            if marker and (marker[1] == "auto") != (by == "rule"):
                raise ValueError(f"{pid}: marked ({marker[1]}) but total {total} makes it by {by}")
            if by == "rule" and judged["feasibility"] < RULE_MIN_FEASIBILITY:
                raise ValueError(f"{pid}: total {total} but feasibility {judged['feasibility']:g}: the rule would not approve it")
            decision, reason = "approve", why
        elif cell.startswith("⏸"):
            if not needs:
                raise ValueError(f"{pid}: held in the decisions table but needs no untested capability")
            decision, by, reason = "hold", "rule", _hold_reason(why, cell)
        else:
            raise ValueError(f"{pid}: unknown decision {cell!r} (expected ✅ approved or ⏸ hold)")
        if alone and (enh := _optional(_column(d, "Our enhancement"))):
            proposal["enhancement"] = enh
        picks.append(
            PickRow(
                id=pid, rank=int(_clean(s["Rank"])), url=url, platform=platform, creator=creator,
                views=views, outlier_x=outlier_x, character=_clean(s["Character"]), judged=judged,
                total=total, proposal=proposal, decision=decision, by=by, reason=reason,
            )
        )
    picks.sort(key=lambda p: p.rank)
    return picks


def seed_picks(store: Store, text: str) -> dict[str, int]:
    """File and decide every pick of the document; a summary of what this run did (see the module doc)."""
    rows = parse_picks(text)  # everything is checked before the first write
    known = {c.slug for c in store.characters()}
    summary = dict.fromkeys(("picks", "created", "existing", "approved", "held"), 0)
    summary["picks"] = len(rows)
    for row in rows:
        existed = bool(store.list_favorites(url=row.url))
        summary["existing" if existed else "created"] += 1
        proposal = dict(row.proposal)
        slug = row.character if row.character in known else None
        if slug is None:
            proposal["intended_character"] = row.character
        f = add_pick(
            store, row.url, row.platform, row.creator, row.views, row.outlier_x, slug, proposal,
            "scan", **row.judged,
        )
        if f.status != "new" or "decision" in f.proposal:
            continue  # already decided, by the owner or by an earlier run: leave it alone
        decide(store, f.id, row.decision, row.reason, row.by)  # type: ignore[arg-type]
        summary["approved" if row.decision == "approve" else "held"] += 1
    return summary


# ---- CLI -----------------------------------------------------------------------------------------

app = typer.Typer(
    help="Seed characters + accounts from characters/*/refs.json (`studio seed`), the batch-1 Viral "
    "Picks (`studio seed picks FILE`), or show the characters (`studio seed status`). "
    "Prints JSON; exit 2 = something to fix.",
    invoke_without_command=True,
)


@app.callback()
def seed_command(
    ctx: typer.Context,
    characters_dir: Annotated[
        Path | None, typer.Option(help="Folder holding <slug>/refs.json (default: the repo's characters/).")
    ] = None,
) -> None:
    """Upsert characters and accounts from refs.json (idempotent; a missing handle skips that account)."""
    if ctx.invoked_subcommand is not None:
        return
    store = open_store()
    try:
        report = seed_characters(store, DEFAULT_CHARACTERS_DIR if characters_dir is None else characters_dir)
    except ValueError as e:
        fail(str(e))
    emit(
        {
            "characters": [
                {
                    "slug": c.slug, "name": c.name, "status": c.status, "bodies": [b.value for b in c.bodies],
                    "setup": c.setup,
                }
                for c in report.characters
            ],
            "accounts": [{"character": a.character_slug, **_account_json(a)} for a in report.accounts],
            "skipped_accounts": report.skipped,
        }
    )


@app.command("status")
def status_command() -> None:
    """Each character with its status (the daily run skips any that is not live) and its accounts."""
    store = open_store()
    emit(
        [
            {
                "slug": c.slug,
                "name": c.name,
                "status": c.status,
                "live": c.status == "live",
                "bodies": [b.value for b in c.bodies],
                "traits": c.setup.get("traits"),
                "accounts": [_account_json(a) for a in store.accounts(c.slug)],
            }
            for c in store.characters()
        ]
    )


@app.command("picks")
def picks_command(
    file: Annotated[Path, typer.Argument(help="The picks document, e.g. docs/launch/viral-picks-2026-10-04.md.")],
) -> None:
    """Load the picks of a batch document with its recorded decisions (idempotent)."""
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"no such file: {file}")
    except OSError as e:
        fail(f"cannot read {file}: {e}")
    store = open_store()
    try:
        emit(seed_picks(store, text))
    except ValueError as e:
        fail(str(e))

"""``studio.lunar``: LunarCrush's trend data for the hits job's freshness gate (task 18; research
``docs/research/2026-10-08-tools-data-earn.md`` section 3, rule P5 of ``docs/research/2026-10-07-hit-patterns.md`` section 5).

ScrapeCreators finds the clips; LunarCrush dates the trend: **is the sound or trend a hit is riding still alive?** One call to
LunarCrush's hosted MCP endpoint (``keyword_time_series``, interval ``1m``: one row a day for 30 days, per-network columns) gives
the curve; ``trend_curve`` turns it into a stage (``rising`` / ``peak`` / ``fading`` / ``dead``) and the days since the peak.
Cloud API only, like ScrapeCreators (CLAUDE.md, research scraping): never the Mac's browser, cookies or a logged-in session.

**Inert without the key.** The key is ``LUNARCRUSH_API_KEY`` in the environment (a GitHub secret on the cloud job; LunarCrush's free
plan gives no API key (owner, 12 Oct 2026), so the gate stays off until a paid key is pasted with ``gh secret set``), never a file, never printed or logged. Without it ``TrendGate`` answers
``unknown`` and makes no call: the hits job files as it always did.

**The wire** (MCP "streamable HTTP", ``Authorization: Bearer <key>`` to ``https://lunarcrush.ai/mcp``): ``initialize`` (the session
id the server answers with is sent back on every later request), the ``notifications/initialized`` notice, then ``tools/call``
``keyword_time_series`` ``{keyword, interval: "1m", network: "tiktok"}``; the answer is JSON or an event stream with the
Markdown table in ``result.content[].text``. NOT YET VERIFIED against a live key (LunarCrush's developer page names only the
endpoint and the header; the rest is the MCP specification's transport and the tool's schema as an MCP client lists it): the
first real call is ``bin/studio hits lunar-probe "<keyword>"``, which prints the parsed curve, or the raw head of an answer it
cannot read.

**Free-tier limits** (research 3.1): 4 calls a minute and 100 a day, shared with the owner's other uses of the key, and a refused
call still counts. So: calls are ``CALL_SPACING_S`` (16 s) apart; a refused call is never retried in the same minute (the next
call waits 60 s from the refusal, or the 429's ``Retry-After`` when longer, up to 5 minutes) and two refusals in a row stop the
client for the run. A refusal is an HTTP 429, a JSON-RPC error or an ``isError`` result that says rate limit, or an ordinary answer
with no table that says so (the exact form is not known); ``hits.lunar_daily_cap`` (40 by default)
calls at most per run (the job runs once a London day), leaving 60 of the 100 for the owner's MCP use. The handshake is not
counted (it is not a metered tool call as far as the capture of 8 Oct showed) and not paced.

**The curve** (``trend_curve``, research 3.2 step 3): the 3-day mean of ``tiktok_interactions`` (the summed ``interactions``
column when the table has no TikTok column), the mean centred on the day (a day at an end of the series has one neighbour, so the
peak is the day it happened on, not a day later). Days missing between two rows count as nothing posted. LunarCrush tracks a
sample of posts (4-11 TikTok posts a day for "single ladies"), which is why the mean is taken. The latest day is the last full
day (``as_of``, yesterday in London: today's part day is not in it). A series whose last row is more than ``STALE_DAYS`` (2)
before it has stopped (a dead small trend gets no row on the days nobody posted about it), so the days up to ``as_of`` count as
nothing posted; a last row 2 days behind is only LunarCrush's usual lag. Stages, in this order:

- ``rising``: the latest day is at 90% of the peak or more (``NEAR_PEAK``) and the last 3 days climb;
- ``peak``: otherwise, the peak is on the latest day or the day before;
- ``fading``: otherwise, the peak was 7 or fewer days ago, or the latest day is at 50% or more of the peak (P5 (a) and (b));
- ``dead``: neither. P5: a dead trend is not filed.

``days_since_peak`` counts from the peak day to the latest day. A series with no signal (every day nothing) is no curve at all,
not a dead trend: a sound LunarCrush does not track is *unknown*, never blocked.

**Fail open.** A missing key, a refused or failed call, the cap, an answer that is not a table, a flat series: the reading is
``unknown`` and the hit is filed as before. Parse failures are logged with the first 300 characters of the answer (never the key).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

ENDPOINT = "https://lunarcrush.ai/mcp"
KEY_ENV = "LUNARCRUSH_API_KEY"
PROTOCOL_VERSION = "2025-03-26"  # the MCP streamable-HTTP revision this client speaks
TOOL = "keyword_time_series"
INTERVAL = "1m"  # daily rows for the last month
NETWORK = "tiktok"  # the free answers carried every network anyway (research 3.1); the TikTok column is the one read
CALL_SPACING_S = 16.0  # 4 calls a minute
REFUSAL_COOLDOWN_S = 60.0  # a refused call is not retried in the same minute
RETRY_AFTER_MAX_S = 300.0  # a 429's Retry-After is honoured up to this (the job has 30 minutes)
REFUSALS_STOP = 2  # refused this often in a row: no more calls this run
DEFAULT_CAP = 40  # hits.lunar_daily_cap
KEY_MAX = 80  # the longest trend key asked for
HEAD_CHARS = 300  # how much of an unreadable answer is logged

NEAR_PEAK = 0.9  # rising: the latest day is at least this share of the peak
PEAK_DAYS = 1  # peak: the peak day is the latest day or the day before
FADING_DAYS = 7  # fading: the peak was this many days ago or fewer (P5 (a))
FADING_RATIO = 0.5  # fading: the latest day is at least this share of the peak (P5 (b))
MIN_DAYS = 3  # fewer days than this give no curve
STALE_DAYS = 2  # a last row this many days before the latest full day is LunarCrush's usual lag; older, the series has stopped
STAGES = ("rising", "peak", "fading", "dead")
UNKNOWN = "unknown"

log = logging.getLogger("studio.lunar")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_BODY_CHARS = 200
_RATE_LIMITED = re.compile(r"rate.?limit|too many requests|quota|limit (?:reached|exceeded)|\b429\b", re.I)


def _retry_after(value: str | None) -> float | None:
    """A ``Retry-After`` header in seconds (the HTTP-date form is not read), or None."""
    try:
        seconds = float((value or "").strip())
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _has_table(text: str) -> bool:
    return any(line.lstrip().startswith("|") for line in text.splitlines())


class LunarError(RuntimeError):
    """A LunarCrush call failed. ``status`` is the HTTP status when there was one (401/403: the key is refused); ``refused`` is
    true when the account's rate limit said no (a refused call still counts against the day); ``retry_after`` is the seconds a 429
    asked us to wait (None when it said nothing usable)."""

    def __init__(self, message: str, *, status: int | None = None, refused: bool = False, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status, self.refused, self.retry_after = status, refused, retry_after


class LunarParseError(ValueError):
    """The answer is not a table this module can read. ``head`` is its first ``HEAD_CHARS`` characters, for the log."""

    def __init__(self, message: str, head: str) -> None:
        super().__init__(message)
        self.head = head[:HEAD_CHARS]


# ---- the answer: a Markdown table -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One day of the answer: TikTok interactions and the all-network total (None where the table says N/A or has no column)."""

    day: date
    tiktok: int | None = None
    total: int | None = None


_DAY_COLUMNS = frozenset({"time", "date", "day", "timestamp", "datetime", "period", "time_utc", "date_utc"})
_TOTAL_COLUMNS = frozenset({"interactions", "engagements", "total_interactions", "total_engagements", "total"})
_NO_NUMBER = frozenset({"", "n/a", "na", "-", "--", "null", "none", "nan", "unknown"})
_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}


def _cells(line: str) -> list[str] | None:
    line = line.strip()
    return [c.strip() for c in line.strip("|").split("|")] if line.startswith("|") else None


def _is_rule(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells)


def _name(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")


def _number(raw: str) -> int | None:
    text = raw.strip().strip("`*").replace(",", "").replace(" ", "")
    if text.lower() in _NO_NUMBER:
        return None
    scale = 1.0
    if text[-1:].lower() in _SUFFIX:
        scale, text = _SUFFIX[text[-1].lower()], text[:-1]
    try:
        value = float(text) * scale
    except ValueError:
        return None
    return int(round(value)) if math.isfinite(value) and value >= 0 else None


_DAY_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y/%m/%d", "%d/%m/%Y")


def _day(raw: str) -> date | None:
    text = raw.strip().strip("`*")
    if not text:
        return None
    if text.isdigit():
        n = int(text)
        n = n / 1000 if n > 10**11 else n  # milliseconds
        if n < 10**8:
            return None
        return datetime.fromtimestamp(n, tz=timezone.utc).date()
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _DAY_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None
    return (at.astimezone(timezone.utc) if at.tzinfo is not None else at).date()


def parse_keyword_series(text: str) -> list[Row]:
    """The daily rows of a ``keyword_time_series`` answer: the first Markdown table, its columns found by NAME (any order): a
    day column (``time``, ``date``, ... else the first column), ``tiktok_interactions`` and the all-network ``interactions`` (else
    the sum of the per-network ``*_interactions`` columns). A day may be an ISO date or datetime or unix seconds or
    milliseconds; hourly rows of one day are added up; ``N/A`` is unknown (None). Rows come out oldest first.
    ``LunarParseError`` (with the answer's first 300 characters) when there is no table, no interactions column or no readable
    day."""
    lines = text.splitlines() if isinstance(text, str) else []
    header: list[str] | None = None
    body: list[list[str]] = []
    for i, line in enumerate(lines):
        cells = _cells(line)
        if cells is None:
            if header is not None and body:
                break
            continue
        if header is None:
            nxt = _cells(lines[i + 1]) if i + 1 < len(lines) else None
            if nxt is not None and _is_rule(nxt):
                header = cells
            continue
        if not _is_rule(cells):
            body.append(cells)
    if header is None:
        raise LunarParseError("no table in the answer", text if isinstance(text, str) else "")
    names = [_name(h) for h in header]
    day_col = next((i for i, n in enumerate(names) if n in _DAY_COLUMNS), 0)
    tiktok_col = next((i for i, n in enumerate(names) if n == "tiktok_interactions"), None)
    if tiktok_col is None:
        tiktok_col = next((i for i, n in enumerate(names) if "tiktok" in n and ("interaction" in n or "engagement" in n)), None)
    total_col = next((i for i, n in enumerate(names) if n in _TOTAL_COLUMNS), None)
    network_cols = [
        i for i, n in enumerate(names) if i not in (tiktok_col, total_col) and ("interaction" in n or "engagement" in n)
    ]
    if tiktok_col is None and total_col is None and not network_cols:
        raise LunarParseError("the table has no interactions column", text)

    def at(cells: list[str], col: int | None) -> int | None:
        return _number(cells[col]) if col is not None and col < len(cells) else None

    days: dict[date, list[int | None]] = {}
    for cells in body:
        d = _day(cells[day_col]) if day_col < len(cells) else None
        if d is None:
            continue
        tiktok = at(cells, tiktok_col)
        if total_col is not None:
            total = at(cells, total_col)
        else:
            parts = [v for v in (tiktok, *(at(cells, c) for c in network_cols)) if v is not None]
            total = sum(parts) if parts else None
        have = days.setdefault(d, [None, None])
        for slot, value in enumerate((tiktok, total)):
            if value is not None:
                have[slot] = (have[slot] or 0) + value
    if not days:
        raise LunarParseError("no row of the table has a readable day", text)
    return [Row(d, t, s) for d, (t, s) in sorted(days.items())]


# ---- the curve ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Curve:
    """What ``trend_curve`` read: ``stage`` (one of ``STAGES``), ``days_since_peak`` (from the peak day to the latest day),
    the 3-day-smoothed ``peak_value`` and ``latest_value``, ``ratio`` = latest / peak, ``source`` (``tiktok`` or ``total``: the
    column read) and the whole ``smoothed`` series ``((day, value), ...)``."""

    stage: str
    days_since_peak: int
    peak_day: date
    peak_value: float
    latest_value: float
    ratio: float
    source: str
    smoothed: tuple[tuple[date, float], ...]


def source_of(rows: Iterable[Row]) -> str:
    """The column a curve is read from: ``tiktok`` when any row has a TikTok number, else the summed ``total``."""
    return "tiktok" if any(r.tiktok is not None for r in rows) else "total"


def trend_curve(rows: Iterable[Row], as_of: date | None = None) -> Curve | None:
    """The stage of a trend from its daily rows (see the module doc), or None when the rows give no curve: fewer than
    ``MIN_DAYS`` days with a number, or no signal at all (nothing is not a dead trend, it is unknown).

    ``as_of`` is the latest full day (yesterday, London). A trend nobody posts about any more has no rows after its last post, so
    reading the series "as of its last row" would call a dead small trend a peak. When the last row is more than ``STALE_DAYS``
    before ``as_of`` the series has stopped: the days up to ``as_of`` are days of nothing posted. A last row at most that many
    days behind is LunarCrush's usual lag and changes nothing; without ``as_of`` the series is read as of its last row."""
    rows = list(rows)
    source = source_of(rows)
    by_day: dict[date, int] = {}
    for r in rows:
        value = r.tiktok if source == "tiktok" else r.total
        if value is not None:
            by_day[r.day] = by_day.get(r.day, 0) + value
    if len(by_day) < MIN_DAYS:
        return None
    first, last = min(by_day), max(by_day)
    if as_of is not None and (as_of - last).days > STALE_DAYS:
        last = as_of
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    values = [float(by_day.get(d, 0)) for d in days]
    smoothed = []
    for i in range(len(values)):
        window = values[max(0, i - 1): i + 2]
        smoothed.append(sum(window) / len(window))
    peak_value = max(smoothed)
    if peak_value <= 0:
        return None
    peak_i = max(i for i, v in enumerate(smoothed) if v == peak_value)  # a plateau's peak is its latest day
    latest = smoothed[-1]
    ratio = latest / peak_value
    since = len(days) - 1 - peak_i
    climbing = len(smoothed) >= 3 and smoothed[-1] > smoothed[-2] > smoothed[-3]
    if climbing and ratio >= NEAR_PEAK:
        stage = "rising"
    elif since <= PEAK_DAYS:
        stage = "peak"
    elif since <= FADING_DAYS or ratio >= FADING_RATIO:
        stage = "fading"
    else:
        stage = "dead"
    return Curve(stage, since, days[peak_i], peak_value, latest, ratio, source, tuple(zip(days, smoothed)))


# ---- the trend key of a hit -------------------------------------------------------------------------------------------------------------


# a sound nobody named: TikTok's "original sound - <handle>", Instagram's "Original audio", and the localised forms
_GENERIC_SOUND = re.compile(
    r"^(original\s+(sound|audio)|son\s+original|sonido\s+original|originalton|suono\s+originale|som\s+original)\b", re.I,
)


def _clean(text: str) -> str:
    return " ".join(text.lower().split())


def trend_key(sound: str | None, caption: str | None, names: Sequence[str]) -> tuple[str, str] | None:
    """What to ask LunarCrush about for a hit, as ``(key, kind)``: its ``sound`` (kind ``sound``) unless that is generic
    ("original sound - <handle>"), else the first of ``names`` (a character's keywords, the events: in the caller's order) that
    the caption says as a whole word or a hashtag (kind ``caption``); None when there is nothing to ask about."""
    s = _clean(sound) if isinstance(sound, str) else ""
    if s and not _GENERIC_SOUND.match(s):
        return s[:KEY_MAX], "sound"
    if not isinstance(caption, str) or not caption.strip():
        return None
    text = _clean(caption)
    words = f" {re.sub(r'[^a-z0-9]+', ' ', text)} "
    tags = set(re.findall(r"#(\w+)", text))
    for name in names:
        n = _clean(name) if isinstance(name, str) else ""
        plain = re.sub(r"[^a-z0-9]+", " ", n).strip()
        if not plain:
            continue
        if f" {plain} " in words or plain.replace(" ", "") in tags:
            return n[:KEY_MAX], "caption"
    return None


EVENTS_PATH = Path(__file__).resolve().parents[1] / "config" / "events.yaml"


def event_names(path: Path | str | None = None) -> list[str]:
    """The event names of ``config/events.yaml`` (the file is optional and has no fixed format yet; no YAML parser is a
    dependency): the text of each ``- <name>`` list line and of each ``name: <name>`` line, quotes removed. [] when the file is
    missing or unreadable."""
    try:
        lines = Path(path or EVENTS_PATH).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[str] = []
    for line in lines:
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if item.startswith("- "):
            item = item[2:].strip()
        elif not item.startswith("name:"):
            continue
        if item.startswith("name:"):
            item = item[5:].strip()
        elif ": " in item or item.endswith(":"):
            continue  # a `- key: value` line that is not a name
        item = item.strip("'\"").strip()
        if item:
            out.append(item)
    return out


# ---- the client ---------------------------------------------------------------------------------------------------------------------


class LunarCrush:
    """The hosted MCP endpoint with one key (see the module doc for the wire and the limits). ``http`` is for tests (an
    ``httpx.Client`` on a ``MockTransport``): the key is only ever sent to ``endpoint``, never logged, never in an error."""

    def __init__(
        self, api_key: str, http: httpx.Client | None = None, *, endpoint: str = ENDPOINT, cap: int = DEFAULT_CAP,
        clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not (api_key or "").strip():
            raise ValueError(f"LunarCrush needs {KEY_ENV}")
        self._key = api_key.strip()
        self._endpoint = endpoint
        self._http = http if http is not None else httpx.Client(timeout=_TIMEOUT, follow_redirects=False)
        self._clock, self._sleep, self.cap = clock, sleep, cap
        self.calls = 0  # tool calls made this run, the refused ones too (a refused call still counts)
        self._ids = 0
        self._session: str | None = None
        self._ready = False
        self._last_call: float | None = None
        self._cool_until = 0.0
        self._refusals = 0  # in a row
        self._stopped: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kw: Any) -> LunarCrush | None:
        """The client for ``LUNARCRUSH_API_KEY``; None when it is not set (the owner has not made a key yet)."""
        env = os.environ if env is None else env
        key = (env.get(KEY_ENV) or "").strip()
        return cls(key, **kw) if key else None

    def __repr__(self) -> str:
        return f"LunarCrush(endpoint={self._endpoint!r}, calls={self.calls})"

    def scrub(self, text: str) -> str:
        """``text`` with the key replaced: everything that is logged or raised goes through this."""
        return text.replace(self._key, "***")

    # ---- the transport

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._ready or self._session:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        return headers

    def _post(self, payload: Mapping[str, Any]) -> httpx.Response:
        try:
            response = self._http.post(self._endpoint, content=json.dumps(payload), headers=self._headers())
        except httpx.HTTPError as e:
            raise LunarError(f"LunarCrush: no answer ({type(e).__name__})") from None
        if not response.is_success:
            body = self.scrub(response.text.strip()[:_BODY_CHARS])
            status = response.status_code
            if status in (401, 403):
                self._stopped = "the key is refused"
            retry = _retry_after(response.headers.get("retry-after")) if status == 429 else None
            raise LunarError(f"LunarCrush answered HTTP {status}: {body}", status=status, refused=status == 429, retry_after=retry)
        return response

    def _message(self, response: httpx.Response, id_: int) -> dict[str, Any]:
        """The JSON-RPC message answering request ``id_`` (a JSON body, or the matching ``data:`` line of an event stream)."""
        if "text/event-stream" in response.headers.get("content-type", ""):
            found: dict[str, Any] | None = None
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    message = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(message, dict) and ("result" in message or "error" in message):
                    found = message
                    if message.get("id") == id_:
                        break
            if found is None:
                raise LunarError("LunarCrush: the event stream had no answer")
            return found
        try:
            message = response.json()
        except ValueError:
            raise LunarError(f"LunarCrush: the answer is not JSON: {self.scrub(response.text.strip()[:_BODY_CHARS])}") from None
        if not isinstance(message, dict):
            raise LunarError("LunarCrush: the answer is not a JSON-RPC message")
        return message

    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    def _handshake(self) -> None:
        if self._ready:
            return
        id_ = self._next_id()
        response = self._post({
            "jsonrpc": "2.0", "id": id_, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "oddeyes-studio", "version": "1"}},
        })  # fmt: skip
        session = response.headers.get("mcp-session-id")
        message = self._message(response, id_)
        if "error" in message:
            raise LunarError(f"LunarCrush refused the handshake: {self._error_text(message['error'])}")
        self._session = session or None
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._ready = True

    def _error_text(self, error: Any) -> str:
        text = error.get("message") if isinstance(error, Mapping) else error
        return self.scrub(str(text)[:_BODY_CHARS])

    # ---- one tool call

    def _wait(self) -> None:
        now = self._clock()
        due = max(self._cool_until, (self._last_call + CALL_SPACING_S) if self._last_call is not None else 0.0)
        if due > now:
            self._sleep(due - now)

    def _refused(self, retry_after: float | None = None) -> None:
        """A call was refused: no more calls this minute (longer when the refusal said so, up to ``RETRY_AFTER_MAX_S``)."""
        self._refusals += 1
        wait = min(max(retry_after or 0.0, REFUSAL_COOLDOWN_S), RETRY_AFTER_MAX_S)
        self._cool_until = self._clock() + wait
        if self._refusals >= REFUSALS_STOP:
            self._stopped = f"refused {self._refusals} times in a row"

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> str:
        """The text of one ``tools/call`` answer. ``LunarError`` when the run is stopped (cap, a refused key, two refusals in a
        row), the call is refused or fails, or the tool answers an error; a refused call is counted and never retried."""
        if self._stopped is not None:
            raise LunarError(f"LunarCrush stopped for this run: {self._stopped}")
        if self.calls >= self.cap:
            raise LunarError(f"LunarCrush: this run's cap of {self.cap} calls is used (hits.lunar_daily_cap)")
        self._handshake()
        self._wait()
        self._last_call = self._clock()
        self.calls += 1  # counted before it is sent: a refused call still counts
        id_ = self._next_id()
        try:
            response = self._post({"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": {"name": name, "arguments": dict(arguments)}})
            message = self._message(response, id_)
        except LunarError as e:
            if e.refused or _RATE_LIMITED.search(str(e)):
                self._refused(e.retry_after)
                e.refused = True
            raise
        if "error" in message:
            text = self._error_text(message["error"])
            refused = bool(_RATE_LIMITED.search(text))
            if refused:
                self._refused()
            raise LunarError(f"LunarCrush: {text}", refused=refused)
        result = message.get("result") if isinstance(message.get("result"), Mapping) else {}
        content = result.get("content") if isinstance(result.get("content"), list) else []
        text = "\n".join(c["text"] for c in content if isinstance(c, Mapping) and isinstance(c.get("text"), str))
        if result.get("isError") is True:
            refused = bool(_RATE_LIMITED.search(text))
            if refused:
                self._refused()
            raise LunarError(f"LunarCrush: {self.scrub(text.strip()[:_BODY_CHARS])}", refused=refused)
        if _RATE_LIMITED.search(text) and not _has_table(text):  # a refusal that came back as an ordinary answer: the same path
            self._refused()
            raise LunarError(f"LunarCrush: {self.scrub(text.strip()[:_BODY_CHARS])}", refused=True)
        self._refusals = 0
        return text

    def keyword_time_series(self, keyword: str) -> str:
        """The Markdown answer of ``keyword_time_series`` for ``keyword`` (daily rows of the last month, TikTok)."""
        return self.call_tool(TOOL, {"keyword": keyword, "interval": INTERVAL, "network": NETWORK})


# ---- the gate -------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """What the gate read for one trend key: ``stage`` (one of ``STAGES`` or ``unknown``), ``days_since_peak`` (None unless
    measured) and, for ``unknown``, the ``reason``."""

    stage: str
    days_since_peak: int | None = None
    reason: str | None = None


class TrendGate:
    """One LunarCrush check per distinct trend key per run (an in-process cache: no table, no migration). Everything that can go
    wrong is an ``unknown`` reading, remembered for the key, and never an exception: the hits job fails open."""

    def __init__(self, client: LunarCrush | None) -> None:
        self.client = client
        self._cache: dict[str, Reading] = {}

    @classmethod
    def from_env(cls, *, cap: int = DEFAULT_CAP, env: Mapping[str, str] | None = None, **kw: Any) -> TrendGate:
        """The gate for ``LUNARCRUSH_API_KEY``; with no key it is off (every reading ``unknown``, no call)."""
        return cls(LunarCrush.from_env(env, cap=cap, **kw))

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def read(self, key: str, as_of: date | None = None) -> Reading:
        """The trend ``key``'s stage and days since its peak, or ``unknown`` with the reason. ``as_of`` is the latest full day
        (``trend_curve``); a key is read once per run, so the first ``as_of`` it was asked with stands."""
        key = _clean(key or "")
        if self.client is None:
            return Reading(UNKNOWN, reason=f"{KEY_ENV} is not set: the trend gate is off")
        if not key:
            return Reading(UNKNOWN, reason="no trend key")
        if key not in self._cache:
            self._cache[key] = self._check(self.client, key, as_of)
        return self._cache[key]

    def _check(self, client: LunarCrush, key: str, as_of: date | None = None) -> Reading:
        try:
            rows = parse_keyword_series(client.keyword_time_series(key))
            curve = trend_curve(rows, as_of)
        except LunarParseError as e:
            log.warning("LunarCrush %r: the answer is not a table this job can read: %s", key, client.scrub(e.head))
            return Reading(UNKNOWN, reason="the answer could not be read")
        except LunarError as e:
            log.warning("LunarCrush %r: %s", key, client.scrub(str(e)))
            return Reading(UNKNOWN, reason=client.scrub(str(e))[:_BODY_CHARS])
        except Exception as e:  # noqa: BLE001 - whatever an odd answer does (an OSError from a huge day cell), it never stops the filing
            log.warning("LunarCrush %r: unreadable (%s)", key, type(e).__name__)
            return Reading(UNKNOWN, reason="the answer could not be read")
        if curve is None:
            return Reading(UNKNOWN, reason="the curve has no signal to judge")
        return Reading(curve.stage, curve.days_since_peak)

    def summary(self) -> dict[str, Any]:
        """``{"enabled", "keys", "calls", "stages": {stage: n}}``: what this run asked and found."""
        return {
            "enabled": self.enabled, "keys": len(self._cache), "calls": self.client.calls if self.client is not None else 0,
            "stages": dict(Counter(r.stage for r in self._cache.values())),
        }


__all__ = [
    "Curve", "LunarCrush", "LunarError", "LunarParseError", "Reading", "Row", "TrendGate", "event_names", "parse_keyword_series",
    "source_of", "trend_curve", "trend_key",
]

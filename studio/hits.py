"""``studio hits``: the cloud hits job (terminal v3 spec section 10; plan ``docs/superpowers/plans/2026-10-07-terminal-v3.md``
Task 6). Owner 2026-10-07: "set up the scrapecreators cloud job" and "let it scrape if necessary. I just don't want it to need the
Mac running and browsing to get it done" (spec section 8).

**What.** Once a day (``.github/workflows/studio-hits.yml``, 06:30 London) ``studio hits pull`` asks ScrapeCreators' API for the
top TikTok and Instagram posts of our niches and keeps them in ``studio.hits`` (migration 0016): **metadata only**. No Mac, no
browser, no cookies, no login, and nothing is downloaded here (a thumbnail URL is stored, never fetched).

**The searches** (``plan_calls``, in this order, so a cap that stops the run early still leaves every character his first
keyword): the general lane's trending feeds (TikTok ``GET /v1/tiktok/get-trending-feed`` for GB and US, Instagram
``GET /v1/instagram/reels/trending``, once a day), then, keyword by keyword, each live character's keywords (``config/scan.json``
``hits.keywords``, at most 3) on TikTok (``GET /v1/tiktok/search/keyword``, ``date_posted=this-week``, ``sort_by=most-liked``,
``trim=true``) and Instagram (``GET /v2/instagram/reels/search``, ``date_posted=last-week``), each round followed by one broad
search of the general lane (``hits.general.keywords`` on TikTok, by likes this week). Header ``x-api-key`` from the environment
(``SCRAPECREATORS_API_KEY``, a GitHub secret: never in a file). ``hits.daily_credit_cap`` (25) stops the run when the credits the
calls charged (``credits_charged``, usually 1) reach it.

**The two lanes.** A character's search keeps whatever it finds for him (``character_slug`` = his slug); the general lane
(``character_slug`` None) keeps any hot post whatever its topic (owner 2026-10-07: "don't skip cool viral up-and-coming clips
because you think they don't fit a character"): fit is never a reason to drop a hit, the check recommends who takes it later.

**Kept per hit** (``parse_tiktok``, ``parse_instagram``): platform, the canonical URL (unique), creator handle, followers when
given (0 counts as unknown), views, likes, comments, shares, saves, posted_at, caption (first 300 characters), sound name,
duration, thumbnail URL, the keyword and the character it was searched for, ``reach`` = views / followers (None without both),
and ``score`` (``hit_score``). A hit already stored is updated: its numbers, ``last_seen`` and score; its status (a dismissed hit
stays dismissed) and when it was first seen stay (``Store.upsert_hit``). **Skipped**: photo carousels, ads and paid partnerships
(scan.json ``global_reject_rules``), a link that is not a TikTok video or an Instagram Reel, videos over 60 s, posts older than
14 days, a creator already kept 3 times in 30 days (hit-pattern rule 4), and a post a run already saw.

**The score** (0-100, hit-pattern rules 2-3: reach over raw views, fresh over old): views 30 points (log scale, 10K = 0, 10M =
30), reach 40 points (log scale, 0.1x = 0, about 30x = 40; unknown followers: half), freshness 30 points (today 30, 14 days 0;
unknown date: half). Instagram's search gives no play count: the score alone reads likes x ``LIKES_TO_VIEWS`` (a 10% like rate)
in its place; ``views`` and ``reach`` stay None in the record (never guessed).

**Auto-filing** (``auto_file``, owner 2026-10-07: "set our system up with tons of clips as we will need them"): after the pull
the best new hits become drops, best score first: at most ``hits.auto_file_per_character`` (3) a London day per live character
(his own hits, waiting under him as the provisional character) and ``hits.auto_file_general`` (3) from the general lane (no
character: the studio's provisional one, the check recommends), each through ``studio.drop.add_drop`` exactly as a pasted link
(``character_by`` studio, so the check may move it), tagged ``drop.auto_filed`` (the learning tag ``source_kind``; retention's
30 days) and ``drop.hit`` ``{id, lane}``. A link that is already a pick (any status) is never filed again: the hit is marked
``dropped`` and the day's room is kept for another. A paused character's hits wait. The cloud drop job fetches each filed link
one at a time (yt-dlp, else ``ScrapeCreators.download_post`` for that ONE post).

**The one-post download** (``download_post``, used only by ``studio.fetch.fetch_pick_clip`` for a link the owner dropped or this
job filed, after yt-dlp failed): ``GET /v2/tiktok/video`` or ``/v1/instagram/post`` with ``download_media=true`` (10 credits
when the media is found, 1 otherwise) answers with a hosted copy of that one post; it is downloaded (https only, a timeout,
at most 200 MB, our key never sent to it) and ingested exactly like a yt-dlp result. Never a batch, never a third-party
downloader site.

CLI: ``studio hits pull [--dry-run] [--no-file]`` prints ``{"calls", "credits", "kept", "updated", "skipped": {reason: n},
"stopped": "cap" | null, "errors": [...], "filed": [{"hit_id", "pick_id", "character", "provisional"}]}``; without the key it
prints a ``::notice::`` and exits 0; ``--dry-run`` prints the plan of calls and calls nothing. ``studio hits list`` prints the
stored hits. Exit 1 only when not one call worked.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
import typer

from studio import drop, seed
from studio.fetch import filed_at
from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, now_london
from studio.favorites import is_drop, parse_video_url
from studio.models import HIT_CAPTION_MAX, Hit
from studio.store import HIT_REFRESHED, Store

API_ROOT = "https://api.scrapecreators.com"
KEY_ENV = "SCRAPECREATORS_API_KEY"
SCAN_PATH = Path(__file__).resolve().parents[1] / "config" / "scan.json"
DEFAULTS = {"daily_credit_cap": 25, "auto_file_per_character": 3, "auto_file_general": 3}
KEYWORDS_PER_CHARACTER = 3
TIKTOK_REGIONS = ("GB", "US")
MAX_SECONDS = 60.0  # skipped: videos over 60 s
MAX_AGE_DAYS = 14  # skipped: posts older than 14 days
CREATOR_LIMIT, CREATOR_DAYS = 3, 30  # skipped: a creator already kept 3 times in 30 days
LIKES_TO_VIEWS = 10  # the score's stand-in for a missing play count (a 10% like rate); never stored as views
MEDIA_MAX_BYTES = 200 * 1024 * 1024  # as yt-dlp's --max-filesize 200M
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm")
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_MEDIA_TIMEOUT = httpx.Timeout(60.0, connect=15.0, read=120.0)
_BODY_CHARS = 200


class ScrapeCreatorsError(RuntimeError):
    """A ScrapeCreators call failed. ``status`` is the HTTP status when there was one (401/403: the key is refused)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _https(url: Any) -> str | None:
    if not isinstance(url, str) or len(url) > 4096 or any(c.isspace() for c in url):
        return None
    parts = urlsplit(url)
    return url if parts.scheme == "https" and parts.hostname else None


def credits_of(data: Mapping[str, Any]) -> int:
    """What a call cost: its ``credits_charged`` (a whole number), else 1 (the usual price of a call)."""
    value = data.get("credits_charged")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 1


class ScrapeCreators:
    """ScrapeCreators' REST API with one key. ``http`` is for tests (an ``httpx.Client`` on a ``MockTransport``): nothing here
    is ever called without the owner's key, and the key is only ever sent to ``API_ROOT``'s host."""

    def __init__(self, api_key: str, http: httpx.Client | None = None, *, base_url: str = API_ROOT) -> None:
        if not (api_key or "").strip():
            raise ValueError(f"ScrapeCreators needs {KEY_ENV}")
        self._key = api_key.strip()
        self._root = base_url.rstrip("/")
        self._http = http if http is not None else httpx.Client(timeout=_TIMEOUT, follow_redirects=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kw: Any) -> ScrapeCreators | None:
        """The client for ``SCRAPECREATORS_API_KEY``; None when it is not set (the owner has not added the secret)."""
        env = os.environ if env is None else env
        key = (env.get(KEY_ENV) or "").strip()
        return cls(key, **kw) if key else None

    def __repr__(self) -> str:
        return f"ScrapeCreators(base_url={self._root!r})"

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "***")

    def _get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        query = {k: ("true" if v is True else "false" if v is False else v) for k, v in params.items() if v is not None}
        try:
            response = self._http.get(f"{self._root}{path}", params=query, headers={"x-api-key": self._key, "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise ScrapeCreatorsError(f"ScrapeCreators {path}: no answer ({type(e).__name__})") from None
        body = self._scrub(response.text.strip()[:_BODY_CHARS])
        if not response.is_success:
            raise ScrapeCreatorsError(f"ScrapeCreators {path} answered HTTP {response.status_code}: {body}", response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise ScrapeCreatorsError(f"ScrapeCreators {path}: the answer is not JSON: {body}", response.status_code) from None
        if not isinstance(data, dict):
            raise ScrapeCreatorsError(f"ScrapeCreators {path}: the answer is not a JSON object", response.status_code)
        if data.get("success") is False:
            raise ScrapeCreatorsError(f"ScrapeCreators {path} said it failed: {body}", response.status_code)
        return data

    # ---- the searches (metadata only) ------------------------------------------------------------------------------

    def tiktok_keyword(self, query: str) -> dict[str, Any]:
        return self._get("/v1/tiktok/search/keyword", {"query": query, "date_posted": "this-week", "sort_by": "most-liked", "trim": True})

    def tiktok_trending(self, region: str) -> dict[str, Any]:
        return self._get("/v1/tiktok/get-trending-feed", {"region": region, "trim": True})

    def instagram_reels(self, query: str) -> dict[str, Any]:
        return self._get("/v2/instagram/reels/search", {"query": query, "date_posted": "last-week"})

    def instagram_trending(self) -> dict[str, Any]:
        return self._get("/v1/instagram/reels/trending", {})

    # ---- one post (the fetch fallback of a dropped link) -------------------------------------------------------------

    def tiktok_video(self, url: str, *, download_media: bool = False) -> dict[str, Any]:
        return self._get("/v2/tiktok/video", {"url": url, "download_media": download_media or None})  # untrimmed: the video addresses

    def instagram_post(self, url: str, *, download_media: bool = False) -> dict[str, Any]:
        return self._get("/v1/instagram/post", {"url": url, "download_media": download_media or None})

    def download_post(self, url: str, platform: str, dest: Path | str) -> dict[str, Any]:
        """The ONE post at ``url`` (its canonical TikTok / Instagram Reel link) with ``download_media=true``, its video saved to
        ``dest``: ``{"credits", "media_url", "bytes"}``. ``ScrapeCreatorsError`` when the API has no usable copy or the download
        fails (``dest`` is then not left behind)."""
        if platform == "tiktok":
            data = self.tiktok_video(url, download_media=True)
        elif platform == "instagram":
            data = self.instagram_post(url, download_media=True)
        else:
            raise ScrapeCreatorsError(f"ScrapeCreators has no single-post download for {platform}")
        media = media_url(data, platform)
        size = self._download(media, Path(dest))
        return {"credits": credits_of(data), "media_url": media, "bytes": size}

    def _download(self, url: str, dest: Path) -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(f".{dest.name}.part")
        size = 0
        try:
            # no key, no cookies: the hosted copy is a plain https file (redirects followed, https only)
            with self._http.stream("GET", url, timeout=_MEDIA_TIMEOUT, follow_redirects=True) as response:
                if not response.is_success:
                    raise ScrapeCreatorsError(f"the copy's download answered HTTP {response.status_code}", response.status_code)
                if response.url.scheme != "https":
                    raise ScrapeCreatorsError("the copy's download left https")
                with part.open("wb") as out:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > MEDIA_MAX_BYTES:
                            raise ScrapeCreatorsError(f"the copy is over {MEDIA_MAX_BYTES // (1024 * 1024)} MB")
                        out.write(chunk)
            if size == 0:
                raise ScrapeCreatorsError("the copy is empty")
            os.replace(part, dest)
        except httpx.HTTPError as e:
            raise ScrapeCreatorsError(f"the copy's download failed ({type(e).__name__})") from None
        finally:
            part.unlink(missing_ok=True)
        return size


def _walk_urls(data: Any) -> list[str]:
    out: list[str] = []
    if isinstance(data, Mapping):
        for value in data.values():
            out.extend(_walk_urls(value))
    elif isinstance(data, list):
        for value in data:
            out.extend(_walk_urls(value))
    elif isinstance(data, str) and data.startswith("https://"):
        out.append(data)
    return out


def _first(urls: Any) -> str | None:
    return _https(urls[0]) if isinstance(urls, list) and urls else None


def media_url(data: Mapping[str, Any], platform: str) -> str:
    """The video of a single-post answer: the permanent copy ``download_media=true`` hosts (an https video file on a
    ``*.supabase.co`` host, wherever the answer carries it), else the documented fields: TikTok
    ``aweme_detail.video.download_no_watermark_addr.url_list[0]``, or ``play_addr`` when TikTok says the video has no watermark
    (never a watermarked copy); Instagram ``data.xdt_shortcode_media.video_url``. ``ScrapeCreatorsError`` when there is none."""
    for url in _walk_urls(data):
        parts = urlsplit(url)
        if (parts.hostname or "").endswith(".supabase.co") and parts.path.lower().endswith(VIDEO_SUFFIXES):
            return url
    if platform == "tiktok":
        detail = data.get("aweme_detail") if isinstance(data.get("aweme_detail"), Mapping) else {}
        video = detail.get("video") if isinstance(detail.get("video"), Mapping) else {}
        clean = video.get("download_no_watermark_addr") if isinstance(video.get("download_no_watermark_addr"), Mapping) else {}
        if (found := _first(clean.get("url_list"))) is not None:
            return found
        play = video.get("play_addr") if isinstance(video.get("play_addr"), Mapping) else {}
        if video.get("has_watermark") is False and (found := _first(play.get("url_list"))) is not None:
            return found
        raise ScrapeCreatorsError("ScrapeCreators gave no copy of this TikTok without its watermark")
    inner = data.get("data") if isinstance(data.get("data"), Mapping) else {}
    media = inner.get("xdt_shortcode_media") if isinstance(inner.get("xdt_shortcode_media"), Mapping) else {}
    if media.get("is_video") is not False and (found := _https(media.get("video_url"))) is not None:
        return found
    raise ScrapeCreatorsError("ScrapeCreators gave no video for this Instagram post")


# ---- parsing (one item of an answer -> a Hit, or the reason it is skipped) -------------------------------------------------------


def _count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and math.isfinite(value) and value >= 0:
        return int(value)
    return None


def _followers(value: Any) -> int | None:
    n = _count(value)
    return n if n else None  # 0 is what a trimmed answer says when it does not know: unknown, never an infinite reach


def _when(unix: Any, iso: Any) -> datetime | None:
    if isinstance(unix, (int, float)) and not isinstance(unix, bool) and unix > 0:
        return datetime.fromtimestamp(unix, tz=timezone.utc)
    if isinstance(iso, str) and iso:
        try:
            at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)
    return None


def _text(value: Any, limit: int | None = None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value[:limit] if limit else value


def reach_of(views: int | None, followers: int | None) -> float | None:
    return views / followers if views is not None and followers else None


def _hit(platform: str, raw_url: Any, *, keyword: str | None, character: str | None, **fields: Any) -> Hit | str:
    try:
        found, canonical = parse_video_url(raw_url if isinstance(raw_url, str) else "")
    except ValueError:
        return "bad_url"
    if found != platform:
        return "bad_url"
    return Hit(
        platform=platform, url=canonical, keyword=keyword, character_slug=character,
        reach=reach_of(fields.get("views"), fields.get("followers")), **fields,
    )  # fmt: skip


def parse_tiktok(item: Mapping[str, Any], *, keyword: str | None, character: str | None) -> Hit | str:
    """A TikTok search or trending item (``aweme``) as a ``Hit``, or the skip reason (``photo``, ``ad``, ``bad_url``)."""
    if item.get("image_post_info"):
        return "photo"
    if item.get("is_ad") is True or item.get("is_paid_partnership") is True:
        return "ad"
    author = item.get("author") if isinstance(item.get("author"), Mapping) else {}
    stats = item.get("statistics") if isinstance(item.get("statistics"), Mapping) else {}
    video = item.get("video") if isinstance(item.get("video"), Mapping) else {}
    music = item.get("music") if isinstance(item.get("music"), Mapping) else {}
    cover = video.get("cover") if isinstance(video.get("cover"), Mapping) else {}
    handle = _text(author.get("unique_id"))
    url = item.get("url")
    if not isinstance(url, str) and handle and item.get("aweme_id"):
        url = f"https://www.tiktok.com/@{handle}/video/{item['aweme_id']}"
    if isinstance(url, str) and "/photo/" in url:
        return "photo"
    duration = video.get("duration")  # TikTok gives milliseconds
    hit = _hit(
        "tiktok", url, keyword=keyword, character=character,
        creator_handle=None, followers=_followers(author.get("follower_count")),
        views=_count(stats.get("play_count")), likes=_count(stats.get("digg_count")), comments=_count(stats.get("comment_count")),
        shares=_count(stats.get("share_count")), saves=_count(stats.get("collect_count")),
        posted_at=_when(item.get("create_time"), item.get("create_time_utc")), caption=_text(item.get("desc"), HIT_CAPTION_MAX),
        sound=_text(music.get("title")),
        duration_s=round(duration / 1000, 3) if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0 else None,
        thumbnail_url=_first(cover.get("url_list")),
    )  # fmt: skip
    if isinstance(hit, Hit):
        hit.creator_handle = "@" + (handle or hit.url.split("/@", 1)[1].split("/", 1)[0]).lower()  # TikTok handles ignore case
    return hit


def parse_instagram(item: Mapping[str, Any], *, keyword: str | None, character: str | None) -> Hit | str:
    """An Instagram reel (the search's or the trending page's shape) as a ``Hit``, or the skip reason."""
    if item.get("is_video") is False or item.get("media_type") in (1, 8) or item.get("product_type") == "carousel_container":
        return "photo"
    if item.get("is_ad") is True or item.get("is_paid_partnership") is True:
        return "ad"
    owner = item.get("owner") if isinstance(item.get("owner"), Mapping) else item.get("user") if isinstance(item.get("user"), Mapping) else {}
    followed = owner.get("edge_followed_by") if isinstance(owner.get("edge_followed_by"), Mapping) else {}
    music = item.get("clips_music_attribution_info") if isinstance(item.get("clips_music_attribution_info"), Mapping) else {}
    url = item.get("url")
    if not isinstance(url, str) and _text(item.get("shortcode")):
        url = f"https://www.instagram.com/reel/{item['shortcode']}/"
    views = next((v for v in (_count(item.get(k)) for k in ("play_count", "ig_play_count", "video_play_count", "video_view_count")) if v), None)
    taken = item.get("taken_at")
    sound = _text(music.get("song_name")) or ("Original audio" if music.get("uses_original_audio") is True else None)
    candidates = item.get("image_versions2", {}).get("candidates") if isinstance(item.get("image_versions2"), Mapping) else None
    thumb = next(
        (u for u in (_https(item.get("thumbnail_src")), _https(item.get("image_url")), _https(item.get("display_url"))) if u),
        _https(candidates[0].get("url")) if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping) else None,
    )
    duration = item.get("video_duration")
    hit = _hit(
        "instagram", url, keyword=keyword, character=character,
        creator_handle=f"@{owner['username'].lower()}" if _text(owner.get("username")) else None,
        followers=_followers(owner.get("follower_count")) or _followers(followed.get("count")),
        views=views, likes=_count(item.get("like_count")), comments=_count(item.get("comment_count")),
        posted_at=_when(taken if isinstance(taken, (int, float)) else item.get("taken_at_timestamp"), taken if isinstance(taken, str) else None),
        caption=_text(item.get("caption"), HIT_CAPTION_MAX), sound=sound,
        duration_s=float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0 else None,
        thumbnail_url=thumb,
    )  # fmt: skip
    return hit


def skip_reason(hit: Hit, now: datetime) -> str | None:
    """Why a NEW hit is not kept, past what parsing refused: ``too_long`` (over 60 s), ``too_old`` (over 14 days)."""
    if hit.duration_s is not None and hit.duration_s > MAX_SECONDS:
        return "too_long"
    if hit.posted_at is not None and now - hit.posted_at > timedelta(days=MAX_AGE_DAYS):
        return "too_old"
    return None


def _scale(value: float, low: float, high: float) -> float:
    return min(1.0, max(0.0, (value - low) / (high - low)))


def hit_score(hit: Hit, now: datetime) -> int:
    """0-100 from views, reach and freshness (see the module doc): reach over raw views, fresh over old."""
    views = hit.views if hit.views is not None else (hit.likes * LIKES_TO_VIEWS if hit.likes is not None else None)
    v = _scale(math.log10(views), 4.0, 7.0) if views else 0.0
    reach = views / hit.followers if views is not None and hit.followers else None
    r = _scale(math.log10(reach), -1.0, 1.5) if reach else (0.0 if reach == 0 else 0.5)
    if hit.posted_at is None:
        f = 0.5
    else:
        age_days = max(0.0, (now - hit.posted_at).total_seconds() / 86400)
        f = _scale(MAX_AGE_DAYS - age_days, 0.0, MAX_AGE_DAYS)
    return int(round(30 * v + 40 * r + 30 * f))


# ---- the configuration -------------------------------------------------------------------------------------------------------


def load_scan(path: Path | str | None = None) -> dict[str, Any]:
    return json.loads(Path(path or SCAN_PATH).read_text(encoding="utf-8"))


def _words(raw: Any, limit: int | None = None) -> list[str]:
    words = [w.strip() for w in raw if isinstance(w, str) and w.strip()] if isinstance(raw, list) else []
    return words[:limit] if limit else words


def hits_config(scan: Mapping[str, Any]) -> dict[str, Any]:
    """``config/scan.json`` ``hits``, with the defaults (a cap of 25 credits, 3 drops a character and 3 general ones a day)."""
    raw = scan.get("hits") if isinstance(scan.get("hits"), Mapping) else {}
    out: dict[str, Any] = {}
    for name, default in DEFAULTS.items():
        value = raw.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"config/scan.json hits.{name} must be a whole number of 0 or more, got {value!r}")
        out[name] = value
    keywords = raw.get("keywords") if isinstance(raw.get("keywords"), Mapping) else {}
    out["keywords"] = {slug: _words(words, KEYWORDS_PER_CHARACTER) for slug, words in keywords.items() if not str(slug).startswith("_")}
    general = raw.get("general") if isinstance(raw.get("general"), Mapping) else {}
    out["general_keywords"] = _words(general.get("keywords"))
    regions = general.get("tiktok_regions", list(TIKTOK_REGIONS))
    out["tiktok_regions"] = [r.strip().upper() for r in _words(regions) if len(r.strip()) == 2]
    out["instagram_trending"] = general.get("instagram_trending", True) is not False
    return out


# ---- the pull ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    """One API call of the day's plan: ``kind`` tiktok_trending | instagram_trending | tiktok_search | instagram_search."""

    kind: str
    query: str | None = None
    character: str | None = None

    @property
    def label(self) -> str:
        if self.kind == "tiktok_trending":
            return f"tiktok trending {self.query}"
        if self.kind == "instagram_trending":
            return "instagram trending"
        platform = self.kind.split("_", 1)[0]
        return f"{platform} search '{self.query}'" + (f" ({self.character})" if self.character else "")

    @property
    def keyword(self) -> str:
        return self.query if self.kind.endswith("_search") else self.label

    def run(self, client: ScrapeCreators) -> dict[str, Any]:
        if self.kind == "tiktok_trending":
            return client.tiktok_trending(self.query or "")
        if self.kind == "instagram_trending":
            return client.instagram_trending()
        if self.kind == "tiktok_search":
            return client.tiktok_keyword(self.query or "")
        return client.instagram_reels(self.query or "")

    def items(self, data: Mapping[str, Any]) -> list[Any]:
        if self.kind == "tiktok_trending":
            found = data.get("aweme_list")
        elif self.kind == "tiktok_search":
            found = data.get("search_item_list")
        elif self.kind == "instagram_search":
            found = data.get("reels")
        else:
            inner = data.get("data") if isinstance(data.get("data"), Mapping) else {}
            found = inner.get("reels", data.get("reels"))
        return [i for i in found if isinstance(i, Mapping)] if isinstance(found, list) else []

    def parse(self, item: Mapping[str, Any]) -> Hit | str:
        parser = parse_tiktok if self.kind.startswith("tiktok") else parse_instagram
        return parser(item, keyword=self.keyword, character=self.character)


def live_characters(store: Store) -> list[str]:
    return sorted(c.slug for c in store.characters() if c.status == "live")


def plan_calls(store: Store, cfg: Mapping[str, Any]) -> list[Call]:
    """The day's calls in order (see the module doc): the trending feeds, then each round of the live characters' keywords
    (TikTok, then Instagram) followed by one broad search, then the broad searches left."""
    plan = [Call("tiktok_trending", region) for region in cfg["tiktok_regions"]]
    if cfg["instagram_trending"]:
        plan.append(Call("instagram_trending"))
    crew = [(slug, cfg["keywords"].get(slug, [])) for slug in live_characters(store)]
    general = list(cfg["general_keywords"])
    for i in range(KEYWORDS_PER_CHARACTER):
        for slug, words in crew:
            if i < len(words):
                plan += [Call("tiktok_search", words[i], slug), Call("instagram_search", words[i], slug)]
        if i < len(general):
            plan.append(Call("tiktok_search", general[i]))
    plan += [Call("tiktok_search", word) for word in general[KEYWORDS_PER_CHARACTER:]]
    return plan


def _merge(old: Hit, new: Hit, now: datetime) -> Hit:
    """The stored hit with what this pull saw (the store applies the same rules: ``Store.upsert_hit``), scored again."""
    merged = Hit(**{
        **vars(old),
        **{k: v for k, v in vars(new).items() if v is not None and k in HIT_REFRESHED},
        "character_slug": old.character_slug or new.character_slug, "keyword": old.keyword or new.keyword, "last_seen": now,
    })  # fmt: skip
    merged.reach = reach_of(merged.views, merged.followers)
    merged.score = hit_score(merged, now)
    return merged


def _creator_kept(store: Store, hit: Hit, now: datetime) -> int:
    if not hit.creator_handle:
        return 0
    since = now - timedelta(days=CREATOR_DAYS)
    return sum(
        1 for h in store.list_hits(platform=hit.platform, creator_handle=hit.creator_handle)
        if h.created_at is not None and h.created_at >= since
    )  # fmt: skip


def pull(store: Store, client: ScrapeCreators, scan_config: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Run the day's calls (see the module doc) and keep what they found. Returns ``{"calls", "credits", "kept", "updated",
    "skipped": {reason: n}, "stopped": "cap" | None, "errors": [{"call", "error"}]}``: ``calls`` are the calls that answered.
    A refused key (401/403) stops the run; any other failed call is listed and the run goes on."""
    cfg = hits_config(scan_config)
    cap = cfg["daily_credit_cap"]
    plan = plan_calls(store, cfg)
    calls = spent = kept = updated = 0
    skipped: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    stopped: str | None = None
    seen: set[str] = set()
    for call in plan:
        if spent >= cap:
            stopped = "cap"
            break
        try:
            data = call.run(client)
        except ScrapeCreatorsError as e:
            errors.append({"call": call.label, "error": str(e)[:300]})
            if e.status in (401, 403):
                break  # the key is refused: no other call would work
            continue
        calls += 1
        spent += credits_of(data)
        with store.transaction():  # one connection for the call's reads and writes
            for item in call.items(data):
                try:
                    parsed = call.parse(item)
                except (ValueError, TypeError, OverflowError, OSError):  # one odd item never stops the run
                    parsed = "unreadable"
                if isinstance(parsed, str):
                    skipped[parsed] += 1
                    continue
                if parsed.url in seen:
                    skipped["duplicate"] += 1
                    continue
                seen.add(parsed.url)
                old = next(iter(store.list_hits(url=parsed.url)), None)
                if old is not None:
                    store.upsert_hit(_merge(old, parsed, now))
                    updated += 1
                    continue
                reason = skip_reason(parsed, now)
                if reason is None and _creator_kept(store, parsed, now) >= CREATOR_LIMIT:
                    reason = "creator"
                if reason is not None:
                    skipped[reason] += 1
                    continue
                parsed.score = hit_score(parsed, now)
                parsed.created_at = parsed.last_seen = now
                store.upsert_hit(parsed)
                kept += 1
    return {
        "calls": calls, "credits": spent, "kept": kept, "updated": updated, "skipped": dict(sorted(skipped.items())),
        "stopped": stopped, "errors": errors,
    }  # fmt: skip


# ---- auto-filing -------------------------------------------------------------------------------------------------------------------


def filed_today(store: Store, now: datetime) -> Counter[str]:
    """How many drops the job filed today (London) per lane (a character's slug, or ``general``)."""
    today = now.astimezone(LONDON).date()
    out: Counter[str] = Counter()
    for f in store.list_favorites():
        if not is_drop(f.proposal):
            continue
        d = f.proposal["drop"]
        lane = d.get("hit", {}).get("lane") if isinstance(d.get("hit"), Mapping) else None
        at = filed_at(f)
        if d.get("auto_filed") is True and isinstance(lane, str) and at is not None and at.astimezone(LONDON).date() == today:
            out[lane] += 1
    return out


def auto_file(
    store: Store, scan_config: Mapping[str, Any], now: datetime, *, characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR,
) -> list[dict[str, Any]]:
    """File the best new hits as drops (see the module doc); ``[{"hit_id", "pick_id", "character", "provisional"}]`` in the
    order they were filed (``character`` None for the general lane; ``provisional`` is who the drop waits under)."""
    cfg = hits_config(scan_config)
    live = live_characters(store)
    takers = {c.slug for c in drop.roster(store, characters_dir)}
    used = filed_today(store, now)
    fresh = sorted(store.list_hits(status="new"), key=lambda h: (-h.score, -(h.views or 0), h.url))
    filed: list[dict[str, Any]] = []
    for lane in [*live, "general"]:
        room = (cfg["auto_file_general"] if lane == "general" else cfg["auto_file_per_character"]) - used[lane]
        for hit in fresh:
            if room <= 0:
                break
            if hit.character_slug != (None if lane == "general" else lane):
                continue
            with store.transaction():
                if store.list_favorites(url=hit.url):  # already a pick (any status): never filed twice
                    store.update_hit(hit.id, status="dropped")
                    continue
                pick, _ = drop.add_drop(
                    store, None, hit.url, now, characters_dir=characters_dir, auto_filed=True,
                    provisional_slug=lane if lane in takers else None, hit={"id": hit.id, "lane": lane},
                )  # fmt: skip
                store.update_hit(hit.id, status="dropped")
            filed.append({
                "hit_id": hit.id, "pick_id": pick.id, "character": None if lane == "general" else lane, "provisional": pick.character_slug,
            })  # fmt: skip
            room -= 1
    return filed


# ---- CLI ---------------------------------------------------------------------------------------------------------------------------

app = typer.Typer(
    help="The cloud hits job: the top TikTok and Instagram posts of our niches from ScrapeCreators (metadata only, no Mac), the "
    "best filed as drops. Prints JSON.",
    no_args_is_help=True,
)

NO_KEY = f"{KEY_ENV} is not set: no hits were pulled (gh secret set {KEY_ENV})"


@app.command("pull")
def pull_command(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the day's calls only: nothing is called, spent or written.")] = False,
    file: Annotated[bool, typer.Option("--file/--no-file", help="After the pull, file the best new hits as drops (the default).")] = True,
) -> None:
    """Pull today's hits (at most hits.daily_credit_cap credits) and file the best as drops. Without SCRAPECREATORS_API_KEY: a
    notice and exit 0. Exit 1 only when not one call worked."""
    scan = load_scan()
    try:
        cfg = hits_config(scan)
    except ValueError as e:
        fail(str(e))
    store = open_store()
    if dry_run:
        emit({"dry_run": True, "cap": cfg["daily_credit_cap"], "plan": [c.label for c in plan_calls(store, cfg)]})
        return
    client = ScrapeCreators.from_env()
    if client is None:
        typer.echo(f"::notice::{NO_KEY}", err=True)
        emit({"skipped_run": NO_KEY, "calls": 0, "credits": 0, "kept": 0, "updated": 0, "skipped": {}, "stopped": None,
              "errors": [], "filed": []})  # fmt: skip
        return
    now = now_london()
    out = pull(store, client, scan, now)
    filed: list[dict[str, Any]] = []
    if file:
        try:
            filed = auto_file(store, scan, now)
        except ValueError as e:  # every character paused, say: the pull is kept, nothing is filed
            out["file_error"] = str(e)[:300]
    emit({**out, "filed": filed})
    if out["calls"] == 0 and out["errors"]:
        raise typer.Exit(1)


@app.command("list")
def list_command(
    status: Annotated[str | None, typer.Option("--status", help="new, dropped or dismissed.")] = None,
    character_slug: Annotated[str | None, typer.Option("--character", help="A character's slug (his lane).")] = None,
    general: Annotated[bool, typer.Option("--general", help="Only the general lane (no character).")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, help="At most this many, best score first.")] = 50,
) -> None:
    """The stored hits, best score first."""
    filters: dict[str, Any] = {}
    if status is not None:
        filters["status"] = status
    if general:
        filters["character_slug"] = None
    elif character_slug is not None:
        filters["character_slug"] = character_slug
    rows = sorted(open_store().list_hits(**filters), key=lambda h: (-h.score, h.url))[:limit]
    emit([vars(h) for h in rows])


__all__ = [
    "Call", "ScrapeCreators", "ScrapeCreatorsError", "auto_file", "credits_of", "hit_score", "hits_config", "media_url",
    "parse_instagram", "parse_tiktok", "plan_calls", "pull", "skip_reason",
]

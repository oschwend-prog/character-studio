"""The Postiz adapter: ``postiz upload`` then ``postiz posts:create``, driven through the Postiz CLI.

``PostizPublisher(run=subprocess.run)`` implements ``Publisher``. One ``publish`` call:

1. fetches the master from its signed URL into a private temp folder (Postiz only accepts media it
   hosted itself, so the file has to pass through ``postiz upload``; Rule 2 of the postiz skill),
2. ``postiz upload <file>`` and reads the ``path`` it returns, then deletes the temp folder,
3. ``postiz posts:create -c <caption + hashtags> -s <now> -i <integration> -m <path> --settings
   <json>``, with the per-platform settings below, and reads the Postiz post id from its output.

The posts are scheduled for *now*: the 15-minute publish job decides when a post is due, Postiz
just sends it. ``posted`` in our database therefore means "Postiz accepted it", and the
``platform_post_id`` is the Postiz post id (what ``postiz analytics:post`` takes).

The CLI prints a status line before its JSON (``✅ File uploaded successfully!``); the JSON is
picked out of stdout, with or without that line. Credentials are the CLI's own: ``POSTIZ_API_KEY``
from the environment (``bin/studio`` exports it from the Keychain).

**What is safe to retry.** A failed fetch and a failed or timed-out upload happen before any post
exists: plain ``PostizError``, retried by ``publish_due``. So is a ``posts:create`` whose output shows
a definite 4xx (``API Error (4xx)``, except 408 and 409): Postiz refused the request. Every other way
``posts:create`` can end may already have committed server-side, and Postiz has no idempotency key: a
timeout (408 Request Timeout too), a 409 Conflict, a 5xx (502, 524...), a network failure
(``Request failed: socket hang up``), any other non-zero exit, and exit 0 without a post id we can read.
Those raise ``UncertainPublish`` and end in ``needs_check``, never in a retry.

A caption whose composed text (caption + AI disclosure + hashtags) is over 2,200 characters raises
``ValueError`` before anything is fetched or uploaded (``studio.captions``): a plain failed attempt.

The signed URL carries a token: it is never put in an error message.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from studio.captions import (  # noqa: F401 - re-exported: the text rules live in studio.captions
    AI_DISCLOSURE,
    CAPTION_LIMIT,
    caption_length,
    clean_tags,
    compose_content,
)
from studio.models import Platform
from studio.publish.base import PublishResult, UncertainPublish

# Rule 3 of the postiz skill: DIRECT_POST publishes; UPLOAD only drops a draft in the TikTok inbox
# while Postiz still reports success. Rule 4: a key the integration does not know is silently
# dropped, so these keys are pinned to the Postiz provider DTOs (tiktok.dto.ts / instagram.dto.ts).
# VERIFY at go-live (Task 16): postiz integrations:settings <id>
TIKTOK_SETTINGS: dict[str, Any] = {
    "content_posting_method": "DIRECT_POST",
    "privacy_level": "PUBLIC_TO_EVERYONE",
    "autoAddMusic": "no",  # required by the DTO; "no" keeps TikTok from adding third-party music
    "video_made_with_ai": True,  # TikTok's "AI-generated content" label: always on
    "duet": True,
    "stitch": True,
    "comment": True,
    "brand_content_toggle": False,
    "brand_organic_toggle": False,
}

# Postiz publishes a single video with post_type "post" as a Reel (media_type=REELS); the only other
# value is "story". The Instagram AI label is account-level (set when the account is created).
# VERIFY at go-live (Task 16): postiz integrations:settings <id>
INSTAGRAM_SETTINGS: dict[str, Any] = {"post_type": "post"}

PLATFORM_SETTINGS: dict[Platform, dict[str, Any]] = {
    Platform.tiktok: TIKTOK_SETTINGS,
    Platform.instagram: INSTAGRAM_SETTINGS,
}

# The Postiz CLI prints "Request failed: API Error (<status>): ..." for an HTTP error answer. A 4xx is a
# definite refusal, except 408 (Request Timeout: the server gave up waiting, the create may have gone
# through) and 409 (Conflict: it may be the post already existing): those stay uncertain.
_DEFINITE_REJECTION = re.compile(r"API Error \((?!408\)|409\))4\d\d\)")

UPLOAD_TIMEOUT_S = 900
CREATE_TIMEOUT_S = 180
_OUTPUT_CHARS = 500
_CHUNK = 1024 * 1024
_FETCH_TIMEOUT = httpx.Timeout(30.0, read=600.0)


class PostizError(RuntimeError):
    """A Postiz CLI step or the media fetch failed before anything was published."""


def download_media(
    url: str, dest: Path | str, *, transport: httpx.BaseTransport | None = None
) -> None:
    """Fetch ``url`` (a Storage signed URL: https, or file:// for ``LocalStorage``) into ``dest``."""
    dest = Path(dest)
    parsed = urlparse(url)
    if parsed.scheme == "file":
        shutil.copyfile(url2pathname(parsed.path), dest)
        return
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"media url has an unsupported scheme {parsed.scheme!r}")
    try:
        client = httpx.Client(transport=transport, timeout=_FETCH_TIMEOUT, follow_redirects=True)
        with client, client.stream("GET", url) as response:
            if not response.is_success:
                raise PostizError(f"could not fetch the clip master: HTTP {response.status_code}")
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(_CHUNK):
                    out.write(chunk)
    except httpx.HTTPError as e:
        # Not str(e): some httpx errors quote the (token-carrying) URL.
        raise PostizError(f"could not fetch the clip master: {type(e).__name__}") from None


def _json_in(text: str) -> Any:
    """The first JSON value in ``text`` (the CLI prints a status line before it)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            return decoder.raw_decode(text, match.start())[0]
        except ValueError:
            continue
    raise ValueError("no JSON in the output")


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    text = (proc.stderr or proc.stdout or "").strip()
    return text[-_OUTPUT_CHARS:] if text else "no output"


def _post_id(payload: Any) -> tuple[str | None, str | None]:
    """(Postiz post id, url) from ``posts:create`` output: ``[{"postId": ..., "integration": ...}]``."""
    for item in payload if isinstance(payload, list) else [payload]:
        if not isinstance(item, dict):
            continue
        for key in ("postId", "id"):
            value = item.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
                url = item.get("url")
                return str(value), url if isinstance(url, str) and url else None
    return None, None


class PostizPublisher:
    """``Publisher`` over the Postiz CLI. ``run`` is ``subprocess.run`` (injected in tests)."""

    def __init__(
        self,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        *,
        fetch: Callable[[str, Path], None] = download_media,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        executable: str = "postiz",
    ) -> None:
        self._run = run
        self._fetch = fetch
        self._clock = clock
        self._exe = executable

    def publish(
        self,
        *,
        platform: Platform,
        integration_id: str,
        media_url: str,
        caption: str,
        hashtags: list[str],
        ai_label: bool,
    ) -> PublishResult:
        platform = Platform(platform)
        if not ai_label:
            raise ValueError("refusing to publish without the AI label")
        if not integration_id:
            raise ValueError("no Postiz integration id for this account")
        if not caption.strip() and not clean_tags(hashtags):
            raise ValueError("nothing to post: caption and hashtags are empty")
        content = compose_content(caption, hashtags)  # ValueError when over the limit: nothing sent
        settings = PLATFORM_SETTINGS[platform]  # never mutated, only serialised

        with tempfile.TemporaryDirectory(prefix="studio-publish-") as tmp:
            local = Path(tmp) / f"master{Path(urlparse(media_url).path).suffix.lower() or '.mp4'}"
            self._fetch(media_url, local)
            uploaded = self._upload(local)
        return self._create(content, integration_id, uploaded, settings)

    # ---- the two CLI steps ----------------------------------------------------------------

    def _call(self, argv: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        # Explicit utf-8: the CLI prints emoji, and a locale that cannot decode them must not raise
        # *after* posts:create has already created the post (that would look like a retriable failure).
        return self._run(
            argv,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )

    def _upload(self, local: Path) -> str:
        argv = [self._exe, "upload", str(local)]
        try:
            proc = self._call(argv, UPLOAD_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise PostizError(f"postiz upload timed out after {UPLOAD_TIMEOUT_S} s") from None
        if proc.returncode != 0:
            raise PostizError(f"postiz upload failed (exit {proc.returncode}): {_tail(proc)}")
        try:
            payload = _json_in(proc.stdout or "")
        except ValueError:
            payload = None
        path = payload.get("path") if isinstance(payload, dict) else None
        if not isinstance(path, str) or not path:
            raise PostizError(f"postiz upload returned no path: {_tail(proc)}")
        return path

    def _create(
        self, content: str, integration_id: str, media_path: str, settings: dict[str, Any]
    ) -> PublishResult:
        argv = [
            self._exe, "posts:create",
            "-c", content,
            "-s", self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "-i", integration_id,
            "-m", media_path,
            "--settings", json.dumps(settings),
        ]  # fmt: skip
        try:
            proc = self._call(argv, CREATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise UncertainPublish(
                f"postiz posts:create timed out after {CREATE_TIMEOUT_S} s: the post may exist"
            ) from None
        if proc.returncode != 0:
            detail = f"postiz posts:create failed (exit {proc.returncode}): {_tail(proc)}"
            if _DEFINITE_REJECTION.search(f"{proc.stderr or ''}\n{proc.stdout or ''}"):
                raise PostizError(detail)  # Postiz refused the request: nothing was created
            raise UncertainPublish(f"{detail} (the post may exist)")  # 5xx, network, anything else
        try:
            post_id, url = _post_id(_json_in(proc.stdout or ""))
        except ValueError:
            post_id, url = None, None
        if post_id is None:
            raise UncertainPublish(
                f"postiz posts:create exited 0 but returned no post id: {_tail(proc)}"
            )
        return PublishResult(platform_post_id=post_id, url=url)

"""Higgsfield's Genjutsu **Object swap** over its REST API ("Drop a video", plan 2026-10-06).

The cloud make job (``studio drop make``) sends one owner-approved clip and the character's reference images to
``POST https://api.higgsfield.ai/higgsfield/genjutsu/object-swap/v1.0`` (docs.higgsfield.ai/docs/models/genjutsu/object-swap):

* header ``Authorization: Key <HF_API_KEY_ID>:<HF_API_KEY_SECRET>`` (from the environment only: GitHub secrets in CI), and an
  ``Idempotency-Key`` the caller chooses and stores BEFORE the request;
* JSON ``video_url`` (a public URL: our signed Storage URL), ``image_urls`` (1-8 public URLs), ``prompt`` (optional, at most
  10,000 characters) and ``resolution`` (``480p``, ``720p`` or ``1080p``). The video must be at least 4 s and 409,600 pixels a
  frame; the API trims anything over 30 s;
* the answer carries ``request_id`` and ``status_url``; ``status_url`` is polled until a terminal status:
  ``queued`` / ``in_progress`` (still going), ``completed`` (``video.url`` is the output, kept at least 7 days), ``failed``,
  ``nsfw`` (refused by moderation) or ``canceled`` (docs/concepts/requests).

**Never a blind resubmit.** ``submit_object_swap`` makes exactly one POST. A timeout or a dropped connection, when the request
may have reached Higgsfield, raises ``SubmitUncertain`` and is never retried here. The API has no "list my requests" call;
its documented way to resolve an ambiguous submit is the SAME request with the SAME ``Idempotency-Key``, which returns the
original request instead of creating a second one. The caller (``studio.drop``) stores the key before the first POST and only
ever repeats the identical body with that stored key; a new attempt (the one re-roll after a failed quality check) gets a new key.

**Shapes.** Unknown extra fields are ignored; a missing or mistyped field we rely on (``request_id``, ``status_url``, a known
``status``, ``video.url`` of a completed request) raises ``UnexpectedResponse`` naming it. A status URL or an output URL that is
not https is refused, and the key is only ever sent to the API's own host (a ``status_url`` elsewhere is refused, never
followed). Error messages never carry the key.

Tests drive the client with an ``httpx.MockTransport``; nothing here is called without the owner's keys.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

API_ROOT = "https://api.higgsfield.ai"
OBJECT_SWAP_PATH = "/higgsfield/genjutsu/object-swap/v1.0"
RESOLUTIONS = ("480p", "720p", "1080p")
PENDING = frozenset({"queued", "in_progress"})
TERMINAL = frozenset({"completed", "failed", "nsfw", "canceled"})
MAX_IMAGES = 8
URL_MAX = 2083
PROMPT_MAX = 10_000
IDEMPOTENCY_KEY_MAX = 255
POLL_TIMEOUT_S = 25 * 60  # the plan: poll at most 25 minutes, then leave it to the next sweep
POLL_INTERVAL_S = 15.0
MAX_TRANSIENT_POLL_ERRORS = 5  # in a row: a status GET is safe to repeat, a submit never is
OUTPUT_MAX_BYTES = 500 * 1024 * 1024
_BODY_CHARS = 300
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=15.0, read=300.0)


class HiggsfieldError(RuntimeError):
    """A Higgsfield call failed. ``status`` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class UnexpectedResponse(HiggsfieldError):
    """Higgsfield answered, but not in the shape the docs describe: fail loudly, never guess."""


class SubmitUncertain(HiggsfieldError):
    """The submit may have reached Higgsfield (a timeout, a dropped connection, a 5xx). Never resubmit blindly: look it up by
    sending the same body with the same ``idempotency_key`` (see the module doc)."""

    def __init__(self, message: str, idempotency_key: str, status: int | None = None) -> None:
        super().__init__(message, status)
        self.idempotency_key = idempotency_key


class PollTimeout(HiggsfieldError):
    """The request was still not finished when the poll gave up. ``last`` is the last status seen."""

    def __init__(self, message: str, status_url: str, last: str | None) -> None:
        super().__init__(message)
        self.status_url = status_url
        self.last = last


@dataclass(frozen=True)
class Submitted:
    request_id: str
    status_url: str
    status: str
    cancel_url: str | None = None


@dataclass(frozen=True)
class RequestStatus:
    status: str
    request_id: str | None = None
    video_url: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def done(self) -> bool:
        return self.status in TERMINAL

    @property
    def ok(self) -> bool:
        return self.status == "completed"


def _https(url: Any, what: str, *, host: str | None = None) -> str:
    if not isinstance(url, str) or not url or len(url) > URL_MAX or any(c.isspace() for c in url):
        raise ValueError(f"{what} must be an https URL of at most {URL_MAX} characters, got {str(url)[:80]!r}")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"{what} must be an https URL, got {url[:80]!r}")
    if host is not None and parts.hostname.lower() != host:
        raise ValueError(f"{what} must be on {host} (our key is never sent anywhere else), got {parts.hostname!r}")
    return url


class HiggsfieldClient:
    """The Object swap API with one key pair. ``transport`` is for tests (``httpx.MockTransport``)."""

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = API_ROOT,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (key_id or "").strip() or not (key_secret or "").strip():
            raise ValueError("the Higgsfield API needs HF_API_KEY_ID and HF_API_KEY_SECRET")
        self._id, self._secret = key_id.strip(), key_secret.strip()
        self._root = _https(base_url.rstrip("/"), "base_url")
        self._host = (urlsplit(self._root).hostname or "").lower()
        self._client = httpx.Client(transport=transport, timeout=_TIMEOUT, follow_redirects=False)
        self._sleep, self._clock = sleep, clock

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kw: Any) -> HiggsfieldClient | None:
        """The client for ``HF_API_KEY_ID`` / ``HF_API_KEY_SECRET``, or None when either is unset (the owner has not made a key yet)."""
        env = os.environ if env is None else env
        key_id, secret = (env.get("HF_API_KEY_ID") or "").strip(), (env.get("HF_API_KEY_SECRET") or "").strip()
        return cls(key_id, secret, **kw) if key_id and secret else None

    def __repr__(self) -> str:
        return f"HiggsfieldClient(base_url={self._root!r})"

    def close(self) -> None:
        self._client.close()

    # ---- plumbing -----------------------------------------------------------------------------------------------

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Key {self._id}:{self._secret}", "Accept": "application/json"}

    def _scrub(self, text: str) -> str:
        for value in (f"{self._id}:{self._secret}", self._secret, self._id):
            text = text.replace(value, "***")
        return text

    def _body(self, response: httpx.Response) -> str:
        return self._scrub(response.text.strip()[:_BODY_CHARS])

    def _json(self, response: httpx.Response, what: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            raise UnexpectedResponse(f"{what}: the answer is not JSON: {self._body(response)}", response.status_code) from None
        if not isinstance(data, dict):
            raise UnexpectedResponse(f"{what}: the answer is not a JSON object: {self._body(response)}", response.status_code)
        return data

    # ---- submit ---------------------------------------------------------------------------------------------------

    def submit_object_swap(
        self,
        *,
        video_url: str,
        image_urls: Sequence[str],
        prompt: str = "",
        resolution: str = "1080p",
        idempotency_key: str,
    ) -> Submitted:
        """POST one Object swap (exactly one request; see the module doc). ``ValueError`` for bad input (nothing sent),
        ``SubmitUncertain`` when it may have reached Higgsfield, ``HiggsfieldError`` for a refusal (4xx: nothing created),
        ``UnexpectedResponse`` for an answer without ``request_id`` / ``status_url``."""
        _https(video_url, "video_url")
        images = list(image_urls)
        if not 1 <= len(images) <= MAX_IMAGES:
            raise ValueError(f"image_urls takes 1-{MAX_IMAGES} URLs, got {len(images)}")
        for i, url in enumerate(images):
            _https(url, f"image_urls[{i}]")
        if not isinstance(prompt, str) or len(prompt) > PROMPT_MAX:
            raise ValueError(f"prompt must be text of at most {PROMPT_MAX} characters")
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {', '.join(RESOLUTIONS)}, got {resolution!r}")
        key = (idempotency_key or "").strip()
        if not key or len(key) > IDEMPOTENCY_KEY_MAX or any(c.isspace() for c in key):
            raise ValueError("an Idempotency-Key is required (stored before the request): one token, no spaces")
        body = {"video_url": video_url, "image_urls": images, "prompt": prompt, "resolution": resolution}
        headers = {**self._auth(), "Content-Type": "application/json", "Idempotency-Key": key}
        try:
            response = self._client.post(f"{self._root}{OBJECT_SWAP_PATH}", json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise SubmitUncertain(f"the submit timed out ({type(e).__name__}): look it up with the same Idempotency-Key", key) from None
        except httpx.TransportError as e:
            # a connection that failed before anything was sent is safe, but we cannot tell which one it was
            raise SubmitUncertain(f"the submit did not complete ({type(e).__name__}): look it up with the same Idempotency-Key", key) from None
        if response.status_code >= 500:
            raise SubmitUncertain(f"Higgsfield answered HTTP {response.status_code}: {self._body(response)}", key, response.status_code)
        if not response.is_success:
            raise HiggsfieldError(f"Higgsfield refused the submit: HTTP {response.status_code}: {self._body(response)}", response.status_code)
        data = self._json(response, "submit")
        request_id = data.get("request_id")
        status = data.get("status")
        if not isinstance(request_id, str) or not request_id.strip():
            raise UnexpectedResponse(f"submit: no request_id in the answer: {self._body(response)}", response.status_code)
        if not isinstance(status, str) or status not in PENDING | TERMINAL:
            raise UnexpectedResponse(f"submit: unknown status {status!r}", response.status_code)
        try:
            status_url = _https(data.get("status_url"), "status_url", host=self._host)
        except ValueError as e:
            raise UnexpectedResponse(f"submit: {e}", response.status_code) from None
        cancel = data.get("cancel_url")
        return Submitted(request_id.strip(), status_url, status, cancel if isinstance(cancel, str) else None)

    # ---- status and polling -----------------------------------------------------------------------------------------

    def status(self, status_url: str) -> RequestStatus:
        """GET the request's status (safe to repeat). ``HiggsfieldError`` for a failed call, ``UnexpectedResponse`` for a
        shape the docs do not describe (an unknown status, a completed request without ``video.url``)."""
        _https(status_url, "status_url", host=self._host)
        try:
            response = self._client.get(status_url, headers=self._auth())
        except httpx.HTTPError as e:
            raise HiggsfieldError(f"the status call failed ({type(e).__name__})") from None
        if not response.is_success:
            raise HiggsfieldError(f"the status call answered HTTP {response.status_code}: {self._body(response)}", response.status_code)
        return parse_status(self._json(response, "status"))

    def wait(
        self, status_url: str, *, timeout_s: float = POLL_TIMEOUT_S, interval_s: float = POLL_INTERVAL_S,
        on_status: Callable[[RequestStatus], None] | None = None,
    ) -> RequestStatus:
        """Poll ``status_url`` until a terminal status (returned, whatever it is) or ``timeout_s`` (``PollTimeout``).

        A failed status GET (a timeout, a 5xx) is tried again on the next tick, at most ``MAX_TRANSIENT_POLL_ERRORS`` times in
        a row; an unexpected shape or a 4xx stops at once."""
        start = self._clock()
        last: str | None = None
        errors = 0
        while True:
            try:
                st = self.status(status_url)
            except UnexpectedResponse:
                raise
            except HiggsfieldError as e:
                if e.status is not None and 400 <= e.status < 500:
                    raise
                errors += 1
                if errors >= MAX_TRANSIENT_POLL_ERRORS:
                    raise
            else:
                errors = 0
                last = st.status
                if on_status is not None:
                    on_status(st)
                if st.done:
                    return st
            if self._clock() - start + interval_s > timeout_s:
                raise PollTimeout(f"still {last or 'unknown'} after {timeout_s / 60:.0f} min", status_url, last)
            self._sleep(interval_s)

    # ---- the output -------------------------------------------------------------------------------------------------

    def download(self, url: str, dest: Path | str) -> Path:
        """Fetch the output video (``video.url``: Higgsfield's own https URL, no key sent) to ``dest``; a failed download leaves
        no file. ``HiggsfieldError`` for a failure or a file over 500 MB."""
        _https(url, "the output URL")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.part")
        try:
            with self._client.stream("GET", url, timeout=_DOWNLOAD_TIMEOUT) as response:
                if not response.is_success:
                    response.read()
                    raise HiggsfieldError(f"the output download answered HTTP {response.status_code}", response.status_code)
                size = 0
                with tmp.open("wb") as out:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > OUTPUT_MAX_BYTES:
                            raise HiggsfieldError(f"the output is over {OUTPUT_MAX_BYTES // (1024 * 1024)} MB")
                        out.write(chunk)
            os.replace(tmp, dest)
        except httpx.HTTPError as e:
            raise HiggsfieldError(f"the output download failed ({type(e).__name__})") from None
        finally:
            tmp.unlink(missing_ok=True)
        return dest


def parse_status(data: Mapping[str, Any]) -> RequestStatus:
    """A status answer as ``RequestStatus`` (see the module doc); ``UnexpectedResponse`` for any other shape."""
    status = data.get("status")
    if not isinstance(status, str) or status not in PENDING | TERMINAL:
        raise UnexpectedResponse(f"status: unknown status {status!r} (known: {', '.join(sorted(PENDING | TERMINAL))})")
    request_id = data.get("request_id")
    error = data.get("error")
    error_text = error if isinstance(error, str) else (str(error)[:_BODY_CHARS] if error is not None else None)
    video_url: str | None = None
    if status == "completed":
        video = data.get("video")
        url = video.get("url") if isinstance(video, Mapping) else None
        try:
            video_url = _https(url, "video.url")
        except ValueError as e:
            raise UnexpectedResponse(f"status: a completed request without a usable video.url ({e})") from None
    return RequestStatus(
        status=status, request_id=request_id if isinstance(request_id, str) else None, video_url=video_url,
        error=error_text, raw=dict(data),
    )


__all__ = [
    "HiggsfieldClient", "HiggsfieldError", "PollTimeout", "RequestStatus", "SubmitUncertain", "Submitted", "UnexpectedResponse",
    "parse_status",
]

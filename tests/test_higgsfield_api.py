"""``studio.higgsfield_api``: the Object swap client, driven by a fake HTTP transport (no request ever leaves the machine).

What matters: exactly one POST per submit with the key and the Idempotency-Key, never a blind second POST; unknown extra fields
tolerated; a missing or mistyped field we rely on refused loudly; the key never sent to another host or printed.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from studio.higgsfield_api import (
    MAX_TRANSIENT_POLL_ERRORS,
    HiggsfieldClient,
    HiggsfieldError,
    PollTimeout,
    SubmitUncertain,
    UnexpectedResponse,
    parse_status,
)

KEY_ID, SECRET = "kid-123", "s3cr3t-value"
VIDEO = "https://proj.supabase.co/storage/v1/object/sign/sources/owner_inbox/a.mp4?token=t"
IMAGES = ["https://d8j0ntlcm91z4.cloudfront.net/u/master.png", "https://d8j0ntlcm91z4.cloudfront.net/u/sheet.png"]
STATUS_URL = "https://api.higgsfield.ai/requests/REQ1/status"
SUBMITTED = {
    "status": "queued", "request_id": "REQ1", "status_url": STATUS_URL,
    "cancel_url": "https://api.higgsfield.ai/requests/REQ1/cancel", "eta_s": 300,  # an unknown extra field is fine
}


class Fake:
    """A transport that answers from a list of handlers (one per request) and records every request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(request)
        status, body = answer
        if isinstance(body, (dict, list)):
            return httpx.Response(status, json=body)
        return httpx.Response(status, content=body if isinstance(body, bytes) else str(body).encode())


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def client(fake: Fake, clock: Clock | None = None) -> HiggsfieldClient:
    clock = clock or Clock()
    return HiggsfieldClient(KEY_ID, SECRET, transport=httpx.MockTransport(fake), sleep=clock.sleep, clock=clock.now)


def submit(c: HiggsfieldClient, **over):
    kw = {"video_url": VIDEO, "image_urls": IMAGES, "prompt": "replace the man with the butler from the reference images",
          "resolution": "1080p", "idempotency_key": "clip-1-attempt-1"}
    kw.update(over)
    return c.submit_object_swap(**kw)


# ---- submit ------------------------------------------------------------------------------------------------------------


def test_a_submit_is_one_post_with_the_key_the_idempotency_key_and_the_documented_body():
    fake = Fake((200, SUBMITTED))
    got = submit(client(fake))
    assert (got.request_id, got.status_url, got.status) == ("REQ1", STATUS_URL, "queued")
    assert len(fake.requests) == 1
    r = fake.requests[0]
    assert r.method == "POST" and str(r.url) == "https://api.higgsfield.ai/higgsfield/genjutsu/object-swap/v1.0"
    assert r.headers["Authorization"] == f"Key {KEY_ID}:{SECRET}"
    assert r.headers["Idempotency-Key"] == "clip-1-attempt-1"
    assert json.loads(r.content) == {
        "video_url": VIDEO, "image_urls": IMAGES,
        "prompt": "replace the man with the butler from the reference images", "resolution": "1080p",
    }


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("slow"), httpx.ConnectError("reset"), httpx.RemoteProtocolError("cut")],
)
def test_a_timeout_or_a_dropped_connection_is_uncertain_and_never_posted_again(error):
    fake = Fake(error)
    with pytest.raises(SubmitUncertain) as info:
        submit(client(fake))
    assert info.value.idempotency_key == "clip-1-attempt-1"
    assert len(fake.requests) == 1  # no retry inside the client
    assert SECRET not in str(info.value)


def test_a_server_error_is_uncertain_too_and_a_client_error_is_a_refusal():
    fake = Fake((502, "bad gateway"))
    with pytest.raises(SubmitUncertain) as info:
        submit(client(fake))
    assert info.value.status == 502 and len(fake.requests) == 1
    fake = Fake((422, {"detail": f"video too short (key {KEY_ID}:{SECRET})"}))
    with pytest.raises(HiggsfieldError) as refused:
        submit(client(fake))
    assert not isinstance(refused.value, SubmitUncertain) and refused.value.status == 422
    assert SECRET not in str(refused.value) and KEY_ID not in str(refused.value)  # an echoed key is scrubbed


def test_the_same_key_and_body_is_the_lookup_of_an_uncertain_submit():
    """The documented way to resolve a timeout: the identical request with the stored key returns the original request."""
    fake = Fake(httpx.ReadTimeout("slow"), (200, SUBMITTED))
    c = client(fake)
    with pytest.raises(SubmitUncertain) as info:
        submit(c)
    got = submit(c, idempotency_key=info.value.idempotency_key)
    assert got.request_id == "REQ1"
    first, second = fake.requests
    assert first.content == second.content and first.headers["Idempotency-Key"] == second.headers["Idempotency-Key"]


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"video_url": "http://x.example/a.mp4"}, "video_url must be an https URL"),
        ({"image_urls": []}, "1-8 URLs"),
        ({"image_urls": IMAGES * 5}, "1-8 URLs"),
        ({"image_urls": ["https://x.example/a b.png"]}, r"image_urls\[0\]"),
        ({"prompt": "x" * 10_001}, "at most 10000"),
        ({"resolution": "4k"}, "resolution must be one of"),
        ({"idempotency_key": ""}, "Idempotency-Key is required"),
        ({"idempotency_key": "a b"}, "Idempotency-Key is required"),
    ],
)
def test_bad_input_is_refused_before_anything_is_sent(over, message):
    fake = Fake()
    with pytest.raises(ValueError, match=message):
        submit(client(fake), **over)
    assert fake.requests == []


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        ["a", "list"],
        {"status": "queued", "status_url": STATUS_URL},  # no request_id
        {"status": "queued", "request_id": "R", "status_url": "http://api.higgsfield.ai/requests/R/status"},
        {"status": "queued", "request_id": "R", "status_url": "https://evil.example/requests/R/status"},  # our key would go there
        {"status": "sleeping", "request_id": "R", "status_url": STATUS_URL},
    ],
)
def test_a_submit_answer_in_an_unexpected_shape_fails_loudly(body):
    with pytest.raises(UnexpectedResponse):
        submit(client(Fake((200, body))))


def test_the_client_needs_both_keys_and_from_env_returns_none_without_them():
    with pytest.raises(ValueError, match="HF_API_KEY_ID"):
        HiggsfieldClient("", SECRET)
    assert HiggsfieldClient.from_env({"HF_API_KEY_ID": KEY_ID}) is None
    assert HiggsfieldClient.from_env({}) is None
    c = HiggsfieldClient.from_env({"HF_API_KEY_ID": KEY_ID, "HF_API_KEY_SECRET": SECRET})
    assert isinstance(c, HiggsfieldClient) and SECRET not in repr(c)


# ---- status and polling ------------------------------------------------------------------------------------------------


def test_a_completed_status_carries_the_output_url_and_extra_fields_are_ignored():
    st = parse_status({"status": "completed", "request_id": "REQ1", "video": {"url": "https://cdn.higgsfield.ai/o.mp4", "w": 1080}, "x": 1})
    assert st.ok and st.done and st.video_url == "https://cdn.higgsfield.ai/o.mp4"
    failed = parse_status({"status": "failed", "error": "the reference video is too short"})
    assert failed.done and not failed.ok and failed.error == "the reference video is too short"
    assert parse_status({"status": "nsfw"}).done and parse_status({"status": "canceled"}).done
    assert not parse_status({"status": "in_progress"}).done


@pytest.mark.parametrize(
    "body",
    [
        {"status": "completed"},  # no video
        {"status": "completed", "video": {"url": "http://cdn.example/o.mp4"}},
        {"status": "completed", "video": "https://cdn.example/o.mp4"},
        {"status": "done"},
        {},
    ],
)
def test_a_status_in_an_unexpected_shape_fails_loudly(body):
    with pytest.raises(UnexpectedResponse):
        parse_status(body)


def test_wait_polls_until_completed_with_the_key_on_the_api_host_only():
    fake = Fake((200, {"status": "queued"}), (200, {"status": "in_progress"}), (200, {"status": "completed", "video": {"url": "https://cdn.example/o.mp4"}}))
    clock = Clock()
    seen = []
    st = client(fake, clock).wait(STATUS_URL, interval_s=15, on_status=lambda s: seen.append(s.status))
    assert st.video_url == "https://cdn.example/o.mp4" and seen == ["queued", "in_progress", "completed"]
    assert clock.sleeps == [15, 15]
    assert all(str(r.url) == STATUS_URL and r.headers["Authorization"].startswith("Key ") for r in fake.requests)


def test_wait_gives_up_after_the_timeout_with_the_last_status():
    fake = Fake(*[(200, {"status": "in_progress"})] * 200)
    with pytest.raises(PollTimeout) as info:
        client(fake, Clock()).wait(STATUS_URL, timeout_s=60, interval_s=15)
    assert info.value.last == "in_progress" and info.value.status_url == STATUS_URL
    assert len(fake.requests) <= 5


def test_a_failed_status_call_is_tried_again_a_few_times_but_a_refusal_stops_at_once():
    flaky = Fake(httpx.ReadTimeout("t"), (503, "busy"), (200, {"status": "completed", "video": {"url": "https://cdn.example/o.mp4"}}))
    assert client(flaky).wait(STATUS_URL, interval_s=1).ok
    down = Fake(*[httpx.ReadTimeout("t")] * MAX_TRANSIENT_POLL_ERRORS)
    with pytest.raises(HiggsfieldError):
        client(down).wait(STATUS_URL, interval_s=1)
    assert len(down.requests) == MAX_TRANSIENT_POLL_ERRORS
    gone = Fake((404, "unknown request"))
    with pytest.raises(HiggsfieldError) as info:
        client(gone).wait(STATUS_URL, interval_s=1)
    assert info.value.status == 404 and len(gone.requests) == 1


def test_a_status_url_on_another_host_is_never_called():
    fake = Fake()
    with pytest.raises(ValueError, match="never sent anywhere else"):
        client(fake).status("https://evil.example/requests/R/status")
    assert fake.requests == []


# ---- the output -----------------------------------------------------------------------------------------------------------


def test_the_output_is_downloaded_without_the_key(tmp_path: Path):
    fake = Fake((200, b"video-bytes"))
    out = client(fake).download("https://cdn.example/o.mp4", tmp_path / "gen.mp4")
    assert out.read_bytes() == b"video-bytes"
    assert "Authorization" not in fake.requests[0].headers


def test_a_failed_download_leaves_no_file(tmp_path: Path):
    with pytest.raises(HiggsfieldError, match="HTTP 403"):
        client(Fake((403, "expired"))).download("https://cdn.example/o.mp4", tmp_path / "gen.mp4")
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError, match="https"):
        client(Fake()).download("http://cdn.example/o.mp4", tmp_path / "gen.mp4")

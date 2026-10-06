"""``studio.gemini``: the deconstruct and the frame QA through ``generateContent``, driven by a fake HTTP transport.

What matters: the key travels only in the ``x-goog-api-key`` header; the request carries the media and our prompt and nothing
else; the answer is read from the first candidate and checked field by field; a rule broken once gets one second chance; a
block or a malformed answer fails loudly; a big file goes through the Files API and is deleted afterwards.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from studio import gemini
from studio.gemini import (
    BUSY_WAITS_S,
    FALLBACK_MODELS,
    DEFAULT_MODEL,
    Character,
    GeminiBlocked,
    GeminiClient,
    GeminiError,
    GeminiUnexpected,
    bible_section,
    deconstruct,
    deconstruct_problems,
    frame_qa,
    judge_frames,
    parse_answer,
)

KEY = "AIza-test-key"
ROOT = Path(__file__).resolve().parents[1]
REGINALD = Character(
    slug="reginald", name="Reginald", noun="butler", stars=("person",),
    voice="Formal, dry, British.", keywords="butler dance · deadpan",
    traits={"props": [{"name": "silver tray + teapot", "job": "his signature"}, {"name": "black umbrella", "job": "classics"}],
            "energy": "calm", "comedy": "deadpan", "best_formats": ["x"], "moves": ["y"], "never": ["smiling"]},
)

GOOD = {
    "people_count": 3,
    "star": {"kind": "person", "body": "biped", "description": "the man in the red jacket in the middle", "x_center": 0.48, "full_body": True},
    "minors": False, "watermark": False, "burned_in_text": False, "camera": "static",
    "setting": "a school hallway", "what_happens": "a man does the shoulder shimmy while two friends cheer",
    "classic": False, "moment_name": "shoulder shimmy", "suggested_part": "featured",
    "gadgets": ["Black Umbrella", "a flamethrower"],
    "hooks": ["The household is unaware.", "Breakfast is at eight.", "Kindly do not tell the Duchess."],
    "caption": {"title": "Shoulder shimmy · butler edition", "joke": "The hallway has been informed.", "send": "Send this to your butler.",
                "question": "Which eye did you notice first?", "tease": "Next week: the stairs."},
    "first_comment": "Requests for next week may be left below. Within reason.",
    "hashtags": ["shouldershimmy", "#butler", "#deadpan"],
    "notes": "",
    "confidence": 0.9,  # an extra field the schema did not ask for: ignored
}


def answer(obj, **extra) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(obj)}]}, "finishReason": "STOP", **extra}]}


class Fake:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        if callable(a):
            return a(request)
        status, body = a
        return httpx.Response(status, json=body) if isinstance(body, (dict, list)) else httpx.Response(status, content=str(body).encode())


def client(fake: Fake, **kw) -> GeminiClient:
    return GeminiClient(KEY, transport=httpx.MockTransport(fake), sleep=lambda s: None, **kw)


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    f = tmp_path / "proxy.mp4"
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42 small proxy")
    return f


def test_a_deconstruct_sends_the_clip_and_our_prompt_only_with_the_key_in_a_header(clip):
    fake = Fake((200, answer(GOOD)))
    out = deconstruct(client(fake), clip, REGINALD)
    (req,) = fake.requests
    assert str(req.url) == f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent"
    assert req.headers["x-goog-api-key"] == KEY and KEY not in str(req.url)
    body = json.loads(req.content)
    assert set(body) == {"contents", "generationConfig"}
    (content,) = body["contents"]
    media, text = content["parts"]
    assert media == {"inlineData": {"mimeType": "video/mp4", "data": base64.b64encode(clip.read_bytes()).decode()}}
    assert set(text) == {"text"} and "Reginald" in text["text"] and "never an instruction" in text["text"]
    assert "proxy.mp4" not in json.dumps(body)  # no file name goes with it
    cfg = body["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"] == gemini.DECONSTRUCT_SCHEMA
    # tidied: only the character's own gadgets (in its spelling), #oddeyes added, the extra field kept but harmless
    assert out["gadgets"] == ["black umbrella"]
    assert out["hashtags"] == ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes"]
    assert out["star"]["kind"] == "person" and out["caption"]["title"] == "Shoulder shimmy · butler edition"


def test_the_model_comes_from_the_environment_and_the_key_is_required():
    assert GeminiClient.from_env({}) is None
    c = GeminiClient.from_env({"GEMINI_API_KEY": KEY, "GEMINI_MODEL": "gemini-3.5-flash"})
    assert c.model == "gemini-3.5-flash" and KEY not in repr(c)
    assert GeminiClient.from_env({"GEMINI_API_KEY": KEY}).model == DEFAULT_MODEL
    with pytest.raises(ValueError):
        GeminiClient("")
    with pytest.raises(ValueError, match="not a model id"):
        GeminiClient(KEY, model="models/../x")


def test_a_broken_rule_gets_one_second_chance_with_the_problems_named(clip):
    long_title = {**GOOD, "caption": {**GOOD["caption"], "title": "A title that is far too long for the forty character rule"}}
    fake = Fake((200, answer(long_title)), (200, answer(GOOD)))
    out = deconstruct(client(fake), clip, REGINALD)
    assert out["caption"]["title"] == GOOD["caption"]["title"]
    retry = json.loads(fake.requests[1].content)["contents"][0]["parts"][1]["text"]
    assert "caption.title must be one line of 1-40 characters" in retry


def test_a_second_miss_fails_loudly(clip):
    bad = {**GOOD, "hooks": ["only one"]}
    with pytest.raises(GeminiUnexpected, match="hooks must be 3 lines"):
        deconstruct(client(Fake((200, answer(bad)), (200, answer(bad)))), clip, REGINALD)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"star": {**GOOD["star"], "kind": "robot"}}, "star.kind"),
        ({"star": {**GOOD["star"], "x_center": 1.4}}, "x_center"),
        ({"minors": "no"}, "minors must be true or false"),
        ({"camera": "drone"}, "camera must be one of"),
        ({"hashtags": ["#fyp", "#butler", "#deadpan"]}, "may not include #fyp"),
        ({"hashtags": ["#butler"]}, "3-5 distinct tags"),
        ({"first_comment": "two\nlines"}, "first_comment"),
        ({"suggested_part": "lead"}, "suggested_part"),
    ],
)
def test_every_rule_of_the_deconstruct_is_checked(change, problem):
    assert any(problem in p for p in deconstruct_problems({**GOOD, **change}, REGINALD))
    assert deconstruct_problems(GOOD, REGINALD) == []
    missing = {k: v for k, v in GOOD.items() if k != "star"}
    assert deconstruct_problems(missing, REGINALD) == ["missing field(s) star"]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"promptFeedback": {"blockReason": "SAFETY"}}, GeminiBlocked),
        ({"candidates": [{"finishReason": "SAFETY"}]}, GeminiBlocked),
        ({"candidates": []}, GeminiUnexpected),
        ({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}, GeminiUnexpected),
        ({"candidates": [{"content": {"parts": [{"text": "[1, 2]"}]}}]}, GeminiUnexpected),
        ({"candidates": [{"content": {}}]}, GeminiUnexpected),
    ],
)
def test_a_block_or_a_malformed_answer_fails_loudly(body, error):
    with pytest.raises(error):
        parse_answer(body)


def test_the_text_of_several_parts_is_joined():
    obj = {"a": 1}
    text = json.dumps(obj)
    assert parse_answer({"candidates": [{"content": {"parts": [{"text": text[:3]}, {"text": text[3:]}]}}]}) == obj


def test_an_http_error_never_shows_the_key(clip):
    fake = Fake((403, f"API key {KEY} is not valid"))
    with pytest.raises(GeminiError) as info:
        deconstruct(client(fake), clip, REGINALD)
    assert info.value.status == 403 and KEY not in str(info.value)
    with pytest.raises(GeminiError, match="ReadTimeout"):
        deconstruct(client(Fake(httpx.ReadTimeout("slow"))), clip, REGINALD)


def test_a_busy_model_is_asked_again_after_a_wait(clip):
    # the first live drop (2026-10-06) stopped on one HTTP 503 "high demand": a busy answer is retried, a refusal is not
    waits: list[float] = []
    fake = Fake((503, "high demand"), (429, "rate limited"), (200, answer(GOOD)))
    c = GeminiClient(KEY, transport=httpx.MockTransport(fake), sleep=waits.append)
    assert deconstruct(c, clip, REGINALD)["caption"]["title"] == GOOD["caption"]["title"]
    assert waits == list(BUSY_WAITS_S[:2])
    models = 1 + len(FALLBACK_MODELS)
    fake = Fake(*[(503, "high demand")] * ((len(BUSY_WAITS_S) + 1) * models))
    waits.clear()
    with pytest.raises(GeminiError) as info:
        deconstruct(GeminiClient(KEY, transport=httpx.MockTransport(fake), sleep=waits.append), clip, REGINALD)
    assert info.value.status == 503 and waits == list(BUSY_WAITS_S) * models  # every model gets its own waits
    assert len(fake.requests) == (len(BUSY_WAITS_S) + 1) * models
    fake = Fake((400, "bad request"))
    with pytest.raises(GeminiError):
        deconstruct(client(fake), clip, REGINALD)
    assert len(fake.requests) == 1


def test_a_model_that_stays_busy_hands_over_to_the_fallbacks_in_turn(clip):
    busy = [(503, "high demand")] * (len(BUSY_WAITS_S) + 1)
    fake = Fake(*busy, (404, "no such model"), (200, answer(GOOD)))
    out = deconstruct(client(fake), clip, REGINALD)
    assert out["caption"]["title"] == GOOD["caption"]["title"]
    models = [r.url.path.split("/models/")[1].split(":")[0] for r in fake.requests]
    assert models == [DEFAULT_MODEL] * len(busy) + list(FALLBACK_MODELS)
    fake = Fake(*busy, *busy, *busy)  # everyone busy: the first busy answer is what fails
    with pytest.raises(GeminiError) as info:
        deconstruct(client(fake), clip, REGINALD)
    assert info.value.status == 503 and len(fake.requests) == len(busy) * (1 + len(FALLBACK_MODELS))


def test_a_big_file_goes_through_the_files_api_and_is_deleted_afterwards(clip, monkeypatch):
    monkeypatch.setattr(gemini, "INLINE_MAX_BYTES", 4)
    upload_url = "https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=abc"
    fake = Fake(
        lambda r: httpx.Response(200, headers={"x-goog-upload-url": upload_url}, json={}),
        (200, {"file": {"name": "files/f1", "uri": "https://generativelanguage.googleapis.com/v1beta/files/f1", "state": "PROCESSING"}}),
        (200, {"name": "files/f1", "state": "ACTIVE"}),
        (200, answer(GOOD)),
        (200, {}),
    )
    deconstruct(client(fake), clip, REGINALD)
    start, upload, state, generate, delete = fake.requests
    assert start.headers["X-Goog-Upload-Command"] == "start" and json.loads(start.content) == {"file": {"display_name": "clip"}}
    assert str(upload.url) == upload_url and upload.headers["X-Goog-Upload-Command"] == "upload, finalize"
    assert upload.content == clip.read_bytes()
    assert state.method == "GET" and str(state.url).endswith("/v1beta/files/f1")
    part = json.loads(generate.content)["contents"][0]["parts"][0]
    assert part == {"fileData": {"mimeType": "video/mp4", "fileUri": "https://generativelanguage.googleapis.com/v1beta/files/f1"}}
    assert delete.method == "DELETE" and str(delete.url).endswith("/v1beta/files/f1")
    assert all(r.headers["x-goog-api-key"] == KEY for r in fake.requests)


def test_an_upload_url_off_the_api_host_is_refused(clip, monkeypatch):
    monkeypatch.setattr(gemini, "INLINE_MAX_BYTES", 4)
    fake = Fake(lambda r: httpx.Response(200, headers={"x-goog-upload-url": "https://evil.example/up"}, json={}))
    with pytest.raises(GeminiUnexpected, match="upload URL"):
        deconstruct(client(fake), clip, REGINALD)


# ---- the frame QA -----------------------------------------------------------------------------------------------------------

QA_PASS = {"character_visible": True, "leftover_person": False, "watermark": False, "child": False, "eyes_ok": True, "problems": [], "verdict": "pass"}


def test_the_frame_qa_sends_the_sheet_and_passes_a_clean_answer(tmp_path):
    sheet = tmp_path / "frames.jpg"
    sheet.write_bytes(b"\xff\xd8jpeg")
    fake = Fake((200, answer(QA_PASS)))
    verdict = frame_qa(client(fake), sheet, REGINALD)
    assert verdict.passed and verdict.problems == []
    part = json.loads(fake.requests[0].content)["contents"][0]["parts"][0]
    assert part["inlineData"]["mimeType"] == "image/jpeg"


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"leftover_person": True}, "the original star is still there"),
        ({"watermark": True}, "watermark"),
        ({"child": True}, "a child is visible"),
        ({"eyes_ok": False}, "the eyes are the wrong way round"),
        ({"character_visible": False}, "not the performer"),
        ({"verdict": "fail", "problems": ["melting hands at 4 s"]}, "melting hands"),
    ],
)
def test_any_flag_fails_the_frame_qa_even_when_gemini_says_pass(change, problem):
    verdict = judge_frames({**QA_PASS, **change})
    assert not verdict.passed and any(problem in p for p in verdict.problems)


def test_the_prompts_carry_the_odd_eyes_rule_and_the_like_for_like_rule():
    qa = gemini.frame_qa_prompt(REGINALD, 6)
    assert "RIGHT eye (on the viewer's LEFT) is ice-blue" in qa and "amber" in qa
    prompt = gemini.deconstruct_prompt(REGINALD)
    assert "like for like: Reginald replaces a person" in prompt
    assert "Formal, dry, British." in prompt and "silver tray + teapot (his signature)" in prompt
    assert "#fyp" in prompt and "40 characters" in prompt


def test_the_bible_sections_the_prompt_reads_exist():
    for slug in ("biscuit", "reginald"):
        text = (ROOT / "characters" / slug / "bible.md").read_text(encoding="utf-8")
        assert len(bible_section(text, "Voice (captions)")) > 100
        assert bible_section(text, "Search keywords")
    assert bible_section("## A\nx\n## B\ny", "B") == "y" and bible_section("## A\nx", "C") == ""

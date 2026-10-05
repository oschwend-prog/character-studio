"""The caption playbook (owner 2026-10-05): at most 5 hashtags and none of the dead ones, the first comment stored on the clip,
the terminal's mirror of the post text (parity-cases.json `captions`) and the formula in the character bibles."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio import clips
from studio.captions import AI_DISCLOSURE, BANNED_HASHTAGS, HASHTAG_LIMIT, caption_length, compose_content
from studio.cli import app
from studio.clips import FIRST_COMMENT_MAX_CHARS, new_clip, set_first_comment, validate_first_comment
from studio.models import Body, Character
from studio.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
PARITY = json.loads((ROOT / "terminal" / "src" / "lib" / "parity-cases.json").read_text())
FEATURES = {
    "format_id": "B-DANCE", "hook_pattern": "x", "hook_text": "x", "prop": "none", "setting": "x", "motion_type": "x",
    "audio_arm": "original_audio", "bodies_in_frame": 1, "seamless_loop": False, "eye_closeup_end": True, "trend_name": "evergreen",
}  # fmt: skip


# ---- hashtags -----------------------------------------------------------------------------------------------------


def test_five_hashtags_is_instagrams_cap_and_exactly_five_pass():
    assert HASHTAG_LIMIT == 5
    out = compose_content("lead dancer. obviously. 💙", ["#singleladies", "#dachshund", "#dogdance", "#sausagedog", "#oddeyes"])
    assert out.endswith("#singleladies #dachshund #dogdance #sausagedog #oddeyes")


def test_six_hashtags_are_refused_naming_the_limit_and_duplicates_do_not_count():
    with pytest.raises(ValueError, match=r"6 hashtags, over the limit of 5"):
        compose_content("x", ["a", "b", "c", "d", "e", "f"])
    assert compose_content("x", ["a", "b", "c", "d", "e", "#A", " e "]).endswith("#a #b #c #d #e")  # cleaned first


@pytest.mark.parametrize("tag", ["fyp", "#foryou", "ForYouPage", "#VIRAL", " #explore "])
def test_the_dead_hashtags_are_refused_naming_the_tag_whatever_the_case(tag):
    assert BANNED_HASHTAGS == {"fyp", "foryou", "foryoupage", "viral", "explore"}
    with pytest.raises(ValueError, match=f"hashtag #{tag.strip().lstrip('#')} is refused"):
        compose_content("x", ["#dachshund", tag])
    assert compose_content("x", ["#explorer", "#viralvideo"]).endswith("#explorer #viralvideo")  # only the exact tags


@pytest.mark.parametrize("case", PARITY["captions"], ids=lambda c: (c.get("error") or c.get("expect", ""))[:30] or "length")
def test_the_terminal_composes_the_same_post_text(case):
    """terminal/src/lib/parity-cases.json `captions` is read by captions.test.ts too: one list, two implementations."""
    caption = case["caption"] * case.get("repeat", 1)
    if "error" in case:
        with pytest.raises(ValueError) as e:
            compose_content(caption, case["hashtags"])
        assert case["error"] in str(e.value)
        return
    out = compose_content(caption, case["hashtags"])
    if "expect" in case:
        assert out == case["expect"]
    if "expect_length" in case:
        assert caption_length(out) == case["expect_length"]
    assert AI_DISCLOSURE in out


# ---- the first comment --------------------------------------------------------------------------------------------


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    return store


def test_the_first_comment_is_one_trimmed_line_of_at_most_300_characters():
    assert validate_first_comment("  which eye did you notice first? 💙🧡 ") == "which eye did you notice first? 💙🧡"
    assert FIRST_COMMENT_MAX_CHARS == 300
    assert validate_first_comment("x" * 300) == "x" * 300
    for bad, message in (("", "empty"), ("   ", "empty"), ("one\ntwo", "one line"), ("x" * 301, "301 characters"), ("🌭" * 151, "302")):
        with pytest.raises(ValueError, match=message):
            validate_first_comment(bad)


def test_the_first_comment_is_stored_on_the_clip_and_keeps_its_other_features():
    store = make_store()
    clip = new_clip(store, "biscuit", None, "recreate", FEATURES)
    out = set_first_comment(store, clip.id, "Requests for next week may be left below. Within reason.")
    assert out.features["first_comment"] == "Requests for next week may be left below. Within reason."
    assert out.features["format_id"] == "B-DANCE" and out.features["rerolls"] == 0
    with pytest.raises(KeyError):
        set_first_comment(store, "missing", "x")
    with pytest.raises(ValueError):
        set_first_comment(store, clip.id, "two\nlines")
    assert store.get_clip(clip.id).features["first_comment"].startswith("Requests")  # nothing written by the refusal


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(clips, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["clip", *args])


def test_cli_clip_set_first_comment_file(cli_store, tmp_path):
    cid = new_clip(cli_store, "biscuit", None, "recreate", FEATURES).id
    f = tmp_path / "fc.txt"
    f.write_text("which eye did you notice first? 💙🧡\n", encoding="utf-8")
    r = run("set", cid, "--first-comment-file", str(f))
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["features"]["first_comment"] == "which eye did you notice first? 💙🧡"
    # with other fields in the same call
    r = run("set", cid, "--hook", "h", "--first-comment", "second try")
    assert r.exit_code == 0, r.output
    assert (cli_store.get_clip(cid).hook, cli_store.get_clip(cid).features["first_comment"]) == ("h", "second try")
    f.write_text("two\nlines", encoding="utf-8")
    r = run("set", cid, "--first-comment-file", str(f))
    assert r.exit_code == 2 and "one line" in r.output
    assert run("set", "nope", "--first-comment", "x").exit_code == 2
    assert run("set", cid, "--first-comment", "x", "--first-comment-file", str(f)).exit_code == 2
    assert cli_store.get_clip(cid).features["first_comment"] == "second try"  # the refusals wrote nothing


def test_cli_clip_set_refuses_too_many_or_dead_hashtags_with_exit_2(cli_store):
    cid = new_clip(cli_store, "biscuit", None, "recreate", FEATURES).id
    r = run("set", cid, *[x for t in ("a", "b", "c", "d", "e", "f") for x in ("--hashtag", t)])
    assert r.exit_code == 2 and "limit of 5" in r.output
    r = run("set", cid, "--caption", "ok", "--hashtag", "#fyp")
    assert r.exit_code == 2 and "#fyp is refused" in r.output
    assert (cli_store.get_clip(cid).caption, cli_store.get_clip(cid).hashtags) == (None, [])
    assert run("set", cid, *[x for t in ("a", "b", "c", "d", "e") for x in ("--hashtag", t)]).exit_code == 0


# ---- the bibles ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug, keywords, edition, comment",
    [
        ("biscuit", ["dancing dachshund", "dog dance", "sausage dog", "dachshund"], "dachshund", "which eye did you notice first? 💙🧡"),
        ("reginald", ["butler dance", "british butler", "deadpan", "butler"], "butler", "Requests for next week may be left below. Within reason."),
    ],
)
def test_each_bible_has_its_search_keywords_the_post_formula_and_the_first_comment(slug, keywords, edition, comment):
    bible = (ROOT / "characters" / slug / "bible.md").read_text()
    section = bible.split("## Search keywords", 1)[1].split("\n## ", 1)[0]
    for word in keywords:
        assert word in section, word
    voice = bible.split("## Voice (captions)", 1)[1].split("\n## ", 1)[0]
    assert f"· {edition} edition" in voice and "at most 40 characters" in voice
    assert "ONE engagement line" in voice and "send this to" in voice and "series tease" in voice
    assert "🎵 <song> – <artist>" in voice and "no handle known, no credit line" in voice
    assert "3-5 hashtags" in voice and "#oddeyes" in voice and "Never #fyp, #foryou, #foryoupage, #viral or #explore" in voice
    assert f"**First comment**" in voice and comment in voice
    never = bible.split("## Never", 1)[1]
    assert "no famous IP" not in never and "no third-party footage or audio in the output" not in never
    assert "a famous moment, meme or dance is fine" in never and "never the original costume, look or likeness" in never
    assert "keeps the clip's own original audio by default" in never


def test_reginalds_sentences_never_mention_dancing_but_his_title_may():
    voice = (ROOT / "characters" / "reginald" / "bible.md").read_text().split("## Voice (captions)", 1)[1].split("\n## ", 1)[0]
    assert "never mentions dancing directly" in voice and "line 1 may: it is a label" in voice

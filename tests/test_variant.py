"""``studio clip variant`` (studio/variant.py): a posted clip is posted again with a NEW hook as a clip of its own.

MemoryStore and a local folder as Storage; the master build is a stub that copies a ready 1080x1920 master (the real build is
tested in test_master.py), everything around it is real: the refusals, the features that are copied and the ones that are not,
the state path, the audio rule, the master check and the upload. Nothing here spends a credit or reaches Higgsfield.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from studio import clips, drop, experiments, higgsfield_api, variant
from studio.cli import app
from studio.config import now_london
from studio.media import master, overlays
from studio.models import Body, Character, ClipState, Favorite, Mode, Source, SourceKind
from studio.storage import LocalStorage
from studio.store import MemoryStore
from studio.variant import VariantFailed, VariantRefused, make_variant

S = ClipState
HOOK = "The household is unaware."
NEW_HOOK = "Kindly do not tell the Duchess."
CDN = "https://d8j0ntlcm91z4.cloudfront.net/user_x/out.mp4"

# what the publisher and the metrics add to a clip once it is posted (none of it is the variant's)
POSTED = {
    "story": {"post_id": "p1", "status": "posted", "at": "2026-10-20T19:35:00+01:00"},
    "story_path": "reginald/ORIG-story.mp4",
    "story_reshares": [{"at": "2026-10-21T12:00:00+01:00", "post_id": "p1", "status": "posted"}],
    "trial_reel": True, "trial_refused": "a 4xx", "first_comment_posted": True, "outlier_x": 2.5,
    "collab": ["franz.unimpressed"], "collab_auto": {"week": "2026-10-26", "partner": "franz"}, "collab_by": "owner",
}
# what the master wrote about itself
MASTER_RECORD = {"length_s": 12.0, "length_bucket": "11_16", "zoom_pulses": 2, "hook_entrance": "fade_rise", "beats": 14}
# what a drop's clip carries (studio.drop._features)
FEATURES = {
    "format_id": "swap_trend", "hook_pattern": "understatement", "hook_text": HOOK, "prop": "black umbrella",
    "setting": "an office corridor", "motion_type": "object_swap", "audio_arm": "original_audio", "bodies_in_frame": 1,
    "seamless_loop": False, "eye_closeup_end": False, "trend_name": "shoulder shimmy",
    "music": "original", "drop": True, "presence": "featured", "engagement_kind": "send", "crop_y": {"top": 0.1, "bottom": 0.1, "x": 0.5},
    "hook_index": 1, "hook_by": "studio", "caption_line1": "label-first", "first_comment_kind": "vote", "trend_stage": "none",
    "days_since_trend_peak": None, "sound_type": "own_trend_sound", "sound_rising": False,
    "score_bucket": "65_79", "score_total": 70, "score_potential": 7, "score_swap": 8, "part": "featured", "version_index": 1,
    "series": "none", "episode": None, "hit_rules_version": "v1", "source_kind": "owner_saved", "explore_pick": True,
    "test_arms": {"zoom": True, "word_pop": False, "hook": "understatement"},
    "first_comment": "Requests for next week may be left below. Within reason.",
    **MASTER_RECORD, **POSTED,
}
REQUIRED = {k: FEATURES[k] for k in clips.REQUIRED_FEATURES}
CAPTION = "Shoulder shimmy · butler edition\nThe corridor has been informed.\nSend this to your butler."
TAGS = ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes", "#asyouwere"]
LOOK = {"hooks": [HOOK, "Breakfast is at eight.", NEW_HOOK], "hook_patterns": ["understatement", "false-premise", "trend-label"]}


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.quadruped]))
    return store


def walk(store, clip_id, *states):
    for state in states:
        clips.transition(store, clip_id, state)


def posted_original(store, features=None, *, path=(S.scheduled, S.posted), output_url=CDN, fav=True):
    """A Reel that went out: a drop's clip, mastered, scheduled and posted, with its pick (the output Higgsfield made for it)."""
    source = store.add_source(
        Source(kind=SourceKind.owner_inbox, body=Body.biped, bodies=1, duration_s=8.0, has_watermark=False, has_overlay=False,
               other_people=0, has_minors=False)
    )
    pick = None
    feats = dict(FEATURES if features is None else features)
    if fav:
        pick = store.add_favorite(Favorite(
            url="owner-drop:1", platform="drop", origin="owner", character_slug="reginald", status="made",
            proposal={"drop": {"state": "made", "hooks": LOOK["hooks"], "deconstruct": LOOK,
                               "make": {"status": "completed", **({"output_url": output_url} if output_url else {})}}},
        ))
        feats.update(fav_id=pick.id, family_id=pick.id)
    clip = clips.new_clip(store, "reginald", source.id, Mode.dropin, feats)
    walk(store, clip.id, S.generating, S.generated, S.qa_passed)
    clips.transition(store, clip.id, S.mastered, hook=HOOK, caption=CAPTION, hashtags=TAGS)
    store.update_clip(clip.id, master_path=f"reginald/{clip.id}.mp4")
    walk(store, clip.id, *path)
    if pick is not None:
        store.update_favorite(pick.id, clip_id=clip.id)
    return store.get_clip(clip.id), pick


@pytest.fixture
def renders(tmp_path, monkeypatch):
    """The repo folder of the test (it holds renders/): nothing is written into the real one."""
    monkeypatch.setattr(variant, "ROOT", tmp_path)
    return tmp_path / "renders"


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def gen_file(synth_video):
    """A generation: 6.5 s, 540x960, with the clip's own sound."""
    return synth_video(w=540, h=960, dur=6.5)


class Builds(list):
    """The specs the stubbed master build was given; ``story`` makes it write a Story video next to the master, as a build does
    while Stories are on."""

    story = False


@pytest.fixture
def built(monkeypatch, synth_video):
    """The master build replaced by a copy of a ready 1080x1920 master. A spec with ``edits`` is told they were applied, as the real
    build records it (``spec.applied``)."""
    ready = synth_video(w=1080, h=1920, dur=7)
    builds = Builds()

    def build(spec):
        builds.append(spec)
        Path(spec.out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ready, spec.out)
        if builds.story:
            shutil.copyfile(ready, master.story_file(spec.out))
        if spec.edits is not None:
            spec.applied = {"zoom_pulses": 3, "hook_entrance": "none", "beats": 14}
        return Path(spec.out)

    monkeypatch.setattr(master, "build_master", build)
    builds.build = build
    return builds


def write_renders(renders, original, gen_file, spec=True):
    """What the daily run left for the original: renders/<id>/gen.mp4 and, made by hand, spec.json (paths relative to the repo)."""
    folder = renders / original.id
    folder.mkdir(parents=True)
    shutil.copyfile(gen_file, folder / "gen.mp4")
    if spec:
        (folder / "spec.json").write_text(json.dumps({
            "clip_id": original.id, "dance": f"renders/{original.id}/gen.mp4", "closeup": None, "closeup_center": [540, 800],
            "blue_eye_xy": [540, 800], "hook1": [], "hook2": [HOOK], "hook2_until_s": 4.0, "music": "original",
            "audio": f"renders/{original.id}/gen.mp4", "audio_offset_s": 0.0, "character": "reginald",
            "enhancements": [{"type": "zoom_hit", "at_s": 3.1}], "out": f"renders/{original.id}/master.mp4",
        }), encoding="utf-8")
    return folder


def variants_of(store, original):
    return [c for c in store.list_clips() if c.features.get("variant_of") == original.id]


# ---- the variant itself ------------------------------------------------------------------------------------------------------


def test_a_variant_is_a_new_mastered_clip_of_the_same_generation(renders, storage, gen_file, built, monkeypatch):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)
    before = store.get_clip(original.id)
    walked = []
    real = clips.transition
    monkeypatch.setattr(variant.clips, "transition", lambda s, cid, to, **kw: walked.append(ClipState(to)) or real(s, cid, to, **kw))

    out = make_variant(store, storage, original.id, NEW_HOOK)

    assert set(out) == {"clip_id", "variant_of", "hook", "master_path", "story_path"}
    assert out["variant_of"] == original.id and out["hook"] == NEW_HOOK and out["clip_id"] != original.id
    new = store.get_clip(out["clip_id"])
    assert walked == [S.generating, S.generated, S.qa_passed, S.mastered]  # the one path every clip walks
    assert new.state is S.mastered and (new.character_slug, new.source_id, new.mode) == ("reginald", original.source_id, Mode.dropin)
    assert (new.credits_reserved, new.credits_actual, new.hf_job_id) == (0, 0, None)
    assert new.qa == {"pass": True, "variant_of": original.id, "note": "same generation as the posted original"}
    assert (new.hook, new.caption, new.hashtags) == (NEW_HOOK, CAPTION, TAGS)
    assert new.master_path == f"reginald/{new.id}.mp4" == out["master_path"] and out["story_path"] is None
    assert (storage.root / "clips" / new.master_path).is_file()
    assert store.ledger_month(now_london().strftime("%Y-%m")) == []  # nothing reserved, nothing spent
    assert store.get_clip(original.id) == before  # the original is only read

    # the master is the original's spec again, with only the hook, the dance, the output and the clip changed
    (spec,) = built
    folder = renders / new.id
    assert spec.hook2 == drop.hook_lines(NEW_HOOK) and spec.hook1 == []
    assert spec.dance == renders / original.id / "gen.mp4" and spec.audio == spec.dance  # the generation's own sound
    assert spec.out == folder / "master.mp4" and spec.clip_id == new.id
    assert (spec.character, spec.hook2_until_s, spec.music) == ("reginald", 4.0, "original")
    assert spec.enhancements == [{"type": "zoom_hit", "at_s": 3.1}]
    assert json.loads((folder / "spec.json").read_text())["hook2"] == drop.hook_lines(NEW_HOOK)  # kept for the record


def test_the_variants_story_video_is_uploaded_with_its_master(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)
    built.story = True
    out = make_variant(store, storage, original.id, NEW_HOOK)
    assert out["story_path"] == f"reginald/{out['clip_id']}-story.mp4"  # not the original's
    assert (storage.root / "clips" / out["story_path"]).is_file()
    assert store.get_clip(out["clip_id"]).features["story_path"] == out["story_path"]


def test_the_variant_copies_the_clip_but_not_the_post_the_outcome_or_the_place_in_a_test(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)

    new = store.get_clip(make_variant(store, storage, original.id, NEW_HOOK)["clip_id"])
    f = new.features

    assert not set(POSTED) & set(f)  # no story, no trial reel, no collaborator, no outcome: it has not been posted
    assert f["length_s"] == 7.0 and f["length_bucket"] == "under_8" and "zoom_pulses" not in f  # the new master's, not the original's
    assert f["rerolls"] == 0 and f["variant_of"] == original.id
    assert f["test_arms"] == {} and "drop" not in f  # in no test (see below)
    for same in ("format_id", "prop", "setting", "motion_type", "trend_name", "music", "fav_id", "family_id", "part", "presence",
                 "score_total", "score_bucket", "caption_line1", "first_comment", "first_comment_kind", "engagement_kind", "crop_y",
                 "source_kind", "sound_type", "version_index", "explore_pick", "hit_rules_version"):
        assert f[same] == original.features[same], same
    # the new line is one of the check's hooks, so its pattern and place are known; it is never a bandit draw
    assert (f["hook_text"], f["hook_pattern"], f["hook_index"], f["hook_by"]) == (NEW_HOOK, "trend-label", 3, "variant")
    assert clips.learn_problems(f) == []
    # a repost is no new coin position (a clip that ever carried a key takes a place in its block) ...
    assert experiments.block_position(store, "reginald", "zoom") == 1  # the original's, not two
    # ... and no second observation of the score test, which reads posted clips with `drop` true
    assert [c.id for c in store.list_clips() if c.features.get("drop") is True] == [original.id]


def test_a_hook_that_is_none_of_the_checks_is_tagged_none_and_a_variants(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)
    f = store.get_clip(make_variant(store, storage, original.id, "Tea is at four. Do not be late.")["clip_id"]).features
    assert (f["hook_text"], f["hook_pattern"], f["hook_index"], f["hook_by"]) == ("Tea is at four. Do not be late.", "none", 0, "variant")
    assert clips.learn_problems(f) == []


def test_a_clip_made_before_the_learning_tags_is_copied_with_its_hook_retagged(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store, {**REQUIRED, "music": "original"}, fav=False)
    write_renders(renders, original, gen_file)
    f = store.get_clip(make_variant(store, storage, original.id, NEW_HOOK)["clip_id"]).features
    assert (f["hook_text"], f["hook_pattern"], f["hook_by"], f["variant_of"]) == (NEW_HOOK, "none", "variant", original.id)
    assert "hook_index" not in f  # it had none either


def test_without_a_spec_the_master_is_built_like_a_drops_master(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file, spec=False)

    new = store.get_clip(make_variant(store, storage, original.id, NEW_HOOK)["clip_id"])

    (spec,) = built
    refs = {r["slug"]: r for r in drop.seed.load_refs()}
    assert (spec.character, spec.style, spec.music, spec.closeup) == ("reginald", refs["reginald"]["style"], "original", None)
    assert spec.hook1 == [] and spec.hook2 == drop.hook_lines(NEW_HOOK) and spec.audio == spec.dance
    assert spec.dance == renders / original.id / "gen.mp4" and spec.clip_id == new.id
    assert 1.0 <= spec.hook2_until_s <= drop.HOOK_ON_SCREEN_S
    assert spec.edits == {"zoom_pulses": True, "word_pop": False}  # the original's two coins ...
    assert new.features["test_arms"] == {}  # ... without the variant taking a position in their blocks
    assert (new.features["zoom_pulses"], new.features["beats"]) == (3, 14)  # what the build says it applied is recorded anew


# ---- the generation: --gen, renders/<original>/gen.mp4, the output on the drop ---------------------------------------------------


def test_the_generation_is_looked_for_in_order(renders, storage, gen_file, built, tmp_path):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)
    mine = tmp_path / "other" / "gen.mp4"
    mine.parent.mkdir()
    shutil.copyfile(gen_file, mine)
    asked = []

    def download(url, dest):
        asked.append(url)
        raise AssertionError("a generation was at hand")

    first = make_variant(store, storage, original.id, NEW_HOOK, gen=mine, download=download)["clip_id"]
    assert built[-1].dance == mine.resolve()  # 1. --gen
    walk(store, first, S.awaiting_approval, S.rejected)  # a rejected variant does not hold the original
    make_variant(store, storage, original.id, "Breakfast is at eight.", download=download)
    assert built[-1].dance == renders / original.id / "gen.mp4"  # 2. renders/<original>/gen.mp4
    assert asked == []


def test_the_generation_with_its_sound_put_back_is_the_one_the_original_was_mastered_from(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)
    folder = write_renders(renders, original, gen_file)
    shutil.copyfile(gen_file, folder / "gen_audio.mp4")  # gen.mp4 lost its sound; the daily run muxed it back and mastered that
    spec = json.loads((folder / "spec.json").read_text())
    spec.update(dance=f"renders/{original.id}/gen_audio.mp4", audio=f"renders/{original.id}/gen_audio.mp4")
    (folder / "spec.json").write_text(json.dumps(spec))
    make_variant(store, storage, original.id, NEW_HOOK)
    assert built[-1].dance == folder / "gen_audio.mp4" and built[-1].audio == built[-1].dance


def test_without_a_file_the_output_on_the_drop_is_downloaded_into_the_new_clips_folder(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)  # no renders/<original>/ at all
    seen = []

    def download(url, dest):
        seen.append(url)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gen_file, dest)
        return Path(dest)

    out = make_variant(store, storage, original.id, NEW_HOOK, download=download)

    gen = renders / out["clip_id"] / "gen.mp4"
    assert seen == [CDN] and gen.is_file()
    (spec,) = built  # no spec.json for the original: built like a drop's master, from the downloaded generation
    assert spec.dance == gen and spec.audio == gen and spec.out == renders / out["clip_id"] / "master.mp4"


def test_no_generation_anywhere_is_refused_with_the_way_out_and_nothing_written(renders, storage, built):
    store = make_store()
    original, _ = posted_original(store, output_url=None)
    with pytest.raises(VariantRefused, match=f"no generation for {original.id}: pass --gen"):
        make_variant(store, storage, original.id, NEW_HOOK)
    assert [c.id for c in store.list_clips()] == [original.id] and built == [] and not renders.exists()


@pytest.mark.parametrize(
    "url, why",
    [("https://evil.example/out.mp4", "only a Higgsfield-hosted"), ("http://d8j0ntlcm91z4.cloudfront.net/o.mp4", "only a Higgsfield-hosted"),
     ("https://other.cloudfront.net/o.mp4", "only a Higgsfield-hosted"), (CDN, "HTTP 403")],
)
def test_only_a_higgsfield_url_is_downloaded_and_a_dead_one_asks_for_the_file(renders, storage, built, url, why):
    store = make_store()
    original, _ = posted_original(store, output_url=url)

    def download(u, dest):
        return higgsfield_api.download_output(u, dest, transport=httpx.MockTransport(lambda r: httpx.Response(403)))

    with pytest.raises(VariantRefused, match=f"no generation for {original.id}: pass --gen") as e:
        make_variant(store, storage, original.id, NEW_HOOK, download=download)
    assert why in str(e.value) and len(store.list_clips()) == 1 and built == []


def test_download_output_checks_the_host_and_sends_no_key(tmp_path):
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, content=b"mp4")

    dest = tmp_path / "x" / "gen.mp4"
    assert higgsfield_api.download_output(CDN, dest, transport=httpx.MockTransport(handler)) == dest
    assert dest.read_bytes() == b"mp4" and "authorization" not in asked[0].headers
    for url in ("https://cdn.higgsfield.ai/a.mp4", "https://higgsfield.ai/a.mp4"):
        assert higgsfield_api.is_higgsfield_url(url)
    for url in ("https://higgsfield.ai.evil.example/a.mp4", "https://evilhiggsfield.ai/a.mp4", "http://cdn.higgsfield.ai/a.mp4",
                "https://example.cloudfront.net/a.mp4", None, ""):
        assert not higgsfield_api.is_higgsfield_url(url)
    with pytest.raises(ValueError):
        higgsfield_api.download_output("https://evil.example/a.mp4", tmp_path / "no.mp4", transport=httpx.MockTransport(handler))
    assert len(asked) == 1 and not (tmp_path / "no.mp4").exists()


# ---- what is refused, and nothing is written ------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [(), (S.awaiting_approval,), (S.awaiting_approval, S.approved), (S.scheduled,)])
def test_only_a_posted_clip_has_a_variant(renders, storage, gen_file, built, path):
    store = make_store()
    original, _ = posted_original(store, path=path)
    write_renders(renders, original, gen_file)
    with pytest.raises(VariantRefused, match="only a posted clip"):
        make_variant(store, storage, original.id, NEW_HOOK)
    assert len(store.list_clips()) == 1 and built == []


def test_a_rejected_clip_has_no_variant_either(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store, path=(S.awaiting_approval, S.rejected))
    write_renders(renders, original, gen_file)
    with pytest.raises(VariantRefused, match="rejected: only a posted clip"):
        make_variant(store, storage, original.id, NEW_HOOK)


@pytest.mark.parametrize(
    "hook, why",
    [("", "empty"), ("   \n", "empty"), ("one line\nand another", "one line"), ("Tea 🫖 is at four", "cannot draw"), ("🫖", "cannot draw"),
     ("The household is UNAWARE.", "the original's own line"), ("  the household   is unaware. ", "the original's own line"),
     ("The household has, in the last several weeks and without any warning whatsoever given to the staff, "
      "been quite unaware of everything", "too long for the pill")],
)
def test_a_bad_hook_is_refused_before_anything_is_made(renders, storage, gen_file, built, hook, why):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)
    with pytest.raises(VariantRefused, match=why):
        make_variant(store, storage, original.id, hook)
    assert len(store.list_clips()) == 1 and built == []


def test_the_hook_limit_is_what_the_pill_holds(renders, storage, gen_file, built):
    """Two lines of the character's pill at its smallest type: a line that fits is made, one word more is refused."""
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)
    probe = master.spec_from_json({"dance": "a.mp4", "out": "b.mp4", "closeup": None, "audio": "a.mp4", "hook2": ["x"], "character": "reginald"})
    words = ["Kindly"] * 3
    while master.hook_fits(dataclasses.replace(probe, hook2=[" ".join(words)])):
        words.append("Kindly")
    fits, too_long = " ".join(words[:-1]), " ".join(words)
    with pytest.raises(VariantRefused, match="too long for the pill"):
        make_variant(store, storage, original.id, too_long)
    assert len(store.list_clips()) == 1
    assert make_variant(store, storage, original.id, fits)["hook"] == fits


def test_pill_fits_is_the_pill_png_rule():
    assert overlays.pill_fits(["Sausage coming through."]) and overlays.pill_fits(["a b", "c d"])
    assert not overlays.pill_fits(["word " * 40])
    with pytest.raises(ValueError):
        overlays.pill_fits(["🫖"])  # nothing the fonts can draw


def test_one_live_variant_per_original_and_a_dropped_or_rejected_one_does_not_count(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)
    first = make_variant(store, storage, original.id, NEW_HOOK)["clip_id"]
    n = len(store.list_clips())
    with pytest.raises(VariantRefused, match=f"already has a variant \\({first}, mastered\\)"):
        make_variant(store, storage, original.id, "Breakfast is at eight.")
    assert len(store.list_clips()) == n and store.get_clip(first).state is S.mastered  # nothing written, the first is what it was
    walk(store, first, S.awaiting_approval, S.rejected)
    second = make_variant(store, storage, original.id, "Breakfast is at eight.")["clip_id"]
    store.update_clip(second, state=S.dropped)
    third = make_variant(store, storage, original.id, "Tea is at four. Do not be late.")["clip_id"]
    assert len({first, second, third}) == 3 and len(variants_of(store, original)) == 3
    other, _ = posted_original(store)  # another clip's variant is another matter
    write_renders(renders, other, gen_file)
    assert make_variant(store, storage, other.id, NEW_HOOK)["variant_of"] == other.id


def test_an_unknown_clip_and_a_missing_file(renders, storage, built):
    store = make_store()
    original, _ = posted_original(store)
    with pytest.raises(KeyError):
        make_variant(store, storage, "no-such-clip", NEW_HOOK)
    with pytest.raises(VariantRefused, match="no such file"):
        make_variant(store, storage, original.id, NEW_HOOK, gen=renders / "nope.mp4")
    assert len(store.list_clips()) == 1


def test_a_master_with_an_intro_hook_over_a_close_up_is_not_guessed_at(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)
    folder = write_renders(renders, original, gen_file)
    spec = json.loads((folder / "spec.json").read_text())
    spec.update(closeup="renders/closeups/x.png", hook1=["he hits every", "single beat"])
    (folder / "spec.json").write_text(json.dumps(spec))
    with pytest.raises(VariantRefused, match="intro hook"):
        make_variant(store, storage, original.id, NEW_HOOK)
    assert len(store.list_clips()) == 1


# ---- a variant that cannot be finished is dropped, never left on the path ------------------------------------------------------------


def test_a_failed_build_drops_the_variant_and_the_original_may_be_varianted_again(renders, storage, gen_file, built, monkeypatch):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)

    def boom(spec):
        raise master.MasterError("ffmpeg failed (1): no space left")

    monkeypatch.setattr(master, "build_master", boom)
    with pytest.raises(VariantFailed, match="could not be mastered"):
        make_variant(store, storage, original.id, NEW_HOOK)
    (failed,) = variants_of(store, original)
    assert failed.state is S.dropped and "no space left" in failed.reject_reason and failed.master_path is None
    assert failed.qa["pass"] is False and failed.qa["variant_of"] == original.id and failed.credits_reserved == 0
    monkeypatch.setattr(master, "build_master", built.build)
    assert make_variant(store, storage, original.id, NEW_HOOK)["clip_id"] != failed.id


def test_a_master_that_misses_the_spec_is_dropped(renders, storage, gen_file, built, monkeypatch):
    store = make_store()
    original, _ = posted_original(store)
    write_renders(renders, original, gen_file)

    def small(spec):  # 540x960: not a master
        Path(spec.out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gen_file, spec.out)
        return Path(spec.out)

    monkeypatch.setattr(master, "build_master", small)
    with pytest.raises(VariantFailed, match="missed the spec"):
        make_variant(store, storage, original.id, NEW_HOOK)
    (failed,) = variants_of(store, original)
    assert failed.state is S.dropped and failed.master_path is None


def test_the_audio_rule_is_the_drop_masters(renders, storage, gen_file, built, tmp_path):
    """The sound is the generation's own (music original) and nothing else: a file from an inbox folder is refused, and so is a
    pick whose owner chose another music."""
    store = make_store()
    original, pick = posted_original(store)
    write_renders(renders, original, gen_file)
    inbox = tmp_path / "inbox" / "gen.mp4"
    inbox.parent.mkdir()
    shutil.copyfile(gen_file, inbox)
    with pytest.raises(VariantRefused, match="audio rule refused"):
        make_variant(store, storage, original.id, NEW_HOOK, gen=inbox)
    (failed,) = variants_of(store, original)
    assert failed.state is S.dropped and built == []
    store.update_favorite(pick.id, proposal={**store.get_favorite(pick.id).proposal, "owner_music": "in_app"})
    with pytest.raises(VariantRefused, match="owner chose in_app"):
        make_variant(store, storage, original.id, NEW_HOOK)


# ---- a repost takes no turn of the studio's rotations -----------------------------------------------------------------------------


def test_a_variant_takes_no_turn_of_the_engagement_rotation(renders, storage, gen_file, built):
    store = make_store()
    original, _ = posted_original(store)  # a "send"
    for kind in ("question", "tease"):  # two clips made after it ...
        clips.new_clip(store, "reginald", None, Mode.recreate, {**REQUIRED, "engagement_kind": kind})
    write_renders(renders, original, gen_file)
    new = store.get_clip(make_variant(store, storage, original.id, NEW_HOOK)["clip_id"])  # ... then the repost, made last
    assert new.features["engagement_kind"] == "send"
    assert drop.next_engagement(store, "reginald") == "send"  # the one after "tease", as if the repost had not been made


def test_a_variant_is_no_explore_pick_and_no_turn_of_the_exploration_rhythm(renders, storage, gen_file, built, experiments_on):
    store = make_store()
    original, _ = posted_original(store)  # explore_pick true: the last explore pick ...
    for _ in range(3):  # ... then three that were not: it is his turn
        clips.new_clip(store, "reginald", None, Mode.recreate, {**REQUIRED, "explore_pick": False})
    write_renders(renders, original, gen_file)
    new = store.get_clip(make_variant(store, storage, original.id, NEW_HOOK)["clip_id"])  # the repost copies explore_pick true, made last
    assert new.features["explore_pick"] is True
    assert drop.explore_turn(store, "reginald", now_london()) is True
    # the same clip as a draw of its own would have taken the turn
    store.update_clip(new.id, features={k: v for k, v in new.features.items() if k != "variant_of"})
    assert drop.explore_turn(store, "reginald", now_london()) is False


# ---- the command line ------------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch, renders, storage):
    store = make_store()
    monkeypatch.setattr(clips, "open_store", lambda: store)
    monkeypatch.setattr(clips, "open_storage", lambda: storage)
    return store


def run(*args):
    return CliRunner().invoke(app, ["clip", "variant", *args])


def test_the_command_prints_the_new_clip(cli, renders, gen_file, built, tmp_path):
    original, _ = posted_original(cli)
    hook = tmp_path / "hook.txt"
    hook.write_text(NEW_HOOK + "\n", encoding="utf-8")
    result = run(original.id, "--hook-file", str(hook), "--gen", str(gen_file))
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert set(out) == {"clip_id", "variant_of", "hook", "master_path", "story_path"}
    assert out["variant_of"] == original.id and out["hook"] == NEW_HOOK and out["master_path"] == f"reginald/{out['clip_id']}.mp4"
    assert cli.get_clip(out["clip_id"]).state is S.mastered


def test_the_command_exits_2_for_every_refusal_and_1_for_a_failed_build(cli, renders, gen_file, built, tmp_path, monkeypatch):
    original, _ = posted_original(cli)
    hook = tmp_path / "hook.txt"
    hook.write_text(HOOK, encoding="utf-8")
    same = run(original.id, "--hook-file", str(hook), "--gen", str(gen_file))
    assert same.exit_code == 2 and "the original's own line" in same.output
    assert run("no-such-clip", "--hook-file", str(hook)).exit_code == 2
    assert run(original.id, "--hook-file", str(tmp_path / "missing.txt")).exit_code == 2
    hook.write_text(NEW_HOOK, encoding="utf-8")
    no_file = run(original.id, "--hook-file", str(hook), "--gen", str(tmp_path / "nope.mp4"))
    assert no_file.exit_code == 2 and "no such file" in no_file.output
    monkeypatch.setattr(higgsfield_api, "download_output", lambda url, dest, **kw: (_ for _ in ()).throw(higgsfield_api.HiggsfieldError("no network in a test")))
    no_gen = run(original.id, "--hook-file", str(hook))  # nothing in renders/, and the drop's output cannot be fetched
    assert no_gen.exit_code == 2 and "pass --gen" in no_gen.output
    monkeypatch.setattr(master, "build_master", lambda spec: (_ for _ in ()).throw(master.MasterError("ffmpeg failed")))
    failed = run(original.id, "--hook-file", str(hook), "--gen", str(gen_file))
    assert failed.exit_code == 1 and "could not be mastered" in failed.output
    assert len(cli.list_clips()) == 2 and [c.state for c in variants_of(cli, original)] == [S.dropped]

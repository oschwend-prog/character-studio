import json
from datetime import datetime

import pytest
from typer.testing import CliRunner

from studio import clips
from studio.cli import app
from studio.clips import (
    ALLOWED,
    REQUIRED_FEATURES,
    IllegalTransition,
    new_clip,
    set_fields,
    set_source,
    transition,
)
from studio.config import LONDON
from studio.models import Body, Character, ClipState, Mode, Post, Snapshot, Source, SourceKind
from studio.store import MemoryStore

S = ClipState

FEATURES = {
    "format_id": "B1",
    "hook_pattern": "ego",
    "hook_text": "he knows what he did",
    "prop": "teacup",
    "setting": "kitchen",
    "motion_type": "quadruped",
    "audio_arm": "own-AI-beat",
    "bodies_in_frame": 1,
    "seamless_loop": True,
    "eye_closeup_end": True,
    "trend_name": "evergreen",
}


def make_store() -> MemoryStore:
    # MemoryStore enforces no foreign keys; seed what Postgres would require.
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


def add_source(store: MemoryStore) -> Source:
    """A clean, Drop-in eligible inbox source (what a dropin clip would really be made from)."""
    return store.add_source(
        Source(kind=SourceKind.owner_inbox, body=Body.biped, bodies=1, duration_s=8.0,
               has_watermark=False, has_overlay=False, other_people=0, has_minors=False)
    )


def fresh(store: MemoryStore | None = None, **over):
    store = store or make_store()
    args = {"character_slug": "biscuit", "source_id": None, "mode": Mode.recreate, "features": FEATURES}
    args.update(over)
    return store, new_clip(store, **args)


def walk(store, clip_id, *states):
    clip = None
    for state in states:
        clip = transition(store, clip_id, state)
    return clip


# ---- the table itself --------------------------------------------------------------------


def test_allowed_is_exactly_the_spec():
    assert ALLOWED == {
        S.planned: {S.generating, S.dropped},
        S.generating: {S.generated, S.gen_failed},
        S.gen_failed: {S.generating, S.dropped},
        S.generated: {S.qa_passed, S.qa_failed},
        S.qa_failed: {S.generating, S.dropped},
        S.qa_passed: {S.mastered},
        S.mastered: {S.awaiting_approval, S.scheduled},
        S.awaiting_approval: {S.approved, S.rejected},
        S.approved: {S.scheduled},
        S.scheduled: {S.posted, S.rejected},  # rejected: a scheduled clip whose posts were all dropped
    }
    # Final states have no way out: rejected, posted and dropped are not keys at all.
    assert set(S) - set(ALLOWED) == {S.rejected, S.posted, S.dropped}


def test_required_features_is_exactly_the_spec():
    assert REQUIRED_FEATURES == {
        "format_id", "hook_pattern", "hook_text", "prop", "setting", "motion_type",
        "audio_arm", "bodies_in_frame", "seamless_loop", "eye_closeup_end", "trend_name",
    }


@pytest.mark.parametrize("src", list(S))
def test_every_pair_is_allowed_or_refused_exactly_as_the_table_says(src):
    for dst in S:
        store, clip = fresh()
        store.update_clip(clip.id, state=src)  # seeding the starting state, not under test
        if dst in ALLOWED.get(src, set()):
            assert transition(store, clip.id, dst).state is dst
        else:
            with pytest.raises(IllegalTransition):
                transition(store, clip.id, dst)
            assert store.get_clip(clip.id).state is src


# ---- state machine -----------------------------------------------------------------------


def test_happy_path_to_awaiting_approval():
    store, clip = fresh()
    assert clip.state is S.planned
    for state in (S.generating, S.generated, S.qa_passed, S.mastered, S.awaiting_approval):
        clip = transition(store, clip.id, state)
        assert clip.state is state
        assert store.get_clip(clip.id).state is state  # persisted, not just returned


def test_approval_branches_after_awaiting_approval():
    store, clip = fresh()
    walk(store, clip.id, S.generating, S.generated, S.qa_passed, S.mastered, S.awaiting_approval)
    assert walk(store, clip.id, S.approved, S.scheduled, S.posted).state is S.posted

    store, clip = fresh()  # an `auto` account skips approval
    walk(store, clip.id, S.generating, S.generated, S.qa_passed, S.mastered)
    assert walk(store, clip.id, S.scheduled).state is S.scheduled

    store, clip = fresh()
    walk(store, clip.id, S.generating, S.generated, S.qa_passed, S.mastered, S.awaiting_approval)
    assert walk(store, clip.id, S.rejected).state is S.rejected


def test_illegal_jump_rejected():
    store, clip = fresh()
    with pytest.raises(IllegalTransition, match="planned"):
        transition(store, clip.id, S.posted)
    assert store.get_clip(clip.id).state is S.planned


def test_final_states_cannot_be_left():
    store, clip = fresh()
    transition(store, clip.id, S.dropped)
    with pytest.raises(IllegalTransition, match="final"):
        transition(store, clip.id, S.generating)


def test_reroll_from_qa_failed_allowed_once():
    store, clip = fresh()
    assert clip.features["rerolls"] == 0
    walk(store, clip.id, S.generating, S.generated, S.qa_failed)
    clip = transition(store, clip.id, S.generating)  # the one re-roll
    assert clip.state is S.generating and clip.features["rerolls"] == 1
    walk(store, clip.id, S.generated, S.qa_failed)
    with pytest.raises(IllegalTransition, match="max one re-roll") as err:
        transition(store, clip.id, S.generating)
    assert str(err.value) == "max one re-roll"
    stored = store.get_clip(clip.id)
    assert (stored.state, stored.features["rerolls"]) == (S.qa_failed, 1)
    assert transition(store, clip.id, S.dropped).state is S.dropped  # the way out that is left


def test_reroll_keeps_the_other_feature_tags():
    store, clip = fresh()
    walk(store, clip.id, S.generating, S.generated, S.qa_failed)
    clip = transition(store, clip.id, S.generating)
    assert {k: v for k, v in clip.features.items() if k != "rerolls"} == FEATURES


def test_retry_after_gen_failed_is_not_a_reroll():
    store, clip = fresh()
    walk(store, clip.id, S.generating, S.gen_failed, S.generating, S.gen_failed)
    clip = transition(store, clip.id, S.generating)
    assert clip.features["rerolls"] == 0
    # ... and the one re-roll is still there for a QA failure afterwards
    walk(store, clip.id, S.generated, S.qa_failed)
    assert transition(store, clip.id, S.generating).features["rerolls"] == 1


def test_transition_unknown_clip_and_bad_state():
    store, clip = fresh()
    with pytest.raises(KeyError):
        transition(store, "no-such-clip", S.generating)
    with pytest.raises(ValueError, match="state"):
        transition(store, clip.id, "teleported")
    assert transition(store, clip.id, "generating").state is S.generating  # plain strings are fine


def test_transition_sets_fields_in_the_same_write():
    store, clip = fresh()
    clip = transition(store, clip.id, S.generating, hf_job_id="job-1", credits_reserved=115)
    assert (clip.state, clip.hf_job_id, clip.credits_reserved) == (S.generating, "job-1", 115)
    clip = transition(store, clip.id, S.generated, credits_actual=112)
    assert clip.credits_actual == 112
    clip = transition(store, clip.id, S.qa_failed, qa={"flags": ["anatomy"]})
    assert clip.qa == {"flags": ["anatomy"]}
    store.update_clip(clip.id, state=S.awaiting_approval)  # seed; the paths into it are covered above
    clip = transition(store, clip.id, S.rejected, reject_reason="off-brand smile")
    assert (clip.state, clip.reject_reason) == (S.rejected, "off-brand smile")


def test_refused_transition_applies_none_of_its_fields():
    store, clip = fresh()
    with pytest.raises(IllegalTransition):
        transition(store, clip.id, S.posted, hook="should not stick")
    assert store.get_clip(clip.id).hook is None


@pytest.mark.parametrize(
    "bad", ["state", "features", "id", "character_slug", "source_id", "mode", "created_at", "nope"]
)
def test_transition_only_takes_settable_fields(bad):
    store, clip = fresh()
    with pytest.raises(TypeError, match=bad):
        transition(store, clip.id, S.generating, **{bad: "x"})
    assert store.get_clip(clip.id) == clip  # nothing moved, nothing written


def test_transition_reads_and_writes_inside_one_transaction():
    # PostgresStore opens a connection per call outside transaction(); the read-check-write of a
    # transition must share one so the state it checked is the state it updates.
    events: list[str] = []

    class Spy(MemoryStore):
        def transaction(self):
            events.append("begin")
            outer = super().transaction()

            class Ctx:
                def __enter__(_self):
                    return outer.__enter__()

                def __exit__(_self, *exc):
                    events.append("end")
                    return outer.__exit__(*exc)

            return Ctx()

        def get_clip(self, id):
            events.append("get_clip")
            return super().get_clip(id)

        def update_clip(self, id, /, **kw):
            events.append("update_clip")
            return super().update_clip(id, **kw)

    store = Spy()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    _, clip = fresh(store)
    events.clear()
    transition(store, clip.id, S.generating)
    assert events == ["begin", "get_clip", "update_clip", "end"]


# ---- a clip that leaves `scheduled` for rejected / dropped takes its never-sent posts with it ------


def scheduled_clip_with_posts(**posts: dict):
    """A scheduled clip and one post per name in ``posts`` (the fields it is made with); {name: Post}."""
    store, clip = fresh()
    walk(store, clip.id, S.generating, S.generated, S.qa_passed, S.mastered, S.scheduled)
    when = datetime(2026, 10, 7, 19, 30, tzinfo=LONDON)
    made = {
        name: store.add_post(Post(clip_id=clip.id, account_id=f"acct-{name}", scheduled_for=when, **fields))
        for name, fields in posts.items()
    }
    return store, clip, made


def test_rejecting_a_scheduled_clip_deletes_its_scheduled_and_failed_posts():
    store, clip, p = scheduled_clip_with_posts(
        due={}, broken={"status": "failed", "attempts": 3, "error": "boom"}
    )
    assert transition(store, clip.id, S.rejected, reject_reason="old version").state is S.rejected
    assert store.list_posts(clip_id=clip.id) == []
    assert store.list_posts(id=p["due"].id) == [] and store.list_posts(id=p["broken"].id) == []


def test_rejecting_a_scheduled_clip_keeps_a_post_that_may_be_live():
    store, clip, p = scheduled_clip_with_posts(
        sending={"status": "posting"},
        unsure={"status": "needs_check"},
        live={"status": "posted", "platform_post_id": "pz-1"},
        refused={"status": "failed", "platform_post_id": "pz-2"},  # a platform id: it went out
        measured={"status": "failed"},
        due={},
    )
    store.add_snapshot(Snapshot(post_id=p["measured"].id, views=10))  # a metrics reading: it was live
    transition(store, clip.id, S.rejected, reject_reason="old version")
    assert {x.id for x in store.list_posts(clip_id=clip.id)} == {
        p[k].id for k in ("sending", "unsure", "live", "refused", "measured")
    }


def test_rejecting_a_scheduled_clip_leaves_the_posts_of_other_clips_alone():
    store, clip, _ = scheduled_clip_with_posts(due={})
    _, other = fresh(store)
    walk(store, other.id, S.generating, S.generated, S.qa_passed, S.mastered, S.scheduled)
    keep = store.add_post(
        Post(clip_id=other.id, account_id="acct-due", scheduled_for=datetime(2026, 10, 7, 19, 30, tzinfo=LONDON))
    )
    transition(store, clip.id, S.rejected, reject_reason="old version")
    assert [x.id for x in store.list_posts()] == [keep.id]


def test_dropping_a_scheduled_clip_deletes_its_never_sent_posts(monkeypatch):
    # the table has no scheduled -> dropped today; the rule follows the destination, not the table
    monkeypatch.setitem(ALLOWED, S.scheduled, {S.posted, S.rejected, S.dropped})
    store, clip, _ = scheduled_clip_with_posts(due={}, broken={"status": "failed"})
    transition(store, clip.id, S.dropped, reject_reason="gone")
    assert store.list_posts(clip_id=clip.id) == []


def test_other_moves_out_of_scheduled_or_into_rejected_do_not_delete_posts():
    store, clip, p = scheduled_clip_with_posts(live={"status": "posted", "platform_post_id": "pz-1"})
    transition(store, clip.id, S.posted)
    assert [x.id for x in store.list_posts(clip_id=clip.id)] == [p["live"].id]
    store, clip = fresh()  # a clip rejected from awaiting_approval has no posts to take
    walk(store, clip.id, S.generating, S.generated, S.qa_passed, S.mastered, S.awaiting_approval)
    assert transition(store, clip.id, S.rejected, reject_reason="no").state is S.rejected


def test_a_refused_transition_deletes_no_post():
    store, clip, p = scheduled_clip_with_posts(due={})
    with pytest.raises(IllegalTransition):
        transition(store, clip.id, S.approved)  # scheduled -> approved is not allowed
    assert [x.id for x in store.list_posts(clip_id=clip.id)] == [p["due"].id]


# ---- set_fields (non-state fields, written directly) ------------------------------------------


def test_set_fields_writes_non_state_fields_without_moving_the_state():
    store, clip = fresh()
    clip = set_fields(
        store, clip.id, hook="he knows", caption="tea. again.", hashtags=["#odd", "#eyes"],
        qa={"tech": "ok"}, master_path="clips/x.mp4", hf_job_id="j", credits_reserved=115,
        credits_actual=110,
    )
    assert clip.state is S.planned
    assert (clip.hook, clip.caption, clip.hashtags) == ("he knows", "tea. again.", ["#odd", "#eyes"])
    assert (clip.qa, clip.master_path, clip.hf_job_id) == ({"tech": "ok"}, "clips/x.mp4", "j")
    assert (clip.credits_reserved, clip.credits_actual) == (115, 110)
    assert store.get_clip(clip.id) == clip


@pytest.mark.parametrize("bad", ["state", "features", "id", "mode", "nope"])
def test_set_fields_refuses_state_and_everything_else_off_the_list(bad):
    store, clip = fresh()
    with pytest.raises(TypeError, match=bad):
        set_fields(store, clip.id, **{bad: "x"})
    assert store.get_clip(clip.id) == clip


def test_set_fields_state_error_points_at_transition():
    store, clip = fresh()
    with pytest.raises(TypeError, match="transition"):
        set_fields(store, clip.id, state=S.posted)


def test_set_fields_unknown_clip():
    with pytest.raises(KeyError):
        set_fields(make_store(), "no-such-clip", hook="x")


# ---- feature tags ------------------------------------------------------------------------


def test_new_clip_starts_planned_with_its_tags():
    store = make_store()
    src = add_source(store)
    clip = new_clip(store, "reginald", src.id, "dropin", FEATURES)
    assert (clip.state, clip.mode, clip.character_slug, clip.source_id) == (
        S.planned, Mode.dropin, "reginald", src.id,
    )
    assert clip.id and clip.created_at
    assert clip.features == {**FEATURES, "rerolls": 0}
    assert store.get_clip(clip.id) == clip


def test_new_clip_accepts_extra_tags_and_falsy_values_and_does_not_alias():
    store = make_store()
    feats = {**FEATURES, "seamless_loop": False, "eye_closeup_end": False, "bodies_in_frame": 0,
             "hook_chars": 21}
    clip = new_clip(store, "biscuit", None, Mode.recreate, feats)
    assert clip.features["seamless_loop"] is False and clip.features["hook_chars"] == 21
    assert "rerolls" not in feats  # the caller's dict is not touched
    feats["prop"] = "changed later"
    assert store.get_clip(clip.id).features["prop"] == "teacup"


def test_missing_features_rejected():
    store = make_store()
    feats = {k: v for k, v in FEATURES.items() if k not in ("prop", "audio_arm")}
    with pytest.raises(ValueError) as err:
        new_clip(store, "biscuit", None, Mode.recreate, feats)
    assert "audio_arm" in str(err.value) and "prop" in str(err.value)
    assert "format_id" not in str(err.value)  # only what is missing
    assert store.list_clips() == []


@pytest.mark.parametrize("arm", ["in_app", "ai_beat"])
def test_the_music_tag_is_checked_when_present(arm):
    store = make_store()
    clip = new_clip(store, "biscuit", None, Mode.dropin, {**FEATURES, "music": arm})
    assert clip.features["music"] == arm
    with pytest.raises(ValueError, match="music"):
        new_clip(store, "biscuit", None, Mode.dropin, {**FEATURES, "music": "spotify"})
    assert len(store.list_clips()) == 1


def test_original_audio_is_only_for_a_dropin():
    """music "original" keeps the Genjutsu output's own audio: it exists only for a Drop-in."""
    store = make_store()
    assert new_clip(store, "biscuit", None, Mode.dropin, {**FEATURES, "music": "original"}).features["music"] == "original"
    with pytest.raises(ValueError, match="original"):
        new_clip(store, "biscuit", None, Mode.recreate, {**FEATURES, "music": "original"})


def test_a_tag_without_a_value_counts_as_missing():
    store = make_store()
    with pytest.raises(ValueError, match="trend_name"):
        new_clip(store, "biscuit", None, Mode.recreate, {**FEATURES, "trend_name": None})
    with pytest.raises(ValueError) as err:
        new_clip(store, "biscuit", None, Mode.recreate, {})
    assert all(k in str(err.value) for k in REQUIRED_FEATURES)


def test_rerolls_is_the_state_machines_not_the_callers():
    store = make_store()
    with pytest.raises(ValueError, match="rerolls"):
        new_clip(store, "biscuit", None, Mode.recreate, {**FEATURES, "rerolls": 1})
    assert store.list_clips() == []


def test_new_clip_refuses_unknown_character_source_and_mode():
    store = make_store()
    with pytest.raises(ValueError, match="character"):
        new_clip(store, "nobody", None, Mode.recreate, FEATURES)
    with pytest.raises(ValueError, match="source"):
        new_clip(store, "biscuit", "no-such-source", Mode.recreate, FEATURES)
    with pytest.raises(ValueError, match="mode"):
        new_clip(store, "biscuit", None, "remix", FEATURES)
    assert store.list_clips() == []


def test_new_clip_accepts_mode_as_string():
    store = make_store()
    assert new_clip(store, "biscuit", None, "recreate", FEATURES).mode is Mode.recreate


# ---- the learning tags (docs/launch/measurement-and-learning-plan.md section 2) --------------------------

# a Recreate made by hand that opts in (``source_kind``): every learning tag, each from its vocabulary
LEARN = {
    **FEATURES, "format_id": "recreate", "hook_pattern": "ego-claim", "hook_index": 0, "hook_by": "studio",
    "caption_line1": "label-first", "first_comment_kind": "vote", "trend_stage": "none", "days_since_trend_peak": None,
    "sound_type": "ai_beat", "sound_rising": False, "score_bucket": "none", "score_total": None, "score_potential": None,
    "score_swap": None, "part": "star", "family_id": "none", "version_index": 1, "series": "none", "episode": None,
    "hit_rules_version": "v1", "source_kind": "recreate", "test_arms": {}, "explore_pick": False,
}


def test_the_learning_tags_are_the_plans():
    assert clips.LEARN_FEATURES == {
        "hook_index", "hook_by", "caption_line1", "first_comment_kind", "trend_stage", "days_since_trend_peak", "sound_type",
        "sound_rising", "length_s", "length_bucket", "score_bucket", "score_total", "score_potential", "score_swap", "part",
        "family_id", "version_index", "series", "episode", "hit_rules_version", "source_kind", "test_arms", "explore_pick",
    }
    assert clips.MASTER_FEATURES == {"length_s", "length_bucket"} < clips.LEARN_FEATURES  # the master writes these two
    assert not clips.LEARN_FEATURES & REQUIRED_FEATURES  # format_id and hook_pattern stay required for every clip
    v = clips.LEARN_VALUES
    assert v["format_id"] == ("swap_trend", "swap_classic", "swap_other", "recreate", "own_footage")
    assert v["hook_pattern"] == (
        "ego-claim", "when-relatable", "false-premise", "understatement", "mid-deal", "trend-label", "myth-bust", "owner", "none",
    )
    assert v["caption_line1"] == ("label-first", "joke-first") and v["first_comment_kind"] == ("vote", "question", "none")
    assert v["trend_stage"] == ("rising", "peak", "fading", "classic", "none")
    assert v["sound_type"] == ("own_trend_sound", "own_other", "ai_beat", "in_app", "none")
    assert v["length_bucket"] == ("under_8", "8_10", "11_16")
    assert v["score_bucket"] == ("none", "under_50", "50_64", "65_79", "80_up") and v["part"] == ("cameo", "featured", "star")
    assert v["series"] == ("sausage_vs_trend", "household_unaware", "on_hold", "classics", "halloween_countdown", "none")
    assert v["source_kind"] == ("owner_saved", "auto_filed", "own_footage", "recreate")
    assert v["hook_by"] == ("studio", "owner", "bandit")


def test_a_clip_that_opts_in_carries_every_learning_tag():
    store = make_store()
    clip = new_clip(store, "biscuit", None, Mode.recreate, LEARN)
    assert {k: clip.features[k] for k in LEARN} == LEARN and clips.learn_problems(clip.features) == []


@pytest.mark.parametrize("key", sorted(LEARN.keys() - FEATURES.keys() - {"source_kind"}))  # source_kind: below
def test_a_missing_learning_tag_refuses_new_clip(key):
    store = make_store()
    with pytest.raises(ValueError, match=f"missing feature tags: .*{key}"):
        new_clip(store, "biscuit", None, Mode.recreate, {k: v for k, v in LEARN.items() if k != key})
    assert store.list_clips() == []


def test_a_drop_clip_needs_the_learning_tags_even_without_source_kind():
    """``studio drop`` marks its clips ``drop: True``: one that lost a tag (or ``source_kind`` itself) is refused."""
    store = make_store()
    no_kind = {k: v for k, v in LEARN.items() if k != "source_kind"}
    with pytest.raises(ValueError, match="source_kind"):
        new_clip(store, "biscuit", None, Mode.dropin, {**no_kind, "drop": True, "fav_id": "p1"})
    with pytest.raises(ValueError, match="hook_index"):
        new_clip(store, "biscuit", None, Mode.dropin, {**FEATURES, "drop": True, "fav_id": "p1"})
    assert store.list_clips() == []


def test_a_by_hand_clip_that_does_not_opt_in_is_made_as_before():
    """Legacy and by-hand clips (no ``source_kind``, no pick, not a drop's): the eleven required tags are enough."""
    store = make_store()
    assert new_clip(store, "biscuit", None, Mode.recreate, FEATURES).features["format_id"] == "B1"


def test_every_clip_made_from_a_pick_needs_the_learning_tags():
    """A clip whose features name its pick (``fav_id``: the daily run's Recreate or Drop-in of a pick) is a made clip to learn
    from, whatever else it says: without the learning tags it is refused; with them (the daily-run create step) it is made."""
    store = make_store()
    with pytest.raises(ValueError, match="missing feature tags: .*hook_index"):
        new_clip(store, "biscuit", None, Mode.recreate, {**FEATURES, "fav_id": "p1"})
    assert store.list_clips() == []
    clip = new_clip(store, "biscuit", None, Mode.recreate, {**LEARN, "fav_id": "p1", "family_id": "p1"})
    assert clip.features["fav_id"] == "p1" and clip.features["source_kind"] == "recreate"
    assert clips.needs_learn_tags({"fav_id": "p1"}) and not clips.needs_learn_tags({"fav_id": None})
    assert not clips.needs_learn_tags(FEATURES)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"format_id": "drop_object_swap"}, "format_id"),
        ({"hook_pattern": "drop"}, "hook_pattern"),
        ({"hook_by": "bandito"}, "hook_by"),
        ({"hook_index": 4}, "hook_index"),
        ({"hook_index": True}, "hook_index"),
        ({"caption_line1": "hook-first"}, "caption_line1"),
        ({"first_comment_kind": "poll"}, "first_comment_kind"),
        ({"trend_stage": "dead"}, "trend_stage"),
        ({"days_since_trend_peak": -1}, "days_since_trend_peak"),
        ({"sound_type": "spotify"}, "sound_type"),
        ({"sound_rising": 1}, "sound_rising"),
        ({"explore_pick": "no"}, "explore_pick"),
        ({"score_bucket": "80_up"}, "score_bucket"),  # no score: the bucket is none
        ({"score_total": 81, "score_potential": 8, "score_swap": 9}, "score_bucket"),  # 81 is 80_up, not none
        ({"score_bucket": "80_up", "score_total": 101, "score_potential": 8, "score_swap": 9}, "score_total"),
        ({"score_bucket": "65_79", "score_total": 70, "score_potential": 11, "score_swap": 9}, "score_potential"),
        ({"part": "lead"}, "part"),
        ({"family_id": ""}, "family_id"),
        ({"version_index": 4}, "version_index"),
        ({"version_index": 0}, "version_index"),
        ({"series": "my_series"}, "series"),
        ({"episode": 0}, "episode"),
        ({"hit_rules_version": ""}, "hit_rules_version"),
        ({"hit_rules_version": "1"}, "hit_rules_version"),
        ({"hit_rules_version": "v1.2"}, "hit_rules_version"),
        ({"hit_rules_version": "V1"}, "hit_rules_version"),
        ({"hit_rules_version": "v"}, "hit_rules_version"),
        ({"hit_rules_version": "v1 · 2026-10-08"}, "hit_rules_version"),
        ({"score_potential": 7}, "score_potential"),  # no score (bucket none): no score numbers either
        ({"score_swap": 9}, "score_swap"),
        ({"days_since_trend_peak": 3}, "days_since_trend_peak"),  # trend_stage none: no days since a peak
        ({"trend_stage": "classic", "days_since_trend_peak": 3}, "days_since_trend_peak"),  # a classic never peaks
        ({"episode": 2}, "episode"),  # series none: no episode
        ({"source_kind": "scraped"}, "source_kind"),
        ({"test_arms": []}, "test_arms"),
        ({"hook_by": None}, "hook_by"),  # a categorical tag is never null: "none" is a value
    ],
)
def test_a_learning_tag_outside_its_vocabulary_refuses_new_clip(change, problem):
    store = make_store()
    with pytest.raises(ValueError, match=problem):
        new_clip(store, "biscuit", None, Mode.recreate, {**LEARN, **change})
    assert store.list_clips() == []


def test_the_score_tags_agree():
    store = make_store()
    scored = {**LEARN, "score_bucket": "65_79", "score_total": 78, "score_potential": 7, "score_swap": 9}
    assert new_clip(store, "biscuit", None, Mode.recreate, scored).features["score_bucket"] == "65_79"


def test_the_detail_tags_go_with_their_tag():
    store = make_store()
    rising = new_clip(store, "biscuit", None, Mode.recreate, {**LEARN, "trend_stage": "rising", "days_since_trend_peak": 3})
    assert rising.features["days_since_trend_peak"] == 3
    episode = new_clip(store, "biscuit", None, Mode.recreate, {**LEARN, "series": "household_unaware", "episode": 2})
    assert episode.features["episode"] == 2
    for version in ("none", "v1", "v12"):
        assert new_clip(store, "biscuit", None, Mode.recreate, {**LEARN, "hit_rules_version": version})


@pytest.mark.parametrize(
    ("total", "bucket"),
    [(None, "none"), (0, "under_50"), (49, "under_50"), (50, "50_64"), (64, "50_64"), (65, "65_79"), (79, "65_79"),
     (80, "80_up"), (100, "80_up")],
)
def test_score_bucket(total, bucket):
    assert clips.score_bucket(total) == bucket


@pytest.mark.parametrize(
    ("seconds", "bucket"),
    [(6.0, "under_8"), (7.99, "under_8"), (8.0, "8_10"), (10.9, "8_10"), (10.99, "8_10"), (11.0, "11_16"), (16.0, "11_16")],
)
def test_length_bucket(seconds, bucket):
    assert clips.length_bucket(seconds) == bucket


def test_set_length_writes_the_masters_length_and_its_bucket():
    store, clip = fresh(features=LEARN)
    got = clips.set_length(store, clip.id, 9.0333)
    assert got.features["length_s"] == 9.03 and got.features["length_bucket"] == "8_10"
    assert {k: got.features[k] for k in LEARN} == LEARN  # the other tags are kept
    with pytest.raises(KeyError):
        clips.set_length(store, "nope", 9.0)
    with pytest.raises(ValueError):
        clips.set_length(store, clip.id, float("nan"))


# ---- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(clips, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["clip", *args])


def cli_new(**over):
    base = {"--character": "biscuit", "--mode": "recreate", "--features": json.dumps(FEATURES)}
    base.update(over)
    return [x for kv in base.items() for x in kv]


def cli_clip(cli_store, **over) -> str:
    r = run("new", *cli_new(**over))
    assert r.exit_code == 0, r.output
    return json.loads(r.stdout)["id"]


def test_cli_new_prints_the_clip(cli_store):
    r = run("new", *cli_new())
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["state"], out["mode"], out["character_slug"]) == ("planned", "recreate", "biscuit")
    assert out["features"] == {**FEATURES, "rerolls": 0}
    assert out["next_states"] == ["dropped", "generating"]
    assert cli_store.get_clip(out["id"]) is not None


def test_cli_new_with_a_source(cli_store):
    src = add_source(cli_store)
    out = json.loads(run("new", *cli_new(**{"--source": src.id})).stdout)
    assert out["source_id"] == src.id


def test_cli_new_missing_tags_exit_2_and_names_them(cli_store):
    feats = {k: v for k, v in FEATURES.items() if k != "setting"}
    r = run("new", *cli_new(**{"--features": json.dumps(feats)}))
    assert r.exit_code == 2 and "setting" in r.output
    assert cli_store.list_clips() == []


def test_cli_new_rejects_bad_features_json_and_values(cli_store):
    assert run("new", *cli_new(**{"--features": "{not json"})).exit_code == 2
    assert run("new", *cli_new(**{"--features": "[1, 2]"})).exit_code == 2
    assert run("new", *cli_new(**{"--mode": "remix"})).exit_code == 2
    assert run("new", *cli_new(**{"--character": "nobody"})).exit_code == 2
    assert run("new", *cli_new(**{"--source": "nope"})).exit_code == 2
    assert run("new", "--character", "biscuit", "--mode", "recreate").exit_code == 2  # no --features
    assert cli_store.list_clips() == []


def test_cli_set_state_goes_through_the_state_machine(cli_store):
    cid = cli_clip(cli_store)
    r = run("set", cid, "--state", "posted")
    assert r.exit_code == 2 and "planned" in r.output and "posted" in r.output
    assert cli_store.get_clip(cid).state is S.planned

    r = run("set", cid, "--state", "generating", "--hf-job-id", "job-7", "--credits-reserved", "115")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["state"], out["hf_job_id"], out["credits_reserved"]) == ("generating", "job-7", 115)
    assert out["next_states"] == ["gen_failed", "generated"]


def test_cli_set_refused_state_applies_no_other_field(cli_store):
    cid = cli_clip(cli_store)
    r = run("set", cid, "--state", "posted", "--hook", "should not stick")
    assert r.exit_code == 2
    assert cli_store.get_clip(cid).hook is None


def test_cli_set_second_reroll_refused(cli_store):
    cid = cli_clip(cli_store)
    for state in ("generating", "generated", "qa_failed", "generating", "generated", "qa_failed"):
        assert run("set", cid, "--state", state).exit_code == 0
    r = run("set", cid, "--state", "generating")
    assert r.exit_code == 2 and "max one re-roll" in r.output
    assert cli_store.get_clip(cid).state is S.qa_failed


def test_cli_set_plain_fields_leave_the_state_alone(cli_store):
    cid = cli_clip(cli_store)
    r = run(
        "set", cid, "--hook", "he knows", "--caption", "tea. again.", "--hashtag", "#odd",
        "--hashtag", "#eyes", "--qa", '{"tech": "ok"}', "--master-path", "clips/a.mp4",
        "--credits-reserved", "115", "--credits-actual", "0",
    )
    assert r.exit_code == 0, r.output
    clip = cli_store.get_clip(cid)
    assert clip.state is S.planned
    assert (clip.hook, clip.caption, clip.hashtags) == ("he knows", "tea. again.", ["#odd", "#eyes"])
    assert (clip.qa, clip.master_path) == ({"tech": "ok"}, "clips/a.mp4")
    assert (clip.credits_reserved, clip.credits_actual) == (115, 0)  # zero is a value, not "unset"


def test_cli_set_caption_over_the_post_limit_is_refused_with_the_disclosure_counted(cli_store):
    """The text posted is caption + AI disclosure + hashtags: over 2,200 is refused when it is set."""
    cid = cli_clip(cli_store)
    r = run("set", cid, "--caption", "z" * 2190)  # the disclosure line alone takes it past 2,200
    assert r.exit_code == 2 and "2200" in r.output and "caption" in r.output
    assert cli_store.get_clip(cid).caption is None  # nothing written
    assert run("set", cid, "--caption", "z" * 2100).exit_code == 0


def test_cli_set_hashtags_are_checked_against_the_caption_already_stored(cli_store):
    cid = cli_clip(cli_store)
    assert run("set", cid, "--caption", "z" * 2100).exit_code == 0
    r = run("set", cid, "--hashtag", "#" + "t" * 90)
    assert r.exit_code == 2 and "2200" in r.output
    assert cli_store.get_clip(cid).hashtags == []


def test_cli_set_a_state_move_with_an_over_long_caption_writes_nothing(cli_store):
    cid = cli_clip(cli_store)
    r = run("set", cid, "--state", "generating", "--caption", "z" * 3000)
    assert r.exit_code == 2 and cli_store.get_clip(cid).state is S.planned


def test_cli_set_without_caption_or_hashtags_is_not_checked(cli_store):
    cid = cli_clip(cli_store)
    cli_store.update_clip(cid, caption="z" * 5000)  # whatever is stored already: a hook edit still works
    assert run("set", cid, "--hook", "h").exit_code == 0


def test_cli_set_one_field_leaves_the_others_alone(cli_store):
    cid = cli_clip(cli_store)
    run("set", cid, "--hook", "h", "--hashtag", "#a", "--qa", '{"k": 1}', "--credits-reserved", "9")
    assert run("set", cid, "--caption", "c").exit_code == 0
    clip = cli_store.get_clip(cid)
    assert (clip.caption, clip.hook, clip.hashtags, clip.qa, clip.credits_reserved) == (
        "c", "h", ["#a"], {"k": 1}, 9,
    )


def test_cli_set_needs_something_to_set_and_a_real_clip(cli_store):
    cid = cli_clip(cli_store)
    assert run("set", cid).exit_code == 2
    r = run("set", "nope", "--hook", "x")
    assert r.exit_code == 2 and "unknown clip" in r.output
    r = run("set", "nope", "--state", "generating")
    assert r.exit_code == 2 and "unknown clip" in r.output


def test_cli_set_rejects_bad_values(cli_store):
    cid = cli_clip(cli_store)
    assert run("set", cid, "--state", "teleported").exit_code == 2
    assert run("set", cid, "--qa", "[1]").exit_code == 2
    assert run("set", cid, "--qa", "{nope").exit_code == 2
    assert run("set", cid, "--credits-reserved", "-1").exit_code == 2
    assert run("set", cid, "--credits-actual", "lots").exit_code == 2


def test_cli_show_and_unknown(cli_store):
    cid = cli_clip(cli_store)
    out = json.loads(run("show", cid).stdout)
    assert (out["id"], out["state"], out["next_states"]) == (cid, "planned", ["dropped", "generating"])
    r = run("show", "nope")
    assert r.exit_code == 2 and "unknown clip" in r.output


def test_cli_show_final_state_has_no_next_states(cli_store):
    cid = cli_clip(cli_store)
    run("set", cid, "--state", "dropped")
    assert json.loads(run("show", cid).stdout)["next_states"] == []


def test_cli_list_filters(cli_store):
    a = cli_clip(cli_store)
    b = cli_clip(cli_store, **{"--character": "reginald"})
    src = add_source(cli_store)
    c = cli_clip(cli_store, **{"--mode": "dropin", "--source": src.id})
    run("set", a, "--state", "generating")

    def ids(*args):
        r = run("list", *args)
        assert r.exit_code == 0, r.output
        return [x["id"] for x in json.loads(r.stdout)]

    assert ids() == [a, b, c]
    assert ids("--state", "planned") == [b, c]
    assert ids("--state", "generating") == [a]
    assert ids("--character", "reginald") == [b]
    assert ids("--mode", "dropin") == [c]
    assert ids("--source", src.id) == [c]
    assert ids("--character", "biscuit", "--state", "planned") == [c]
    assert ids("--state", "posted") == []
    assert run("list", "--state", "teleported").exit_code == 2


def test_clip_group_is_registered_once():
    r = CliRunner().invoke(app, ["clip", "--help"])
    assert r.exit_code == 0
    for cmd in ("new", "set", "show", "list"):
        assert cmd in r.output


# ---- the source may be linked while the clip is still planned ---------------------------------------
# A synthetic driver only exists after the clip was created and its credits reserved, so the clip
# has to take its source later. Once generation starts the source is fixed again.


def test_set_source_links_a_source_to_a_planned_clip():
    store, clip = fresh()
    src = add_source(store)
    got = set_source(store, clip.id, src.id)
    assert got.source_id == src.id and got.state is S.planned
    assert store.get_clip(clip.id).source_id == src.id


def test_set_source_can_swap_the_source_while_planned():
    store, clip = fresh()
    a, b = add_source(store), add_source(store)
    set_source(store, clip.id, a.id)
    assert set_source(store, clip.id, b.id).source_id == b.id


@pytest.mark.parametrize(
    "state", [S.generating, S.gen_failed, S.generated, S.qa_failed, S.qa_passed, S.mastered, S.awaiting_approval, S.dropped]
)
def test_set_source_is_refused_once_the_clip_left_planned(state):
    store, clip = fresh()
    src = add_source(store)
    store.update_clip(clip.id, state=state)  # straight to the state under test
    with pytest.raises(ValueError, match="planned"):
        set_source(store, clip.id, src.id)
    assert store.get_clip(clip.id).source_id is None


def test_set_source_refuses_an_unknown_source_or_clip():
    store, clip = fresh()
    with pytest.raises(ValueError, match="unknown source"):
        set_source(store, clip.id, "no-such-source")
    assert store.get_clip(clip.id).source_id is None
    with pytest.raises(KeyError):
        set_source(store, "nope", add_source(store).id)


def test_source_id_is_still_not_a_settable_field():
    store, clip = fresh()
    with pytest.raises(TypeError, match="source_id"):
        set_fields(store, clip.id, source_id=add_source(store).id)  # only set_source may move it


def test_cli_set_source_id_on_a_planned_clip(cli_store):
    cid = cli_clip(cli_store)
    src = add_source(cli_store)
    r = run("set", cid, "--source-id", src.id)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["source_id"], out["state"]) == (src.id, "planned")


def test_cli_set_source_id_with_the_state_move_applies_the_source_first(cli_store):
    cid = cli_clip(cli_store)
    src = add_source(cli_store)
    r = run("set", cid, "--source-id", src.id, "--state", "generating", "--credits-reserved", "160")
    assert r.exit_code == 0, r.output
    clip = cli_store.get_clip(cid)
    assert (clip.source_id, clip.state, clip.credits_reserved) == (src.id, S.generating, 160)


def test_cli_set_source_id_is_refused_after_planned_and_for_unknown_sources(cli_store):
    cid = cli_clip(cli_store)
    src = add_source(cli_store)
    r = run("set", cid, "--source-id", "nope")
    assert r.exit_code == 2 and "unknown source" in r.output
    assert run("set", cid, "--state", "generating").exit_code == 0
    r = run("set", cid, "--source-id", src.id)
    assert r.exit_code == 2 and "planned" in r.output
    assert cli_store.get_clip(cid).source_id is None
    assert run("set", "nope", "--source-id", src.id).exit_code == 2


def test_cli_set_a_refused_source_applies_no_other_field(cli_store):
    cid = cli_clip(cli_store)
    r = run("set", cid, "--source-id", "nope", "--hook", "should not stick")
    assert r.exit_code == 2
    assert cli_store.get_clip(cid).hook is None


# ---- free text through files (never inline in the shell line) ---------------------------------------

NASTY = "it's $(echo pwned) `x` \"q\" ; && | > \U0001F499"


def test_cli_set_text_fields_from_files(cli_store, tmp_path):
    cid = cli_clip(cli_store)
    hook, caption, qa = tmp_path / "h.txt", tmp_path / "c.txt", tmp_path / "q.json"
    hook.write_text(NASTY + "\n", encoding="utf-8")
    caption.write_text(NASTY + " caption\n", encoding="utf-8")
    qa.write_text(json.dumps({"tech": "ok", "visual": NASTY}), encoding="utf-8")
    r = run("set", cid, "--hook-file", str(hook), "--caption-file", str(caption), "--qa-file", str(qa))
    assert r.exit_code == 0, r.output
    clip = cli_store.get_clip(cid)
    assert (clip.hook, clip.caption, clip.qa) == (NASTY, NASTY + " caption", {"tech": "ok", "visual": NASTY})


def test_cli_set_file_and_inline_together_are_refused(cli_store, tmp_path):
    cid = cli_clip(cli_store)
    f = tmp_path / "h.txt"
    f.write_text("x")
    for flag in ("hook", "caption", "qa"):
        r = run("set", cid, f"--{flag}", "{}", f"--{flag}-file", str(f))
        assert r.exit_code == 2 and f"--{flag}" in r.output
    assert run("set", cid, "--hook-file", str(tmp_path / "nope")).exit_code == 2


def test_cli_new_features_from_a_file(cli_store, tmp_path):
    f = tmp_path / "features.json"
    f.write_text(json.dumps({**FEATURES, "hook_text": NASTY}), encoding="utf-8")
    r = run("new", "--character", "biscuit", "--mode", "recreate", "--features-file", str(f))
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["features"]["hook_text"] == NASTY
    assert run("new", "--character", "biscuit", "--mode", "recreate").exit_code == 2  # neither flag
    r = run("new", "--character", "biscuit", "--mode", "recreate", "--features", "{}", "--features-file", str(f))
    assert r.exit_code == 2 and "--features" in r.output
    assert cli_store.list_clips()[0].features["hook_text"] == NASTY and len(cli_store.list_clips()) == 1

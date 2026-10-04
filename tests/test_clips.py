import json

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
    transition,
)
from studio.models import Body, Character, ClipState, Mode, Source, SourceKind
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
               has_watermark=False, has_overlay=False, other_people=0)
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
        S.scheduled: {S.posted},
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

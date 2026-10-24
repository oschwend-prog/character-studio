"""Collab posts (studio/collab.py, owner 2026-10-24): one collab Reel per character per London week, partners rotating weekly."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from studio import collab
from studio.cli import app
from studio.collab import CollabRule, collab_at_make, load_collabs, partner_of, set_collab
from studio.config import LONDON
from studio.models import Account, Character, Clip, ClipState, Mode, Platform
from studio.publish.reach import ReachConfig, plan_post
from studio.store import MemoryStore

WEEK_A = date(2026, 10, 26)  # a Monday: week A of the repo's rule
RULE = CollabRule(on=True, order=("franz", "reginald", "lenny"), since=WEEK_A)
TUE = datetime(2026, 10, 27, 9, 0, tzinfo=LONDON)
HANDLES = {"franz": "franz.unimpressed", "reginald": "reginald.thebutler", "lenny": "lennygold.agent"}


def roster(*, live=("franz", "reginald", "lenny"), postiz=("franz", "reginald", "lenny")) -> MemoryStore:
    store = MemoryStore()
    for slug, handle in HANDLES.items():
        store.add_character(Character(slug=slug, name=slug.title(), status="live" if slug in live else "designing"))
        store.add_account(Account(
            character_slug=slug, platform=Platform.instagram, handle=handle,
            postiz_integration_id=f"pz-{slug}" if slug in postiz else None,
        ))
        store.add_account(Account(character_slug=slug, platform=Platform.tiktok, handle=f"{slug}.tt", postiz_integration_id=f"pt-{slug}"))
    return store


def made(store: MemoryStore, slug: str, at: datetime, rule: CollabRule = RULE, state: ClipState = ClipState.generating) -> Clip:
    """A clip made at ``at`` with the collab tags the make writes (``collab_at_make``), then moved to ``state``."""
    tags = collab_at_make(store, slug, at, rule)
    clip = store.add_clip(Clip(character_slug=slug, mode=Mode.dropin, features={"hook_text": "x", **tags}, created_at=at))
    return store.update_clip(clip.id, state=state) if state is not ClipState.generating else clip


# ---- who partners with whom ------------------------------------------------------------------------------------------------------


def test_week_a_takes_the_next_in_the_ring_week_b_the_one_after_and_then_it_starts_again():
    week_b, week_c = WEEK_A + timedelta(days=7), WEEK_A + timedelta(days=14)
    assert {s: partner_of(RULE, s, WEEK_A) for s in RULE.order} == {"franz": "reginald", "reginald": "lenny", "lenny": "franz"}
    assert {s: partner_of(RULE, s, week_b) for s in RULE.order} == {"franz": "lenny", "reginald": "franz", "lenny": "reginald"}
    assert {s: partner_of(RULE, s, week_c) for s in RULE.order} == {s: partner_of(RULE, s, WEEK_A) for s in RULE.order}
    for monday in (WEEK_A, week_b):  # every character is the guest on exactly one other Reel a week
        assert sorted(partner_of(RULE, s, monday) for s in RULE.order) == sorted(RULE.order)


def test_no_partner_before_the_start_for_a_character_outside_the_ring_or_with_two_always_the_other():
    assert partner_of(RULE, "franz", WEEK_A - timedelta(days=7)) is None
    assert partner_of(RULE, "biscuit", WEEK_A) is None
    two = CollabRule(on=True, order=("franz", "lenny"), since=WEEK_A)
    assert [partner_of(two, "franz", WEEK_A + timedelta(days=7 * k)) for k in range(3)] == ["lenny"] * 3


def test_the_week_is_londons_monday_to_sunday():
    sunday_late = datetime(2026, 11, 1, 23, 30, tzinfo=LONDON)  # still week A
    assert collab.week_of(sunday_late) == WEEK_A and collab.week_of(sunday_late + timedelta(hours=1)) == WEEK_A + timedelta(days=7)


# ---- the rule in config/scan.json ------------------------------------------------------------------------------------------------


def write_scan(tmp_path, block) -> str:
    path = tmp_path / "scan.json"
    path.write_text(json.dumps({"reach": {"stories": True, **({"collabs": block} if block is not None else {})}}), encoding="utf-8")
    return str(path)


def test_the_repos_rule_is_on_from_monday_26_october_with_the_three_characters():
    assert load_collabs(collab.ROOT / "config" / "scan.json") == RULE


def test_an_absent_block_is_off_and_a_broken_one_is_refused_naming_the_key(tmp_path):
    assert load_collabs(write_scan(tmp_path, None)) == collab.OFF
    good = {"on": True, "order": ["franz", "lenny"], "from": "2026-10-26"}
    assert load_collabs(write_scan(tmp_path, good)).order == ("franz", "lenny")
    for bad, key in (
        ({**good, "on": "yes"}, "collabs.on"), ({**good, "order": ["franz"]}, "collabs.order"),
        ({**good, "order": ["franz", "franz"]}, "collabs.order"), ({**good, "order": ["franz", "nobody"]}, "collabs.order"),
        ({**good, "from": "26 Oct"}, "collabs.from"), ({**good, "from": "2026-10-27"}, "a Monday"), ([], "reach.collabs"),
    ):
        with pytest.raises(ValueError, match=key):
            load_collabs(write_scan(tmp_path, bad))


# ---- at make ---------------------------------------------------------------------------------------------------------------------


def test_his_first_clip_of_the_week_takes_the_partner_and_the_next_one_that_week_does_not():
    store = roster()
    first = made(store, "franz", TUE)
    assert first.features["collab"] == ["reginald.thebutler"]
    assert first.features["collab_auto"] == {"week": "2026-10-26", "partner": "reginald"}
    second = made(store, "franz", TUE + timedelta(days=1))
    assert "collab" not in second.features and "collab_auto" not in second.features
    assert made(store, "lenny", TUE).features["collab"] == ["franz.unimpressed"]  # each character has his own week


@pytest.mark.parametrize("state", [ClipState.gen_failed, ClipState.qa_failed, ClipState.rejected, ClipState.dropped])
def test_a_failed_rejected_or_dropped_clip_gives_the_week_back(state):
    store = roster()
    made(store, "franz", TUE, state=state)
    assert made(store, "franz", TUE + timedelta(hours=2)).features["collab"] == ["reginald.thebutler"]


def test_a_posted_or_waiting_clip_keeps_the_week_and_next_week_has_a_new_partner():
    store = roster()
    made(store, "franz", TUE, state=ClipState.posted)
    assert "collab" not in made(store, "franz", TUE + timedelta(days=2)).features
    assert made(store, "franz", TUE + timedelta(days=7)).features["collab"] == ["lennygold.agent"]  # week B


def test_no_collab_when_the_rule_is_off_before_its_start_or_without_a_partner_who_can_post():
    store = roster()
    assert collab_at_make(store, "franz", TUE, CollabRule(on=False, order=RULE.order, since=WEEK_A)) == {}
    assert collab_at_make(store, "franz", TUE - timedelta(days=7), RULE) == {}
    assert collab_at_make(roster(live=("franz", "lenny")), "franz", TUE, RULE) == {}  # Reginald is not live
    assert collab_at_make(roster(postiz=("franz", "lenny")), "franz", TUE, RULE) == {}  # Reginald's Instagram cannot post
    store = roster(live=("franz", "lenny"))
    assert "collab" not in made(store, "franz", TUE).features  # no partner this week: the week is not held ...
    store.add_character(Character(slug="reginald", name="Reginald", status="live"))
    assert made(store, "franz", TUE + timedelta(days=1)).features["collab"] == ["reginald.thebutler"]  # ... a later clip takes it


def test_the_publisher_sends_the_partner_the_make_wrote():
    store = roster()
    clip = made(store, "reginald", TUE)
    accounts = store.accounts()
    ig = next(a for a in accounts if a.character_slug == "reginald" and a.platform is Platform.instagram)
    tt = next(a for a in accounts if a.character_slug == "reginald" and a.platform is Platform.tiktok)
    plan = plan_post(clip, ig, accounts, ReachConfig(), live={"franz", "reginald", "lenny"})
    assert plan.reach.collaborators == ("lennygold.agent",) and plan.reach.trial_reel is False
    assert plan_post(clip, tt, accounts, ReachConfig(), live={"franz", "reginald", "lenny"}).reach.collaborators == ()  # TikTok: none


# ---- the owner's choice ----------------------------------------------------------------------------------------------------------


def test_the_owner_changes_or_removes_the_partner_and_the_week_stays_with_that_clip():
    store = roster()
    clip = made(store, "franz", TUE)
    changed = set_collab(store, clip.id, "@LennyGold.Agent")
    assert changed.features["collab"] == ["lennygold.agent"] and changed.features["collab_by"] == "owner"
    removed = set_collab(store, clip.id, None)
    assert removed.features["collab"] == [] and removed.features["collab_auto"]["week"] == "2026-10-26"
    assert "collab" not in made(store, "franz", TUE + timedelta(days=1)).features  # his call: not handed to the next clip


def test_the_owner_cannot_pick_himself_a_stranger_a_partner_who_cannot_post_or_change_a_posted_clip():
    store = roster(postiz=("franz", "reginald"))
    clip = made(store, "franz", TUE)
    for handle in ("franz.unimpressed", "someone.else", "lennygold.agent"):
        with pytest.raises(ValueError, match="not the Instagram account"):
            set_collab(store, clip.id, handle)
    assert store.get_clip(clip.id).features["collab"] == ["reginald.thebutler"]  # nothing written
    store.update_clip(clip.id, state=ClipState.posted)
    with pytest.raises(ValueError, match="already posted"):
        set_collab(store, clip.id, None)
    with pytest.raises(KeyError):
        set_collab(store, "no-such-clip", None)


def test_clip_set_collab_and_no_collab(monkeypatch):
    store = roster()
    clip = made(store, "franz", TUE)
    monkeypatch.setattr("studio.clips.open_store", lambda: store)
    run = CliRunner().invoke
    out = run(app, ["clip", "set", clip.id, "--collab", "lennygold.agent"])
    assert out.exit_code == 0, out.output
    assert json.loads(out.output)["features"]["collab"] == ["lennygold.agent"]
    out = run(app, ["clip", "set", clip.id, "--no-collab"])
    assert out.exit_code == 0 and json.loads(out.output)["features"]["collab"] == []
    both = run(app, ["clip", "set", clip.id, "--collab", "lennygold.agent", "--no-collab"])
    assert both.exit_code == 2 and "pass one of them" in both.output
    bad = run(app, ["clip", "set", clip.id, "--collab", "someone.else"])
    assert bad.exit_code == 2 and "not the Instagram account" in bad.output

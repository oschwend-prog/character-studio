"""``studio drop auto-make``: the studio asks for the clip of every coming slot by itself (owner decision 2026-10-14: "the studio
makes them"). Pure store work with fakes: no ffmpeg, no request leaves the machine. What matters:

- a live character whose next slot is inside the horizon and that has nothing in the pipeline gets ONE of his ready drops
  requested (``make_requested.by`` ``studio``): the best score, ties oldest first, no score last; one in every 4 clips from below
  his median (test A's Explore pick);
- every reason to leave a character alone is its own case: a make already asked for, a clip already on its way (and where its post
  falls), no ready drop, no connected account, no slot, the slot too far off, a studio make that just failed;
- the money gates (kill switch, monthly cap, Higgsfield's balance) ask for nothing and say why, quietly: exit 0;
- a dry run writes nothing; a second run asks for nothing more; the make path accepts the studio's request (tests/test_drop.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from studio import budget, drop
from studio.cli import app
from studio.config import LONDON
from studio.drop import DropError
from studio.higgsfield_api import HiggsfieldError, UnexpectedResponse
from studio.models import Account, Body, Character, Clip, ClipState, Favorite, LedgerEntry, Mode, Post, PostStatus, Settings
from studio.store import MemoryStore

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=LONDON)  # Wednesday morning: Franz 19:00, Reginald 19:30 today; Lenny 12:30 tomorrow
WEEK = ["mon", "tue", "wed", "thu", "fri"]
CADENCE = {
    "franz": {"days": WEEK, "slot": "19:00"},
    "reginald": {"days": WEEK, "slot": "19:30"},
    "lenny": {"days": WEEK, "slot": "12:30"},
}
PRICE = 91  # 8 s: ceil(8 x 11) + 3


class FakeHF:
    """The one thing auto-make asks Higgsfield: ``balance()``."""

    def __init__(self, credits: int | Exception = 5000):
        self.credits, self.reads = credits, 0

    def balance(self) -> int:
        self.reads += 1
        if isinstance(self.credits, Exception):
            raise self.credits
        return self.credits

    def close(self) -> None:
        pass


def world(*slugs: str, cadence=CADENCE, connected: bool = True, **settings) -> MemoryStore:
    store = MemoryStore(settings=Settings(cadence=dict(cadence), **settings))
    for slug in slugs or ("franz", "reginald", "lenny"):
        store.add_character(Character(slug=slug, name=slug.title(), status="live", bodies=[Body.biped]))
        if connected:
            store.add_account(Account(character_slug=slug, platform="instagram", handle=f"@{slug}", postiz_integration_id=f"pz-{slug}"))
    return store


def ready(store, slug: str, score: int | None = None, *, age_h: float = 24, credits: int = PRICE, **drop_over) -> str:
    """A checked, priced drop of ``slug`` (state ready) filed ``age_h`` hours before ``NOW``."""
    d = {
        "state": "ready", "kind": "file", "at": (NOW - timedelta(hours=age_h)).isoformat(), "reason": None, "own_footage": False,
        "character_by": "owner", "source_id": "src-1", "window": {"start_s": 0.0, "length_s": 8.0},
        "star": {"kind": "person", "body": "biped", "description": "the man in the suit"}, "credits": credits, "seconds": 8.0,
        **drop_over,
    }
    if score is not None:
        d["score"] = {"total": score, "potential": 5, "swap": 5, "reason": "a test score"}
    pick = store.add_favorite(Favorite(
        url=f"owner-drop:{slug}-{len(store.list_favorites())}", platform="drop", origin="owner", character_slug=slug, status="approved",
        created_at=NOW - timedelta(hours=age_h), proposal={"decision": {"decision": "approve", "by": "owner"}, "drop": d},
    ))
    return pick.id


def ask(store, pick_id: str, by: str = "owner", *, state: str = "making", **drop_over) -> None:
    """What request_job('make') writes (and ``studio drop auto-make`` for the studio): the record and the state."""
    f = store.get_favorite(pick_id)
    store.update_favorite(pick_id, proposal={
        **f.proposal, "drop": {**f.proposal["drop"], "state": state, **drop_over}, "make_requested": {"at": NOW.isoformat(), "by": by},
    })


def run(store, *, hf=None, now=NOW, **kw) -> dict:
    return drop.auto_make(store, now, hf=hf if hf is not None else FakeHF(), scan=kw.pop("scan", {}), **kw)


def requested(out: dict) -> dict[str, str]:
    """character -> pick id of what was asked for."""
    return {r["character"]: r["pick_id"] for r in out["requested"]}


def skipped(out: dict) -> dict[str, str]:
    return {s["character"]: s["reason"] for s in out["skipped"]}


def clip(store, slug: str, state: ClipState, *, age_h: float = 5, explore: bool | None = None, **features) -> Clip:
    if explore is not None:
        features["explore_pick"] = explore
    return store.add_clip(Clip(character_slug=slug, mode=Mode.dropin, state=state, created_at=NOW - timedelta(hours=age_h), features=features))


def post(store, c: Clip, when: datetime, status: PostStatus = PostStatus.scheduled) -> Post:
    account = store.accounts(c.character_slug)[0]
    return store.add_post(Post(clip_id=c.id, account_id=account.id, scheduled_for=when, status=status))


# ---- who is asked for, and with what ----------------------------------------------------------------------------------------------


def test_a_live_character_with_a_slot_in_reach_and_nothing_on_its_way_gets_his_best_drop_requested_as_the_studios():
    store = world("franz")
    low, best = ready(store, "franz", 60), ready(store, "franz", 80)
    out = run(store)
    assert requested(out) == {"franz": best} and out["waiting"] is None and skipped(out) == {}
    (row,) = out["requested"]
    assert row["credits"] == PRICE and row["explore"] is False
    assert datetime.fromisoformat(row["slot"]) == datetime(2026, 10, 14, 19, 0, tzinfo=LONDON)
    pick = store.get_favorite(best)
    d = pick.proposal["drop"]
    # exactly what the terminal's Make it writes (request_job), with the studio's name on it and no Adjust
    assert d["state"] == "making" and d["reason"] is None and "adjust" not in d and d["requested"]["make"] == NOW.isoformat()
    assert d["at"] == NOW.isoformat()
    rec = pick.proposal["make_requested"]
    assert rec["by"] == "studio" and rec["at"] == NOW.isoformat() and rec["explore"] is False
    assert datetime.fromisoformat(rec["slot"]) == datetime(2026, 10, 14, 19, 0, tzinfo=LONDON)
    assert drop.make_requested(pick) and drop.make_requested_by(pick) == "studio" and pick.status == "approved"
    assert store.get_favorite(low).proposal["drop"]["state"] == "ready" and "make_requested" not in store.get_favorite(low).proposal


def test_the_ranking_is_the_highest_score_ties_oldest_first_and_a_drop_without_a_score_last():
    store = world("franz", "reginald", "lenny")
    ready(store, "franz", 70, age_h=2)
    tie_old, tie_new = ready(store, "franz", 90, age_h=48), ready(store, "franz", 90, age_h=5)
    ready(store, "franz", None, age_h=200)
    only_unscored_old = ready(store, "reginald", None, age_h=30)
    ready(store, "reginald", None, age_h=3)
    out = run(store)
    assert requested(out)["franz"] == tie_old and tie_new != tie_old  # 90 twice: the one filed first
    assert requested(out)["reginald"] == only_unscored_old  # no score at all: the oldest
    assert "no ready drop" in skipped(out)["lenny"]
    store2 = world("franz")
    ready(store2, "franz", None, age_h=500)
    scored = ready(store2, "franz", 12)
    assert requested(run(store2)) == {"franz": scored}  # even a poor score beats none, however old the other is


def test_an_unchecked_unpriced_skipped_leased_or_taken_drop_is_not_a_choice():
    store = world("franz")
    for state in ("checking", "blocked", "failed", "making", "made", "waiting"):
        ready(store, "franz", 99, state=state)
    for gap in ("source_id", "credits", "window", "star"):
        ready(store, "franz", 99, **{gap: None})
    store.update_favorite(ready(store, "franz", 99), status="skipped")
    ready(store, "franz", 99, job={"id": "gh-1-1", "kind": "check", "at": (NOW - timedelta(minutes=5)).isoformat()})  # a run holds it
    out = run(store)
    assert out["requested"] == [] and "no ready drop" in skipped(out)["franz"]
    stale = ready(store, "franz", 10, job={"id": "gh-0-1", "kind": "check", "at": (NOW - timedelta(hours=3)).isoformat()})  # an old lease
    assert requested(run(store)) == {"franz": stale}


def test_only_his_own_drops_are_his_choice():
    store = world("franz", "reginald")
    mine, theirs = ready(store, "franz", 50), ready(store, "reginald", 99)
    assert requested(run(store)) == {"franz": mine, "reginald": theirs}


def test_a_drop_whose_character_the_studio_chose_is_made_too_the_check_already_ruled_on_like_for_like():
    store = world("franz")
    pid = ready(store, "franz", 70, character_by="studio")
    assert requested(run(store)) == {"franz": pid}


def test_request_make_refuses_a_drop_that_is_not_ready_or_already_asked_for():
    store = world("franz")
    pid = ready(store, "franz", 70)
    slot = datetime(2026, 10, 14, 19, 0, tzinfo=LONDON)
    drop.request_make(store, pid, NOW, slot=slot, explore=False)
    with pytest.raises(DropError, match="making"):
        drop.request_make(store, pid, NOW, slot=slot, explore=False)  # a second request is refused, never doubled
    other = ready(store, "franz", 70)
    ask(store, other, "owner", state="ready")
    with pytest.raises(DropError, match="make is already requested"):
        drop.request_make(store, other, NOW, slot=slot, explore=False)
    with pytest.raises(KeyError):
        drop.request_make(store, "no-such-pick", NOW, slot=slot, explore=False)


# ---- the slot and the horizon -----------------------------------------------------------------------------------------------------


def test_the_next_slot_must_start_within_the_horizon_which_the_config_sets():
    store = world("franz", "reginald", "lenny")
    for slug in ("franz", "reginald", "lenny"):
        ready(store, slug, 70)
    # Wednesday 09:00: Lenny 12:30 is 3.5 h away, Franz 19:00 exactly 10 h (inside), Reginald 19:30 is 10.5 h
    out = run(store, dry_run=True, scan={"auto_make": {"horizon_hours": 10}})
    assert set(requested(out)) == {"franz", "lenny"} and "more than 10 h away" in skipped(out)["reginald"]
    assert "Wed 14 Oct 19:30" in skipped(out)["reginald"]
    # Wednesday 13:00: Lenny's slot has passed, so his next is Thursday 12:30 (23.5 h)
    after_lenny = datetime(2026, 10, 14, 13, 0, tzinfo=LONDON)
    out = run(store, now=after_lenny, dry_run=True, scan={"auto_make": {"horizon_hours": 10}})
    assert set(requested(out)) == {"franz", "reginald"}
    assert "more than 10 h away" in skipped(out)["lenny"] and "Thu 15 Oct 12:30" in skipped(out)["lenny"]
    out = run(store, now=after_lenny, dry_run=True)  # the default 30 h reaches all three
    assert set(requested(out)) == {"franz", "reginald", "lenny"}


def test_the_slot_passed_today_means_the_next_cadence_day_and_a_weekend_is_out_of_reach():
    store = world("franz")
    ready(store, "franz", 70)
    friday_evening = datetime(2026, 10, 16, 20, 0, tzinfo=LONDON)  # Franz's slot has passed: the next is Monday 19:00
    out = run(store, now=friday_evening, dry_run=True)
    assert out["requested"] == [] and "more than 30 h away" in skipped(out)["franz"] and "Mon 19 Oct 19:00" in skipped(out)["franz"]
    thursday_evening = datetime(2026, 10, 15, 20, 0, tzinfo=LONDON)  # tomorrow's 19:00 is 23 h off
    assert set(requested(run(store, now=thursday_evening, dry_run=True))) == {"franz"}


def test_the_slot_is_read_in_london_time_across_the_clock_change():
    store = world("franz")
    ready(store, "franz", 70)
    # BST ends on Sunday 25 Oct: Monday 26 Oct 19:00 is GMT. 00:30 that morning is 18.5 h before it, whatever the offset
    out = run(store, now=datetime(2026, 10, 26, 0, 30, tzinfo=LONDON), dry_run=True)
    assert datetime.fromisoformat(out["requested"][0]["slot"]) == datetime(2026, 10, 26, 19, 0, tzinfo=LONDON)
    friday_evening = datetime(2026, 10, 23, 20, 0, tzinfo=LONDON)  # Monday's 19:00 GMT is 72 h later
    assert run(store, now=friday_evening, dry_run=True)["requested"] == []


def test_a_naive_now_is_refused():
    with pytest.raises(ValueError, match="aware"):
        drop.auto_make(world("franz"), datetime(2026, 10, 14, 9, 0), hf=FakeHF(), scan={})


@pytest.mark.parametrize("status", ["designing", "paused"])
def test_a_character_who_is_not_live_is_not_considered_at_all(status):
    store = world("franz", "reginald")
    ready(store, "franz", 70)
    ready(store, "reginald", 70)
    store.upsert_character(Character(slug="franz", name="Franz", status=status, bodies=[Body.biped]))
    out = run(store)
    assert set(requested(out)) == {"reginald"} and "franz" not in skipped(out)


def test_a_live_character_with_no_connected_account_has_nowhere_to_post():
    store = world("franz", connected=False)
    ready(store, "franz", 70)
    store.add_account(Account(character_slug="franz", platform="tiktok", handle="@franz", postiz_integration_id=None))  # not connected yet
    out = run(store)
    assert out["requested"] == [] and "no connected account" in skipped(out)["franz"]


def test_a_character_without_a_cadence_slot_is_skipped_with_that_reason():
    store = world("franz", cadence={})
    ready(store, "franz", 70)
    out = run(store)
    assert out["requested"] == [] and "no posting slot" in skipped(out)["franz"]


# ---- something already covers the slot --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("by", ["owner", "studio"])
def test_a_pick_with_a_make_requested_covers_the_slot_whoever_asked(by):
    store = world("franz")
    asked, spare = ready(store, "franz", 50), ready(store, "franz", 90)
    ask(store, asked, by)
    out = run(store)
    assert out["requested"] == [] and "make is already requested" in skipped(out)["franz"] and asked in skipped(out)["franz"]
    assert store.get_favorite(spare).proposal["drop"]["state"] == "ready"


def test_a_pick_about_to_be_made_but_still_marked_ready_covers_the_slot_too():
    store = world("franz")
    asked = ready(store, "franz", 50)
    ask(store, asked, "owner", state="ready")
    ready(store, "franz", 90)
    assert "make is already requested" in skipped(run(store))["franz"]


def test_a_failed_make_covers_nothing_so_the_next_drop_is_tried():
    store = world("franz")
    asked, spare = ready(store, "franz", 50), ready(store, "franz", 90)
    ask(store, asked, "owner", state="failed", reason="Higgsfield refused the job")
    assert requested(run(store)) == {"franz": spare}  # a failed owner make is his to retry; it covers nothing


@pytest.mark.parametrize("state", [
    ClipState.generating, ClipState.gen_failed, ClipState.generated, ClipState.qa_failed, ClipState.qa_passed, ClipState.mastered,
    ClipState.awaiting_approval, ClipState.approved,
])
def test_a_clip_on_its_way_with_no_post_yet_covers_the_slot(state):
    store = world("franz")
    ready(store, "franz", 70)
    clip(store, "franz", state)
    out = run(store)
    assert out["requested"] == [] and "already on its way" in skipped(out)["franz"] and state.value in skipped(out)["franz"]


@pytest.mark.parametrize("state", [ClipState.planned, ClipState.dropped, ClipState.rejected, ClipState.posted])
def test_a_clip_that_is_dead_not_started_or_already_posted_covers_nothing(state):
    store = world("franz")
    pid = ready(store, "franz", 70)
    c = clip(store, "franz", state)
    if state is ClipState.posted:
        post(store, c, NOW - timedelta(days=1), PostStatus.posted)  # yesterday's post
    assert requested(run(store)) == {"franz": pid}


def test_a_scheduled_clip_covers_the_slot_only_when_its_post_is_on_the_slots_london_day():
    store = world("franz")
    pid = ready(store, "franz", 70)
    c = clip(store, "franz", ClipState.scheduled)
    p = post(store, c, datetime(2026, 10, 15, 19, 0, tzinfo=LONDON))  # tomorrow's slot: today's (19:00 Wed) is still empty
    assert requested(run(store, dry_run=True)) == {"franz": pid}
    store.update_post(p.id, scheduled_for=datetime(2026, 10, 14, 19, 0, tzinfo=LONDON))  # today's slot
    out = run(store)
    assert out["requested"] == [] and "already on its way" in skipped(out)["franz"]


def test_the_day_of_a_post_is_the_london_day_not_the_utc_day():
    store = world("franz")
    ready(store, "franz", 70)
    c = clip(store, "franz", ClipState.scheduled)
    post(store, c, datetime(2026, 10, 13, 23, 30, tzinfo=timezone.utc))  # 00:30 on 14 Oct in London (BST): the slot's day
    out = run(store)
    assert out["requested"] == [] and "already on its way" in skipped(out)["franz"]


def test_a_clip_whose_posts_all_failed_still_counts_as_not_posted_yet():
    store = world("franz")
    ready(store, "franz", 70)
    c = clip(store, "franz", ClipState.scheduled)
    post(store, c, datetime(2026, 10, 15, 19, 0, tzinfo=LONDON), PostStatus.failed)  # a failed post never held a day
    assert "already on its way" in skipped(run(store))["franz"]  # no post that holds a day: like a clip with no post yet


def test_another_characters_clip_covers_nothing_of_his():
    store = world("franz", "reginald")
    ready(store, "franz", 70)
    clip(store, "reginald", ClipState.awaiting_approval)
    assert set(requested(run(store))) == {"franz"}


def test_a_studio_make_that_failed_in_the_last_day_holds_the_character_until_the_owner_looks():
    store = world("franz")
    failed, spare = ready(store, "franz", 99), ready(store, "franz", 50)
    ask(store, failed, "studio", state="failed", reason="Higgsfield refused the job: no credits", at=(NOW - timedelta(hours=3)).isoformat())
    out = run(store)
    assert out["requested"] == [] and "failed" in skipped(out)["franz"] and "the owner" in skipped(out)["franz"]
    ask(store, failed, "studio", state="failed", at=(NOW - timedelta(hours=30)).isoformat())
    assert requested(run(store)) == {"franz": spare}  # a day later it tries the next drop
    store2 = world("franz")  # an owner's failed make never holds him
    pid, other = ready(store2, "franz", 40), ready(store2, "franz", 99)
    ask(store2, other, "owner", state="failed", at=NOW.isoformat())
    assert requested(run(store2)) == {"franz": pid}


# ---- test A: one clip in every 4 from below his median ----------------------------------------------------------------------------


def made(store, slug: str, *flags: bool, first_age_h: float = 40) -> None:
    """His clips made since test A started (12 Oct), oldest first, each tagged ``explore_pick`` as given, all posted yesterday."""
    for i, flag in enumerate(flags):
        c = clip(store, slug, ClipState.posted, age_h=first_age_h - i, explore=flag)
        post(store, c, NOW - timedelta(days=1), PostStatus.posted)


def scored_franz(store) -> dict[int, str]:
    return {s: ready(store, "franz", s, age_h=100 - s) for s in (95, 85, 75, 40, 30)}  # median 75: below it are 40 and 30


def test_every_fourth_clip_is_an_explore_pick_the_best_drop_below_his_median(experiments_on):
    store = world("franz")
    by = scored_franz(store)
    made(store, "franz", False, False, False)  # three normal clips since the test began: this one is the explore turn
    out = run(store)
    assert requested(out) == {"franz": by[40]} and out["requested"][0]["explore"] is True


def test_before_the_explore_turn_it_is_the_top_score(experiments_on):
    store = world("franz")
    by = scored_franz(store)
    made(store, "franz", False, False)  # only two since the test began (or since his last explore clip)
    out = run(store)
    assert requested(out) == {"franz": by[95]} and out["requested"][0]["explore"] is False


def test_an_explore_clip_in_his_last_three_restarts_the_count(experiments_on):
    store = world("franz")
    by = scored_franz(store)
    made(store, "franz", False, False, False, True, False, False)  # the explore one is third from last: two normal since
    assert requested(run(store, dry_run=True)) == {"franz": by[95]}
    store2 = world("franz")
    by2 = scored_franz(store2)
    made(store2, "franz", True, False, False, False)  # three normal since the explore one: the turn again
    assert requested(run(store2)) == {"franz": by2[40]}


def test_the_explore_turn_waits_when_nothing_is_below_the_median_and_comes_again(experiments_on):
    store = world("franz")
    only = ready(store, "franz", 70)  # one scored drop: no median, nothing below it
    made(store, "franz", False, False, False)
    out = run(store)
    assert requested(out) == {"franz": only} and out["requested"][0]["explore"] is False
    assert drop.explore_turn(store, "franz", NOW) is True  # still his explore turn: the next clip with a drop below the median takes it


def test_an_unscored_drop_is_never_an_explore_pick(experiments_on):
    store = world("franz")
    ready(store, "franz", 80)
    mid = ready(store, "franz", 60)
    ready(store, "franz", None, age_h=300)  # the oldest of all, but it has no score
    made(store, "franz", False, False, False)
    out = run(store)  # the median of the two scores is 70: the 60 is below it
    assert requested(out) == {"franz": mid} and out["requested"][0]["explore"] is True


def test_the_pick_is_judged_against_the_same_pool_the_clips_explore_tag_will_use(experiments_on):
    """``learn_tags``' ``explore_pick`` is ``experiments.is_explore(score, checked_scores(...))`` at Make it: the pick says the same."""
    from studio import experiments

    store = world("franz")
    by = scored_franz(store)
    made(store, "franz", False, False, False)
    assert experiments.is_explore(40, drop.checked_scores(store, store.get_favorite(by[40]))) is True
    assert requested(run(store)) == {"franz": by[40]}


def test_clips_before_the_test_started_or_given_up_or_without_the_tag_do_not_count_toward_the_turn(experiments_on):
    store = world("franz")
    by = scored_franz(store)
    made(store, "franz", False, False, first_age_h=40)
    old = clip(store, "franz", ClipState.posted, age_h=24 * 20, explore=False)  # 20 days ago: before 12 Oct
    post(store, old, NOW - timedelta(days=19), PostStatus.posted)
    clip(store, "franz", ClipState.dropped, age_h=1, explore=False)  # given up: never made
    recreate = clip(store, "franz", ClipState.posted, age_h=30)  # a Recreate carries no explore tag at all
    post(store, recreate, NOW - timedelta(days=1), PostStatus.posted)
    assert requested(run(store)) == {"franz": by[95]}  # two counted clips, not three


def test_with_test_a_off_the_top_score_is_always_the_choice():
    store = world("franz")
    by = scored_franz(store)  # the suite's default registry has every test off
    made(store, "franz", False, False, False, False, False)
    assert requested(run(store)) == {"franz": by[95]}


# ---- the money: kill switch, cap, Higgsfield's balance ---------------------------------------------------------------------------


def test_the_kill_switch_asks_for_nothing_and_says_so():
    store = world("franz", "reginald", kill_switch=True)
    ready(store, "franz", 70)
    ready(store, "reginald", 70)
    hf = FakeHF()
    out = run(store, hf=hf)
    assert out["requested"] == [] and "kill switch" in out["waiting"] and hf.reads == 0
    assert all(f.proposal["drop"]["state"] == "ready" for f in store.list_favorites())


def test_a_clip_that_would_pass_the_monthly_cap_is_not_asked_for():
    store = world("franz", monthly_cap_credits=6000)
    pid = ready(store, "franz", 70)
    spent = clip(store, "franz", ClipState.posted, age_h=100)
    month = budget.month_key(NOW)
    store.ledger_add(LedgerEntry(clip_id=spent.id, month=month, kind="reserve", credits=5950, created_at=NOW - timedelta(days=1)))
    out = run(store)
    assert out["requested"] == [] and "monthly cap" in out["waiting"] and "5950" in out["waiting"] and "monthly cap" in skipped(out)["franz"]
    store.ledger_add(LedgerEntry(clip_id=spent.id, month=month, kind="settle", credits=5000, created_at=NOW - timedelta(hours=1)))
    assert requested(run(store)) == {"franz": pid}  # 5000 + 91 is inside the cap


def test_the_balance_must_cover_the_price():
    store = world("franz")
    pid = ready(store, "franz", 70)
    out = run(store, hf=FakeHF(42))  # today: 42 credits, a clip is 91
    assert out["requested"] == [] and "waiting for credits" in out["waiting"] and "42" in out["waiting"] and "91" in out["waiting"]
    assert store.get_favorite(pid).proposal["drop"]["state"] == "ready"
    assert requested(run(store, hf=FakeHF(91))) == {"franz": pid}  # exactly enough


def test_the_credits_are_shared_by_the_characters_in_the_order_of_their_slots():
    store = world("franz", "reginald", "lenny")
    for slug in ("franz", "reginald", "lenny"):
        ready(store, slug, 70)
    out = run(store, hf=FakeHF(200))  # 91 + 91 fit, a third does not; the slots run Lenny 12:30, Franz 19:00, Reginald 19:30
    assert set(requested(out)) == {"lenny", "franz"}
    assert "Higgsfield has 200" in skipped(out)["reginald"] and "waiting for credits" in out["waiting"]


def test_makes_asked_for_but_not_yet_reserved_count_against_the_cap_and_the_balance_until_they_reserve():
    store = world("franz", "reginald")
    sent = ready(store, "reginald", 70)
    ask(store, sent, "owner")
    ready(store, "franz", 70)
    out = run(store, hf=FakeHF(150), dry_run=True)  # 150 - 91 promised to the owner's make = 59 left: not enough
    assert out["requested"] == [] and "waiting for credits" in out["waiting"]
    assert set(requested(run(store, hf=FakeHF(182), dry_run=True))) == {"franz"}
    ask(store, sent, "owner", make={"reserved": PRICE})  # its credits are in the ledger now: not promised twice
    assert set(requested(run(store, hf=FakeHF(100), dry_run=True))) == {"franz"}
    # ... and the cap counts the promise too
    store.set_settings(monthly_cap_credits=PRICE + PRICE - 1)
    ask(store, sent, "owner", make=None)
    assert "monthly cap" in run(store, dry_run=True)["waiting"]


@pytest.mark.parametrize("hf, why", [
    (None, "no Higgsfield key"),  # nothing could be submitted without the key: a make would only wait for it
    (FakeHF(RuntimeError("boom")), "balance could not be read"),  # a bug in the read is not Higgsfield's answer: fail closed
])
def test_no_key_or_a_bug_in_the_balance_read_waits(hf, why):
    store = world("franz")
    pid = ready(store, "franz", 70)
    out = drop.auto_make(store, NOW, hf=hf, scan={})
    assert out["requested"] == [] and why in out["waiting"] and "waiting for credits" in out["waiting"]
    assert store.get_favorite(pid).proposal["drop"]["state"] == "ready"


@pytest.mark.parametrize("error", [
    HiggsfieldError("the balance call answered HTTP 404", 404),  # Higgsfield documents no balance route
    UnexpectedResponse("balance: no credits in the answer: {}", 200),
    HiggsfieldError("the balance call failed (ConnectError)"),
])
def test_a_balance_that_cannot_be_read_is_unknown_not_short_so_one_make_is_tried_as_a_probe(error):
    """Higgsfield's docs describe no balance route: an unreadable balance must not stop the studio for ever. It asks for ONE make per
    run (the earliest slot's); a refusal for credits at submit (HTTP 403) is what then holds it (tests/test_drop.py)."""
    store = world("franz", "reginald", "lenny")
    for slug in ("franz", "reginald", "lenny"):
        ready(store, slug, 70)
    out = run(store, hf=FakeHF(error))
    assert requested(out) == {"lenny": store.list_favorites(character_slug="lenny")[0].id}  # Lenny 12:30 is the first slot
    assert out["requested"][0]["probe"] is True and out["waiting"] is None
    assert set(skipped(out)) == {"franz", "reginald"} and all("one make at a time" in why for why in skipped(out).values())


def test_the_probe_of_each_run_is_the_next_character_and_a_known_balance_is_no_probe():
    store = world("franz", "reginald", "lenny")
    for slug in ("franz", "reginald", "lenny"):
        ready(store, slug, 70)
    unknown = FakeHF(HiggsfieldError("HTTP 404", 404))
    first = run(store, hf=unknown)
    second = run(store, hf=unknown, now=NOW + timedelta(hours=2))
    third = run(store, hf=unknown, now=NOW + timedelta(hours=4))
    assert [list(requested(o)) for o in (first, second, third)] == [["lenny"], ["franz"], ["reginald"]]
    known = world("franz", "reginald", "lenny")
    for slug in ("franz", "reginald", "lenny"):
        ready(known, slug, 70)
    out = run(known, hf=FakeHF(5000))  # a readable balance that covers them: all three, no probe
    assert set(requested(out)) == {"franz", "reginald", "lenny"} and all("probe" not in r for r in out["requested"])


def test_a_readable_balance_that_is_short_still_waits_and_asks_for_no_probe():
    store = world("franz", "reginald")
    ready(store, "franz", 70), ready(store, "reginald", 70)
    out = run(store, hf=FakeHF(10))
    assert out["requested"] == [] and "Higgsfield has 10" in out["waiting"]


def test_an_unknown_balance_still_meets_the_cap_and_the_kill_switch_first():
    store = world("franz", monthly_cap_credits=50)  # a clip costs 91
    ready(store, "franz", 70)
    out = run(store, hf=FakeHF(HiggsfieldError("HTTP 404", 404)))
    assert out["requested"] == [] and "monthly cap" in out["waiting"]
    store2 = world("franz", kill_switch=True)
    ready(store2, "franz", 70)
    out = run(store2, hf=FakeHF(HiggsfieldError("HTTP 404", 404)))
    assert out["requested"] == [] and "kill switch" in out["waiting"]


def test_an_unreadable_balance_is_not_mentioned_when_nobody_needs_a_clip():
    store = world("franz")  # no drop at all
    out = run(store, hf=FakeHF(HiggsfieldError("HTTP 404", 404)))
    assert out["waiting"] is None and "no ready drop" in skipped(out)["franz"]


# ---- Higgsfield said not enough credits (HTTP 403 at submit): wait 12 hours, then probe again -------------------------------------------


def stamp(store, pick_id: str, hours_ago: float, **over) -> None:
    """What a studio make that Higgsfield refused for credits leaves on its drop (``drop._refused_for_credits``)."""
    f = store.get_favorite(pick_id)
    at = (NOW - timedelta(hours=hours_ago)).isoformat()
    store.update_favorite(pick_id, proposal={**f.proposal, "drop": {**f.proposal["drop"], "credits_refused_at": at, **over}})


def test_a_refusal_for_credits_in_the_last_12_hours_holds_every_character_and_names_it():
    store = world("franz", "reginald")
    refused, other = ready(store, "franz", 70), ready(store, "reginald", 70)
    stamp(store, refused, 3)  # 06:00 today
    out = run(store, hf=FakeHF(HiggsfieldError("HTTP 404", 404)))
    assert out["requested"] == [] and out["waiting"] == (
        "waiting for credits: Higgsfield said not enough credits at Wed 14 Oct 06:00; next try after Wed 14 Oct 18:00"
    )
    assert set(skipped(out)) == {"franz", "reginald"} and store.get_favorite(other).proposal["drop"]["state"] == "ready"
    rich = run(store, hf=FakeHF(5000))  # a readable balance does not lift it: the account just said no
    assert rich["requested"] == [] and "Higgsfield said not enough credits" in rich["waiting"]


def test_after_12_hours_it_probes_again_one_make_at_a_time():
    store = world("franz", "reginald")
    refused, other = ready(store, "franz", 70), ready(store, "reginald", 70)
    stamp(store, refused, drop.CREDITS_REFUSED_HOLD_H + 0.1)
    out = run(store, hf=FakeHF(HiggsfieldError("HTTP 404", 404)))
    assert len(out["requested"]) == 1 and out["requested"][0]["probe"] is True and out["waiting"] is None
    assert drop.CREDITS_REFUSED_HOLD_H == 12 and other
    store2 = world("franz")  # just inside the 12 hours: still held
    only = ready(store2, "franz", 70)
    stamp(store2, only, 11.9)
    assert run(store2, hf=FakeHF(HiggsfieldError("HTTP 404", 404)))["waiting"].startswith("waiting for credits: Higgsfield said not enough")


def test_the_newest_refusal_counts_a_skipped_drops_counts_and_a_stamp_after_now_does_not_free_anyone():
    store = world("franz")
    old, newer, hidden = ready(store, "franz", 70), ready(store, "franz", 60), ready(store, "franz", 50)
    stamp(store, old, 30)
    stamp(store, newer, 5)  # 04:00
    stamp(store, hidden, 20)
    store.update_favorite(hidden, status="skipped")
    out = run(store, hf=FakeHF(5000))
    assert "at Wed 14 Oct 04:00; next try after Wed 14 Oct 16:00" in out["waiting"]
    skewed = world("franz")
    pid = ready(skewed, "franz", 70)
    stamp(skewed, pid, -1)  # a clock a little ahead of ours: still a fresh refusal
    assert "Higgsfield said not enough credits" in run(skewed, hf=FakeHF(5000))["waiting"]


def test_a_garbled_refusal_stamp_is_ignored():
    store = world("franz")
    pid = ready(store, "franz", 70)
    stamp(store, pid, 1, credits_refused_at="yesterday")
    assert requested(run(store, hf=FakeHF(5000))) == {"franz": pid}


def test_the_refusal_hold_is_not_mentioned_when_nobody_needs_a_clip():
    store = world("franz")
    pid = ready(store, "franz", 70)
    stamp(store, pid, 1)
    ask(store, pid, "owner")  # his own make covers the slot: nothing to wait for
    assert run(store, hf=FakeHF(5000))["waiting"] is None


# ---- dry run, idempotence, the switch -----------------------------------------------------------------------------------------------


def snapshot(store) -> str:
    return json.dumps([(f.id, f.status, f.proposal) for f in store.list_favorites()], sort_keys=True, default=str)


def test_a_dry_run_prints_the_plan_and_writes_nothing():
    store = world("franz", "reginald")
    best = ready(store, "franz", 70)
    ready(store, "reginald", 55)
    before = snapshot(store)
    out = run(store, dry_run=True)
    assert out["dry_run"] is True and requested(out)["franz"] == best and set(requested(out)) == {"franz", "reginald"}
    assert snapshot(store) == before and store.ledger_month(budget.month_key(NOW)) == []
    real = run(store)
    assert requested(real) == requested(out) and "dry_run" not in real  # the plan is the real run's plan


def test_a_second_run_asks_for_nothing_more():
    store = world("franz", "reginald", "lenny")
    for slug in ("franz", "reginald", "lenny"):
        ready(store, slug, 70)
        ready(store, slug, 60)
    first = run(store)
    assert set(requested(first)) == {"franz", "reginald", "lenny"}
    again = run(store, now=NOW + timedelta(minutes=5))
    assert again["requested"] == [] and set(skipped(again)) == {"franz", "reginald", "lenny"}
    assert all("make is already requested" in why for why in skipped(again).values())
    assert sum(1 for f in store.list_favorites() if "make_requested" in f.proposal) == 3


def test_it_is_a_no_op_when_the_switch_is_off():
    store = world("franz")
    ready(store, "franz", 70)
    hf = FakeHF()
    out = run(store, hf=hf, scan={"auto_make": {"enabled": False}})
    assert out["requested"] == [] and out["enabled"] is False and hf.reads == 0
    assert store.list_favorites()[0].proposal["drop"]["state"] == "ready"


def test_the_config_has_defaults_and_refuses_nonsense():
    assert drop.auto_make_config({}) == {"enabled": True, "horizon_hours": 30}
    assert drop.auto_make_config({"auto_make": {"enabled": False, "horizon_hours": 12, "_doc": "x"}}) == {"enabled": False, "horizon_hours": 12}
    for bad in ({"enabled": "yes"}, {"horizon_hours": 0}, {"horizon_hours": 2.5}, {"horizon_hours": True}, {"horizon_hours": 400}):
        with pytest.raises(ValueError, match="auto_make"):
            drop.auto_make_config({"auto_make": bad})


def test_the_shipped_scan_json_carries_the_switch_and_the_horizon_next_to_the_hits_block():
    from studio import hits

    scan = hits.load_scan()
    assert list(scan).index("auto_make") == list(scan).index("hits") + 1
    assert drop.auto_make_config(scan) == {"enabled": True, "horizon_hours": 30}
    assert "2026-10-14" in scan["auto_make"]["_doc"]


# ---- the CLI ------------------------------------------------------------------------------------------------------------------------


def invoke(monkeypatch, store, hf, *args):
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "now_london", lambda: NOW)
    monkeypatch.setattr(drop.HiggsfieldClient, "from_env", classmethod(lambda cls, *a, **k: hf))
    monkeypatch.setattr(drop, "_scan", lambda: {})
    return CliRunner().invoke(app, ["drop", "auto-make", *args])


def test_the_command_prints_the_one_json_object_and_exits_0_even_while_waiting_for_credits(monkeypatch):
    store = world("franz")
    pid = ready(store, "franz", 70)
    r = invoke(monkeypatch, store, FakeHF(42))
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert set(out) == {"requested", "skipped", "waiting"} and out["requested"] == [] and "waiting for credits" in out["waiting"]
    r = invoke(monkeypatch, store, FakeHF(5000), "--dry-run")
    out = json.loads(r.output)
    assert r.exit_code == 0 and out["dry_run"] is True and requested(out) == {"franz": pid}
    assert store.get_favorite(pid).proposal["drop"]["state"] == "ready"
    r = invoke(monkeypatch, store, FakeHF(5000))
    assert r.exit_code == 0 and requested(json.loads(r.output)) == {"franz": pid}
    assert store.get_favorite(pid).proposal["make_requested"]["by"] == "studio"


def test_a_missing_higgsfield_key_is_quiet_too(monkeypatch):
    store = world("franz")
    ready(store, "franz", 70)
    r = invoke(monkeypatch, store, None)
    assert r.exit_code == 0 and "no Higgsfield key" in json.loads(r.output)["waiting"]


def test_a_broken_test_registry_is_the_callers_to_fix(monkeypatch, tmp_path):
    from studio import experiments

    bad = tmp_path / "experiments.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(experiments, "EXPERIMENTS_PATH", bad)
    store = world("franz")
    ready(store, "franz", 70)
    r = invoke(monkeypatch, store, FakeHF())
    assert r.exit_code == 2 and "registry" in r.output.lower()
    assert store.list_favorites()[0].proposal["drop"]["state"] == "ready"

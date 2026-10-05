"""``studio clip schedule``: the autopilot path from ``mastered`` / ``approved`` to ``scheduled`` posts.

It is the rule the terminal's approve RPC mirrors: one post per account ``accounts_for_clip`` picks,
at ``--at`` or the character's next cadence slot, and the clip moves to ``scheduled`` through the
state machine. Everything runs on ``MemoryStore`` (no foreign keys: seed what Postgres would need).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from studio import clips
from studio.clips import schedule_clip
from studio.cli import app
from studio.config import LONDON
from studio.models import (
    Account,
    Character,
    Clip,
    ClipState,
    Mode,
    Platform,
    Post,
    PostStatus,
    Settings,
)
from studio.planning import upcoming_slot
from studio.store import MemoryStore

S = ClipState
CADENCE = {
    "biscuit": {"days": ["tue", "wed", "thu"], "slot": "19:00"},
    "reginald": {"days": ["tue", "wed", "thu"], "slot": "19:30"},
}
# Tue 6 Oct 2026 08:00 BST (the default cadence has Tue/Wed/Thu at 19:00).
TUE = datetime(2026, 10, 6, 8, 0, tzinfo=LONDON)


def slot(day: int, hour: int = 19, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=LONDON)


def make_store(*, tiktok: bool = True, instagram: bool = True, cadence=None) -> MemoryStore:
    store = MemoryStore(
        settings=Settings(cadence=cadence if cadence is not None else CADENCE),
        characters=[Character(slug="biscuit", name="Biscuit"), Character(slug="reginald", name="Reginald")],
    )
    for platform, connected in ((Platform.tiktok, tiktok), (Platform.instagram, instagram)):
        store.add_account(
            Account(
                character_slug="biscuit",
                platform=platform,
                handle=f"@biscuit.{platform.value}",
                postiz_integration_id=f"pz-{platform.value}" if connected else None,
            )
        )
    return store


def add_clip(store: MemoryStore, state: ClipState = S.mastered, mode: Mode = Mode.recreate, **over) -> Clip:
    return store.add_clip(
        Clip(character_slug="biscuit", mode=mode, state=state, master_path="clips/m.mp4", **over)
    )


# ---- upcoming_slot ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (TUE, slot(6)),  # a cadence day with the slot still ahead: today
        (slot(6, 18, 59), slot(6)),
        (slot(6, 19, 0), slot(7)),  # the slot is this very minute: not ahead, take the next cadence day
        (slot(6, 20), slot(7)),
        (slot(8, 20), slot(13)),  # Thu evening: Fri..Mon are not cadence days, next is Tue 13th
        (datetime(2026, 10, 5, 8, 0, tzinfo=LONDON), slot(6)),  # Monday is not a cadence day
        (datetime(2026, 10, 24, 12, 0, tzinfo=LONDON), datetime(2026, 10, 27, 19, 0, tzinfo=LONDON)),
    ],
)
def test_upcoming_slot_is_today_if_ahead_else_the_next_cadence_day(now, expected):
    got = upcoming_slot("biscuit", now, CADENCE)
    assert got == expected and got.tzinfo is not None


def test_upcoming_slot_keeps_london_wall_time_across_the_clock_change():
    got = upcoming_slot("biscuit", datetime(2026, 10, 24, 12, 0, tzinfo=LONDON), CADENCE)  # BST ends Sun 25 Oct
    assert got.utcoffset() == timedelta(0) and got.hour == 19  # 19:00 GMT on Tue 27 Oct


def test_upcoming_slot_uses_the_london_day_not_the_utc_day():
    just_after_midnight = datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc)  # Wed 00:30 in London
    assert upcoming_slot("biscuit", just_after_midnight, CADENCE) == slot(7)


def test_upcoming_slot_with_one_cadence_day_and_the_slot_gone_waits_a_week():
    cadence = {"biscuit": {"days": ["tue"], "slot": "19:00"}}
    assert upcoming_slot("biscuit", slot(6, 20), cadence) == slot(13)


def test_upcoming_slot_refuses_a_character_without_slot_or_days():
    with pytest.raises(ValueError, match="slot"):
        upcoming_slot("nobody", TUE, CADENCE)
    with pytest.raises(ValueError, match="days"):
        upcoming_slot("biscuit", TUE, {"biscuit": {"days": [], "slot": "19:00"}})


# ---- schedule_clip ---------------------------------------------------------------------------------


@pytest.mark.parametrize("state", [S.mastered, S.approved])
def test_a_mastered_or_approved_clip_gets_one_post_per_connected_account_and_becomes_scheduled(state):
    store = make_store()
    clip = add_clip(store, state)
    done, posts = schedule_clip(store, clip.id, now=TUE)
    assert done.state is S.scheduled and store.get_clip(clip.id).state is S.scheduled
    assert sorted(p.account_id for p in posts) == sorted(a.id for a in store.accounts("biscuit"))
    assert {p.scheduled_for for p in posts} == {slot(6)}
    assert {p.status for p in posts} == {PostStatus.scheduled} and all(p.id for p in posts)
    assert len(store.list_posts(clip_id=clip.id)) == 2


def test_at_overrides_the_slot_for_every_post():
    store = make_store()
    clip = add_clip(store)
    at = datetime(2026, 10, 9, 7, 45, tzinfo=timezone.utc)
    _, posts = schedule_clip(store, clip.id, at=at, now=TUE)
    assert {p.scheduled_for for p in posts} == {at}


def test_at_must_be_aware():
    store = make_store()
    clip = add_clip(store)
    with pytest.raises(ValueError, match="timezone-aware"):
        schedule_clip(store, clip.id, at=datetime(2026, 10, 9, 19, 0), now=TUE)
    assert store.list_posts() == [] and store.get_clip(clip.id).state is S.mastered


@pytest.mark.parametrize(
    "state",
    [S.planned, S.generating, S.generated, S.qa_passed, S.awaiting_approval, S.rejected,
     S.scheduled, S.posted, S.dropped],
)
def test_only_mastered_or_approved_clips_can_be_scheduled(state):
    store = make_store()
    clip = add_clip(store, state)
    with pytest.raises(ValueError, match=state.value):
        schedule_clip(store, clip.id, now=TUE)
    assert store.list_posts() == [] and store.get_clip(clip.id).state is state


def test_an_unknown_clip_is_a_key_error():
    with pytest.raises(KeyError):
        schedule_clip(make_store(), "nope", now=TUE)


def test_it_refuses_when_no_account_is_connected():
    store = make_store(tiktok=False, instagram=False)
    clip = add_clip(store)
    with pytest.raises(ValueError, match="no connected account"):
        schedule_clip(store, clip.id, now=TUE)
    assert store.list_posts() == [] and store.get_clip(clip.id).state is S.mastered


def test_only_connected_accounts_get_a_post():
    store = make_store(instagram=False)
    clip = add_clip(store)
    _, posts = schedule_clip(store, clip.id, now=TUE)
    (account,) = store.accounts("biscuit")[1:]  # accounts() sorts instagram before tiktok
    assert [p.account_id for p in posts] == [account.id] and account.platform is Platform.tiktok


def _dropin_history(store: MemoryStore, account: Account, n_dropin: int, n_recreate: int = 0) -> None:
    start = datetime(2026, 9, 1, 19, 0, tzinfo=LONDON)
    modes = [Mode.dropin] * n_dropin + [Mode.recreate] * n_recreate
    for i, mode in enumerate(modes):
        past = store.add_clip(Clip(character_slug="biscuit", mode=mode, state=S.posted))
        store.add_post(
            Post(clip_id=past.id, account_id=account.id, scheduled_for=start + timedelta(days=i),
                 status=PostStatus.posted)
        )


def test_a_dropin_clip_skips_an_account_that_is_over_its_share():
    store = make_store()
    instagram = next(a for a in store.accounts("biscuit") if a.platform is Platform.instagram)
    _dropin_history(store, instagram, n_dropin=5, n_recreate=5)  # 0.5 against the Instagram share of 0.40
    clip = add_clip(store, mode=Mode.dropin)
    _, posts = schedule_clip(store, clip.id, now=TUE)
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    assert [p.account_id for p in posts] == [tiktok.id]


def test_a_dropin_clip_that_no_connected_account_may_take_is_refused_with_its_own_message():
    store = make_store()
    for account in store.accounts("biscuit"):
        _dropin_history(store, account, n_dropin=10)  # ratio 1.0: over every share
    clip = add_clip(store, mode=Mode.dropin)
    with pytest.raises(ValueError, match="drop-in share") as e:
        schedule_clip(store, clip.id, now=TUE)
    assert "no connected account" not in str(e.value)
    assert store.get_clip(clip.id).state is S.mastered
    assert [p for p in store.list_posts(clip_id=clip.id)] == []


def test_scheduling_is_idempotent_no_duplicate_posts():
    store = make_store()
    clip = add_clip(store)
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    kept = store.add_post(  # left behind by an earlier, interrupted run
        Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=slot(1, 12), status=PostStatus.scheduled)
    )
    done, posts = schedule_clip(store, clip.id, now=TUE)
    assert done.state is S.scheduled
    assert len(store.list_posts(clip_id=clip.id)) == 2  # TikTok kept, Instagram added
    by_account = {p.account_id: p for p in posts}
    assert by_account[tiktok.id].id == kept.id and by_account[tiktok.id].scheduled_for == slot(1, 12)

    with pytest.raises(ValueError, match="scheduled"):  # asking again is refused by state, writes nothing
        schedule_clip(store, clip.id, now=TUE)
    assert len(store.list_posts(clip_id=clip.id)) == 2


def test_a_post_that_appears_between_the_lookup_and_the_insert_is_reused(monkeypatch):
    store = make_store(instagram=False)
    clip = add_clip(store)
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    real_add = store.add_post

    def racing_add(post):  # another process wins the (clip, account) slot first
        real_add(Post(clip_id=post.clip_id, account_id=post.account_id, scheduled_for=slot(1, 12)))
        return real_add(post)  # -> DuplicatePost

    monkeypatch.setattr(store, "add_post", racing_add)
    done, posts = schedule_clip(store, clip.id, now=TUE)
    assert done.state is S.scheduled
    assert [(p.account_id, p.scheduled_for) for p in posts] == [(tiktok.id, slot(1, 12))]
    assert len(store.list_posts(clip_id=clip.id)) == 1


def test_a_character_without_a_slot_is_refused_before_anything_is_written():
    store = make_store(cadence={})
    clip = add_clip(store)
    with pytest.raises(ValueError, match="slot"):
        schedule_clip(store, clip.id, now=TUE)
    assert store.list_posts() == [] and store.get_clip(clip.id).state is S.mastered


def test_at_makes_a_cadence_free_call_possible():
    store = make_store(cadence={})
    clip = add_clip(store)
    at = slot(9, 12)
    _, posts = schedule_clip(store, clip.id, at=at, now=TUE)
    assert {p.scheduled_for for p in posts} == {at}


# ---- the CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(clips, "open_store", lambda: store)
    monkeypatch.setattr(clips, "now_london", lambda: TUE)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["clip", *args])


def test_clip_help_lists_schedule():
    r = run("--help")
    assert r.exit_code == 0 and "schedule" in r.output


def test_cli_schedule_prints_the_clip_and_its_posts(cli_store):
    clip = add_clip(cli_store)
    r = run("schedule", clip.id)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["clip"]["state"] == "scheduled" and out["clip"]["id"] == clip.id
    assert len(out["posts"]) == 2 and {p["scheduled_for"] for p in out["posts"]} == {slot(6).isoformat()}
    assert {p["status"] for p in out["posts"]} == {"scheduled"}
    assert cli_store.get_clip(clip.id).state is S.scheduled


def test_cli_schedule_at_takes_iso_with_or_without_an_offset(cli_store):
    clip = add_clip(cli_store)
    r = run("schedule", clip.id, "--at", "2026-10-09T18:30:00+01:00")
    assert r.exit_code == 0, r.output
    assert {p["scheduled_for"] for p in json.loads(r.stdout)["posts"]} == {"2026-10-09T18:30:00+01:00"}

    other = add_clip(cli_store)
    r = run("schedule", other.id, "--at", "2026-12-01T19:00")  # naive: London wall clock (GMT in December)
    assert r.exit_code == 0, r.output
    assert {p["scheduled_for"] for p in json.loads(r.stdout)["posts"]} == {"2026-12-01T19:00:00+00:00"}


def test_cli_schedule_refusals_exit_2_and_write_nothing(cli_store):
    assert run("schedule", "nope").exit_code == 2  # unknown clip
    waiting = add_clip(cli_store, S.awaiting_approval)
    r = run("schedule", waiting.id)
    assert r.exit_code == 2 and "awaiting_approval" in r.output
    ok = add_clip(cli_store)
    r = run("schedule", ok.id, "--at", "tomorrow")
    assert r.exit_code == 2 and "--at" in r.output
    assert cli_store.list_posts() == []


def test_cli_schedule_without_a_connected_account_exits_2(monkeypatch):
    store = make_store(tiktok=False, instagram=False)
    monkeypatch.setattr(clips, "open_store", lambda: store)
    clip = add_clip(store)
    r = run("schedule", clip.id)
    assert r.exit_code == 2 and "no connected account" in r.output
    assert store.get_clip(clip.id).state is S.mastered

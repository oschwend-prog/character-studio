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
    Favorite,
    Mode,
    Platform,
    Post,
    PostStatus,
    Settings,
)
from studio.planning import FAMILY_GAP_DAYS, family_days, free_slot, taken_days, upcoming_slot
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


def make_store(
    *, tiktok: bool = True, instagram: bool = True, cadence=None, mode: str = "auto"
) -> MemoryStore:
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
                mode=mode,
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


# ---- free_slot: one rule for approve_clip (SQL), schedule_clip and the publish deferral -------------


def d(day: int, month: int = 10):
    return slot(day, month=month).date()


def test_free_slot_is_the_upcoming_slot_when_its_day_is_free():
    assert free_slot("biscuit", TUE, CADENCE, set()) == slot(6)
    assert free_slot("biscuit", TUE, CADENCE, {d(1), d(5)}) == slot(6)  # other days do not matter


@pytest.mark.parametrize(
    ("taken", "expected"),
    [
        ({d(6)}, slot(7)),  # Tue taken -> Wed
        ({d(6), d(7)}, slot(8)),
        ({d(6), d(7), d(8)}, slot(13)),  # the whole cadence week taken -> next Tue (Fri..Mon are not days)
        ({d(7)}, slot(6)),  # a later day taken does not push an earlier free one
    ],
)
def test_free_slot_takes_the_first_cadence_slot_on_a_day_nobody_posts(taken, expected):
    assert free_slot("biscuit", TUE, CADENCE, taken) == expected


def test_free_slot_starts_from_the_upcoming_slot_not_from_today():
    evening = slot(6, 20)  # today's slot is gone: Wed is the first candidate
    assert free_slot("biscuit", evening, CADENCE, set()) == slot(7)
    assert free_slot("biscuit", evening, CADENCE, {d(7)}) == slot(8)


def test_free_slot_gives_up_after_eight_weeks_with_a_clear_error():
    every_day = {d(6) + timedelta(days=i) for i in range(70)}
    with pytest.raises(ValueError, match="no free posting day"):
        free_slot("biscuit", TUE, CADENCE, every_day)


def test_free_slot_keeps_the_london_wall_time_across_the_clock_change():
    before = datetime(2026, 10, 22, 8, 0, tzinfo=LONDON)  # Thu 22 Oct, BST
    got = free_slot("biscuit", before, CADENCE, {before.date()})  # Thu taken -> Tue 27 Oct (GMT)
    assert got == datetime(2026, 10, 27, 19, 0, tzinfo=LONDON) and got.utcoffset() == timedelta(0)


def _post(store, account, clip, day_slot, status, **kw):
    return store.add_post(
        Post(clip_id=clip.id, account_id=account.id, scheduled_for=day_slot, status=status, **kw)
    )


@pytest.mark.parametrize("status", [PostStatus.scheduled, PostStatus.posting, PostStatus.posted, PostStatus.needs_check])
def test_taken_days_counts_every_status_that_holds_or_used_a_slot(status):
    store = make_store()
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    other = add_clip(store, S.scheduled)
    _post(store, tiktok, other, slot(6), status)
    assert taken_days(store, [tiktok.id]) == {d(6)}


def test_taken_days_ignores_failed_posts_other_accounts_and_the_clips_own_posts():
    store = make_store()
    tiktok, instagram = (
        next(a for a in store.accounts("biscuit") if a.platform is p) for p in (Platform.tiktok, Platform.instagram)
    )
    other, own = add_clip(store, S.scheduled), add_clip(store)
    _post(store, tiktok, other, slot(6), PostStatus.failed)
    _post(store, instagram, other, slot(7), PostStatus.scheduled)  # not a target account
    _post(store, tiktok, own, slot(8), PostStatus.scheduled)  # this clip's own half-written post
    assert taken_days(store, [tiktok.id], exclude_clip_id=own.id) == set()
    assert taken_days(store, [tiktok.id]) == {d(8)}


def test_taken_days_dates_a_post_by_claimed_at_else_its_slot_in_london():
    store = make_store()
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    other = add_clip(store, S.scheduled)
    late = datetime(2026, 10, 7, 23, 30, tzinfo=timezone.utc)  # 00:30 BST on the 8th
    _post(store, tiktok, other, slot(6), PostStatus.posted, claimed_at=late)
    assert taken_days(store, [tiktok.id]) == {d(8)}


# ---- the family of a clip (terminal v3): one clip used by up to 3 characters, their posts 14 days apart -----------------


def family(store, *slugs, skipped=()):
    """A root drop and its versions (``drop.copy_of``), one clip each: ``{slug: clip}``, the first slug the root's."""
    root = store.add_favorite(Favorite(url=f"owner-drop:root-{slugs[0]}", platform="drop", origin="owner", status="made",
                                       character_slug=slugs[0], proposal={"drop": {"state": "made"}}))
    out = {}
    for slug in slugs:
        pick = root if slug == slugs[0] else store.add_favorite(Favorite(
            url=f"owner-drop:{slugs[0]}-{slug}", platform="drop", origin="owner", status="skipped" if slug in skipped else "made",
            character_slug=slug, proposal={"drop": {"state": "made", "copy_of": root.id}}))
        clip = store.add_clip(Clip(character_slug=slug, mode=Mode.dropin, state=S.mastered, master_path=f"{slug}/m.mp4",
                                   features={"fav_id": pick.id}))
        store.update_favorite(pick.id, clip_id=clip.id)
        out[slug] = clip
    return out


def test_family_days_block_13_days_either_side():
    assert FAMILY_GAP_DAYS == 14
    store = make_store()
    reginald_tt = store.add_account(Account(character_slug="reginald", platform=Platform.tiktok, handle="@reg", postiz_integration_id="pz-r"))
    clips_ = family(store, "reginald", "biscuit", "lenny")
    _post(store, reginald_tt, clips_["reginald"], slot(20), PostStatus.posted)  # on another character's account: it counts
    reginald_ig = store.add_account(Account(character_slug="reginald", platform=Platform.instagram, handle="@reg.ig"))
    _post(store, reginald_ig, clips_["reginald"], slot(6), PostStatus.failed)  # a failed post never took a day
    window = {d(20) + timedelta(days=k) for k in range(-13, 14)}
    assert family_days(store, clips_["biscuit"].id) == window and len(window) == 27
    assert d(20) - timedelta(days=14) not in window and d(20) + timedelta(days=14) not in window
    assert family_days(store, clips_["reginald"].id) == set()  # the clip being scheduled: its own posts are no family
    late = datetime(2026, 10, 8, 23, 30, tzinfo=timezone.utc)  # claimed 00:30 BST on the 9th: dated by claimed_at in London
    _post(store, reginald_tt, clips_["lenny"], slot(8), PostStatus.posted, claimed_at=late)
    assert family_days(store, clips_["biscuit"].id) == window | {d(9) + timedelta(days=k) for k in range(-13, 14)}
    assert family_days(store, add_clip(store).id) == set()  # a clip of no family
    assert family_days(store, "nope") == set()


def test_family_days_count_a_skipped_members_posts_too():
    """Skipped picks do not count towards the 3 characters, but a post is a post: its days stay taken for the family."""
    store = make_store()
    clips_ = family(store, "reginald", "biscuit", "lenny", skipped=("biscuit",))
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    other = family(store, "franz", "dj")  # another family: nothing to do with this one
    _post(store, tiktok, other["franz"], slot(27), PostStatus.scheduled)
    _post(store, tiktok, clips_["biscuit"], slot(13), PostStatus.scheduled)
    assert family_days(store, clips_["lenny"].id) == {d(13) + timedelta(days=k) for k in range(-13, 14)}


def test_schedule_skips_family_days():
    store = make_store()
    reginald_tt = store.add_account(Account(character_slug="reginald", platform=Platform.tiktok, handle="@reg", postiz_integration_id="pz-r"))
    clips_ = family(store, "reginald", "biscuit")
    _post(store, reginald_tt, clips_["reginald"], slot(6), PostStatus.scheduled)  # the root goes out on Tue 6 Oct
    _, posts = schedule_clip(store, clips_["biscuit"].id, now=TUE)
    assert {p.scheduled_for for p in posts} == {slot(20)}  # Tue 20 Oct: the first cadence day 14 days on
    plain = add_clip(store)  # a clip of no family is not held back by them
    _, posts = schedule_clip(store, plain.id, now=TUE)
    assert {p.scheduled_for for p in posts} == {slot(6)}


def test_an_explicit_at_may_land_inside_the_familys_two_weeks():
    """The owner's own time is his choice, as on a taken day."""
    store = make_store()
    reginald_tt = store.add_account(Account(character_slug="reginald", platform=Platform.tiktok, handle="@reg", postiz_integration_id="pz-r"))
    clips_ = family(store, "reginald", "biscuit")
    _post(store, reginald_tt, clips_["reginald"], slot(6), PostStatus.scheduled)
    _, posts = schedule_clip(store, clips_["biscuit"].id, at=slot(8), now=TUE)
    assert {p.scheduled_for for p in posts} == {slot(8)}


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
     S.posted, S.dropped],
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

    again, again_posts = schedule_clip(store, clip.id, now=TUE)  # asking again: idempotent, writes nothing
    assert again.state is S.scheduled and {p.id for p in again_posts} == {p.id for p in posts}
    assert len(store.list_posts(clip_id=clip.id)) == 2


def test_rescheduling_an_already_scheduled_clip_returns_its_existing_posts_unchanged():
    store = make_store()
    clip = add_clip(store)
    first_clip, first = schedule_clip(store, clip.id, now=TUE)
    again_clip, again = schedule_clip(store, clip.id, at=slot(20), now=TUE + timedelta(days=1))
    assert again_clip.state is S.scheduled
    assert sorted(p.id for p in again) == sorted(p.id for p in first)
    assert {p.scheduled_for for p in again} == {slot(6)}  # the existing posts are returned as they are
    assert len(store.list_posts(clip_id=clip.id)) == 2


def test_rescheduling_a_scheduled_clip_is_fine_even_when_an_account_is_now_in_approval_mode():
    """It writes nothing, so there is no approval to bypass: the answer is just the existing posts."""
    store = make_store()
    clip = add_clip(store)
    schedule_clip(store, clip.id, now=TUE)
    for account in store.accounts("biscuit"):
        store.update_account(account.id, mode="approval")
    _, again = schedule_clip(store, clip.id, now=TUE)
    assert len(again) == 2 and len(store.list_posts(clip_id=clip.id)) == 2


def test_a_scheduled_clip_with_no_posts_is_still_refused():
    """``scheduled`` with nothing to return is an inconsistent clip: say so, do not answer ``[]``."""
    store = make_store()
    clip = add_clip(store, S.scheduled)
    with pytest.raises(ValueError, match="scheduled"):
        schedule_clip(store, clip.id, now=TUE)
    assert store.list_posts() == []


def test_two_approvals_for_the_same_accounts_land_on_different_days():
    """Each default slot is the first cadence day on which no target account already has a post."""
    store = make_store()
    first, second, third = (add_clip(store) for _ in range(3))
    days = [
        {p.scheduled_for for p in schedule_clip(store, c.id, now=TUE)[1]} for c in (first, second, third)
    ]
    assert days == [{slot(6)}, {slot(7)}, {slot(8)}]
    assert {len(store.list_posts(clip_id=c.id)) for c in (first, second, third)} == {2}


def test_the_free_day_is_judged_per_target_account_set():
    """A day taken only on an account this clip does not go to does not count."""
    store = make_store(instagram=False)  # Biscuit's only connected account is TikTok
    ig = store.add_account(Account(character_slug="biscuit", platform=Platform.instagram, handle="@x.ig"))
    other = add_clip(store, S.scheduled)
    _post(store, ig, other, slot(6), PostStatus.scheduled)  # unconnected account, not a target
    _, posts = schedule_clip(store, add_clip(store).id, now=TUE)
    assert {p.scheduled_for for p in posts} == {slot(6)}


def test_an_explicit_at_is_the_owners_choice_even_on_a_taken_day():
    store = make_store()
    schedule_clip(store, add_clip(store).id, now=TUE)  # takes Tuesday
    _, posts = schedule_clip(store, add_clip(store).id, at=slot(6, 20), now=TUE)
    assert {p.scheduled_for for p in posts} == {slot(6, 20)}


def test_a_clips_own_earlier_post_does_not_push_its_other_posts_to_another_day():
    store = make_store()
    clip = add_clip(store)
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=slot(6)))  # an interrupted call
    _, posts = schedule_clip(store, clip.id, now=TUE)
    assert {p.scheduled_for for p in posts} == {slot(6)}


# ---- approval mode: `clip schedule` is not a way round the owner ------------------------------------


def test_a_mastered_clip_for_an_account_in_approval_mode_is_refused_writing_nothing():
    store = make_store(mode="approval")
    clip = add_clip(store)
    with pytest.raises(ValueError, match="approval mode") as e:
        schedule_clip(store, clip.id, now=TUE)
    assert "@biscuit.tiktok" in str(e.value) and "@biscuit.instagram" in str(e.value)
    assert "awaiting_approval" in str(e.value)  # says what to do instead
    assert "--force" not in str(e.value)  # there is no override: the owner approves in the terminal
    assert store.list_posts() == [] and store.get_clip(clip.id).state is S.mastered


def test_one_account_in_approval_mode_refuses_the_whole_call_and_names_it():
    store = make_store()
    instagram = next(a for a in store.accounts("biscuit") if a.platform is Platform.instagram)
    store.update_account(instagram.id, mode="approval")
    clip = add_clip(store)
    with pytest.raises(ValueError, match="approval mode") as e:
        schedule_clip(store, clip.id, now=TUE)
    assert "@biscuit.instagram" in str(e.value) and "@biscuit.tiktok" not in str(e.value)
    assert store.list_posts() == [] and store.get_clip(clip.id).state is S.mastered  # not "just the other one"


def test_an_approved_clip_is_scheduled_whatever_the_account_mode():
    """``approved`` is the owner's yes (the terminal's approve RPC does the same): the mode no longer matters."""
    store = make_store(mode="approval")
    clip = add_clip(store, S.approved)
    done, posts = schedule_clip(store, clip.id, now=TUE)
    assert done.state is S.scheduled and len(posts) == 2


def test_an_unconnected_or_skipped_account_in_approval_mode_does_not_matter():
    """Only the accounts that would get a post count: no integration id, or over the drop-in share."""
    store = make_store()
    instagram = next(a for a in store.accounts("biscuit") if a.platform is Platform.instagram)
    store.update_account(instagram.id, mode="approval")
    _dropin_history(store, instagram, n_dropin=5, n_recreate=5)  # over the Instagram share: skipped
    clip = add_clip(store, mode=Mode.dropin)
    _, posts = schedule_clip(store, clip.id, now=TUE)
    assert [p.account_id for p in posts] != [instagram.id] and len(posts) == 1

    store2 = make_store(instagram=False)
    ig = next(a for a in store2.accounts("biscuit") if a.platform is Platform.instagram)
    store2.update_account(ig.id, mode="approval")  # not connected: no post, no approval needed
    clip2 = add_clip(store2)
    _, posts2 = schedule_clip(store2, clip2.id, now=TUE)
    assert len(posts2) == 1


def test_a_post_that_already_exists_does_not_hide_an_approval_mode_account():
    store = make_store(mode="approval")
    clip = add_clip(store)
    tiktok = next(a for a in store.accounts("biscuit") if a.platform is Platform.tiktok)
    store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=slot(1, 12)))
    with pytest.raises(ValueError, match="approval mode"):
        schedule_clip(store, clip.id, now=TUE)


def test_schedule_clip_has_no_force_parameter():
    with pytest.raises(TypeError):
        schedule_clip(make_store(mode="approval"), "x", now=TUE, force=True)  # type: ignore[call-arg]


def test_a_clip_without_a_master_is_refused_like_the_terminal_does():
    """Mirrors migration 0005's queue_block_reason: the publisher would fail it three times anyway."""
    store = make_store()
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate, state=S.mastered))
    with pytest.raises(ValueError, match="no master"):
        schedule_clip(store, clip.id, now=TUE)
    assert store.list_posts() == [] and store.get_clip(clip.id).state is S.mastered


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


def test_cli_schedule_refuses_an_approval_mode_account_with_exit_2_and_no_force_option(monkeypatch):
    store = make_store(mode="approval")
    monkeypatch.setattr(clips, "open_store", lambda: store)
    monkeypatch.setattr(clips, "now_london", lambda: TUE)
    clip = add_clip(store)
    r = run("schedule", clip.id)
    assert r.exit_code == 2 and "approval mode" in r.output and "awaiting_approval" in r.output
    assert store.list_posts() == [] and store.get_clip(clip.id).state is S.mastered
    assert run("schedule", clip.id, "--force").exit_code == 2  # no such option: no override
    assert store.list_posts() == []
    assert "--force" not in run("schedule", "--help").output


def test_cli_schedule_without_a_master_exits_2(cli_store):
    clip = cli_store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate, state=S.mastered))
    r = run("schedule", clip.id)
    assert r.exit_code == 2 and "no master" in r.output and cli_store.list_posts() == []


def test_cli_rescheduling_a_scheduled_clip_exits_0_with_its_existing_posts(cli_store):
    clip = add_clip(cli_store)
    first = run("schedule", clip.id)
    again = run("schedule", clip.id)
    assert first.exit_code == 0 and again.exit_code == 0, again.output
    ids = lambda r: sorted(p["id"] for p in json.loads(r.stdout)["posts"])  # noqa: E731
    assert ids(first) == ids(again) and len(ids(again)) == 2
    assert len(cli_store.list_posts(clip_id=clip.id)) == 2


def test_cli_schedule_without_a_connected_account_exits_2(monkeypatch):
    store = make_store(tiktok=False, instagram=False)
    monkeypatch.setattr(clips, "open_store", lambda: store)
    clip = add_clip(store)
    r = run("schedule", clip.id)
    assert r.exit_code == 2 and "no connected account" in r.output
    assert store.get_clip(clip.id).state is S.mastered

import itertools
import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from studio import planning
from studio.budget import reserve
from studio.cli import app
from studio.config import LONDON
from studio.models import (
    Account,
    Body,
    Character,
    Clip,
    ClipState,
    Mode,
    Platform,
    Post,
    PostStatus,
    Settings,
    Source,
    SourceKind,
)
from studio.planning import (
    DueClip,
    accounts_for_clip,
    choose_mode,
    dropin_ratio,
    plan_today,
    slot_for,
)
from studio.store import MemoryStore

# Tue 6 Oct 2026 (BST); the default cadence has both characters on Tue/Wed/Thu.
TUE = datetime(2026, 10, 6, 8, 0, tzinfo=LONDON)
SAT = datetime(2026, 10, 10, 8, 0, tzinfo=LONDON)
HISTORY_START = datetime(2026, 9, 1, 19, 0, tzinfo=LONDON)


def make_store(
    cap: int = 6000,
    kill_switch: bool = False,
    *,
    connected: bool = True,
    unconnected: tuple[Platform, ...] = (),
    shares: dict[Platform, float] | None = None,
) -> MemoryStore:
    """Two characters, a TikTok and an Instagram account each.

    ``connected=False`` leaves every account without a Postiz integration, ``unconnected`` just
    the given platforms; ``shares`` overrides the platform-default ``dropin_share``.
    MemoryStore enforces no foreign keys; seed what Postgres would require.
    """
    store = MemoryStore(
        settings=Settings(monthly_cap_credits=cap, kill_switch=kill_switch),
        characters=[
            Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]),
            Character(slug="reginald", name="Reginald", bodies=[Body.biped]),
        ],
    )
    for slug in ("biscuit", "reginald"):
        for platform in (Platform.tiktok, Platform.instagram):
            store.add_account(
                Account(
                    character_slug=slug,
                    platform=platform,
                    handle=f"@{slug}.{platform.value}",
                    postiz_integration_id=(
                        f"pz-{slug}-{platform.value}"
                        if connected and platform not in unconnected
                        else None
                    ),
                    dropin_share=(shares or {}).get(platform),
                )
            )
    return store


def character(store: MemoryStore, slug: str) -> Character:
    return next(c for c in store.characters() if c.slug == slug)


def account(store: MemoryStore, slug: str, platform: Platform) -> Account:
    return next(a for a in store.accounts(slug) if a.platform is platform)


_source_clock = itertools.count()


def clean_source(store: MemoryStore, body: Body = Body.quadruped, **overrides) -> Source:
    """A clean Drop-in source; each one is created a minute after the previous (so ranking is stable)."""
    fields = dict(
        kind=SourceKind.owner_inbox, body=body, bodies=1, duration_s=8.0,
        has_watermark=False, has_overlay=False, other_people=0,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=next(_source_clock)),
    ) | overrides
    return store.add_source(Source(**fields))


def history(store: MemoryStore, acct: Account, modes: list[Mode | str], *, start=HISTORY_START):
    """One clip + one post per mode, oldest first (a day apart); returns the clips."""
    clips = []
    for i, mode in enumerate(modes):
        clip = store.add_clip(Clip(character_slug=acct.character_slug, mode=mode))
        store.add_post(
            Post(clip_id=clip.id, account_id=acct.id, scheduled_for=start + timedelta(days=i))
        )
        clips.append(clip)
    return clips


D, R = Mode.dropin, Mode.recreate


# ---- who is due, and when ---------------------------------------------------------------


def test_due_on_cadence_day_only():
    store = make_store()
    due = plan_today(store, TUE)
    assert [(d.character_slug, d.slot.hour, d.slot.minute) for d in due] == [
        ("biscuit", 19, 0),
        ("reginald", 19, 30),
    ]
    assert all(isinstance(d, DueClip) for d in due)
    assert plan_today(store, SAT) == []
    assert plan_today(store, datetime(2026, 10, 5, 8, 0, tzinfo=LONDON)) == []  # Monday


def test_weekday_is_the_london_weekday_not_utc():
    store = make_store()
    # 23:30 UTC on Mon 5 Oct is already Tue 00:30 in London (BST): due, and the slot is Tuesday's.
    due = plan_today(store, datetime(2026, 10, 5, 23, 30, tzinfo=timezone.utc))
    assert [d.slot.date() for d in due] == [date(2026, 10, 6)] * 2
    # 23:30 UTC on Thu 8 Oct is already Fri in London: nothing due.
    assert plan_today(store, datetime(2026, 10, 8, 23, 30, tzinfo=timezone.utc)) == []
    # in winter London == UTC: 23:30 UTC on Tue 3 Nov is still Tuesday, so due, with Tuesday's slot
    winter = plan_today(store, datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc))
    assert [d.slot.date() for d in winter] == [date(2026, 11, 3)] * 2


def test_cadence_and_slot_come_from_settings():
    store = make_store()
    store.set_settings(
        cadence={
            "biscuit": {"days": ["mon", "fri"], "slot": "18:15"},
            "reginald": {"days": ["tue"], "slot": "20:05"},
        }
    )
    monday = plan_today(store, datetime(2026, 10, 5, 8, 0, tzinfo=LONDON))
    assert [(d.character_slug, d.slot.hour, d.slot.minute) for d in monday] == [("biscuit", 18, 15)]
    tuesday = plan_today(store, TUE)
    assert [(d.character_slug, d.slot.hour, d.slot.minute) for d in tuesday] == [("reginald", 20, 5)]


def test_character_without_cadence_or_cadence_without_character_is_ignored():
    store = make_store()
    store.set_settings(
        cadence={"reginald": {"days": ["tue"], "slot": "19:30"}, "ghost": {"days": ["tue"], "slot": "10:00"}}
    )
    assert [d.character_slug for d in plan_today(store, TUE)] == ["reginald"]


def test_plan_orders_by_slot_then_slug():
    store = make_store()
    store.set_settings(
        cadence={
            "biscuit": {"days": ["tue"], "slot": "19:30"},
            "reginald": {"days": ["tue"], "slot": "19:00"},
        }
    )
    assert [d.character_slug for d in plan_today(store, TUE)] == ["reginald", "biscuit"]


def test_plan_requires_an_aware_now():
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_today(make_store(), datetime(2026, 10, 6, 8, 0))


# ---- one clip a day ---------------------------------------------------------------------


def test_character_with_a_clip_beyond_planned_today_is_not_due():
    store = make_store()
    clip = store.add_clip(
        Clip(character_slug="biscuit", mode=R, state=ClipState.generating, created_at=TUE)
    )
    assert [d.character_slug for d in plan_today(store, TUE)] == ["reginald"]
    # whatever state it reached, today's clip counts (even a dead one: one plan per day)
    for state in (ClipState.gen_failed, ClipState.dropped, ClipState.awaiting_approval):
        store.update_clip(clip.id, state=state)
        assert [d.character_slug for d in plan_today(store, TUE)] == ["reginald"], state


def test_a_planned_clip_does_not_block_and_other_days_or_characters_do_not_count():
    store = make_store()
    store.add_clip(Clip(character_slug="biscuit", mode=R, state=ClipState.planned, created_at=TUE))
    # yesterday's clip (any state) and another character's clip leave biscuit due
    store.add_clip(
        Clip(character_slug="reginald", mode=R, state=ClipState.posted, created_at=TUE - timedelta(days=1))
    )
    store.add_clip(
        Clip(character_slug="biscuit", mode=R, state=ClipState.generated, created_at=TUE - timedelta(days=1))
    )
    assert [d.character_slug for d in plan_today(store, TUE)] == ["biscuit", "reginald"]


def test_today_is_the_london_day_of_created_at():
    store = make_store()
    # 23:30 UTC on Mon 5 Oct is Tue 00:30 London: a Tuesday clip, so biscuit is not due on Tuesday
    store.add_clip(
        Clip(
            character_slug="biscuit", mode=R, state=ClipState.generating,
            created_at=datetime(2026, 10, 5, 23, 30, tzinfo=timezone.utc),
        )
    )
    assert [d.character_slug for d in plan_today(store, TUE)] == ["reginald"]


# ---- kill switch and cap ----------------------------------------------------------------


def test_kill_switch_plans_nothing():
    assert plan_today(make_store(kill_switch=True), TUE) == []


def test_plan_respects_cap():
    store = make_store(cap=170)  # room for one recreate (160), not two (320)
    due = plan_today(store, TUE)
    assert [(d.character_slug, d.est_credits) for d in due] == [("biscuit", 160)]


def test_plan_counts_committed_credits_of_the_month():
    store = make_store(cap=400)
    three_days_ago = TUE - timedelta(days=3)
    held = store.add_clip(
        Clip(character_slug="reginald", mode=R, state=ClipState.generating, created_at=three_days_ago)
    )
    reserve(store, held.id, 200, three_days_ago)
    # 200 + 160 <= 400 < 200 + 320
    assert [d.character_slug for d in plan_today(store, TUE)] == ["biscuit"]
    # another month's spend does not count
    other = make_store(cap=400)
    reserve(other, "old", 300, datetime(2026, 9, 20, 12, 0, tzinfo=LONDON))
    assert len(plan_today(other, TUE)) == 2


def test_plan_may_spend_exactly_up_to_the_cap():
    assert len(plan_today(make_store(cap=320), TUE)) == 2
    assert len(plan_today(make_store(cap=319), TUE)) == 1
    assert plan_today(make_store(cap=159), TUE) == []


def test_plan_stops_at_the_first_clip_that_does_not_fit():
    # biscuit (19:00, recreate 160) does not fit in 130; reginald's cheaper Drop-in (115) would,
    # but the plan stops adding at the first refusal instead of skipping ahead.
    store = make_store(cap=130)
    clean_source(store, Body.biped)
    assert choose_mode(store, character(store, "reginald")) is D
    assert plan_today(store, TUE) == []


def test_est_credits_follow_the_mode():
    store = make_store()
    clean_source(store, Body.biped)  # only reginald has a Drop-in source
    by_slug = {d.character_slug: d for d in plan_today(store, TUE)}
    assert (by_slug["biscuit"].mode, by_slug["biscuit"].est_credits) == (R, 160)
    assert (by_slug["reginald"].mode, by_slug["reginald"].est_credits) == (D, 115)


# ---- slots ------------------------------------------------------------------------------


def test_slot_is_london_time_across_dst():
    winter = slot_for("biscuit", date(2026, 10, 27))  # clocks went back on Sun 25 Oct
    assert (winter.hour, winter.minute) == (19, 0)
    assert winter.utcoffset() == timedelta(0)
    summer = slot_for("biscuit", date(2026, 10, 20))
    assert (summer.hour, summer.minute) == (19, 0)
    assert summer.utcoffset() == timedelta(hours=1)
    # same wall-clock slot, one hour apart in absolute time
    assert winter.astimezone(timezone.utc).hour == 19
    assert summer.astimezone(timezone.utc).hour == 18
    assert winter.tzinfo is LONDON and summer.tzinfo is LONDON


def test_slot_on_the_changeover_days_themselves():
    assert slot_for("reginald", date(2026, 10, 25)).utcoffset() == timedelta(0)  # clocks back 01:00 BST
    assert slot_for("reginald", date(2026, 10, 24)).utcoffset() == timedelta(hours=1)
    assert slot_for("reginald", date(2026, 3, 29)).utcoffset() == timedelta(hours=1)  # clocks forward
    assert slot_for("reginald", date(2026, 3, 28)).utcoffset() == timedelta(0)
    assert slot_for("reginald", date(2026, 3, 29)).minute == 30


def test_slot_inside_the_spring_gap_is_normalised():
    # 01:30 does not exist on 29 Mar 2026 (01:00 -> 02:00): read it as the real instant, 02:30 BST
    gap = slot_for("biscuit", date(2026, 3, 29), {"biscuit": {"days": [], "slot": "01:30"}})
    assert (gap.hour, gap.minute, gap.utcoffset()) == (2, 30, timedelta(hours=1))


def test_slot_for_uses_the_given_cadence_and_rejects_bad_ones():
    cadence = {"biscuit": {"days": ["tue"], "slot": "07:05"}}
    assert (slot_for("biscuit", date(2026, 10, 6), cadence).hour, slot_for("biscuit", date(2026, 10, 6), cadence).minute) == (7, 5)
    with pytest.raises(ValueError, match="no posting slot"):
        slot_for("reginald", date(2026, 10, 6), cadence)
    with pytest.raises(ValueError, match="no posting slot"):
        slot_for("nobody", date(2026, 10, 6))
    for bad in ("7pm", "19:60", "24:00", "19:5", "", None, 1930):
        with pytest.raises(ValueError, match="HH:MM"):
            slot_for("biscuit", date(2026, 10, 6), {"biscuit": {"slot": bad}})


def test_plan_slots_are_aware_london_datetimes():
    for d in plan_today(make_store(), TUE):
        assert d.slot.tzinfo is LONDON
        assert d.slot.utcoffset() == timedelta(hours=1)  # BST on 6 Oct
    winter = plan_today(make_store(), datetime(2026, 10, 28, 8, 0, tzinfo=LONDON))  # Wed after DST end
    assert [(d.slot.hour, d.slot.minute, d.slot.utcoffset()) for d in winter] == [
        (19, 0, timedelta(0)),
        (19, 30, timedelta(0)),
    ]


# ---- mode choice ------------------------------------------------------------------------


def test_dropin_chosen_when_clean_source_and_under_share():
    store = make_store()
    src = clean_source(store)
    tiktok = account(store, "biscuit", Platform.tiktok)
    history(store, tiktok, [D, R, R, D, R, R, R, D, R, R])  # 3 of 10 = 0.3 < 0.70
    assert choose_mode(store, character(store, "biscuit")) is D
    (due,) = [d for d in plan_today(store, TUE) if d.character_slug == "biscuit"]
    assert (due.mode, due.est_credits, due.source_candidates) == (D, 115, [src.id])


def test_dropin_with_no_history_counts_as_ratio_zero():
    store = make_store()
    clean_source(store)
    assert dropin_ratio(store, account(store, "biscuit", Platform.tiktok)) == 0.0
    assert choose_mode(store, character(store, "biscuit")) is D


def test_recreate_without_a_dropin_eligible_source():
    store = make_store()
    biscuit = character(store, "biscuit")
    assert choose_mode(store, biscuit) is R  # no source at all
    clean_source(store, has_watermark=None, has_overlay=None, other_people=None)  # unchecked
    clean_source(store, kind=SourceKind.synthetic)
    clean_source(store, has_watermark=True)
    clean_source(store, has_overlay=True)
    clean_source(store, other_people=1)
    clean_source(store, body=Body.biped)  # clean, but the wrong body for a dachshund
    assert choose_mode(store, biscuit) is R


def test_recreate_when_tiktok_is_at_or_over_its_share():
    store = make_store()
    clean_source(store)
    tiktok = account(store, "biscuit", Platform.tiktok)
    history(store, tiktok, [D] * 7 + [R] * 3)  # exactly 0.70: not under
    assert dropin_ratio(store, tiktok) == pytest.approx(0.7)
    assert choose_mode(store, character(store, "biscuit")) is R

    over = make_store()
    clean_source(over)
    history(over, account(over, "biscuit", Platform.tiktok), [D] * 9 + [R])  # 0.9
    assert choose_mode(over, character(over, "biscuit")) is R

    under = make_store()
    clean_source(under)
    history(under, account(under, "biscuit", Platform.tiktok), [D] * 6 + [R] * 4)  # 0.6
    assert choose_mode(under, character(under, "biscuit")) is D


def test_only_the_last_ten_clips_count():
    store = make_store()
    clean_source(store)
    tiktok = account(store, "biscuit", Platform.tiktok)
    history(store, tiktok, [D] * 10 + [R] * 10)  # the ten Drop-ins are old news
    assert dropin_ratio(store, tiktok) == 0.0
    assert choose_mode(store, character(store, "biscuit")) is D

    other = make_store()
    clean_source(other)
    tt = account(other, "biscuit", Platform.tiktok)
    history(other, tt, [R] * 10 + [D] * 10)  # the newest ten are all Drop-ins
    assert dropin_ratio(other, tt) == 1.0
    assert choose_mode(other, character(other, "biscuit")) is R


def test_ratio_is_over_the_posts_there_are_when_fewer_than_ten():
    store = make_store()
    tiktok = account(store, "biscuit", Platform.tiktok)
    history(store, tiktok, [D, R, D])
    assert dropin_ratio(store, tiktok) == pytest.approx(2 / 3)


def test_ratio_follows_post_schedule_order_not_insertion_order():
    store = make_store()
    tiktok = account(store, "biscuit", Platform.tiktok)
    # newest-scheduled posts inserted first: the ten newest (by scheduled_for) are Recreates
    history(store, tiktok, [R] * 10, start=HISTORY_START + timedelta(days=20))
    history(store, tiktok, [D] * 10, start=HISTORY_START)
    assert dropin_ratio(store, tiktok) == 0.0


def test_ratio_counts_each_account_separately_and_ignores_clips_without_a_post():
    store = make_store()
    tiktok = account(store, "biscuit", Platform.tiktok)
    insta = account(store, "biscuit", Platform.instagram)
    history(store, tiktok, [R] * 4)
    history(store, insta, [D] * 4)
    store.add_clip(Clip(character_slug="biscuit", mode=D))  # a clip that never produced a post
    assert dropin_ratio(store, tiktok) == 0.0
    assert dropin_ratio(store, insta) == 1.0


def test_choose_mode_looks_at_tiktok_only():
    store = make_store()
    clean_source(store)
    history(store, account(store, "biscuit", Platform.instagram), [D] * 10)  # IG way over 0.40
    assert choose_mode(store, character(store, "biscuit")) is D


@pytest.mark.parametrize(
    ("share", "expected"),
    [(0.70, D), (0.2, D), (0.1, R), (0.0, R)],  # ratio is 0.1: not under 0.1; share 0 disables Drop-in
)
def test_choose_mode_uses_the_accounts_own_share(share, expected):
    store = make_store(shares={Platform.tiktok: share})
    clean_source(store)
    tiktok = account(store, "biscuit", Platform.tiktok)
    assert tiktok.dropin_share == share
    history(store, tiktok, [D, R, R, R, R, R, R, R, R, R])  # 0.1
    assert choose_mode(store, character(store, "biscuit")) is expected


def test_unconnected_or_missing_tiktok_account_means_recreate():
    for store in (make_store(connected=False), make_store(unconnected=(Platform.tiktok,))):
        clean_source(store)
        assert choose_mode(store, character(store, "biscuit")) is R

    bare = MemoryStore(characters=[Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped])])
    clean_source(bare)
    assert choose_mode(bare, character(bare, "biscuit")) is R


def test_source_candidates_are_ranked_for_the_chosen_mode():
    store = make_store()
    older = clean_source(store, body=Body.biped)
    newer = clean_source(store, body=Body.biped)
    unchecked = clean_source(store, body=Body.biped, has_watermark=None)  # newest, but not clean
    dachshund = clean_source(store, body=Body.quadruped)
    by_slug = {d.character_slug: d for d in plan_today(store, TUE)}
    # Drop-in: clean sources whose body fits the character, newest first (nothing is measured)
    assert by_slug["reginald"].mode is D
    assert by_slug["reginald"].source_candidates == [newer.id, older.id]
    assert by_slug["biscuit"].mode is D
    assert by_slug["biscuit"].source_candidates == [dachshund.id]

    # Recreate (Reginald's TikTok is over its share): body fit only, so the unchecked one counts too
    history(store, account(store, "reginald", Platform.tiktok), [D] * 10)
    recreate = {d.character_slug: d for d in plan_today(store, TUE)}["reginald"]
    assert recreate.mode is R
    assert recreate.source_candidates == [unchecked.id, newer.id, older.id]


def test_recreate_with_no_source_has_no_candidates():
    (biscuit,) = [d for d in plan_today(make_store(), TUE) if d.character_slug == "biscuit"]
    assert (biscuit.mode, biscuit.source_candidates) == (R, [])


# ---- which accounts get the clip ----------------------------------------------------------


def test_instagram_skipped_for_dropin_when_over_share():
    store = make_store()
    insta = account(store, "biscuit", Platform.instagram)
    history(store, insta, [D, D, D, D, D, R, R, R, R, R])  # 5 of 10 = 0.5 >= share 0.4
    clip = store.add_clip(Clip(character_slug="biscuit", mode=D))
    got = accounts_for_clip(store, clip)
    assert [a.platform for a in got] == [Platform.tiktok]
    assert insta.id not in {a.id for a in got}


def test_dropin_goes_to_every_account_under_its_share():
    store = make_store()
    history(store, account(store, "biscuit", Platform.instagram), [D, D, D, R, R, R, R, R, R, R])  # 0.3 < 0.4
    history(store, account(store, "biscuit", Platform.tiktok), [D] * 6 + [R] * 4)  # 0.6 < 0.7
    clip = store.add_clip(Clip(character_slug="biscuit", mode=D))
    assert {a.platform for a in accounts_for_clip(store, clip)} == {Platform.tiktok, Platform.instagram}


def test_dropin_can_be_refused_by_every_account():
    store = make_store()
    history(store, account(store, "biscuit", Platform.instagram), [D] * 10)
    history(store, account(store, "biscuit", Platform.tiktok), [D] * 10)
    clip = store.add_clip(Clip(character_slug="biscuit", mode=D))
    assert accounts_for_clip(store, clip) == []


def test_recreate_goes_to_all_the_characters_accounts_whatever_their_share():
    store = make_store()
    history(store, account(store, "biscuit", Platform.instagram), [D] * 10)
    history(store, account(store, "biscuit", Platform.tiktok), [D] * 10)
    clip = store.add_clip(Clip(character_slug="biscuit", mode=R))
    got = accounts_for_clip(store, clip)
    assert {a.platform for a in got} == {Platform.tiktok, Platform.instagram}
    assert {a.character_slug for a in got} == {"biscuit"}  # never the other character's accounts


def test_accounts_not_yet_connected_are_skipped():
    store = make_store(connected=False)
    for mode in (R, D):
        assert accounts_for_clip(store, store.add_clip(Clip(character_slug="biscuit", mode=mode))) == []

    store = make_store(unconnected=(Platform.instagram,))
    for mode in (R, D):
        got = accounts_for_clip(store, store.add_clip(Clip(character_slug="biscuit", mode=mode)))
        assert [a.platform for a in got] == [Platform.tiktok]


def test_accounts_for_clip_ignores_the_clips_own_posts():
    store = make_store()
    insta = account(store, "biscuit", Platform.instagram)
    # 4 Drop-ins in the window: 4 of 10 is not under 0.4, but the 4th IS this clip, so 3 of 9 is
    clips = history(store, insta, [R, R, R, R, R, R, D, D, D, D])
    last = clips[-1]
    assert dropin_ratio(store, insta) == pytest.approx(0.4)
    assert dropin_ratio(store, insta, exclude_clip_id=last.id) == pytest.approx(3 / 9)
    assert insta.id in {a.id for a in accounts_for_clip(store, last)}  # same answer before/after posting


def test_failed_posts_still_count_toward_the_window():
    store = make_store()
    insta = account(store, "biscuit", Platform.instagram)
    clips = history(store, insta, [D] * 5 + [R] * 5)
    for post in store.list_posts(account_id=insta.id)[:5]:
        store.update_post(post.id, status=PostStatus.failed)
    assert dropin_ratio(store, insta) == 0.5
    assert clips  # the window is "clips that produced a post", whatever became of the post


# ---- CLI ----------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(planning, "open_store", lambda: store)
    monkeypatch.setattr(planning, "now_london", lambda: TUE)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["plan", *args])


def test_plan_today_cli_prints_the_plan_as_json(cli_store):
    clean_source(cli_store, Body.biped)
    r = run("today")
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["date"] == "2026-10-06" and out["month"] == "2026-10" and out["weekday"] == "tue"
    assert out["kill_switch"] is False
    assert (out["cap"], out["committed"], out["remaining"], out["estimated"]) == (6000, 0, 6000, 275)
    biscuit, reginald = out["due"]
    assert biscuit["character_slug"] == "biscuit" and biscuit["mode"] == "recreate"
    assert biscuit["est_credits"] == 160 and biscuit["source_candidates"] == []
    assert biscuit["slot"] == "2026-10-06T19:00:00+01:00"
    assert reginald["mode"] == "dropin" and reginald["est_credits"] == 115
    assert len(reginald["source_candidates"]) == 1
    assert reginald["slot"] == "2026-10-06T19:30:00+01:00"
    assert out["deferred_over_cap"] == []


def test_plan_today_cli_reports_what_the_cap_deferred(cli_store):
    cli_store.set_settings(monthly_cap_credits=170)
    out = json.loads(run("today").output)
    assert [d["character_slug"] for d in out["due"]] == ["biscuit"]
    assert [d["character_slug"] for d in out["deferred_over_cap"]] == ["reginald"]
    assert (out["estimated"], out["remaining"]) == (160, 170)


def test_plan_today_cli_with_kill_switch_or_off_day_is_empty_but_ok(cli_store, monkeypatch):
    cli_store.set_settings(kill_switch=True)
    out = json.loads(run("today").output)
    assert out["kill_switch"] is True and out["due"] == [] and out["deferred_over_cap"] == []

    cli_store.set_settings(kill_switch=False)
    monkeypatch.setattr(planning, "now_london", lambda: SAT)
    r = run("today")
    assert r.exit_code == 0
    out = json.loads(r.output)
    assert out["weekday"] == "sat" and out["due"] == []


def test_plan_today_cli_misconfigured_slot_exits_2(cli_store):
    cli_store.set_settings(cadence={"biscuit": {"days": ["tue"], "slot": "teatime"}})
    r = run("today")
    assert r.exit_code == 2
    assert "HH:MM" in r.output


def test_plan_group_is_registered_once_and_has_today():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    assert len(re.findall(r"^\W*plan\s", r.output, flags=re.MULTILINE)) == 1
    assert "today" in run("--help").output

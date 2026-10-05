from datetime import date, datetime, timedelta

import pytest

from studio.config import LONDON
from studio.models import (
    Account,
    Body,
    Character,
    Clip,
    ClipState,
    Favorite,
    LedgerEntry,
    Mode,
    Platform,
    Post,
    PostStatus,
    Review,
    Run,
    Settings,
    Snapshot,
    Source,
    SourceKind,
)
from studio.store import DuplicatePost, MemoryStore, Store

NOW = datetime(2026, 10, 6, 19, 0, tzinfo=LONDON)


def seeded_store() -> tuple[MemoryStore, Clip, Account, Account]:
    """A store with Biscuit, her two accounts and one planned clip."""
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    tiktok = store.add_account(
        Account(character_slug="biscuit", platform=Platform.tiktok, handle="@biscuit")
    )
    insta = store.add_account(
        Account(character_slug="biscuit", platform=Platform.instagram, handle="biscuit.odd")
    )
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    return store, clip, tiktok, insta


def test_add_and_get_clip_roundtrip():
    store = MemoryStore()
    clip = store.add_clip(
        Clip(
            character_slug="biscuit",
            mode=Mode.dropin,
            hook="Wait for it",
            hashtags=["#odd", "#dog"],
            features={"hook_type": "reveal"},
            qa={"technical": "pass"},
        )
    )
    assert clip.id and clip.created_at is not None
    got = store.get_clip(clip.id)
    assert got == clip
    assert got.state is ClipState.planned
    assert got.mode is Mode.dropin
    assert got.hashtags == ["#odd", "#dog"]
    assert got.features == {"hook_type": "reveal"}
    assert store.get_clip("does-not-exist") is None


def test_claim_due_posts_only_takes_due_scheduled_once():
    store, clip, tiktok, insta = seeded_store()
    due = store.add_post(
        Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=NOW - timedelta(minutes=1))
    )
    later = store.add_post(
        Post(clip_id=clip.id, account_id=insta.id, scheduled_for=NOW + timedelta(hours=1))
    )

    first = store.claim_due_posts(NOW)
    assert [p.id for p in first] == [due.id]
    assert first[0].status is PostStatus.posting
    assert first[0].claimed_at == NOW

    assert store.claim_due_posts(NOW) == []
    assert store.list_posts(status=PostStatus.posting)[0].id == due.id
    assert store.list_posts(status=PostStatus.scheduled)[0].id == later.id


def test_returned_objects_are_copies():
    store = MemoryStore()
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate, hashtags=["#a"]))
    clip.hashtags.append("#mutated")
    clip.state = ClipState.posted
    again = store.get_clip(clip.id)
    assert again.hashtags == ["#a"] and again.state is ClipState.planned


def test_update_clip_changes_fields_and_coerces_enums():
    store = MemoryStore()
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    updated = store.update_clip(clip.id, state="generating", hf_job_id="job-1", credits_reserved=160)
    assert updated.state is ClipState.generating
    assert store.get_clip(clip.id).hf_job_id == "job-1"
    assert store.get_clip(clip.id).credits_reserved == 160


def test_update_clip_rejects_bad_input():
    store = MemoryStore()
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    with pytest.raises(KeyError):
        store.update_clip("nope", state=ClipState.rejected)
    with pytest.raises(TypeError):
        store.update_clip(clip.id, no_such_field=1)
    with pytest.raises(ValueError):
        store.update_clip(clip.id, id="other")
    with pytest.raises(ValueError):
        store.update_clip(clip.id, state="not_a_state")


def test_list_clips_filters():
    store = MemoryStore()
    src = store.add_source(
        Source(kind=SourceKind.owner_inbox, body=Body.biped, bodies=1, duration_s=8.0)
    )
    a = store.add_clip(Clip(character_slug="biscuit", mode=Mode.dropin, source_id=src.id))
    b = store.add_clip(Clip(character_slug="reginald", mode=Mode.recreate))
    store.update_clip(b.id, state=ClipState.approved)

    assert [c.id for c in store.list_clips()] == [a.id, b.id]
    assert [c.id for c in store.list_clips(character_slug="reginald")] == [b.id]
    assert [c.id for c in store.list_clips(state=ClipState.approved)] == [b.id]
    assert [c.id for c in store.list_clips(source_id=src.id)] == [a.id]
    assert [c.id for c in store.list_clips(source_id=None)] == [b.id]
    with pytest.raises(TypeError):
        store.list_clips(bogus=1)


def test_sources_add_update_list():
    store = MemoryStore()
    s = store.add_source(
        Source(
            kind="higgsfield_library",
            url="https://example.com/preset",
            preset_id="p1",
            body="quadruped",
            bodies=1,
            duration_s=7.5,
        )
    )
    assert s.kind is SourceKind.higgsfield_library and s.body is Body.quadruped
    assert s.has_watermark is None  # unchecked until QA'd
    store.update_source(s.id, has_watermark=False, has_overlay=False, other_people=0)
    got = store.list_sources(kind=SourceKind.higgsfield_library)
    assert [x.id for x in got] == [s.id]
    assert got[0].has_watermark is False and got[0].other_people == 0
    assert store.list_sources(body=Body.biped) == []


def test_settings_defaults_and_set_settings():
    store = MemoryStore()
    s = store.get_settings()
    assert s.monthly_cap_credits == 6000 and s.kill_switch is False
    assert s.cadence["biscuit"] == {"days": ["tue", "wed", "thu"], "slot": "19:00"}
    assert s.cadence["reginald"]["slot"] == "19:30"

    updated = store.set_settings(kill_switch=True, monthly_cap_credits=300)
    assert updated == Settings(
        monthly_cap_credits=300, kill_switch=True, cadence=s.cadence
    )
    assert store.get_settings().kill_switch is True
    with pytest.raises(TypeError):
        store.set_settings(nonsense=1)
    # mutating the returned settings must not leak into the store
    s.cadence["biscuit"]["slot"] = "03:00"
    assert store.get_settings().cadence["biscuit"]["slot"] == "19:00"


def test_ledger_by_month():
    store, clip, _, _ = seeded_store()
    store.ledger_add(LedgerEntry(clip_id=clip.id, month="2026-10", kind="reserve", credits=110))
    store.ledger_add(LedgerEntry(clip_id=clip.id, month="2026-10", kind="settle", credits=99))
    store.ledger_add(LedgerEntry(clip_id=clip.id, month="2026-11", kind="reserve", credits=5))
    october = store.ledger_month("2026-10")
    assert [e.kind for e in october] == ["reserve", "settle"]
    assert all(e.id and e.created_at for e in october)
    assert store.ledger_month("2026-12") == []
    with pytest.raises(ValueError):
        LedgerEntry(clip_id=clip.id, month="2026-10", kind="refund", credits=1)


def test_one_post_per_clip_and_account():
    store, clip, tiktok, _ = seeded_store()
    store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=NOW))
    with pytest.raises(DuplicatePost):
        store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=NOW))


def test_naive_datetimes_are_refused():
    store, clip, tiktok, _ = seeded_store()
    with pytest.raises(ValueError):
        Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=datetime(2026, 10, 6, 19, 0))
    with pytest.raises(ValueError):
        store.claim_due_posts(datetime(2026, 10, 6, 19, 0))


def test_update_post_and_list_posts_ordered_by_slot():
    store, clip, tiktok, insta = seeded_store()
    late = store.add_post(Post(clip_id=clip.id, account_id=insta.id, scheduled_for=NOW + timedelta(hours=2)))
    early = store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=NOW))
    assert [p.id for p in store.list_posts()] == [early.id, late.id]
    posted = store.update_post(early.id, status=PostStatus.posted, platform_post_id="tt-1", attempts=1)
    assert posted.status is PostStatus.posted and posted.attempts == 1
    assert [p.id for p in store.list_posts(account_id=insta.id)] == [late.id]


def test_snapshots_for_post_in_time_order():
    store, clip, tiktok, _ = seeded_store()
    post = store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=NOW))
    t1, t2 = NOW + timedelta(hours=6), NOW + timedelta(hours=12)
    store.add_snapshot(Snapshot(post_id=post.id, captured_at=t2, views=900, likes=40))
    store.add_snapshot(Snapshot(post_id=post.id, captured_at=t1, views=300))
    got = store.snapshots_for(post.id)
    assert [s.captured_at for s in got] == [t1, t2]
    assert got[0].likes is None  # missing metric stays None, never 0
    assert store.snapshots_for("other") == []


def test_snapshot_keeps_skip_rate_and_watched_pct_and_none_means_unreported():
    store, clip, tiktok, _ = seeded_store()
    post = store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=NOW))
    store.add_snapshot(Snapshot(post_id=post.id, captured_at=NOW, views=10, skip_rate=0.35, watched_pct=62.5))
    store.add_snapshot(Snapshot(post_id=post.id, captured_at=NOW + timedelta(hours=1), views=20))
    first, second = store.snapshots_for(post.id)
    assert (first.skip_rate, first.watched_pct) == (0.35, 62.5)
    assert second.skip_rate is None and second.watched_pct is None  # never 0


def test_update_account_changes_dropin_share_and_returns_the_updated_copy():
    store, _, tiktok, insta = seeded_store()
    got = store.update_account(insta.id, dropin_share=0.20)
    assert got.dropin_share == 0.20 and got.id == insta.id
    assert {a.id: a.dropin_share for a in store.accounts()}[insta.id] == 0.20
    assert {a.id: a.dropin_share for a in store.accounts()}[tiktok.id] == 0.70  # others untouched
    got.dropin_share = 0.99  # a returned copy cannot mutate stored state
    assert {a.id: a.dropin_share for a in store.accounts()}[insta.id] == 0.20


def test_update_account_rejects_unknown_ids_fields_and_id_changes():
    store, _, tiktok, _ = seeded_store()
    with pytest.raises(KeyError):
        store.update_account("nope", dropin_share=0.2)
    with pytest.raises(TypeError):
        store.update_account(tiktok.id, colour="red")
    with pytest.raises(ValueError):
        store.update_account(tiktok.id, id="other")
    with pytest.raises(ValueError):
        store.update_account(tiktok.id, mode="bogus")


def test_accounts_and_characters():
    store, _, tiktok, insta = seeded_store()
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    store.add_account(Account(character_slug="reginald", platform=Platform.tiktok, handle="@reg"))
    assert [c.slug for c in store.characters()] == ["biscuit", "reginald"]
    assert store.characters()[0].bodies == [Body.quadruped]
    assert {a.id for a in store.accounts("biscuit")} == {tiktok.id, insta.id}
    assert len(store.accounts()) == 3


def test_account_dropin_share_defaults_per_platform():
    assert Account(character_slug="b", platform=Platform.tiktok, handle="@x").dropin_share == 0.70
    assert Account(character_slug="b", platform="instagram", handle="x").dropin_share == 0.40
    assert Account(character_slug="b", platform="tiktok", handle="@x", dropin_share=0.2).dropin_share == 0.2
    assert Account(character_slug="b", platform="tiktok", handle="@x").mode == "approval"


def test_favorites_roundtrip():
    store = MemoryStore()
    fav = store.add_favorite(
        Favorite(
            url="https://www.tiktok.com/@x/video/1",
            platform="tiktok",
            origin="scan",
            character_slug="biscuit",
            proposal={"mode": "recreate"},
            scores={"virality": 90},
            total_score=92.0,
        )
    )
    assert fav.status == "new" and fav.id and fav.created_at is not None
    assert store.get_favorite(fav.id) == fav
    assert store.get_favorite("nope") is None
    updated = store.update_favorite(fav.id, status="approved", note="go")
    assert updated.status == "approved" and updated.note == "go"
    assert [f.id for f in store.list_favorites(status="approved")] == [fav.id]
    assert store.list_favorites(status="new") == []
    with pytest.raises(ValueError):
        Favorite(url="u", status="bogus")
    with pytest.raises(ValueError):
        Favorite(url="u", origin="bogus")


def test_transaction_is_a_usable_no_op_context_manager():
    store = MemoryStore()
    with store.transaction():
        store.set_settings(kill_switch=True)
    assert store.get_settings().kill_switch is True


def test_delete_post_removes_the_row_and_nothing_else():
    store = MemoryStore()
    clip = store.add_clip(Clip(character_slug="biscuit", mode="recreate"))
    a = store.add_post(Post(clip_id=clip.id, account_id="a1", scheduled_for=datetime(2026, 10, 6, 19, tzinfo=LONDON)))
    b = store.add_post(Post(clip_id=clip.id, account_id="a2", scheduled_for=datetime(2026, 10, 6, 19, tzinfo=LONDON)))
    store.delete_post(a.id)
    assert [p.id for p in store.list_posts()] == [b.id]
    store.add_post(Post(clip_id=clip.id, account_id="a1", scheduled_for=datetime(2026, 10, 7, 19, tzinfo=LONDON)))
    with pytest.raises(KeyError):
        store.delete_post(a.id)  # already gone
    with pytest.raises(KeyError):
        store.delete_post("nope")


def test_memory_store_implements_the_protocol():
    assert isinstance(MemoryStore(), Store)


def test_invalid_enum_values_are_rejected_at_construction():
    with pytest.raises(ValueError):
        Clip(character_slug="biscuit", mode="sideways")
    with pytest.raises(ValueError):
        Source(kind="tiktok_page", body=Body.biped, bodies=1, duration_s=1.0)


# ---- upserts (used by `studio seed`) ---------------------------------------------------------


def test_upsert_character_inserts_then_updates_in_place():
    store = MemoryStore()
    first = store.upsert_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.biped]))
    assert (first.slug, first.status, first.bodies) == ("biscuit", "designing", [Body.biped])
    again = store.upsert_character(
        Character(slug="biscuit", name="Biscuit II", status="live", bodies=["biped", "quadruped"])
    )
    assert (again.name, again.status, again.bodies) == ("Biscuit II", "live", [Body.biped, Body.quadruped])
    assert [c.slug for c in store.characters()] == ["biscuit"]  # one row, not two


def test_upsert_character_replaces_the_setup_the_seed_writes_and_returns_copies():
    store = MemoryStore()
    setup = {"closeup": False, "planned_handles": {"tiktok": "@biscuit.moves", "instagram": None}}
    store.upsert_character(Character(slug="biscuit", name="Biscuit", setup=setup))
    got = store.characters()[0]
    assert got.setup == setup
    got.setup["closeup"] = True  # a copy: the stored setup is not touched
    assert store.characters()[0].setup["closeup"] is False
    store.upsert_character(Character(slug="biscuit", name="Biscuit", setup={"closeup": True, "planned_handles": {}}))
    assert store.characters()[0].setup == {"closeup": True, "planned_handles": {}}
    assert Character(slug="x", name="X").setup == {}  # a character built without one has an empty setup


def test_a_run_keeps_its_structured_details():
    store = MemoryStore()
    details = {"scan": {"queries": ["reginald #2 hook"], "outliers": 4, "picks_added": 2, "vidiq_credits": 5}}
    store.add_run(Run(kind="daily", status="ok", summary="s", details=details))
    store.add_run(Run(kind="weekly", status="ok"))
    daily, weekly = store.list_runs(kind="daily")[0], store.list_runs(kind="weekly")[0]
    assert daily.details == details and weekly.details == {}
    daily.details["scan"]["outliers"] = 99  # a copy
    assert store.list_runs(kind="daily")[0].details["scan"]["outliers"] == 4


def test_upsert_character_returns_a_copy():
    store = MemoryStore()
    got = store.upsert_character(Character(slug="biscuit", name="Biscuit"))
    got.name = "mutated"
    assert store.characters()[0].name == "Biscuit"


def test_upsert_account_inserts_with_an_id_and_the_explicit_share():
    store = MemoryStore()
    a = store.upsert_account(
        Account(character_slug="biscuit", platform="instagram", handle="b.ig", dropin_share=0.4)
    )
    assert a.id and (a.platform, a.handle, a.dropin_share, a.mode) == (Platform.instagram, "b.ig", 0.4, "approval")


def test_upsert_account_matches_on_character_and_platform_and_keeps_operational_state():
    """Re-seeding refreshes the identity (handle, Postiz id) but never undoes what the weekly
    review's Instagram guard or the terminal's autopilot toggle set (dropin_share, mode)."""
    store = MemoryStore()
    first = store.upsert_account(Account(character_slug="biscuit", platform="instagram", handle="old"))
    store.update_account(first.id, dropin_share=0.2, mode="auto")  # the guard cut it, the owner went auto
    again = store.upsert_account(
        Account(
            character_slug="biscuit", platform="instagram", handle="new",
            postiz_integration_id="pz-1", dropin_share=0.4,
        )
    )
    assert again.id == first.id
    assert (again.handle, again.postiz_integration_id) == ("new", "pz-1")
    assert (again.dropin_share, again.mode) == (0.2, "auto")
    assert len(store.accounts("biscuit")) == 1


def test_upsert_account_keeps_other_platforms_and_characters_apart():
    store = MemoryStore()
    for slug, platform in (("biscuit", "tiktok"), ("biscuit", "instagram"), ("reginald", "tiktok")):
        store.upsert_account(Account(character_slug=slug, platform=platform, handle=f"{slug}.{platform}"))
    assert len(store.accounts()) == 3


# ---- runs and reviews -----------------------------------------------------------------------------


def test_add_run_assigns_id_and_started_at_and_lists_oldest_first():
    store = MemoryStore()
    late = store.add_run(
        Run(kind="daily", status="ok", started_at=NOW, finished_at=NOW + timedelta(minutes=5), summary="2 clips")
    )
    early = store.add_run(Run(kind="weekly", status="error", started_at=NOW - timedelta(days=1)))
    auto = store.add_run(Run(kind="publish", status="ok"))  # no started_at: the store stamps it
    assert late.id and auto.started_at is not None and auto.started_at.tzinfo is not None
    assert early.finished_at is None and early.summary is None
    assert abs(datetime.now(LONDON) - auto.started_at) < timedelta(minutes=1)
    assert [r.id for r in store.list_runs()] == [r.id for r in sorted(
        (early, late, auto), key=lambda r: r.started_at
    )]
    assert [r.id for r in store.list_runs(status="ok", kind="daily")] == [late.id]
    assert [r.id for r in store.list_runs(kind="daily")] == [late.id]
    assert [r.id for r in store.list_runs(status="error")] == [early.id]
    assert store.list_runs(kind="metrics") == []


def test_run_coerces_kind_and_status_and_refuses_bad_values():
    from studio.models import RunKind, RunStatus

    run = Run(kind="daily", status="budget_stop")
    assert (run.kind, run.status) == (RunKind.daily, RunStatus.budget_stop)
    with pytest.raises(ValueError, match="kind"):
        Run(kind="hourly", status="ok")
    with pytest.raises(ValueError, match="status"):
        Run(kind="daily", status="fine")


def test_add_run_refuses_a_naive_time_and_returns_copies():
    store = MemoryStore()
    with pytest.raises(ValueError, match="timezone-aware"):
        store.add_run(Run(kind="daily", status="ok", finished_at=datetime(2026, 10, 6, 12, 0)))
    stored = store.add_run(Run(kind="daily", status="ok", summary="a"))
    stored.summary = "mutated"
    assert store.list_runs()[0].summary == "a"
    with pytest.raises(TypeError):
        store.list_runs(nope=1)


WEEK = date(2026, 10, 5)


def test_upsert_review_inserts_then_replaces_per_week_and_character():
    store = MemoryStore()
    first = store.upsert_review(
        Review(week=WEEK, character_slug="biscuit", report_md="v1", bar_status="not_yet")
    )
    assert first.id and first.created_at is not None
    again = store.upsert_review(
        Review(week=WEEK, character_slug="biscuit", report_md="v2", bar_status="continue")
    )
    assert again.id == first.id and again.created_at == first.created_at  # same row, rewritten
    assert (again.report_md, again.bar_status) == ("v2", "continue")
    other_char = store.upsert_review(Review(week=WEEK, character_slug="reginald", report_md="r"))
    other_week = store.upsert_review(
        Review(week=WEEK + timedelta(days=7), character_slug="biscuit", report_md="w")
    )
    assert len({first.id, other_char.id, other_week.id}) == 3
    assert [(r.character_slug, r.week, r.report_md) for r in store.list_reviews()] == [
        ("biscuit", WEEK, "v2"), ("reginald", WEEK, "r"), ("biscuit", WEEK + timedelta(days=7), "w"),
    ]
    assert [r.id for r in store.list_reviews(character_slug="reginald")] == [other_char.id]
    assert store.list_reviews(week=date(2030, 1, 7)) == []


def test_review_week_must_be_a_date_and_bar_status_is_optional():
    assert Review(week=WEEK, character_slug="biscuit", report_md="x").bar_status is None
    with pytest.raises(ValueError, match="week"):
        Review(week=datetime(2026, 10, 5, 12, 0, tzinfo=LONDON), character_slug="biscuit", report_md="x")
    with pytest.raises(ValueError, match="week"):
        Review(week="2026-10-05", character_slug="biscuit", report_md="x")

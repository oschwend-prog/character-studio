import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from studio import sources
from studio.cli import app
from studio.models import Body, Character, Clip, Mode, Source, SourceKind
from studio.sources import (
    add_source,
    dropin_eligible,
    flag_dirty,
    median_outlier_x,
    rank_sources,
    record_checks,
)
from studio.store import MemoryStore

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def make_store() -> MemoryStore:
    # MemoryStore enforces no foreign keys; seed what Postgres would require.
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


def character(store: MemoryStore, slug: str) -> Character:
    return next(c for c in store.characters() if c.slug == slug)


def new_source(store, *, kind="higgsfield_library", body="biped", url="https://cdn.example.com/a.mp4"):
    return add_source(store, kind, url, body, 1, 8.0)


def clean_source(store, **kw):
    s = new_source(store, **kw)
    return record_checks(store, s.id, False, False, 0)


def made_from(store, source, *outliers, character_slug="reginald"):
    """One clip per value: its ``features['outlier_x']`` as ``studio metrics`` would write it."""
    for x in outliers:
        store.add_clip(
            Clip(
                character_slug=character_slug,
                source_id=source.id,
                mode=Mode.dropin,
                features={"outlier_x": x},
            )
        )


# ---- Drop-in eligibility ---------------------------------------------------------------


def test_unchecked_source_not_dropin_eligible():
    store = make_store()
    s = new_source(store)
    assert (s.has_watermark, s.has_overlay, s.other_people) == (None, None, None)
    assert dropin_eligible(s) is False


def test_clean_library_source_dropin_eligible():
    store = make_store()
    s = clean_source(store)
    assert (s.has_watermark, s.has_overlay, s.other_people) == (False, False, 0)
    assert dropin_eligible(s) is True
    assert dropin_eligible(clean_source(store, kind="owner_inbox", url=None)) is True


def test_synthetic_never_dropin_eligible():
    store = make_store()
    s = clean_source(store, kind="synthetic", url=None)
    assert s.kind is SourceKind.synthetic
    assert dropin_eligible(s) is False


@pytest.mark.parametrize(
    "checks",
    [(True, False, 0), (False, True, 0), (False, False, 1), (False, False, None),
     (None, False, 0), (False, None, 0)],
)
def test_any_failed_or_missing_check_blocks_dropin(checks):
    store = make_store()
    s = new_source(store)
    s = store.update_source(
        s.id, has_watermark=checks[0], has_overlay=checks[1], other_people=checks[2]
    )
    assert dropin_eligible(s) is False


def test_flag_dirty_makes_ineligible():
    store = make_store()
    s = clean_source(store)
    assert dropin_eligible(s) is True
    flagged = flag_dirty(store, s.id, "watermark visible in output frame 40")
    assert flagged.has_watermark is True
    assert (flagged.has_overlay, flagged.other_people) == (False, 0)  # nothing else touched
    assert dropin_eligible(store.list_sources(id=s.id)[0]) is False


def test_flag_dirty_requires_a_reason_and_a_known_source():
    store = make_store()
    s = clean_source(store)
    with pytest.raises(ValueError, match="reason"):
        flag_dirty(store, s.id, "   ")
    assert store.list_sources(id=s.id)[0].has_watermark is False
    with pytest.raises(KeyError):
        flag_dirty(store, "missing", "x")


def test_record_checks_stores_the_three_checks():
    store = make_store()
    s = new_source(store)
    got = record_checks(store, s.id, True, False, 2)
    assert (got.has_watermark, got.has_overlay, got.other_people) == (True, False, 2)
    with pytest.raises(ValueError, match="other_people"):
        record_checks(store, s.id, False, False, -1)
    with pytest.raises(KeyError):
        record_checks(store, "missing", False, False, 0)


# ---- add_source ------------------------------------------------------------------------


def test_add_source_records_an_unchecked_source():
    store = make_store()
    s = add_source(
        store, "higgsfield_library", "https://cdn.example.com/a.mp4", "biped", 1, 8.5,
        preset_id="p1", trend="tea tuesday", credit_handle="@creator",
    )
    assert s.id and s.created_at is not None
    assert (s.kind, s.body, s.bodies, s.duration_s) == (SourceKind.higgsfield_library, Body.biped, 1, 8.5)
    assert (s.preset_id, s.trend, s.credit_handle) == ("p1", "tea tuesday", "@creator")
    assert (s.has_watermark, s.has_overlay, s.other_people) == (None, None, None)
    assert store.list_sources() == [s]


def test_add_source_accepts_enums_and_no_url():
    store = make_store()
    s = add_source(store, SourceKind.synthetic, None, Body.quadruped, 1, 9.0)
    assert (s.kind, s.body, s.url) == (SourceKind.synthetic, Body.quadruped, None)


def test_add_source_rejects_unknown_kind():
    store = make_store()
    with pytest.raises(ValueError, match="kind"):
        add_source(store, "tiktok", None, "biped", 1, 8.0)
    assert store.list_sources() == []


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"body": "reptile"}, "body"),
        ({"bodies": 0}, "bodies"),
        ({"duration_s": 0}, "duration"),
        ({"duration_s": -3.0}, "duration"),
    ],
)
def test_add_source_rejects_bad_values(kwargs, match):
    store = make_store()
    args = {"body": "biped", "bodies": 1, "duration_s": 8.0, **kwargs}
    with pytest.raises(ValueError, match=match):
        add_source(store, "owner_inbox", None, **args)
    assert store.list_sources() == []


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@x/video/1",
        "https://tiktok.com/@x/video/1",
        "tiktok.com/@x/video/1",  # no scheme
        "HTTPS://WWW.TIKTOK.COM/@x/video/1",
        "https://vm.tiktok.com/ZMabc123/",
        "https://vt.tiktok.com/ZSabc123/",
        "https://m.tiktok.com/v/1.html",
        "https://www.instagram.com/reel/Dd9QM6WKSfJ/",
        "https://instagram.com/p/abc/",
        "https://instagr.am/p/abc/",
        "  https://www.tiktok.com/@x/video/1  ",
    ],
)
def test_platform_page_url_rejected(url):
    store = make_store()
    with pytest.raises(ValueError, match="platform page URLs are not sources"):
        add_source(store, "higgsfield_library", url, "biped", 1, 8.0)
    assert store.list_sources() == []


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.higgsfield.ai/library/abc.mp4",
        "https://nottiktok.com/clip.mp4",  # look-alike host is not a subdomain
        "https://example.com/?ref=tiktok.com",  # platform name only in the query
        "https://tiktok.com.example.org/a.mp4",
        None,
        "",
    ],
)
def test_other_urls_are_accepted(url):
    store = make_store()
    s = add_source(store, "higgsfield_library", url, "biped", 1, 8.0)
    assert s.url == (url or None)


# ---- ranking ---------------------------------------------------------------------------


def test_rank_prefers_better_performing_source():
    store = make_store()
    a = clean_source(store, url="https://cdn.example.com/a.mp4")
    b = clean_source(store, url="https://cdn.example.com/b.mp4")  # newer, but weaker
    made_from(store, a, 1.0, 2.0, 3.0)  # median 2.0
    made_from(store, b, 0.8)
    assert median_outlier_x(store, a.id) == 2.0
    assert median_outlier_x(store, b.id) == 0.8
    ranked = rank_sources(store, character(store, "reginald"), Mode.dropin, set())
    assert [s.id for s in ranked] == [a.id, b.id]


def test_rank_filters_body_type():
    store = make_store()
    biped = clean_source(store, body="biped")
    quad = clean_source(store, body="quadruped")
    reginald = rank_sources(store, character(store, "reginald"), Mode.dropin, set())
    biscuit = rank_sources(store, character(store, "biscuit"), Mode.dropin, set())
    assert [s.id for s in reginald] == [biped.id]  # quadruped source excluded for Reginald
    assert [s.id for s in biscuit] == [quad.id]


def test_rank_orders_unproven_sources_last_then_newest_first():
    store = make_store()

    def src(days_old: int, **kw) -> Source:
        s = store.add_source(
            Source(
                kind="higgsfield_library", body="biped", bodies=1, duration_s=8.0,
                has_watermark=False, has_overlay=False, other_people=0,
                created_at=T0 - timedelta(days=days_old), **kw,
            )
        )
        return s

    old_unproven, new_unproven = src(5), src(1)
    oldest_proven = src(30)
    made_from(store, oldest_proven, 0.1)
    ranked = rank_sources(store, character(store, "reginald"), Mode.dropin, set())
    assert [s.id for s in ranked] == [oldest_proven.id, new_unproven.id, old_unproven.id]


def test_rank_ties_on_performance_fall_back_to_newest_first():
    store = make_store()
    older = store.add_source(
        Source(kind="owner_inbox", body="biped", bodies=1, duration_s=8.0, has_watermark=False,
               has_overlay=False, other_people=0, created_at=T0 - timedelta(days=2))
    )
    newer = store.add_source(
        Source(kind="owner_inbox", body="biped", bodies=1, duration_s=8.0, has_watermark=False,
               has_overlay=False, other_people=0, created_at=T0)
    )
    made_from(store, older, 2.0)
    made_from(store, newer, 2.0)
    ranked = rank_sources(store, character(store, "reginald"), "dropin", set())
    assert [s.id for s in ranked] == [newer.id, older.id]


def test_rank_dropin_needs_a_clean_source_recreate_does_not():
    store = make_store()
    clean = clean_source(store)
    unchecked = new_source(store)
    dirty = flag_dirty(store, clean_source(store).id, "watermark leaked")
    synthetic = clean_source(store, kind="synthetic", url=None)
    reginald = character(store, "reginald")
    assert [s.id for s in rank_sources(store, reginald, Mode.dropin, set())] == [clean.id]
    recreate = rank_sources(store, reginald, Mode.recreate, set())
    assert {s.id for s in recreate} == {clean.id, unchecked.id, dirty.id, synthetic.id}


def test_rank_excludes_given_ids():
    store = make_store()
    a, b = clean_source(store), clean_source(store)
    got = rank_sources(store, character(store, "reginald"), Mode.dropin, {a.id})
    assert [s.id for s in got] == [b.id]


def test_rank_returns_nothing_for_a_character_without_bodies():
    store = make_store()
    clean_source(store)
    ghost = Character(slug="ghost", name="Ghost", bodies=[])
    assert rank_sources(store, ghost, Mode.recreate, set()) == []


def test_median_counts_every_clip_of_the_source_and_only_real_numbers():
    store = make_store()
    s = new_source(store)
    other = new_source(store)
    assert median_outlier_x(store, s.id) is None  # no clips at all
    made_from(store, s, None, "huge", True, float("nan"), float("inf"))
    store.add_clip(Clip(character_slug="reginald", source_id=s.id, mode=Mode.dropin))  # no features
    made_from(store, other, 99.0)  # another source's clip never leaks in
    assert median_outlier_x(store, s.id) is None  # nothing numeric yet
    made_from(store, s, 4.0, 1.0)
    assert median_outlier_x(store, s.id) == 2.5
    made_from(store, s, 7)  # ints count
    assert median_outlier_x(store, s.id) == 4.0


# ---- CLI -------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(sources, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["source", *args])


def add_args(**over):
    base = {
        "--kind": "higgsfield_library", "--url": "https://cdn.example.com/a.mp4",
        "--body": "biped", "--bodies": "1", "--duration": "8.2",
    }
    base.update(over)
    return [x for kv in base.items() for x in kv]


def test_cli_add_check_flag_roundtrip(cli_store):
    r = run("add", *add_args(**{"--trend": "tea tuesday", "--credit-handle": "@c", "--preset-id": "p9"}))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["kind"], out["body"], out["bodies"], out["duration_s"]) == ("higgsfield_library", "biped", 1, 8.2)
    assert (out["trend"], out["credit_handle"], out["preset_id"]) == ("tea tuesday", "@c", "p9")
    assert (out["has_watermark"], out["dropin_eligible"]) == (None, False)
    sid = out["id"]

    r = run("check", sid, "--no-watermark", "--no-overlay", "--other-people", "0")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["has_watermark"], out["has_overlay"], out["other_people"]) == (False, False, 0)
    assert out["dropin_eligible"] is True

    r = run("flag", sid, "--reason", "watermark in output frame 40")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["has_watermark"], out["dropin_eligible"]) == (True, False)
    assert cli_store.list_sources()[0].has_watermark is True


def test_cli_check_needs_all_three_checks(cli_store):
    sid = json.loads(run("add", *add_args()).stdout)["id"]
    assert run("check", sid, "--no-watermark", "--no-overlay").exit_code == 2
    assert run("check", sid, "--no-watermark", "--other-people", "0").exit_code == 2
    assert run("check", sid, "--no-watermark", "--no-overlay", "--other-people", "-1").exit_code == 2
    assert cli_store.list_sources()[0].has_watermark is None


def test_cli_unknown_source_exits_2(cli_store):
    r = run("check", "nope", "--no-watermark", "--no-overlay", "--other-people", "0")
    assert r.exit_code == 2 and "unknown source" in r.output
    r = run("flag", "nope", "--reason", "x")
    assert r.exit_code == 2 and "unknown source" in r.output


def test_cli_add_rejects_platform_pages_and_bad_values(cli_store):
    r = run("add", *add_args(**{"--url": "https://www.tiktok.com/@x/video/1"}))
    assert r.exit_code == 2 and "platform page URLs are not sources" in r.output
    assert run("add", *add_args(**{"--kind": "tiktok"})).exit_code == 2
    assert run("add", *add_args(**{"--body": "reptile"})).exit_code == 2
    assert run("add", *add_args(**{"--duration": "0"})).exit_code == 2
    assert run("add", *add_args(**{"--bodies": "0"})).exit_code == 2
    assert cli_store.list_sources() == []


def test_cli_flag_requires_a_reason(cli_store):
    sid = json.loads(run("add", *add_args()).stdout)["id"]
    assert run("flag", sid).exit_code == 2
    assert run("flag", sid, "--reason", " ").exit_code == 2


def test_cli_list_all_and_dropin_eligible_only(cli_store):
    clean = clean_source(cli_store)
    new_source(cli_store)
    r = run("list")
    assert r.exit_code == 0
    rows = json.loads(r.stdout)
    assert len(rows) == 2 and {x["dropin_eligible"] for x in rows} == {True, False}
    r = run("list", "--dropin-eligible")
    assert [x["id"] for x in json.loads(r.stdout)] == [clean.id]


def test_cli_list_rank_orders_by_performance_and_shows_the_median(cli_store):
    weak = clean_source(cli_store)
    strong = clean_source(cli_store)
    clean_source(cli_store, body="quadruped")  # wrong body for Reginald
    made_from(cli_store, strong, 5.0)
    made_from(cli_store, weak, 0.5)
    r = run("list", "--rank", "--character", "reginald", "--mode", "dropin")
    assert r.exit_code == 0, r.output
    rows = json.loads(r.stdout)
    assert [x["id"] for x in rows] == [strong.id, weak.id]
    assert [x["median_outlier_x"] for x in rows] == [5.0, 0.5]
    r = run("list", "--rank", "--character", "reginald", "--mode", "dropin", "--exclude", strong.id)
    assert [x["id"] for x in json.loads(r.stdout)] == [weak.id]


def test_cli_list_rank_needs_character_and_mode_and_a_known_character(cli_store):
    assert run("list", "--rank").exit_code == 2
    assert run("list", "--rank", "--character", "reginald").exit_code == 2
    assert run("list", "--rank", "--mode", "dropin").exit_code == 2
    r = run("list", "--rank", "--character", "ghost", "--mode", "dropin")
    assert r.exit_code == 2 and "unknown character" in r.output
    assert run("list", "--rank", "--character", "reginald", "--mode", "teleport").exit_code == 2


def test_cli_without_database_url_prints_a_clear_error_and_exits_2(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for args in (["list"], ["add", *add_args()], ["flag", "x", "--reason", "y"]):
        r = run(*args)
        assert r.exit_code == 2, args
        assert "DATABASE_URL" in r.output


def test_cli_source_group_is_the_modules_own_app():
    groups = [g for g in app.registered_groups if g.name == "source"]
    assert len(groups) == 1 and groups[0].typer_instance is sources.app
    r = CliRunner().invoke(app, ["source", "--help"])
    assert r.exit_code == 0
    for cmd in ("add", "check", "flag", "list"):
        assert cmd in r.output

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from studio.media.qa import probe
from typer.testing import CliRunner

from studio import sources
from studio.cli import app
from studio.models import Body, Character, Clip, Mode, Source, SourceKind
from studio.sources import (
    DEFAULT_INBOX,
    IngestError,
    add_source,
    dropin_eligible,
    flag_dirty,
    ingest_inbox,
    median_outlier_x,
    rank_sources,
    record_checks,
    signed_source_url,
)
from studio.storage import LocalStorage, StorageError
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
    return record_checks(store, s.id, False, False, 0, False)


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
    assert (s.has_watermark, s.has_overlay, s.other_people, s.has_minors) == (None, None, None, None)
    assert dropin_eligible(s) is False


def test_clean_library_source_dropin_eligible():
    store = make_store()
    s = clean_source(store)
    assert (s.has_watermark, s.has_overlay, s.other_people, s.has_minors) == (False, False, 0, False)
    assert dropin_eligible(s) is True
    assert dropin_eligible(clean_source(store, kind="owner_inbox", url=None)) is True


def test_synthetic_never_dropin_eligible():
    store = make_store()
    s = clean_source(store, kind="synthetic", url=None)
    assert s.kind is SourceKind.synthetic
    assert dropin_eligible(s) is False


@pytest.mark.parametrize(
    "checks",  # (has_watermark, has_overlay, has_minors)
    [(True, False, False), (False, True, False), (False, False, True),
     (None, False, False), (False, None, False), (False, False, None)],
)
def test_any_failed_or_missing_blocking_check_blocks_dropin(checks):
    store = make_store()
    s = new_source(store)
    s = store.update_source(
        s.id, has_watermark=checks[0], has_overlay=checks[1], other_people=0, has_minors=checks[2]
    )
    assert dropin_eligible(s) is False


@pytest.mark.parametrize("background", [0, 1, 3, None])
def test_people_in_the_background_no_longer_block_a_dropin(background):
    """Owner decision 2026-10-05: other people are recorded and shown, but only watermark, overlay and children block."""
    store = make_store()
    s = new_source(store)
    s = store.update_source(
        s.id, has_watermark=False, has_overlay=False, other_people=background, has_minors=False
    )
    assert s.other_people == background
    assert dropin_eligible(s) is True


def test_a_child_in_the_clip_blocks_a_dropin_however_clean_the_rest_is():
    store = make_store()
    s = record_checks(store, new_source(store).id, False, False, 0, True)
    assert s.has_minors is True and dropin_eligible(s) is False


def test_a_source_whose_minors_check_was_never_run_is_not_eligible():
    """A source checked before migration 0008 has has_minors NULL: it is not eligible until it is looked at again."""
    store = make_store()
    s = store.update_source(
        new_source(store).id, has_watermark=False, has_overlay=False, other_people=0
    )
    assert s.has_minors is None
    assert dropin_eligible(s) is False
    assert rank_sources(store, character(store, "reginald"), Mode.dropin, set()) == []
    assert [x.id for x in rank_sources(store, character(store, "reginald"), Mode.recreate, set())] == [s.id]


def test_flag_dirty_makes_ineligible():
    store = make_store()
    s = clean_source(store)
    assert dropin_eligible(s) is True
    flagged = flag_dirty(store, s.id, "watermark visible in output frame 40")
    assert flagged.has_watermark is True
    assert (flagged.has_overlay, flagged.other_people, flagged.has_minors) == (False, 0, False)  # nothing else touched
    assert dropin_eligible(store.list_sources(id=s.id)[0]) is False


def test_flag_dirty_requires_a_reason_and_a_known_source():
    store = make_store()
    s = clean_source(store)
    with pytest.raises(ValueError, match="reason"):
        flag_dirty(store, s.id, "   ")
    assert store.list_sources(id=s.id)[0].has_watermark is False
    with pytest.raises(KeyError):
        flag_dirty(store, "missing", "x")


def test_record_checks_stores_the_four_checks():
    store = make_store()
    s = new_source(store)
    got = record_checks(store, s.id, True, False, 2, False)
    assert (got.has_watermark, got.has_overlay, got.other_people, got.has_minors) == (True, False, 2, False)
    with pytest.raises(ValueError, match="other_people"):
        record_checks(store, s.id, False, False, -1, False)
    with pytest.raises(KeyError):
        record_checks(store, "missing", False, False, 0, False)


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
    assert (s.has_watermark, s.has_overlay, s.other_people, s.has_minors) == (None, None, None, None)
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
                has_watermark=False, has_overlay=False, other_people=0, has_minors=False,
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
               has_overlay=False, other_people=0, has_minors=False, created_at=T0 - timedelta(days=2))
    )
    newer = store.add_source(
        Source(kind="owner_inbox", body="biped", bodies=1, duration_s=8.0, has_watermark=False,
               has_overlay=False, other_people=0, has_minors=False, created_at=T0)
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


def test_rank_reads_everything_inside_one_transaction():
    # PostgresStore opens a connection per call outside transaction(); ranking makes one clip read
    # per candidate source, so it must share a single connection.
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

        def list_clips(self, **filters):
            events.append("list_clips")
            return super().list_clips(**filters)

    store = Spy()
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    for _ in range(3):
        clean_source(store)
    events.clear()
    rank_sources(store, character(store, "reginald"), Mode.dropin, set())
    assert events == ["begin", "list_clips", "list_clips", "list_clips", "end"]


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

    r = run("check", sid, "--no-watermark", "--no-overlay", "--other-people", "0", "--no-minors")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["has_watermark"], out["has_overlay"], out["other_people"], out["has_minors"]) == (False, False, 0, False)
    assert out["dropin_eligible"] is True

    r = run("flag", sid, "--reason", "watermark in output frame 40")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["has_watermark"], out["dropin_eligible"]) == (True, False)
    assert cli_store.list_sources()[0].has_watermark is True


def test_cli_add_reads_the_trend_from_a_file_never_inline(cli_store, tmp_path):
    """Trend names come from a third-party creator: free text goes in a file, not on the shell line."""
    nasty = "tea $(rm -rf ~) `id` \"quoted\" 'single'; & | > x"
    f = tmp_path / "trend.txt"
    f.write_text(nasty + "\n", encoding="utf-8")
    r = run("add", *add_args(**{"--trend-file": str(f)}))
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["trend"] == nasty  # exactly one trailing newline dropped
    assert cli_store.list_sources()[0].trend == nasty
    assert "--trend-file" in run("add", "--help").output


def test_cli_add_trend_and_trend_file_together_is_an_error(cli_store, tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("x", encoding="utf-8")
    r = run("add", *add_args(**{"--trend": "a", "--trend-file": str(f)}))
    assert r.exit_code == 2 and "not both" in r.output and cli_store.list_sources() == []


def test_cli_add_trend_file_missing_is_a_caller_error(cli_store, tmp_path):
    r = run("add", *add_args(**{"--trend-file": str(tmp_path / "nope.txt")}))
    assert r.exit_code == 2 and "no such file" in r.output and cli_store.list_sources() == []


@pytest.mark.parametrize(
    "url",
    [
        "https://v16-webapp.tiktokcdn.com/abc/video.mp4",
        "https://v19.tiktokv.com/abc/video.mp4",
        "https://scontent.cdninstagram.com/v/t50/clip.mp4",
        "https://video-lhr8-1.xx.fbcdn.net/o1/v/t2/clip.mp4",
        "https://tiktokcdn.com/x.mp4",
        "scontent-lhr.cdninstagram.com/clip.mp4",
    ],
)
def test_the_platform_cdn_hosts_are_platform_pages_too(url):
    assert sources.is_platform_page(url) is True


def test_a_host_that_only_ends_like_a_platform_domain_is_not_one():
    assert sources.is_platform_page("https://notfbcdn.net/x.mp4") is False
    assert sources.is_platform_page("https://cdn.example.com/a.mp4") is False


def test_cli_add_refuses_a_platform_cdn_url(cli_store):
    r = run("add", *add_args(**{"--url": "https://v16-webapp.tiktokcdn.com/abc/video.mp4"}))
    assert r.exit_code == 2 and cli_store.list_sources() == []


def test_cli_check_needs_all_four_checks(cli_store):
    sid = json.loads(run("add", *add_args()).stdout)["id"]
    assert run("check", sid, "--no-watermark", "--no-overlay", "--no-minors").exit_code == 2  # no --other-people
    assert run("check", sid, "--no-watermark", "--other-people", "0", "--no-minors").exit_code == 2  # no overlay
    assert run("check", sid, "--no-watermark", "--no-overlay", "--other-people", "0").exit_code == 2  # no child answer
    assert run("check", sid, "--no-watermark", "--no-overlay", "--other-people", "-1", "--no-minors").exit_code == 2
    assert cli_store.list_sources()[0].has_watermark is None


def test_cli_check_records_a_child_and_background_people_with_the_verdict(cli_store):
    sid = json.loads(run("add", *add_args()).stdout)["id"]
    out = json.loads(run("check", sid, "--no-watermark", "--no-overlay", "--other-people", "4", "--no-minors").stdout)
    assert (out["other_people"], out["has_minors"], out["dropin_eligible"]) == (4, False, True)  # a crowd behind him is fine
    out = json.loads(run("check", sid, "--no-watermark", "--no-overlay", "--other-people", "0", "--minors").stdout)
    assert (out["has_minors"], out["dropin_eligible"]) == (True, False)
    assert "--minors" in run("check", "--help").output and "--no-minors" in run("check", "--help").output


def test_cli_unknown_source_exits_2(cli_store):
    r = run("check", "nope", "--no-watermark", "--no-overlay", "--other-people", "0", "--no-minors")
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


# ---- inbox ingest ------------------------------------------------------------------------------


@pytest.fixture
def clip_file(synth_video):
    """A small real 5 s video (the session-cached synthetic one: copy it, never edit it)."""
    return synth_video(w=320, h=568, dur=5, audio=False)


def drop(inbox: Path, clip: Path, name: str) -> Path:
    inbox.mkdir(exist_ok=True)
    return Path(shutil.copyfile(clip, inbox / name))


def fetch(storage: LocalStorage, tmp_path: Path, path: str) -> bytes:
    return storage.download("sources", path, tmp_path / "fetched.bin").read_bytes()


def test_add_source_can_carry_a_storage_path():
    store = make_store()
    s = add_source(store, "owner_inbox", "owner_inbox/x.mp4", "biped", 1, 8.0, storage_path="owner_inbox/x.mp4")
    assert (s.url, s.storage_path) == ("owner_inbox/x.mp4", "owner_inbox/x.mp4")
    assert new_source(store).storage_path is None  # default unchanged


def test_ingest_inbox_uploads_records_and_moves(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    inbox = tmp_path / "inbox"
    drop(inbox, clip_file, "dance.mp4")

    made = ingest_inbox(store, storage, inbox)

    assert len(made) == 1
    s = made[0]
    assert s.id and store.list_sources() == [s]
    assert s.kind is SourceKind.owner_inbox
    assert s.body is Body.biped and s.bodies == 1
    assert s.duration_s == pytest.approx(5.0, abs=0.1)
    # url is the storage path, never a platform URL; storage_path says the same for the downloader
    assert s.url == s.storage_path
    assert s.url.startswith("owner_inbox/") and s.url.endswith(".mp4")
    assert Path(s.url).stem and "://" not in s.url
    # unchecked: not Drop-in eligible until Claude has looked at it
    assert (s.has_watermark, s.has_overlay, s.other_people) == (None, None, None)
    assert dropin_eligible(s) is False
    # the object is in the bucket, byte for byte
    assert fetch(storage, tmp_path, s.url) == clip_file.read_bytes()
    # the file left the inbox for done/
    assert not (inbox / "dance.mp4").exists()
    assert (inbox / "done" / "dance.mp4").read_bytes() == clip_file.read_bytes()


def test_ingest_gives_every_file_its_own_storage_name(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    inbox = tmp_path / "inbox"
    drop(inbox, clip_file, "a.mp4")
    drop(inbox, clip_file, "b.MOV")
    drop(inbox, clip_file, "c.webm")

    made = ingest_inbox(store, storage, inbox)

    assert len(made) == 3 and len({s.url for s in made}) == 3
    assert sorted(Path(s.url).suffix for s in made) == [".mov", ".mp4", ".webm"]  # lower-cased
    assert sorted(p.name for p in (inbox / "done").iterdir()) == ["a.mp4", "b.MOV", "c.webm"]
    assert len(store.list_sources()) == 3


def test_ingest_ignores_non_video_and_done(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    inbox = tmp_path / "inbox"
    (inbox / "done").mkdir(parents=True)
    drop(inbox / "done", clip_file, "old.mp4")  # already ingested earlier
    (inbox / "notes.txt").write_text("not a video")
    (inbox / "cover.png").write_bytes(b"\x89PNG")
    (inbox / ".DS_Store").write_bytes(b"x")
    (inbox / "._dance.mp4").write_bytes(b"AppleDouble sidecar, not a video")
    (inbox / "folder.mp4").mkdir()  # a directory with a video-looking name
    kept = drop(inbox, clip_file, "keep.mp4")
    for ignored in ("notes.txt", "cover.png", ".DS_Store", "._dance.mp4"):
        assert (inbox / ignored).exists()

    made = ingest_inbox(store, storage, inbox)

    assert len(made) == 1 and len(store.list_sources()) == 1
    assert not kept.exists() and (inbox / "done" / "keep.mp4").exists()
    assert (inbox / "done" / "old.mp4").exists()  # untouched
    for ignored in ("notes.txt", "cover.png", ".DS_Store", "._dance.mp4", "folder.mp4"):
        assert (inbox / ignored).exists(), ignored
    assert [p.name for p in (tmp_path / "store" / "sources" / "owner_inbox").iterdir()] == [
        Path(made[0].url).name
    ]


def test_ingest_is_idempotent(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    inbox = tmp_path / "inbox"
    drop(inbox, clip_file, "dance.mp4")
    assert len(ingest_inbox(store, storage, inbox)) == 1
    assert ingest_inbox(store, storage, inbox) == []
    assert len(store.list_sources()) == 1


def test_ingest_missing_or_empty_inbox_is_a_no_op(tmp_path):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    assert ingest_inbox(store, storage, tmp_path / "no-such-inbox") == []
    (tmp_path / "inbox").mkdir()
    assert ingest_inbox(store, storage, tmp_path / "inbox") == []
    assert store.list_sources() == []


def test_ingest_never_overwrites_a_file_already_in_done(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    inbox = tmp_path / "inbox"
    for _ in range(3):  # the owner drops "dance.mp4" again and again
        drop(inbox, clip_file, "dance.mp4")
        assert len(ingest_inbox(store, storage, inbox)) == 1
    done = sorted(p.name for p in (inbox / "done").iterdir())
    assert done == ["dance-2.mp4", "dance-3.mp4", "dance.mp4"]
    assert len(store.list_sources()) == 3


def test_ingest_leaves_an_unreadable_video_in_place_and_reports_it(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    inbox = tmp_path / "inbox"
    drop(inbox, clip_file, "a_good.mp4")
    (inbox / "b_corrupt.mp4").write_bytes(b"this is not a video at all")
    drop(inbox, clip_file, "c_good.mp4")

    with pytest.raises(IngestError) as exc:
        ingest_inbox(store, storage, inbox)

    err = exc.value
    assert [Path(s.url).suffix for s in err.ingested] == [".mp4", ".mp4"]  # the good ones went through
    assert len(store.list_sources()) == 2
    assert len(err.problems) == 1 and err.problems[0].startswith("b_corrupt.mp4:")
    assert "b_corrupt.mp4" in str(err)
    assert (inbox / "b_corrupt.mp4").exists()  # the owner sees what is left to fix
    assert not (inbox / "a_good.mp4").exists() and not (inbox / "c_good.mp4").exists()
    assert len(list((tmp_path / "store" / "sources" / "owner_inbox").iterdir())) == 2  # nothing orphaned


def test_ingest_storage_failure_leaves_file_and_creates_no_source(tmp_path, clip_file):
    class Refusing(LocalStorage):
        def upload(self, bucket, path, file):
            raise StorageError("storage POST sources/x failed: HTTP 413: too big", 413)

    store = make_store()
    inbox = tmp_path / "inbox"
    drop(inbox, clip_file, "big.mp4")

    with pytest.raises(IngestError) as exc:
        ingest_inbox(store, Refusing(tmp_path / "store"), inbox)

    assert exc.value.ingested == [] and "413" in exc.value.problems[0]
    assert store.list_sources() == []  # no row pointing at nothing
    assert (inbox / "big.mp4").exists() and not (inbox / "done").exists()


def test_ingest_probes_before_uploading(tmp_path):
    class Spy(LocalStorage):
        calls = 0

        def upload(self, bucket, path, file):
            Spy.calls += 1
            return super().upload(bucket, path, file)

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "fake.mov").write_bytes(b"nope")
    with pytest.raises(IngestError):
        ingest_inbox(make_store(), Spy(tmp_path / "store"), inbox)
    assert Spy.calls == 0


# ---- CLI: source ingest-inbox ------------------------------------------------------------------


@pytest.fixture
def cli_storage(monkeypatch, tmp_path):
    storage = LocalStorage(tmp_path / "store")
    monkeypatch.setattr(sources, "open_storage", lambda: storage)
    return storage


def test_cli_ingest_inbox_prints_the_new_sources_as_json(cli_store, cli_storage, tmp_path, clip_file):
    inbox = tmp_path / "inbox"
    drop(inbox, clip_file, "dance.mp4")

    r = run("ingest-inbox", "--inbox", str(inbox))

    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert len(out) == 1
    assert out[0]["kind"] == "owner_inbox" and out[0]["dropin_eligible"] is False
    assert out[0]["url"] == out[0]["storage_path"] and out[0]["url"].startswith("owner_inbox/")
    assert [s.id for s in cli_store.list_sources()] == [out[0]["id"]]
    assert (inbox / "done" / "dance.mp4").exists()
    assert json.loads(run("ingest-inbox", "--inbox", str(inbox)).stdout) == []  # nothing left


def test_cli_ingest_inbox_reports_problems_on_stderr_and_exits_2(cli_store, cli_storage, tmp_path, clip_file):
    inbox = tmp_path / "inbox"
    drop(inbox, clip_file, "good.mp4")
    (inbox / "bad.mp4").write_bytes(b"junk")

    r = run("ingest-inbox", "--inbox", str(inbox))

    assert r.exit_code == 2
    assert len(json.loads(r.stdout)) == 1  # stdout is still the list of what did go in
    assert "error: bad.mp4" in r.stderr
    assert (inbox / "bad.mp4").exists()


def test_cli_ingest_inbox_default_folder_is_the_repo_inbox_not_cwd(
    cli_store, cli_storage, tmp_path, monkeypatch, clip_file
):
    assert Path(sources.__file__).resolve().parents[1] / "inbox" == DEFAULT_INBOX
    assert DEFAULT_INBOX.name == "inbox" and (DEFAULT_INBOX.parent / "pyproject.toml").is_file()
    seen = []
    monkeypatch.setattr(sources, "ingest_inbox", lambda store, storage, folder: seen.append(folder) or [])
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    r = run("ingest-inbox")
    assert r.exit_code == 0, r.output
    assert seen == [DEFAULT_INBOX]
    assert json.loads(r.stdout) == []


def test_cli_ingest_inbox_explicit_missing_folder_exits_2(cli_store, cli_storage, tmp_path):
    r = run("ingest-inbox", "--inbox", str(tmp_path / "typo"))
    assert r.exit_code == 2 and "no such folder" in r.output


def test_cli_ingest_inbox_without_supabase_env_exits_2_and_names_the_variables(
    cli_store, monkeypatch, tmp_path
):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb-service-key-DO-NOT-LEAK")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    r = run("ingest-inbox", "--inbox", str(inbox))
    assert r.exit_code == 2
    assert "SUPABASE_URL" in r.output
    assert "DO-NOT-LEAK" not in r.output


def test_cli_ingest_inbox_without_database_url_exits_2(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = run("ingest-inbox")
    assert r.exit_code == 2 and "DATABASE_URL" in r.output


def test_cli_source_help_lists_ingest_inbox():
    r = CliRunner().invoke(app, ["source", "--help"])
    assert r.exit_code == 0 and "ingest-inbox" in r.output


def test_cli_flag_reason_from_a_file(cli_store, tmp_path):
    src = run("add", "--kind", "synthetic", "--body", "biped", "--bodies", "1", "--duration", "9")
    sid = json.loads(src.stdout)["id"]
    f = tmp_path / "why.txt"
    nasty = "it's $(echo pwned) `x` \"q\" ; && | >"
    f.write_text(nasty + "\n", encoding="utf-8")
    r = run("flag", sid, "--reason-file", str(f))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["flag_reason"] == nasty and out["has_watermark"] is True
    r = run("flag", sid, "--reason", "x", "--reason-file", str(f))
    assert r.exit_code == 2 and "--reason" in r.output
    assert run("flag", sid).exit_code == 2  # neither


# ---- signed URL for a source in Storage (Higgsfield media_import_url) -----------------------------


class RecordingStorage:
    """A Storage that only records the sign request and returns a recognisable URL."""

    def __init__(self):
        self.calls: list[tuple[str, str, int]] = []

    def signed_url(self, bucket, path, expires_s=86_400):
        self.calls.append((bucket, path, expires_s))
        return f"https://signed.example/{bucket}/{path}?token=t&exp={expires_s}"


def inbox_source(store, path="owner_inbox/abc.mp4"):
    return add_source(store, "owner_inbox", path, "biped", 1, 8.0, storage_path=path)


def test_signed_source_url_signs_the_storage_path_in_the_sources_bucket():
    store, storage = make_store(), RecordingStorage()
    src = inbox_source(store)
    url = signed_source_url(store, storage, src.id)
    assert storage.calls == [("sources", "owner_inbox/abc.mp4", 3600)]  # default: one hour
    assert url == "https://signed.example/sources/owner_inbox/abc.mp4?token=t&exp=3600"
    signed_source_url(store, storage, src.id, 120)
    assert storage.calls[-1][2] == 120


def test_signed_source_url_with_local_storage_points_at_the_stored_file(tmp_path):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    storage.upload("sources", "owner_inbox/abc.mp4", media)
    src = inbox_source(store)
    assert signed_source_url(store, storage, src.id) == (tmp_path / "store" / "sources" / "owner_inbox" / "abc.mp4").resolve().as_uri()


def test_signed_source_url_refuses_unknown_sources_and_sources_not_in_storage(tmp_path):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    with pytest.raises(KeyError):
        signed_source_url(store, storage, "nope")
    library = new_source(store)  # a Higgsfield library source: a CDN url, nothing in Storage
    with pytest.raises(ValueError, match="storage_path"):
        signed_source_url(store, storage, library.id)
    missing = inbox_source(store, "owner_inbox/gone.mp4")  # catalogued but the object is not there
    with pytest.raises(StorageError) as e:
        signed_source_url(store, storage, missing.id)
    assert e.value.status == 404
    present = tmp_path / "x.mp4"
    present.write_bytes(b"x")
    storage.upload("sources", "owner_inbox/abc.mp4", present)
    with pytest.raises(ValueError, match="expires"):
        signed_source_url(store, storage, inbox_source(store).id, 0)


@pytest.fixture
def signing(cli_store, monkeypatch):
    storage = RecordingStorage()
    monkeypatch.setattr(sources, "open_storage", lambda: storage)
    return cli_store, storage


def test_cli_source_url_prints_just_the_url(signing):
    store, storage = signing
    src = inbox_source(store)
    r = run("url", src.id)
    assert r.exit_code == 0, r.output
    assert r.stdout == "https://signed.example/sources/owner_inbox/abc.mp4?token=t&exp=3600\n"  # one line, nothing else
    assert storage.calls == [("sources", "owner_inbox/abc.mp4", 3600)]
    r = run("url", src.id, "--expires", "120")
    assert r.exit_code == 0 and r.stdout.strip().endswith("exp=120")


def test_cli_source_url_refusals_exit_2(signing):
    store, storage = signing
    assert run("url", "nope").exit_code == 2
    library = new_source(store)
    r = run("url", library.id)
    assert r.exit_code == 2 and "storage_path" in r.output
    src = inbox_source(store)
    assert run("url", src.id, "--expires", "0").exit_code == 2
    assert storage.calls == []


def test_cli_source_url_turns_a_storage_failure_into_exit_2(cli_store, monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "open_storage", lambda: LocalStorage(tmp_path / "empty"))
    src = inbox_source(cli_store)
    r = run("url", src.id)
    assert r.exit_code == 2 and "not found" in r.output


def test_cli_source_url_without_supabase_env_exits_2_and_names_the_variables(cli_store, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb-service-key-DO-NOT-LEAK")
    src = inbox_source(cli_store)
    r = run("url", src.id)
    assert r.exit_code == 2 and "SUPABASE_URL" in r.output and "DO-NOT-LEAK" not in r.output


def test_cli_source_help_lists_url():
    r = CliRunner().invoke(app, ["source", "--help"])
    assert r.exit_code == 0 and " url" in r.output


# ---- the owner's own clip for a pick (Make-it "Attach clip": uploaded from the phone to our Storage) ---------------


def owner_pick(store, storage, clip_file, *, creator="@eatfryhaven", attach=True, name="1759660000000.mp4"):
    """A pick as the terminal leaves it: the browser uploaded the file, ``attach_clip`` stored the path."""
    from studio.models import Favorite

    f = store.add_favorite(Favorite(
        url="https://www.instagram.com/reel/Dde-rPWCOC6/", platform="instagram", creator_handle=creator,
        status="approved", character_slug="reginald", proposal={"mode": "dropin"},
    ))
    path = f"owner/{f.id}/{name}"
    storage.upload("sources", path, clip_file)
    if attach:
        f = store.update_favorite(f.id, proposal={**f.proposal, "owner_clip_path": path})
    return f, path


def test_ingest_owner_clip_catalogues_the_attached_file_and_links_the_pick(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    pick, path = owner_pick(store, storage, clip_file)

    s = sources.ingest_owner_clip(store, storage, pick.id)

    assert s.kind is SourceKind.owner_inbox and (s.body, s.bodies) == (Body.biped, 1)
    assert s.storage_path == path and s.url == path  # the bucket path, never a platform URL
    assert s.credit_handle == "@eatfryhaven"  # the pick's creator, credited in the caption
    assert s.duration_s == pytest.approx(5.0, abs=0.1)
    assert (s.has_watermark, s.has_overlay, s.has_minors) == (None, None, None) and dropin_eligible(s) is False  # looked at next
    assert store.get_favorite(pick.id).source_id == s.id
    assert fetch(storage, tmp_path, s.storage_path) == clip_file.read_bytes()  # still there, nothing moved


def test_ingest_owner_clip_is_idempotent(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    pick, _ = owner_pick(store, storage, clip_file)
    first = sources.ingest_owner_clip(store, storage, pick.id)
    again = sources.ingest_owner_clip(store, storage, pick.id)
    assert again.id == first.id and len(store.list_sources()) == 1
    store.update_source(first.id, has_watermark=False)  # what the visual check recorded must survive another call
    assert sources.ingest_owner_clip(store, storage, pick.id).has_watermark is False


def test_a_sibling_pick_for_the_other_character_reuses_the_same_source(tmp_path, clip_file):
    """"Both" files a copy of the pick that carries the same owner_clip_path: one file, one source row."""
    from studio.models import Favorite

    store, storage = make_store(), LocalStorage(tmp_path / "store")
    pick, path = owner_pick(store, storage, clip_file)
    twin = store.add_favorite(Favorite(
        url=pick.url, platform="instagram", creator_handle=pick.creator_handle, status="approved",
        character_slug="biscuit", proposal=dict(pick.proposal),
    ))
    a, b = sources.ingest_owner_clip(store, storage, pick.id), sources.ingest_owner_clip(store, storage, twin.id)
    assert a.id == b.id and len(store.list_sources()) == 1
    assert store.get_favorite(twin.id).source_id == a.id


def test_ingest_owner_clip_refuses_a_pick_without_an_attached_clip_and_an_unknown_pick(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    pick, _ = owner_pick(store, storage, clip_file, attach=False)
    with pytest.raises(ValueError, match="no clip attached"):
        sources.ingest_owner_clip(store, storage, pick.id)
    with pytest.raises(KeyError):
        sources.ingest_owner_clip(store, storage, "missing")
    assert store.list_sources() == []


@pytest.mark.parametrize(
    "path",
    [
        "inbox/clip.mp4", "owner/clip.mp4", "owner/not-a-uuid/clip.mp4", "owner/../x/clip.mp4",
        "owner/12345678-1234-1234-1234-123456789abc/a/b.mp4", "https://www.tiktok.com/@x/video/1", "",
    ],
)
def test_ingest_owner_clip_only_takes_a_path_the_terminal_could_have_written(tmp_path, clip_file, path):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    pick, _ = owner_pick(store, storage, clip_file)
    store.update_favorite(pick.id, proposal={**pick.proposal, "owner_clip_path": path})
    with pytest.raises(ValueError, match="owner_clip_path|no clip attached"):
        sources.ingest_owner_clip(store, storage, pick.id)
    assert store.list_sources() == []


def test_ingest_owner_clip_reports_a_missing_object_and_a_file_that_is_not_a_video(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    pick, path = owner_pick(store, storage, clip_file)
    store.update_favorite(pick.id, proposal={**pick.proposal, "owner_clip_path": path.replace(".mp4", ".mov")})
    with pytest.raises(StorageError):
        sources.ingest_owner_clip(store, storage, pick.id)

    junk = tmp_path / "junk.mp4"
    junk.write_text("not a video")
    pick2, _ = owner_pick(store, storage, junk, name="2.mp4")
    with pytest.raises(ValueError, match="not a readable video"):
        sources.ingest_owner_clip(store, storage, pick2.id)
    assert store.list_sources() == []


def test_ingest_owner_clip_refuses_a_clip_longer_than_the_sheet_allows(tmp_path, clip_file, monkeypatch):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    pick, _ = owner_pick(store, storage, clip_file)
    long = type("R", (), {"duration_s": 75.0})()
    monkeypatch.setattr(sources, "probe", lambda *a, **k: long)
    with pytest.raises(ValueError, match="60"):
        sources.ingest_owner_clip(store, storage, pick.id)


def test_cli_ingest_owner_prints_the_source_and_links_the_pick(cli_store, cli_storage, clip_file):
    pick, path = owner_pick(cli_store, cli_storage, clip_file)
    r = run("ingest-owner", "--pick", pick.id)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["kind"], out["storage_path"], out["credit_handle"], out["pick_id"]) == ("owner_inbox", path, "@eatfryhaven", pick.id)
    assert out["dropin_eligible"] is False
    assert cli_store.get_favorite(pick.id).source_id == out["id"]
    assert json.loads(run("ingest-owner", "--pick", pick.id).stdout)["id"] == out["id"]  # idempotent through the CLI too


def test_cli_ingest_owner_takes_the_body_of_the_performer(cli_store, cli_storage, clip_file):
    pick, _ = owner_pick(cli_store, cli_storage, clip_file)
    out = json.loads(run("ingest-owner", "--pick", pick.id, "--body", "quadruped", "--bodies", "2").stdout)
    assert (out["body"], out["bodies"]) == ("quadruped", 2)


def test_cli_ingest_owner_exit_codes(cli_store, cli_storage, clip_file):
    assert run("ingest-owner", "--pick", "nope").exit_code == 2
    pick, _ = owner_pick(cli_store, cli_storage, clip_file, attach=False)
    r = run("ingest-owner", "--pick", pick.id)
    assert r.exit_code == 2 and "no clip attached" in r.output
    assert run("ingest-owner").exit_code == 2  # --pick is required
    assert "ingest-owner" in run("--help").output


# ---- trim a catalogued source to its best window (Genjutsu is paid per second) -----------------------------------


def stored_source(store, storage, clip_file):
    key = "owner_inbox/aaaaaaaa-0000-4000-8000-000000000001.mp4"
    storage.upload("sources", key, clip_file)
    return add_source(
        store, "owner_inbox", key, "biped", 1, 5.0, preset_id="p7", trend="tea tuesday", credit_handle="@eatfryhaven", storage_path=key
    )


def test_trim_source_makes_a_child_source_of_the_window_and_leaves_the_parent_alone(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    parent = record_checks(store, stored_source(store, storage, clip_file).id, False, False, 2, False)

    child = sources.trim_source(store, storage, parent.id, 1.0, 3.0)

    assert child.id != parent.id and len(store.list_sources()) == 2
    assert child.kind is SourceKind.owner_inbox and child.storage_path == child.url and child.storage_path.startswith("owner_inbox/")
    assert child.storage_path != parent.storage_path and child.storage_path.endswith(".mp4")
    assert child.duration_s == pytest.approx(3.0, abs=0.25)
    # what was looked at on the whole clip is true of its window: the child inherits the checks, the credit and the tags
    assert (child.has_watermark, child.has_overlay, child.other_people, child.has_minors) == (False, False, 2, False)
    assert (child.credit_handle, child.preset_id, child.trend, child.body, child.bodies) == ("@eatfryhaven", "p7", "tea tuesday", Body.biped, 1)
    assert dropin_eligible(child) is True
    assert fetch(storage, tmp_path, child.storage_path)[:4] != b""  # the window is really in the bucket
    assert store.list_sources(id=parent.id)[0] == parent  # untouched
    assert fetch(storage, tmp_path, parent.storage_path) == clip_file.read_bytes()


def test_trim_source_of_an_unchecked_parent_is_unchecked(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    parent = stored_source(store, storage, clip_file)
    child = sources.trim_source(store, storage, parent.id, 0.0, 2.0)
    assert (child.has_watermark, child.has_minors) == (None, None) and dropin_eligible(child) is False


def test_trim_source_takes_a_local_file_for_a_source_that_is_not_in_storage(tmp_path, clip_file):
    """A Genjutsu library source has only a preview url: its downloaded preview is trimmed with --file."""
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    parent = new_source(store)  # higgsfield_library, no storage_path
    with pytest.raises(ValueError, match="--file"):
        sources.trim_source(store, storage, parent.id, 0.0, 2.0)
    child = sources.trim_source(store, storage, parent.id, 0.0, 2.0, file=clip_file)
    assert child.storage_path and child.kind is SourceKind.owner_inbox and child.body is Body.biped
    assert child.duration_s == pytest.approx(2.0, abs=0.25)
    with pytest.raises(ValueError, match="no such file"):
        sources.trim_source(store, storage, parent.id, 0.0, 2.0, file=tmp_path / "nope.mp4")


def test_trim_source_refuses_an_unknown_source_and_a_bad_window(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    parent = stored_source(store, storage, clip_file)
    with pytest.raises(KeyError):
        sources.trim_source(store, storage, "missing", 0.0, 2.0)
    for start, duration in ((0, 0), (-1, 2), (0, 20), (4, 3)):
        with pytest.raises(ValueError):
            sources.trim_source(store, storage, parent.id, start, duration)
    assert len(store.list_sources()) == 1  # nothing was catalogued


def test_cli_trim_prints_the_child_source(cli_store, cli_storage, clip_file):
    parent = stored_source(cli_store, cli_storage, clip_file)
    r = run("trim", parent.id, "--start", "1", "--duration", "3")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["parent_id"] == parent.id and out["id"] != parent.id and out["credit_handle"] == "@eatfryhaven"
    assert out["duration_s"] == pytest.approx(3.0, abs=0.25) and out["kind"] == "owner_inbox"
    assert len(cli_store.list_sources()) == 2


def test_trim_source_can_crop_a_landscape_parent_to_a_vertical_window(tmp_path, synth_video):
    # owner 2026-10-05: an iconic clip is often landscape; --crop-x keeps its sound and makes it a 9:16 source
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    wide = synth_video(w=640, h=360, dur=5, audio=False)
    key = "owner_inbox/aaaaaaaa-0000-4000-8000-000000000009.mp4"
    storage.upload("sources", key, wide)
    parent = add_source(store, "owner_inbox", key, "biped", 1, 5.0, storage_path=key)
    child = sources.trim_source(store, storage, parent.id, 1.0, 3.0, crop_x=0.5)
    out = tmp_path / "child.mp4"
    out.write_bytes(fetch(storage, tmp_path, child.storage_path))
    report = probe(out, loudness=False)
    assert (report.width, report.height) == (202, 360)
    with pytest.raises(ValueError, match="already 9:16"):
        sources.trim_source(store, storage, child.id, 0.0, 2.0, crop_x=0.5)


def test_cli_trim_takes_crop_x(cli_store, cli_storage, synth_video):
    wide = synth_video(w=640, h=360, dur=5, audio=False)
    key = "owner_inbox/aaaaaaaa-0000-4000-8000-00000000000a.mp4"
    cli_storage.upload("sources", key, wide)
    parent = add_source(cli_store, "owner_inbox", key, "biped", 1, 5.0, storage_path=key)
    assert run("trim", parent.id, "--start", "0", "--duration", "2", "--crop-x", "0.3").exit_code == 0
    assert run("trim", parent.id, "--start", "0", "--duration", "2", "--crop-x", "1.5").exit_code == 2


def test_cli_trim_exit_codes(cli_store, cli_storage, clip_file):
    parent = stored_source(cli_store, cli_storage, clip_file)
    assert run("trim", "nope", "--start", "0", "--duration", "2").exit_code == 2
    assert run("trim", parent.id, "--start", "0", "--duration", "0").exit_code == 2
    assert run("trim", parent.id, "--duration", "2").exit_code == 2  # --start is required
    assert "trim" in run("--help").output

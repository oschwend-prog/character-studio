"""The analyst upgrade (owner request 2026-10-05): richer data on every pick card.

Posted date -> age and velocity (views per day), engagement and share rates, the saturation count and its score, the traits
the pick matches, the analyst's reasoning, and the local check of a clip. The pure rules are pinned here and, through
terminal/src/lib/parity-cases.json, in the terminal's own tests: one list of cases, two implementations.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio import favorites
from studio.cli import app
from studio.favorites import (
    add_pick,
    decide,
    engagement_rates,
    mark_favorite,
    posted_age_days,
    saturation_score,
    validate_card,
    velocity_per_day,
)
from studio.models import Body, Character
from studio.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
PARITY = json.loads((ROOT / "terminal" / "src" / "lib" / "parity-cases.json").read_text())
NOW = datetime.fromisoformat(PARITY["now"].replace("Z", "+00:00"))


def days_ago(n: float) -> str:
    return (NOW - timedelta(days=n)).isoformat()


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


URL = "https://www.tiktok.com/@tillandsialover/video/7688386199270001953"


def file_pick(store, proposal=None, views=3_100_000, outlier_x=40.0, **judged):
    j = {"freshness": 8, "fit": 8, "feasibility": 8, "saturation": 7, **judged}
    return add_pick(
        store, URL, "tiktok", "@tillandsialover", views, outlier_x, "biscuit", {"mode": "dropin", **(proposal or {})}, **j
    )


# ---- age, velocity, engagement, saturation: the pure rules ---------------------------------------------------------


def test_age_comes_from_the_post_date_then_the_scans_age_days():
    assert posted_age_days({"posted_at": days_ago(6)}, NOW) == pytest.approx(6.0)
    assert posted_age_days({"age_days": 12}, NOW) == 12.0
    assert posted_age_days({"posted_at": days_ago(2), "age_days": 40}, NOW) == pytest.approx(2.0)  # the date wins
    assert posted_age_days({}, NOW) is None and posted_age_days({"posted_at": "soon"}, NOW) is None


def test_velocity_is_views_per_day_with_a_floor_of_one_day_and_agrees_with_the_terminal():
    assert len(PARITY["velocity"]) >= 5
    for c in PARITY["velocity"]:
        age = None if c["days_ago"] is None else c["days_ago"]
        assert velocity_per_day(c["views"], age) == c["expect"], c
    assert velocity_per_day(1_000_000, 0.1) == 1_000_000  # a clip posted two hours ago is not "10M a day"
    assert velocity_per_day(-5, 3) is None and velocity_per_day(float("nan"), 3) is None


def test_engagement_and_share_rate_agree_with_the_terminal():
    assert len(PARITY["engagement"]) >= 6
    for c in PARITY["engagement"]:
        got = engagement_rates(c["engagement"], c["views"])
        if c["expect"] is None:
            assert got is None, c
        else:
            assert got is not None, c
            assert got["engagement_rate"] == pytest.approx(c["expect"]["engagement_rate"]), c
            if c["expect"]["share_rate"] is None:
                assert got["share_rate"] is None, c
            else:
                assert got["share_rate"] == pytest.approx(c["expect"]["share_rate"]), c


def test_the_saturation_score_follows_the_owners_table_and_agrees_with_the_terminal():
    assert [(c["count"], saturation_score(c["count"])) for c in PARITY["saturation"]] == [
        (c["count"], c["expect"]) for c in PARITY["saturation"]
    ]
    assert saturation_score(0) == 10 and saturation_score(3) == 8 and saturation_score(4) == 5 and saturation_score(7) == 5
    assert saturation_score(8) == 3 and saturation_score(99) == 3
    for bad in (-1, 2.5, True, "3", None):
        with pytest.raises(ValueError):
            saturation_score(bad)


def test_the_tier_rules_live_in_scan_json_and_the_code_uses_the_same_numbers():
    scan = json.loads((ROOT / "config" / "scan.json").read_text())
    rules = {k: v for k, v in scan["tier_rules"].items() if not k.startswith("_")}
    assert rules == favorites.TIER_RULES
    assert favorites.TIER_RULES == {
        "iconic_min_age_days": 180,
        "iconic_min_views": 50_000_000,
        "viral_now_max_age_days": 21,
        "viral_now_min_outlier": 20,
        "viral_now_min_velocity_per_day": 100_000,
        "rising_max_age_days": 7,
        "rising_min_outlier": 5,
        "fallback_viral_now_max_age_days": 30,
        "velocity_min_age_days": 1,
    }


def test_the_saturation_table_lives_in_scan_json_too():
    scan = json.loads((ROOT / "config" / "scan.json").read_text())
    assert [(r["min_count"], r["score"]) for r in scan["saturation_steps"]] == [
        (floor, int(score)) for floor, score in favorites.SATURATION_STEPS
    ]


# ---- the card fields are validated at the door ---------------------------------------------------------------------

ANALYSIS = {
    "people_count": 1, "main_subject": "a dachshund in a tracksuit", "camera": "static", "watermark": False, "overlay": False,
    "minors": False, "best_window": {"start_s": 2.5, "end_s": 10.0}, "bpm": 112.5, "notes": "clean start, one cut at 9 s",
}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("velocity", 310_000), ("velocity", 0), ("velocity", 12.5),
        ("engagement", {"likes": 4000, "comments": 300, "shares": 500, "saves": 200}), ("engagement", {"likes": 1}),
        ("saturation_count", 0), ("saturation_count", 9),
        ("trait_matches", ["slick upright dance"]), ("trait_matches", ["a", "b", "c", "d"]),
        ("why", "Matches the upright dance and hits every beat; one performer, static camera, full body."),
        ("analysis", ANALYSIS), ("analysis", {**ANALYSIS, "bpm": None, "best_window": None}),
        ("analysis", {k: ANALYSIS[k] for k in ("people_count", "camera", "watermark", "overlay", "minors")}),
    ],
)
def test_a_well_formed_analyst_field_is_accepted(key, value):
    validate_card({key: value})


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("velocity", -1), ("velocity", "310K"), ("velocity", True), ("velocity", float("inf")),
        ("engagement", {}), ("engagement", "5%"), ("engagement", {"likes": -1}), ("engagement", {"views": 5}),
        ("engagement", {"likes": 1.5}), ("engagement", {"likes": True}), ("engagement", {"likes": "9"}),
        ("saturation_count", -1), ("saturation_count", 2.5), ("saturation_count", "3"), ("saturation_count", True),
        ("trait_matches", []), ("trait_matches", "bouncy"), ("trait_matches", ["a", "b", "c", "d", "e"]),
        ("trait_matches", [""]), ("trait_matches", ["x" * 61]), ("trait_matches", [3]),
        ("why", ""), ("why", "   "), ("why", 5), ("why", "x" * 601),
        ("analysis", "clean"), ("analysis", []), ("analysis", {}),
        ("analysis", {**ANALYSIS, "camera": "shaky"}), ("analysis", {**ANALYSIS, "people_count": -1}),
        ("analysis", {**ANALYSIS, "people_count": 1.5}), ("analysis", {**ANALYSIS, "watermark": "no"}),
        ("analysis", {**ANALYSIS, "minors": None}), ("analysis", {**ANALYSIS, "overlay": 0}),
        ("analysis", {**ANALYSIS, "main_subject": ""}), ("analysis", {**ANALYSIS, "notes": "x" * 501}),
        ("analysis", {**ANALYSIS, "bpm": 0}), ("analysis", {**ANALYSIS, "bpm": 400}), ("analysis", {**ANALYSIS, "bpm": "fast"}),
        ("analysis", {**ANALYSIS, "best_window": {"start_s": 5, "end_s": 5}}),
        ("analysis", {**ANALYSIS, "best_window": {"start_s": -1, "end_s": 5}}),
        ("analysis", {**ANALYSIS, "best_window": {"start_s": 2}}), ("analysis", {**ANALYSIS, "best_window": [2, 9]}),
        ("analysis", {**ANALYSIS, "watermak": True}),  # a typo is refused, never silently stored
        ("analysis", {k: ANALYSIS[k] for k in ("people_count", "camera", "watermark", "overlay")}),  # minors missing
    ],
)
def test_a_malformed_analyst_field_is_refused_naming_the_key(key, bad):
    with pytest.raises(ValueError, match=f"proposal.{key}"):
        validate_card({key: bad})


def test_filing_a_pick_refuses_a_bad_analyst_field_and_stores_nothing():
    store = make_store()
    with pytest.raises(ValueError, match="trait_matches"):
        file_pick(store, {"trait_matches": []})
    assert store.list_favorites() == []


# ---- velocity is worked out at filing time -------------------------------------------------------------------------


def test_filing_a_pick_with_a_post_date_stores_its_velocity(monkeypatch):
    monkeypatch.setattr(favorites, "now_london", lambda: NOW)
    store = make_store()
    f = file_pick(store, {"posted_at": days_ago(10)}, views=3_100_000)
    assert f.proposal["velocity"] == 310_000  # views per day since posting, whole numbers


def test_a_velocity_the_scan_gave_is_kept_and_an_unknown_post_date_stores_none(monkeypatch):
    monkeypatch.setattr(favorites, "now_london", lambda: NOW)
    store = make_store()
    given = file_pick(store, {"posted_at": days_ago(10), "velocity": 123_456}, views=3_100_000)
    assert given.proposal["velocity"] == 123_456
    other = add_pick(
        store, "https://www.tiktok.com/@a/video/1", "tiktok", "@a", 500_000, 5.0, "biscuit", {"mode": "dropin"},
        freshness=5, fit=5, feasibility=5, saturation=5,
    )
    assert "velocity" not in other.proposal  # no post date, no velocity: never a made-up number


def test_the_scans_age_days_gives_a_velocity_too(monkeypatch):
    monkeypatch.setattr(favorites, "now_london", lambda: NOW)
    f = file_pick(make_store(), {"age_days": 4}, views=800_000)
    assert f.proposal["velocity"] == 200_000


# ---- the CLI --------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(favorites, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["fav", *args])


def pick_cli(tmp_path, proposal, *extra):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"url": URL, "creator": "@tillandsialover", **proposal}), encoding="utf-8")
    return run(
        "pick", "--platform", "tiktok", "--views", "3100000", "--outlier-x", "40", "--character", "biscuit",
        "--freshness", "8", "--fit", "8", "--feasibility", "8", "--proposal-file", str(f), *extra,
    )


def test_fav_pick_derives_the_saturation_score_from_the_count_when_it_is_not_given(cli_store, tmp_path):
    r = pick_cli(tmp_path, {"mode": "dropin", "saturation_count": 5})
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["scores"]["saturation"] == 5 and out["proposal"]["saturation_count"] == 5


def test_fav_pick_still_takes_an_explicit_saturation_and_needs_one_or_the_other(cli_store, tmp_path):
    r = pick_cli(tmp_path, {"mode": "dropin", "saturation_count": 9}, "--saturation", "6")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["scores"]["saturation"] == 6  # the analyst's judgement stands when it is given
    nothing = pick_cli(tmp_path, {"mode": "dropin"})  # no --saturation and no saturation_count to take it from
    assert nothing.exit_code == 2 and "saturation" in nothing.output


def test_fav_list_hands_the_agent_age_velocity_and_rates_next_to_the_stored_card(cli_store, monkeypatch):
    monkeypatch.setattr(favorites, "now_london", lambda: NOW)
    f = file_pick(cli_store, {"posted_at": days_ago(10), "engagement": {"likes": 90_000, "shares": 31_000}}, views=3_100_000)
    (row,) = json.loads(run("list", "--status", "new").stdout)
    assert row["id"] == f.id
    assert row["age_days"] == pytest.approx(10.0, abs=0.05) and row["velocity_per_day"] == 310_000
    assert row["engagement_rate"] == pytest.approx(121_000 / 3_100_000, rel=1e-3) and row["share_rate"] == pytest.approx(0.01, rel=1e-3)


def test_fav_list_leaves_the_derived_fields_null_when_nothing_is_known(cli_store):
    file_pick(cli_store, None, views=None)
    (row,) = json.loads(run("list", "--status", "new").stdout)
    assert (row["age_days"], row["velocity_per_day"], row["engagement_rate"], row["share_rate"]) == (None, None, None, None)


def write_json(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_fav_mark_stores_the_clip_analysis_from_a_file_and_keeps_the_rest_of_the_proposal(cli_store, tmp_path):
    f = decide(cli_store, file_pick(cli_store, {"theme": "skilled upright dance"}).id, "approve", "ok", "analyst")
    r = run("mark", f.id, "--analysis-file", write_json(tmp_path, "a.json", ANALYSIS))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["proposal"]["analysis"] == ANALYSIS and out["proposal"]["theme"] == "skilled upright dance"
    assert out["status"] == "approved"  # no --status: the pick stays where it is
    assert out["proposal"]["decision"]["by"] == "analyst"
    assert cli_store.get_favorite(f.id).proposal["analysis"] == ANALYSIS


def test_fav_mark_can_move_the_status_and_store_the_analysis_in_one_call(cli_store, tmp_path):
    f = decide(cli_store, file_pick(cli_store).id, "approve", "ok", "analyst")
    r = run("mark", f.id, "--status", "analysed", "--analysis-file", write_json(tmp_path, "a.json", ANALYSIS))
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["status"] == "analysed"


def test_fav_mark_refuses_a_bad_analysis_unknown_pick_or_unreadable_file(cli_store, tmp_path):
    f = decide(cli_store, file_pick(cli_store).id, "approve", "ok", "analyst")
    bad = run("mark", f.id, "--analysis-file", write_json(tmp_path, "b.json", {**ANALYSIS, "camera": "shaky"}))
    assert bad.exit_code == 2 and "analysis" in bad.output
    assert "analysis" not in cli_store.get_favorite(f.id).proposal
    assert run("mark", f.id, "--analysis-file", str(tmp_path / "missing.json")).exit_code == 2
    text = tmp_path / "t.json"
    text.write_text("not json", encoding="utf-8")
    assert run("mark", f.id, "--analysis-file", str(text)).exit_code == 2
    assert run("mark", "no-such-pick", "--analysis-file", write_json(tmp_path, "a.json", ANALYSIS)).exit_code == 2


def test_fav_mark_without_a_status_still_refuses_an_unapproved_pick_from_production(cli_store):
    f = file_pick(cli_store)
    assert run("mark", f.id, "--status", "queued").exit_code == 2  # unchanged: new picks are never produced


def test_the_analysis_is_validated_when_marked_through_the_api_too():
    store = make_store()
    f = decide(store, file_pick(store).id, "approve", "ok", "analyst")
    with pytest.raises(ValueError, match="analysis"):
        mark_favorite(store, f.id, "approved", proposal={**f.proposal, "analysis": {"people_count": 1}})
    ok = mark_favorite(store, f.id, "approved", proposal={**f.proposal, "analysis": ANALYSIS})
    assert ok.proposal["analysis"]["best_window"] == {"start_s": 2.5, "end_s": 10.0}


def test_the_time_zone_of_now_never_matters_for_the_age():
    aware = datetime(2026, 10, 5, 10, 0, tzinfo=timezone(timedelta(hours=1)))  # the same instant as 09:00 UTC
    assert posted_age_days({"posted_at": "2026-10-04T09:00:00+00:00"}, aware) == pytest.approx(1.0)

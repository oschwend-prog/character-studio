"""`fav rescore`: re-assess a pick that is already filed (the long list, owner request 2026-10-05), and the long list's card
fields (migration 0010) at the door of validate_card."""

import json

import pytest
from typer.testing import CliRunner

from studio import favorites
from studio.cli import app
from studio.favorites import add_pick, decide, mark_favorite, rescore_pick, score_pick, validate_card
from studio.models import Body, Character
from studio.store import MemoryStore

URL = "https://www.tiktok.com/@tillandsialover/video/7688386199270001953"
YT = "https://www.youtube.com/watch?v=9bZkp7q19f0"
JUDGED = {"freshness": 7, "fit": 9, "feasibility": 9, "saturation": 7}

# The long list's card as the analyst files it (shapes of the controller's 2026-10-05 long list).
LONGLIST = {
    "mode": "recreate",
    "tier": "iconic",
    "theme": "famous dance, pet edition",
    "saturation_count": 0,
    "trait_matches": ["slick upright trend dance"],
    "why": "The most-viewed dance video on this list and readable in one second from the horse-ride hop alone.",
    "hook": "oppan sausage style",
    "prop": "aviator shades",
    "concept": "Biscuit does the horse-ride hop and lasso arm in a sunlit pastel room.",
    "source_status": "needs a clean clip (recreate fallback)",
    "audio_risk": "chart song: Instagram may mute it, fallback in-app",
    "est_credits": 160,
    "recognisability": 10,
    "original_year": 2012,
    "thumbnail_url": "https://i.ytimg.com/vi/9bZkp7q19f0/hqdefault.jpg",
    "original_url": YT,
    "original_views": 6083137818,
    "posted_at": "2012-07-15",
    "season": "24-31 Oct",
    "source_candidates": [
        {"id": "0r55UgS2yOo", "views": 4591225, "published": "2012-08-29", "why": "solo dance tutorial: preview it first"},
        {"id": "bjQKCLvtLN0", "views": 21090207, "published": "2012-10-04", "why": "probably carries a logo"},
    ],
    "checks": ["the same moment is Reginald's launch pick: not both in the same fortnight"],
}


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


def filed(store, url=URL, proposal=None, views=7_400_000, outlier_x=1177.0, **judged):
    return add_pick(
        store, url, "youtube" if "youtube" in url else "tiktok", "@creator", views, outlier_x, "biscuit",
        proposal if proposal is not None else {"mode": "dropin", "hook": "first try"}, **{**JUDGED, **judged},
    )


# ---- rescore_pick ------------------------------------------------------------------------------------------------


def test_rescore_changes_the_scores_and_the_total_and_keeps_the_status():
    store = make_store()
    f = filed(store)
    assert f.total_score == score_pick(1177.0, 7_400_000, **JUDGED)["total"]
    again = rescore_pick(store, f.id, {"hook": "nailed it"}, freshness=3, fit=4, feasibility=5, saturation=3)
    expected = score_pick(1177.0, 7_400_000, 3, 4, 5, 3)
    assert again.total_score == expected["total"] and again.total_score < f.total_score
    assert again.scores == {k: v for k, v in expected.items() if k != "total"}
    assert again.status == "new" and again.proposal["hook"] == "nailed it" and again.proposal["mode"] == "dropin"
    assert store.get_favorite(f.id).total_score == expected["total"]  # written


def test_rescore_keeps_the_decision_the_owners_choices_the_clip_check_and_the_breakdown():
    store = make_store()
    f = filed(store)
    owner = {"owner_mode": "dropin", "owner_music": "in_app", "owner_props": ["gold chain"], "owner_note": "keep the snare"}
    analysis = {"people_count": 1, "camera": "static", "watermark": False, "overlay": False, "minors": False}
    f = mark_favorite(store, f.id, "new", proposal={**f.proposal, **owner, "analysis": analysis, "breakdown": "beat 1: stare"})
    f = decide(store, f.id, "approve", "fits", "owner")
    out = rescore_pick(store, f.id, {**LONGLIST, "tier": "viral_now"}, **JUDGED)
    assert out.status == "approved"
    assert out.proposal["decision"] == {"decision": "approve", "by": "owner", "reason": "fits"}
    for key, value in {**owner, "analysis": analysis, "breakdown": "beat 1: stare"}.items():
        assert out.proposal[key] == value, key
    assert out.proposal["checks"] == LONGLIST["checks"] and out.proposal["tier"] == "viral_now"  # the card's keys override
    # a key the card names replaces even a kept one
    named = rescore_pick(store, f.id, {"owner_music": "ai_beat", "hold_reason": "waits for the multi-body test"}, **JUDGED)
    assert named.proposal["owner_music"] == "ai_beat" and named.proposal["hold_reason"] == "waits for the multi-body test"


def test_rescore_keeps_a_hold_reason_and_a_skip():
    store = make_store()
    f = filed(store, proposal={"mode": "dropin", "needs": "multi_body"})
    held = decide(store, f.id, "hold", "needs the multi-body test", "rule")
    out = rescore_pick(store, held.id, {"concept": "four dancers"}, **JUDGED)
    assert (out.status, out.proposal["hold_reason"], out.proposal["needs"]) == ("new", "needs the multi-body test", "multi_body")
    skipped = decide(store, filed(store, url=URL + "1").id, "skip", "seen it everywhere", "owner")
    assert rescore_pick(store, skipped.id, {}, **JUDGED).status == "skipped"


@pytest.mark.parametrize("status", ["analysed", "queued", "made"])
def test_rescore_refuses_a_pick_in_production(status):
    store = make_store()
    f = decide(store, filed(store).id, "approve", "", "owner")
    f = mark_favorite(store, f.id, status)
    before = store.get_favorite(f.id)
    with pytest.raises(ValueError, match=f"is {status}: production started"):
        rescore_pick(store, f.id, {"hook": "x"}, **JUDGED)
    assert store.get_favorite(f.id) == before


@pytest.mark.parametrize(
    "card, message",
    [
        ({"tier": "legendary"}, "proposal.tier"),
        ({"needs": "multi-body"}, "proposal.needs"),
        ({"recognisability": 11}, "proposal.recognisability"),
        ({"checks": "one string"}, "proposal.checks"),
        ({"posted_at": "last week"}, "proposal.posted_at"),
    ],
)
def test_rescore_refuses_a_malformed_card_and_writes_nothing(card, message):
    store = make_store()
    f = filed(store)
    with pytest.raises(ValueError, match=message):
        rescore_pick(store, f.id, card, **JUDGED)
    assert store.get_favorite(f.id) == f


def test_an_iconic_rescore_scores_full_virality():
    store = make_store()
    f = filed(store, url=YT, proposal={"mode": "recreate"}, views=6_083_137_818, outlier_x=1.0)
    assert f.scores["virality"] == 0
    out = rescore_pick(store, f.id, LONGLIST, freshness=6, fit=8, feasibility=6, saturation=10)
    assert out.scores["virality"] == 10
    assert out.total_score == score_pick(1.0, 6_083_137_818, 6, 8, 6, 10, iconic=True)["total"]


def test_rescore_works_out_the_velocity_again_from_a_new_post_date_and_the_views():
    store = make_store()
    f = filed(store, proposal={"mode": "dropin", "posted_at": "2026-01-01", "velocity": 5})
    out = rescore_pick(store, f.id, {"posted_at": "2026-10-03"}, views=3_000_000, **JUDGED)
    assert out.views == 3_000_000 and out.proposal["velocity"] > 5  # three million over a few days, not the stale 5
    same = rescore_pick(store, f.id, {"hook": "no date given"}, **JUDGED)
    assert same.proposal["velocity"] == out.proposal["velocity"]  # no posted_at in the card: the stored velocity stays
    given = rescore_pick(store, f.id, {"posted_at": "2026-10-03", "velocity": 42}, **JUDGED)
    assert given.proposal["velocity"] == 42  # the card's own velocity wins, like add_pick


def test_rescore_url_must_be_the_picks_own_and_creator_replaces_the_handle():
    store = make_store()
    f = filed(store)
    with pytest.raises(ValueError, match="not this pick's"):
        rescore_pick(store, f.id, {"url": "https://www.tiktok.com/@other/video/1"}, **JUDGED)
    out = rescore_pick(store, f.id, {"url": URL + "?is_from_webapp=1", "creator": "@newname"}, **JUDGED)
    assert out.creator_handle == "@newname" and "url" not in out.proposal and "creator" not in out.proposal
    with pytest.raises(KeyError):
        rescore_pick(store, "missing", {}, **JUDGED)


# ---- the CLI -------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(favorites, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["fav", *args])


def card_file(tmp_path, data) -> str:
    p = tmp_path / "p.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_cli_rescore_prints_the_pick_and_works_the_saturation_out_from_the_count(cli_store, tmp_path):
    f = filed(cli_store, url=YT, proposal={"mode": "recreate"}, views=6_083_137_818, outlier_x=1.0)
    r = run("rescore", f.id, "--freshness", "6", "--fit", "8", "--feasibility", "6", "--outlier-x", "2",
            "--proposal-file", card_file(tmp_path, LONGLIST))  # fmt: skip
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["id"], out["status"], out["tier"], out["outlier_x"]) == (f.id, "new", "iconic", 2)
    assert out["scores"]["saturation"] == 10 and out["scores"]["virality"] == 10  # saturation_count 0 -> 10
    assert out["total_score"] == score_pick(2, 6_083_137_818, 6, 8, 6, 10, iconic=True)["total"]
    assert out["proposal"]["recognisability"] == 10 and out["proposal"]["source_candidates"][0]["id"] == "0r55UgS2yOo"


def test_cli_rescore_refuses_production_a_bad_card_and_an_unknown_id_with_exit_2(cli_store, tmp_path):
    f = filed(cli_store)
    args = ("--freshness", "6", "--fit", "8", "--feasibility", "6", "--saturation", "5")
    made = mark_favorite(cli_store, decide(cli_store, filed(cli_store, url=URL + "9").id, "approve", "", "owner").id, "made")
    r = run("rescore", made.id, *args, "--proposal-file", card_file(tmp_path, {"hook": "x"}))
    assert r.exit_code == 2 and "production started" in r.output
    r = run("rescore", f.id, *args, "--proposal-file", card_file(tmp_path, {"checks": [""]}))
    assert r.exit_code == 2 and "proposal.checks" in r.output
    r = run("rescore", f.id, *args, "--proposal-file", card_file(tmp_path, ["not", "an", "object"]))
    assert r.exit_code == 2 and "JSON object" in r.output
    r = run("rescore", "nope", *args, "--proposal-file", card_file(tmp_path, {}))
    assert r.exit_code == 2 and "unknown favourite" in r.output
    r = run("rescore", f.id, "--freshness", "6", "--fit", "8", "--feasibility", "6", "--proposal-file", card_file(tmp_path, {}))
    assert r.exit_code == 2 and "--saturation is needed" in r.output
    assert cli_store.get_favorite(f.id) == f  # nothing was written by any refusal


# ---- the long list's card fields at the door ---------------------------------------------------------------------------


def test_the_long_lists_card_passes_the_door():
    validate_card(LONGLIST)
    validate_card({"checks": [], "source_candidates": [], "recognisability": 0, "est_credits": 0})


@pytest.mark.parametrize(
    "card",
    [
        {"recognisability": -1},
        {"recognisability": "high"},
        {"recognisability": True},
        {"original_views": 1.5},
        {"original_views": -3},
        {"est_credits": "160"},
        {"original_url": "http://www.youtube.com/watch?v=9bZkp7q19f0"},
        {"source_status": ""},
        {"audio_risk": "x" * 161},
        {"season": 2026},
        {"checks": ["ok", 5]},
        {"checks": ["x"] * 9},
        {"source_candidates": "0r55UgS2yOo"},
        {"source_candidates": [{}]},
        {"source_candidates": [{"id": "a", "views": "many"}]},
        {"source_candidates": [{"id": "a", "why": ""}]},
    ],
)
def test_a_malformed_long_list_field_is_refused(card):
    with pytest.raises(ValueError, match=next(iter(card))):
        validate_card(card)

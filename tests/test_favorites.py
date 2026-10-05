import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from studio import favorites
from studio.cli import app
from studio.favorites import (
    NeedsAnalyst,
    add_favorite,
    add_pick,
    apply_rule,
    auto_decision,
    decide,
    list_picks,
    mark_favorite,
    next_favorites,
    parse_video_url,
    seen_ids,
    score_pick,
)
from studio.models import Body, Character, Clip, Favorite, Mode, Source
from studio.store import MemoryStore

T0 = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)

# Batch 1 (docs/launch/viral-picks-2026-10-04.md): url, platform, handle, views, outlier_x,
# character, (freshness, fit, feasibility, saturation), proposal, expected total.
B1 = dict(
    url="https://www.instagram.com/reel/Dde-rPWCOC6/", platform="instagram", creator_handle="@eatfryhaven",
    views=43_400_000, outlier_x=1392.8, character_slug="reginald",
    judged=(8, 10, 9, 7), proposal={"mode": "recreate", "hook": "first day as head butler"}, total=92,
)
B2 = dict(
    url="https://www.instagram.com/reel/DdZCANpDgI2/", platform="instagram", creator_handle="@drink321coffee",
    views=5_600_000, outlier_x=3475, character_slug="reginald",
    judged=(8, 9, 9, 8), proposal={"mode": "recreate"}, total=88,
)
D2 = dict(
    url="https://www.tiktok.com/@tillandsialover/video/7688386199270001953", platform="tiktok",
    creator_handle="@tillandsialover", views=7_400_000, outlier_x=1177, character_slug="biscuit",
    judged=(7, 9, 9, 7), proposal={"mode": "dropin"}, total=85,
)
D4 = dict(
    url="https://www.tiktok.com/@banana.the.wiener/video/7673905586383113503", platform="tiktok",
    creator_handle="@banana.the.wiener", views=1_400_000, outlier_x=131.8, character_slug="biscuit",
    judged=(6, 10, 10, 8), proposal={"mode": "recreate"}, total=79,
)
D1 = dict(
    url="https://www.instagram.com/reel/Dd9QM6WKSfJ/", platform="instagram", creator_handle="@muduronline",
    views=2_000_000, outlier_x=997, character_slug="biscuit",
    judged=(9, 10, 4, 5), proposal={"mode": "recreate", "needs": "multi_body"}, total=76,
)
# No `needs` here: with needs=talking_lane the rule would hold it (see the hold test).
O4 = dict(
    url="https://www.instagram.com/reel/DcWMn6QOckQ/", platform="instagram", creator_handle="@theeuropeankid",
    views=1_100_000, outlier_x=3.8, character_slug="reginald",
    judged=(6, 8, 3, 8), proposal={"mode": "recreate"}, total=48,
)


def make_store() -> MemoryStore:
    # MemoryStore enforces no foreign keys; seed what Postgres would require.
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


def pick(store, spec, **over):
    spec = {**spec, **over}
    fresh, fit, feas, sat = spec["judged"]
    return add_pick(
        store, spec["url"], spec["platform"], spec["creator_handle"], spec["views"], spec["outlier_x"],
        spec["character_slug"], spec["proposal"], freshness=fresh, fit=fit, feasibility=feas, saturation=sat,
    )


def aged(store: MemoryStore, id: str, days: int) -> None:
    """Backdate a favourite so oldest-first ordering is deterministic."""
    store._favorites[id].created_at = T0 - timedelta(days=days)


# ---- URLs ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, platform, canonical",
    [
        ("https://www.tiktok.com/@tillandsialover/video/7688386199270001953", "tiktok",
         "https://www.tiktok.com/@tillandsialover/video/7688386199270001953"),
        ("tiktok.com/@Banana.The.Wiener/video/7673905586383113503?is_from_webapp=1&sender_device=pc", "tiktok",
         "https://www.tiktok.com/@banana.the.wiener/video/7673905586383113503"),
        ("https://m.tiktok.com/@x/video/1/", "tiktok", "https://www.tiktok.com/@x/video/1"),
        ("https://www.instagram.com/reel/Dd9QM6WKSfJ/", "instagram", "https://www.instagram.com/reel/Dd9QM6WKSfJ/"),
        ("https://instagram.com/reel/Dd9QM6WKSfJ?igsh=abc#frag", "instagram",
         "https://www.instagram.com/reel/Dd9QM6WKSfJ/"),
        ("https://www.instagram.com/muduronline/reel/Dd9QM6WKSfJ/", "instagram",
         "https://www.instagram.com/reel/Dd9QM6WKSfJ/"),
        ("https://www.youtube.com/shorts/aBc-dEf_123?si=zzz", "youtube", "https://www.youtube.com/shorts/aBc-dEf_123"),
        ("  https://youtube.com/shorts/aBc-dEf_123  ", "youtube", "https://www.youtube.com/shorts/aBc-dEf_123"),
    ],
)
def test_parse_video_url_accepts_full_urls_and_canonicalises(url, platform, canonical):
    assert parse_video_url(url) == (platform, canonical)


@pytest.mark.parametrize(
    "url",
    [
        "https://vm.tiktok.com/ZMabc123/",
        "https://vt.tiktok.com/ZSabc123/",
        "https://www.tiktok.com/t/ZTabc123/",
        "https://instagr.am/reel/abc/",
        "https://youtu.be/aBc-dEf_123",
    ],
)
def test_short_links_are_rejected_with_a_request_for_the_full_url(url):
    with pytest.raises(ValueError, match="short links.*full"):
        parse_video_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://www.tiktok.com/@someone",
        "https://www.instagram.com/someone/",
        "https://www.youtube.com/watch?v=aBc-dEf_123",
        "https://example.com/@x/video/1",
        "https://nottiktok.com/@x/video/1",
        "ftp://www.tiktok.com/@x/video/1",
    ],
)
def test_unsupported_urls_are_rejected(url):
    with pytest.raises(ValueError, match="not a supported video URL|url is required"):
        parse_video_url(url)


def test_fav_accepts_full_urls_rejects_short_links():
    store = make_store()
    t = add_favorite(store, "https://www.tiktok.com/@x/video/123", "biscuit", note="love the snare hits")
    i = add_favorite(store, "https://www.instagram.com/reel/Dd9QM6WKSfJ/", "biscuit")
    y = add_favorite(store, "https://www.youtube.com/shorts/aBc-dEf_123", "reginald")
    assert [f.platform for f in (t, i, y)] == ["tiktok", "instagram", "youtube"]
    assert t.note == "love the snare hits"
    for short in ("https://vm.tiktok.com/ZMabc123/", "https://www.tiktok.com/t/ZTabc123/"):
        with pytest.raises(ValueError, match="full"):
            add_favorite(store, short, "biscuit")
    assert len(store.list_favorites()) == 3


def test_owner_favourites_are_auto_approved_and_not_sources():
    store = make_store()
    f = add_favorite(store, "https://www.tiktok.com/@x/video/123", "biscuit")
    assert (f.origin, f.status, f.character_slug) == ("owner", "approved", "biscuit")
    assert f.proposal["decision"] == {"decision": "approve", "by": "owner", "reason": "owner's own favourite"}
    assert (f.total_score, f.scores, f.source_id, f.clip_id) == (None, {}, None, None)
    assert store.list_sources() == []  # favourites are never downloaded, so never sources


def test_favourite_for_an_unknown_character_is_refused():
    store = make_store()
    with pytest.raises(ValueError, match="unknown character"):
        add_favorite(store, "https://www.tiktok.com/@x/video/123", "biscuti")
    assert store.list_favorites() == []


def test_owner_pasting_a_link_already_in_the_list_does_not_duplicate_it():
    store = make_store()
    scan = pick(store, D2)  # the scan found it first: status new
    assert scan.status == "new"
    mine = add_favorite(store, D2["url"] + "?lang=en", "biscuit", note="mine")
    assert mine.id == scan.id and mine.status == "approved" and mine.note == "mine"
    assert mine.origin == "scan" and mine.total_score == scan.total_score  # scan data kept
    assert mine.proposal["decision"]["by"] == "owner"
    assert len(store.list_favorites()) == 1
    # a pick the owner skipped earlier is revived by pasting it again
    skipped = decide(store, mine.id, "skip", "changed my mind", "owner")
    assert skipped.status == "skipped"
    assert add_favorite(store, D2["url"], "biscuit").status == "approved"
    # one already in production is left exactly as it is
    store.update_favorite(mine.id, status="queued")
    again = add_favorite(store, D2["url"], "biscuit", note="ignored")
    assert (again.status, again.note) == ("queued", "mine")


# ---- scoring ---------------------------------------------------------------------------


def test_score_pick_matches_batch1():
    b1 = score_pick(1392.8, 43_400_000, 8, 10, 9, 7)
    assert b1["total"] == 92
    assert (b1["virality"], b1["reach"]) == (10, 9.8)  # log10(1392.8)/3*10 = 10.5, capped
    assert (b1["freshness"], b1["fit"], b1["feasibility"], b1["saturation"]) == (8, 10, 9, 7)
    assert set(b1) == {"virality", "reach", "freshness", "fit", "feasibility", "saturation", "total"}
    o4 = score_pick(3.8, 1_100_000, 6, 8, 3, 8)
    assert o4["total"] == 48
    assert (o4["virality"], o4["reach"]) == (1.9, 3.9)


# Every row of the batch-1 table: views, outlier x, (freshness, fit, feasibility, saturation),
# then the table's virality, reach and total.
BATCH1 = {
    "B1": (43_400_000, 1392.8, (8, 10, 9, 7), 10, 9.8, 92),
    "B2": (5_600_000, 3475, (8, 9, 9, 8), 10, 6.5, 88),
    "D2": (7_400_000, 1177, (7, 9, 9, 7), 10, 6.9, 85),
    "D6": (12_800_000, 550, (6, 8, 8, 8), 9.1, 7.8, 80),
    "D4": (1_400_000, 131.8, (6, 10, 10, 8), 7.1, 4.2, 79),
    "D1": (2_000_000, 997, (9, 10, 4, 5), 10, 4.8, 76),
    "B3": (5_200_000, 422, (6, 8, 8, 7), 8.8, 6.4, 76),
    "D5": (2_800_000, 221.8, (6, 9, 7, 8), 7.8, 5.4, 74),
    "O1": (5_700_000, 420.8, (6, 10, 3, 9), 8.7, 6.5, 72),
    "O5": (4_300_000, 236.3, (6, 10, 3, 9), 7.9, 6.1, 70),
    "D3": (17_400_000, 44.6, (8, 8, 6, 6), 5.5, 8.3, 68),
    "B4": (22_300_000, 14.9, (8, 8, 6, 6), 3.9, 8.7, 64),
    "B5": (2_900_000, 18.8, (6, 9, 6, 8), 4.2, 5.4, 63),
    "B6": (349_700, 291, (5, 8, 4, 8), 8.2, 2.0, 62),
    "O3": (5_200_000, 18.3, (6, 8, 3, 8), 4.2, 6.4, 56),
    "O2": (1_100_000, 14.5, (6, 8, 3, 8), 3.9, 3.9, 53),
    "O4": (1_100_000, 3.8, (6, 8, 3, 8), 1.9, 3.9, 48),
}


@pytest.mark.parametrize("name", list(BATCH1))
def test_score_pick_reproduces_the_batch1_table(name):
    views, outlier_x, judged, virality, reach, total = BATCH1[name]
    got = score_pick(outlier_x, views, *judged)
    assert (got["virality"], got["reach"], got["total"]) == (virality, reach, total)


def test_total_can_be_recomputed_from_the_stored_sub_scores():
    got = score_pick(131.8, 1_400_000, 6, 10, 10, 8)
    weights = {"virality": .25, "reach": .10, "freshness": .15, "fit": .20, "feasibility": .20, "saturation": .10}
    assert round(10 * sum(w * got[k] for k, w in weights.items())) == got["total"] == 79


def test_score_pick_caps_and_floors_the_computed_scores():
    low = score_pick(0.5, 5_000, 0, 0, 0, 0)  # outlier below 1x, views below the 100K floor
    assert (low["virality"], low["reach"], low["total"]) == (0, 0, 0)
    assert score_pick(None, None, 5, 5, 5, 5)["virality"] == 0  # unknown outlier / views score 0
    high = score_pick(1e9, 1e12, 10, 10, 10, 10)
    assert (high["virality"], high["reach"], high["total"]) == (10, 10, 100)


@pytest.mark.parametrize(
    "judged, total",
    [
        # outlier 1x and 100K views make virality and reach 0, so total = 10*(.15f + .2fit + .2feas + .1sat)
        ((3, 0, 0, 0), 5),  # 4.5 -> 5 (Python's round() would say 4)
        ((7, 0, 0, 0), 11),  # 10.5 -> 11 (round() would say 10)
        ((1, 0, 0, 0), 2),  # 1.5
        ((5, 0, 0, 0), 8),  # 7.5
        ((0, 0, 0, 5), 5),  # exactly 5
        ((10, 10, 0, 5), 40),  # 10*(1.5 + 2.0 + 0.5)
    ],
)
def test_score_pick_rounds_half_up_not_to_even(judged, total):
    assert score_pick(1, 100_000, *judged)["total"] == total


@pytest.mark.parametrize("bad", [-0.1, 10.1, float("nan")])
def test_score_pick_rejects_judged_scores_outside_0_to_10(bad):
    for slot in range(4):
        judged = [5, 5, 5, 5]
        judged[slot] = bad
        with pytest.raises(ValueError, match="between 0 and 10"):
            score_pick(100, 1_000_000, *judged)


# ---- add_pick, dedupe, ordering --------------------------------------------------------


def test_add_pick_stores_scores_total_and_arrives_new():
    store = make_store()
    f = pick(store, B1)
    assert f.id and f.created_at is not None
    assert (f.status, f.origin, f.platform, f.creator_handle) == ("new", "scan", "instagram", "@eatfryhaven")
    assert (f.views, f.outlier_x, f.character_slug) == (43_400_000, 1392.8, "reginald")
    assert f.total_score == 92
    assert f.scores["feasibility"] == 9 and f.scores["fit"] == 10 and "total" not in f.scores
    assert f.proposal == B1["proposal"] and f.url == B1["url"]
    assert store.get_favorite(f.id) == f


def test_pick_dedupes_on_url():
    store = make_store()
    first = pick(store, B1)
    second = pick(store, B1, url="https://instagram.com/reel/Dde-rPWCOC6?igsh=xyz", judged=(1, 1, 1, 1))
    assert second.id == first.id and second.total_score == 92  # nothing overwritten
    assert len(store.list_favorites()) == 1
    other = pick(store, B2)
    assert other.id != first.id and len(store.list_favorites()) == 2


def test_add_pick_validates_before_writing():
    store = make_store()
    with pytest.raises(ValueError, match="platform"):
        pick(store, B1, platform="tiktok")  # an Instagram URL
    with pytest.raises(ValueError, match="unknown character"):
        pick(store, B1, character_slug="nobody")
    with pytest.raises(ValueError, match="origin"):
        add_pick(store, B1["url"], "instagram", "@x", 1, 1, "reginald", {}, origin="bot",
                 freshness=5, fit=5, feasibility=5, saturation=5)
    with pytest.raises(ValueError, match="short links"):
        pick(store, B1, url="https://vm.tiktok.com/ZMabc/", platform="tiktok")
    with pytest.raises(ValueError, match="between 0 and 10"):
        pick(store, B1, judged=(11, 5, 5, 5))
    assert store.list_favorites() == []


def test_owner_origin_picks_are_auto_approved():
    store = make_store()
    f = add_pick(store, D2["url"], "tiktok", "@t", 7_400_000, 1177, "biscuit", {}, origin="owner",
                 freshness=7, fit=9, feasibility=9, saturation=7)
    assert (f.origin, f.status, f.total_score) == ("owner", "approved", 85)


def test_list_picks_sorted_by_total():
    store = make_store()
    for spec in (D1, B1, O4, D4, B2, D2):
        pick(store, spec)
    got = list_picks(store)
    assert [f.total_score for f in got] == [92, 88, 85, 79, 76, 48]
    assert [f.creator_handle for f in got][:2] == ["@eatfryhaven", "@drink321coffee"]


def test_list_picks_filters_by_status_and_puts_unscored_last():
    store = make_store()
    scored = pick(store, D4)
    owner = add_favorite(store, "https://www.tiktok.com/@x/video/1", "biscuit")  # approved, unscored
    other = pick(store, B1)
    decide(store, other.id, "approve", "", "rule")
    assert [f.id for f in list_picks(store)] == [scored.id]  # default: new
    assert [f.id for f in list_picks(store, status="approved")] == [other.id, owner.id]
    assert {f.id for f in list_picks(store, status=None)} == {scored.id, owner.id, other.id}
    with pytest.raises(ValueError, match="status"):
        list_picks(store, status="pending")


def test_list_picks_ties_keep_the_older_first():
    store = make_store()
    a = pick(store, D2)
    b = pick(store, D2, url="https://www.tiktok.com/@tillandsialover/video/2")
    aged(store, a.id, 2)
    aged(store, b.id, 1)
    assert [f.id for f in list_picks(store)] == [a.id, b.id]


# ---- rule and decisions ----------------------------------------------------------------


def test_auto_decision_thresholds():
    store = make_store()
    assert auto_decision(pick(store, B1)) == "approve"  # 92, feasibility 9
    assert auto_decision(pick(store, D4)) == "analyst"  # 79: feasibility 10 but total < 80
    assert auto_decision(pick(store, D1)) == "hold"  # needs multi_body
    assert auto_decision(pick(store, O4)) == "skip"  # 48


def _fav(total, feasibility=None, needs=None):
    proposal = {"needs": needs} if needs else {}
    scores = {} if feasibility is None else {"feasibility": feasibility}
    return Favorite(url="https://www.tiktok.com/@x/video/1", total_score=total, scores=scores, proposal=proposal)


@pytest.mark.parametrize(
    "total, feasibility, needs, expected",
    [
        (80, 7, None, "approve"),
        (79.5, 9, None, "analyst"),
        (80, 6.9, None, "analyst"),  # high total, but not feasible enough to auto-approve
        (100, None, None, "analyst"),  # no feasibility score: never auto-approved
        (65, 10, None, "analyst"),
        (64.9, 10, None, "skip"),
        (0, 0, None, "skip"),
        (None, None, None, "analyst"),  # unscored (owner link): a person decides
        (95, 9, "multi_body", "hold"),  # hold is checked first, whatever the total
        (10, 3, "talking_lane", "hold"),  # ... even below the skip line
        (95, 9, ["x", "talking_lane"], "hold"),
        (95, 9, "something_else", "hold"),  # unreadable (add_pick refuses it): fail closed, never approve
    ],
)
def test_auto_decision_edges(total, feasibility, needs, expected):
    assert auto_decision(_fav(total, feasibility, needs)) == expected


def test_decide_approve_and_skip_set_the_status_and_record_who_and_why():
    store = make_store()
    a, s = pick(store, B1), pick(store, O4)
    approved = decide(store, a.id, "approve", "rule: total 92 >= 80", "rule")
    skipped = decide(store, s.id, "skip", "", "owner")
    assert (approved.status, skipped.status) == ("approved", "skipped")
    assert approved.proposal["decision"] == {"decision": "approve", "by": "rule", "reason": "rule: total 92 >= 80"}
    assert skipped.proposal["decision"] == {"decision": "skip", "by": "owner", "reason": None}
    assert approved.proposal["mode"] == "recreate"  # the rest of the proposal survives
    assert store.get_favorite(a.id) == approved


def test_decide_hold_leaves_the_status_new_and_stores_hold_reason():
    store = make_store()
    d1 = pick(store, D1)
    held = decide(store, d1.id, "hold", "3 bodies untested until the multi-body test passes", "rule")
    assert held.status == "new"
    assert held.proposal["hold_reason"] == "3 bodies untested until the multi-body test passes"
    assert held.proposal["decision"]["decision"] == "hold"
    # hold is resolved later: approving clears the stale hold reason
    approved = decide(store, d1.id, "approve", "multi-body test passed", "analyst")
    assert approved.status == "approved" and "hold_reason" not in approved.proposal
    with pytest.raises(ValueError, match="reason"):
        decide(store, pick(store, O4).id, "hold", " ", "rule")


def test_decide_analyst_needs_a_reason_and_a_final_choice():
    store = make_store()
    d4 = pick(store, D4)
    with pytest.raises(ValueError, match="reason"):
        decide(store, d4.id, "approve", "", "analyst")
    with pytest.raises(ValueError, match="reason"):
        decide(store, d4.id, "skip", "   ", "analyst")
    with pytest.raises(ValueError, match="approve or skip"):
        decide(store, d4.id, "hold", "not sure", "analyst")
    assert store.get_favorite(d4.id).status == "new"  # nothing happened
    done = decide(store, d4.id, "approve", "79: cheapest clip and the ODD EYES signature", "analyst")
    assert done.status == "approved"
    assert done.proposal["decision"]["by"] == "analyst"


def test_decide_rejects_bad_arguments_and_unknown_ids():
    store = make_store()
    f = pick(store, B1)
    with pytest.raises(ValueError, match="decision"):
        decide(store, f.id, "analyst", "x", "owner")
    with pytest.raises(ValueError, match="by"):
        decide(store, f.id, "approve", "x", "intern")
    with pytest.raises(KeyError):
        decide(store, "missing", "approve", "x", "owner")


def test_decide_cannot_touch_picks_already_in_production_and_only_new_ones_can_be_held():
    store = make_store()
    f = pick(store, B1)
    decide(store, f.id, "approve", "", "rule")
    with pytest.raises(ValueError, match="hold"):
        decide(store, f.id, "hold", "second thoughts", "owner")  # hold is for new picks
    assert decide(store, f.id, "skip", "owner changed their mind", "owner").status == "skipped"
    for status in ("queued", "made"):
        store.update_favorite(f.id, status=status)
        with pytest.raises(ValueError, match="already"):
            decide(store, f.id, "skip", "too late", "owner")
    # re-approving a pick that is already analysed keeps its progress
    store.update_favorite(f.id, status="analysed")
    assert decide(store, f.id, "approve", "", "owner").status == "analysed"


def test_apply_rule_decides_the_clear_cases_and_hands_the_rest_to_the_analyst():
    store = make_store()
    b1, d1, o4, d4 = (pick(store, s) for s in (B1, D1, O4, D4))
    approved = apply_rule(store, b1.id)
    held = apply_rule(store, d1.id)
    skipped = apply_rule(store, o4.id)
    assert (approved.status, held.status, skipped.status) == ("approved", "new", "skipped")
    assert approved.proposal["decision"]["by"] == "rule"
    assert "92" in approved.proposal["decision"]["reason"]
    assert "multi_body" in held.proposal["hold_reason"]
    assert "48" in skipped.proposal["decision"]["reason"]
    with pytest.raises(NeedsAnalyst) as exc:
        apply_rule(store, d4.id)
    assert exc.value.favorite.id == d4.id
    assert store.get_favorite(d4.id).status == "new"
    with pytest.raises(ValueError, match="already"):
        apply_rule(store, b1.id)  # decided: the rule only looks at new picks


# ---- production queue ------------------------------------------------------------------


def test_next_favorites_only_approved_oldest_first():
    store = make_store()
    new = pick(store, B1)  # never produced: no approval
    a_old = pick(store, B2)
    a_mid = pick(store, D2)
    analysed = pick(store, D4)
    a_new = add_favorite(store, "https://www.tiktok.com/@x/video/9", "biscuit")
    skipped = pick(store, O4)
    for f in (a_old, a_mid):
        decide(store, f.id, "approve", "", "rule")
    decide(store, skipped.id, "skip", "", "rule")
    store.update_favorite(analysed.id, status="analysed")
    queued = pick(store, D1)
    store.update_favorite(queued.id, status="queued")
    for days, f in ((5, a_old), (4, analysed), (3, a_mid), (2, a_new), (1, new), (9, skipped), (8, queued)):
        aged(store, f.id, days)
    got = next_favorites(store, 10)
    assert [f.id for f in got] == [a_old.id, analysed.id, a_mid.id, a_new.id]
    assert [f.id for f in next_favorites(store, 2)] == [a_old.id, analysed.id]
    assert next_favorites(store, 0) == []
    with pytest.raises(ValueError, match="limit"):
        next_favorites(store, -1)


def test_mark_favorite_moves_a_pick_through_production():
    store = make_store()
    f = pick(store, B1)
    decide(store, f.id, "approve", "", "rule")
    src = store.add_source(Source(kind="owner_inbox", body="biped", bodies=1, duration_s=8.0))
    clip = store.add_clip(Clip(character_slug="reginald", mode=Mode.recreate))
    analysed = mark_favorite(store, f.id, "analysed", breakdown_md="## beats\n1. pour tea")
    assert (analysed.status, analysed.breakdown_md) == ("analysed", "## beats\n1. pour tea")
    queued = mark_favorite(store, f.id, "queued", clip_id=clip.id, source_id=src.id)
    assert (queued.status, queued.clip_id, queued.source_id) == ("queued", clip.id, src.id)
    assert queued.breakdown_md == "## beats\n1. pour tea"  # earlier fields survive
    made = mark_favorite(store, f.id, "made", note="posted 6 Oct")
    assert (made.status, made.note) == ("made", "posted 6 Oct")
    assert store.get_favorite(f.id) == made


def test_mark_favorite_never_pushes_an_unapproved_pick_into_production():
    store = make_store()
    new, skipped = pick(store, B1), pick(store, O4)
    decide(store, skipped.id, "skip", "", "rule")
    for f in (new, skipped):
        for status in ("analysed", "queued", "made"):
            with pytest.raises(ValueError, match="approved"):
                mark_favorite(store, f.id, status)
    assert (store.get_favorite(new.id).status, store.get_favorite(skipped.id).status) == ("new", "skipped")
    assert mark_favorite(store, new.id, "skipped").status == "skipped"  # non-production moves are free


def test_mark_favorite_validates_status_fields_and_id():
    store = make_store()
    f = pick(store, B1)
    decide(store, f.id, "approve", "", "rule")
    with pytest.raises(ValueError, match="status"):
        mark_favorite(store, f.id, "done")
    for field in ("url", "total_score", "scores", "created_at", "platform"):
        with pytest.raises(TypeError, match="unknown field"):
            mark_favorite(store, f.id, "analysed", **{field: 1})
    with pytest.raises(ValueError, match="unknown character"):
        mark_favorite(store, f.id, "approved", character_slug="nobody")
    assert mark_favorite(store, f.id, "approved", character_slug="biscuit").character_slug == "biscuit"
    with pytest.raises(KeyError):
        mark_favorite(store, "missing", "skipped")
    assert store.get_favorite(f.id).status == "approved"


# ---- CLI -------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store()
    monkeypatch.setattr(favorites, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["fav", *args])


def pick_args(spec=B1, **over):
    fresh, fit, feas, sat = spec["judged"]
    base = {
        "--url": spec["url"], "--platform": spec["platform"], "--creator": spec["creator_handle"],
        "--views": str(spec["views"]), "--outlier-x": str(spec["outlier_x"]),
        "--character": spec["character_slug"], "--proposal": json.dumps(spec["proposal"]),
        "--freshness": str(fresh), "--fit": str(fit), "--feasibility": str(feas), "--saturation": str(sat),
    }
    base.update(over)
    return [x for kv in base.items() for x in kv]


def test_cli_add(cli_store):
    r = run("add", "https://www.tiktok.com/@x/video/123", "--character", "biscuit", "--note", "snare hits")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["status"], out["origin"], out["platform"], out["note"]) == ("approved", "owner", "tiktok", "snare hits")
    r = run("add", "https://vm.tiktok.com/ZMabc/", "--character", "biscuit")
    assert r.exit_code == 2 and "full" in r.output
    r = run("add", "https://www.tiktok.com/@x/video/1", "--character", "nobody")
    assert r.exit_code == 2 and "unknown character" in r.output
    assert len(cli_store.list_favorites()) == 1


def test_cli_pick_scores_and_dedupes(cli_store):
    r = run("pick", *pick_args())
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["status"], out["total_score"], out["duplicate"]) == ("new", 92, False)
    assert out["scores"]["virality"] == 10 and out["proposal"]["mode"] == "recreate"
    again = json.loads(run("pick", *pick_args()).stdout)
    assert (again["id"], again["duplicate"]) == (out["id"], True)
    assert len(cli_store.list_favorites()) == 1


def pick_args_in_file(tmp_path, spec=B1, *, keep_flags=(), **proposal_extra):
    """The pick CLI line with url and creator moved out of the shell and into the proposal JSON file."""
    proposal = {**spec["proposal"], "url": spec["url"], "creator": spec["creator_handle"], **proposal_extra}
    f = tmp_path / "p.json"
    f.write_text(json.dumps(proposal), encoding="utf-8")
    args = pick_args(spec)
    for flag in ("--url", "--creator", "--proposal"):
        if flag not in keep_flags:
            i = args.index(flag)
            del args[i : i + 2]
    return [*args, "--proposal-file", str(f)]


def test_cli_pick_takes_url_and_creator_from_the_proposal_file(cli_store, tmp_path):
    r = run("pick", *pick_args_in_file(tmp_path))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["url"] == B1["url"] and out["creator_handle"] == B1["creator_handle"]
    assert "url" not in out["proposal"] and "creator" not in out["proposal"]  # identity, not proposal
    assert out["proposal"]["hook"] == B1["proposal"]["hook"]
    assert (out["status"], out["total_score"]) == ("new", 92)
    assert "--url" in run("pick", "--help").output  # the flags still exist


def test_cli_pick_flags_still_work_and_agree_with_the_file(cli_store, tmp_path):
    same = run("pick", *pick_args_in_file(tmp_path, keep_flags=("--url", "--creator")))
    assert same.exit_code == 0, same.output
    other = run("pick", *pick_args_in_file(tmp_path, B2, keep_flags=("--url",)), "--creator", "@someone_else")
    assert other.exit_code == 2 and "creator" in other.output  # file and flag disagree


def test_cli_pick_url_must_come_from_somewhere(cli_store, tmp_path):
    args = pick_args_in_file(tmp_path)
    f = tmp_path / "p.json"
    f.write_text(json.dumps(B1["proposal"]), encoding="utf-8")  # no url in the file either
    r = run("pick", *args)
    assert r.exit_code == 2 and "url" in r.output and cli_store.list_favorites() == []


def test_cli_pick_third_party_text_in_the_file_is_stored_verbatim(cli_store, tmp_path):
    nasty = "tea $(touch /tmp/pwned) `id` \"q\" 'x'"
    r = run("pick", *pick_args_in_file(tmp_path, hook=nasty))
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["proposal"]["hook"] == nasty


def test_cli_pick_rejects_bad_input(cli_store):
    assert run("pick", *pick_args(**{"--freshness": "11"})).exit_code == 2
    assert run("pick", *pick_args(**{"--proposal": "not json"})).exit_code == 2
    assert run("pick", *pick_args(**{"--proposal": "[1]"})).exit_code == 2
    assert run("pick", *pick_args(**{"--platform": "tiktok"})).exit_code == 2
    assert run("pick", *pick_args(**{"--origin": "bot"})).exit_code == 2
    assert cli_store.list_favorites() == []


def test_cli_list_shows_picks_by_total_with_the_rule_suggestion(cli_store):
    for spec in (D4, B1, O4):
        pick(cli_store, spec)
    rows = json.loads(run("list").stdout)
    assert [(x["total_score"], x["auto_decision"]) for x in rows] == [(92, "approve"), (79, "analyst"), (48, "skip")]
    assert json.loads(run("list", "--status", "approved").stdout) == []
    assert len(json.loads(run("list", "--status", "all").stdout)) == 3
    assert run("list", "--status", "pending").exit_code == 2


def test_cli_list_next_returns_the_approved_queue(cli_store):
    a, b, c = pick(cli_store, B1), pick(cli_store, B2), pick(cli_store, D2)
    for f, days in ((a, 3), (b, 2), (c, 1)):
        aged(cli_store, f.id, days)
    decide(cli_store, b.id, "approve", "", "rule")
    decide(cli_store, a.id, "approve", "", "rule")
    rows = json.loads(run("list", "--next", "1").stdout)
    assert [x["id"] for x in rows] == [a.id]
    assert all("auto_decision" not in x for x in rows)  # only new picks carry the suggestion
    assert [x["id"] for x in json.loads(run("list", "--next", "5").stdout)] == [a.id, b.id]
    assert run("list", "--next", "2", "--status", "new").exit_code == 2
    assert run("list", "--next", "-1").exit_code == 2


def test_cli_mark(cli_store):
    f = pick(cli_store, B1)
    decide(cli_store, f.id, "approve", "", "rule")
    clip = cli_store.add_clip(Clip(character_slug="reginald", mode=Mode.recreate))
    r = run("mark", f.id, "--status", "analysed", "--breakdown", "## beats")
    assert r.exit_code == 0, r.output
    assert (json.loads(r.stdout)["status"], json.loads(r.stdout)["breakdown_md"]) == ("analysed", "## beats")
    r = run("mark", f.id, "--status", "queued", "--clip", clip.id)
    assert r.exit_code == 0 and json.loads(r.stdout)["clip_id"] == clip.id
    assert run("mark", f.id, "--status", "bogus").exit_code == 2
    r = run("mark", "missing", "--status", "skipped")
    assert r.exit_code == 2 and "unknown favourite" in r.output
    new = pick(cli_store, O4)
    r = run("mark", new.id, "--status", "queued")
    assert r.exit_code == 2 and "approved" in r.output


def test_cli_decide_by_rule_and_by_hand(cli_store):
    b1, d1, o4, d4 = (pick(cli_store, s) for s in (B1, D1, O4, D4))
    r = run("decide", b1.id)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["status"] == "approved" and out["proposal"]["decision"]["by"] == "rule"
    out = json.loads(run("decide", d1.id).stdout)
    assert out["status"] == "new" and "multi_body" in out["proposal"]["hold_reason"]
    assert json.loads(run("decide", o4.id).stdout)["status"] == "skipped"

    r = run("decide", d4.id)  # 79: needs a person
    assert r.exit_code == 4
    out = json.loads(r.stdout)
    assert (out["ok"], out["needs"], out["id"], out["total_score"]) == (False, "analyst", d4.id, 79)
    assert cli_store.get_favorite(d4.id).status == "new"

    r = run("decide", d4.id, "--decision", "approve", "--by", "analyst")
    assert r.exit_code == 2 and "reason" in r.output
    r = run("decide", d4.id, "--decision", "approve", "--reason", "cheapest clip", "--by", "intern")
    assert r.exit_code == 2
    r = run("decide", d4.id, "--decision", "approve", "--reason", "cheapest clip")
    assert r.exit_code == 2 and "--by" in r.output
    r = run("decide", d4.id, "--decision", "approve", "--reason", "cheapest clip; ODD EYES signature", "--by", "analyst")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["status"] == "approved"
    assert out["proposal"]["decision"] == {
        "decision": "approve", "by": "analyst", "reason": "cheapest clip; ODD EYES signature",
    }
    r = run("decide", "missing", "--decision", "skip", "--by", "owner")
    assert r.exit_code == 2 and "unknown favourite" in r.output
    r = run("decide", b1.id)  # already decided
    assert r.exit_code == 2 and "already" in r.output
    r = run("decide", b1.id, "--by", "analyst")  # --by without --decision means nothing
    assert r.exit_code == 2


def test_cli_without_database_url_prints_a_clear_error_and_exits_2(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for args in (["list"], ["add", "https://www.tiktok.com/@x/video/1", "--character", "biscuit"],
                 ["decide", "x"], ["mark", "x", "--status", "skipped"], ["pick", *pick_args()]):
        r = run(*args)
        assert r.exit_code == 2, args
        assert "DATABASE_URL" in r.output


def test_cli_fav_group_is_the_modules_own_app():
    groups = [g for g in app.registered_groups if g.name == "fav"]
    assert len(groups) == 1 and groups[0].typer_instance is favorites.app
    r = CliRunner().invoke(app, ["fav", "--help"])
    assert r.exit_code == 0
    for cmd in ("add", "pick", "list", "mark", "decide"):
        assert cmd in r.output
    top = CliRunner().invoke(app, ["--help"])
    assert "fav" in top.output


# ---- proposal.needs is validated when a pick is filed -------------------------------------
# A misspelt `needs` used to be filtered out silently, so the rule approved a pick that was
# really blocked by an untested capability (fail-open). Now it is refused at the door.


def test_a_misspelt_needs_is_rejected_instead_of_auto_approving():
    store = make_store()
    with pytest.raises(ValueError, match="multi_body.*talking_lane"):
        pick(store, B1, proposal={"mode": "recreate", "needs": "multi-body"})
    assert store.list_favorites() == []


@pytest.mark.parametrize(
    "needs", ["multibody", "", ["multi_body", "talking-lane"], ["multi_body", 3], 5, {"multi_body": True}]
)
def test_needs_must_be_one_or_a_list_of_the_known_tokens(needs):
    store = make_store()
    with pytest.raises(ValueError, match="needs"):
        pick(store, B1, proposal={"needs": needs})
    assert store.list_favorites() == []


@pytest.mark.parametrize(
    "needs", ["multi_body", "talking_lane", ["multi_body"], ["multi_body", "talking_lane"], [], None]
)
def test_known_needs_tokens_are_accepted(needs):
    store = make_store()
    f = pick(store, B1, proposal={"mode": "recreate", "needs": needs})
    assert f.proposal["needs"] == needs
    expected = "hold" if needs else "approve"
    assert auto_decision(f) == expected


def test_a_proposal_without_needs_is_fine():
    assert auto_decision(pick(make_store(), B1)) == "approve"


def test_cli_pick_rejects_a_misspelt_needs(cli_store):
    r = run("pick", *pick_args(**{"--proposal": json.dumps({"mode": "recreate", "needs": "multibody"})}))
    assert r.exit_code == 2 and "needs" in r.output
    assert cli_store.list_favorites() == []


# Belt and braces: a malformed `needs` that got into the database some other way (an older row, a hand
# edit, `mark_favorite(proposal=...)`) must hold the pick, never approve it and never break `fav list`.


@pytest.mark.parametrize("needs", [5, {"multi_body": True}, ["multi-body"], ["multi_body", 3], "multibody", ""])
def test_a_malformed_stored_needs_holds_the_pick_instead_of_failing_open_or_raising(cli_store, needs):
    store = cli_store
    f = store.add_favorite(
        Favorite(url="https://www.instagram.com/reel/Zz9/", platform="instagram", status="new",
                 total_score=95.0, scores={"feasibility": 10.0}, proposal={"mode": "recreate", "needs": needs})
    )  # fmt: skip
    assert auto_decision(f) == "hold"
    r = run("list")  # `fav list` prints every new pick with its auto_decision: it must not raise
    assert r.exit_code == 0, r.output
    assert [row["auto_decision"] for row in json.loads(r.stdout)] == ["hold"]


def test_mark_favorite_validates_a_proposal_it_is_given():
    store = make_store()
    f = pick(store, B1)
    with pytest.raises(ValueError, match="needs"):
        favorites.mark_favorite(store, f.id, "approved", proposal={"mode": "recreate", "needs": 5})
    assert store.get_favorite(f.id).proposal.get("needs") is None
    ok = favorites.mark_favorite(store, f.id, "approved", proposal={"mode": "recreate", "needs": "multi_body"})
    assert ok.proposal["needs"] == "multi_body"


# ---- a pick that is not matched to a seeded character yet -----------------------------------


def test_a_pick_may_have_no_character_yet_but_an_unknown_slug_is_refused():
    store = make_store()
    f = pick(store, B1, character_slug=None)
    assert f.character_slug is None and f.status == "new"
    with pytest.raises(ValueError, match="unknown character"):
        pick(store, B2, character_slug="nobody")


# ---- the queue per character, the seen list, and free text from files -----------------------------------

NASTY = "it's $(echo pwned) `x` \"q\" ; && | > \U0001F499"


def approved(store, spec, days):
    f = pick(store, spec)
    aged(store, f.id, days)
    return decide(store, f.id, "approve", "", "rule")


def test_next_favorites_can_be_limited_to_one_character():
    store = make_store()
    b1, b2, d2 = approved(store, B1, 5), approved(store, B2, 4), approved(store, D2, 3)
    assert [f.id for f in next_favorites(store, 1)] == [b1.id]  # oldest overall: reginald's
    assert [f.id for f in next_favorites(store, 1, character="biscuit")] == [d2.id]
    assert [f.id for f in next_favorites(store, 5, character="reginald")] == [b1.id, b2.id]
    with pytest.raises(ValueError, match="unknown character"):
        next_favorites(store, 1, character="nobody")


def test_cli_list_next_with_a_character(cli_store):
    b1, d2 = approved(cli_store, B1, 5), approved(cli_store, D2, 3)
    rows = json.loads(run("list", "--next", "1", "--character", "biscuit").stdout)
    assert [x["id"] for x in rows] == [d2.id]
    assert run("list", "--next", "1", "--character", "nobody").exit_code == 2
    new = pick(cli_store, D4)
    rows = json.loads(run("list", "--status", "new", "--character", "biscuit").stdout)
    assert [x["id"] for x in rows] == [new.id]


def test_seen_ids_are_the_newest_video_ids_first_and_capped():
    store = make_store()
    a, b, c = pick(store, B1), pick(store, D2), pick(store, D4)  # instagram reel, tiktok, tiktok
    for f, days in ((a, 3), (b, 2), (c, 1)):
        aged(store, f.id, days)
    assert seen_ids(store, 100) == ["7673905586383113503", "7688386199270001953", "Dde-rPWCOC6"]
    assert seen_ids(store, 2) == ["7673905586383113503", "7688386199270001953"]
    assert seen_ids(store, 0) == []
    with pytest.raises(ValueError):
        seen_ids(store, -1)


def test_seen_includes_every_status_so_a_rescan_never_resurfaces_a_skip():
    store = make_store()
    f = pick(store, B1)
    decide(store, f.id, "skip", "off brand", "owner")
    assert seen_ids(store, 100) == ["Dde-rPWCOC6"]


def test_cli_seen(cli_store):
    pick(cli_store, B1)
    pick(cli_store, D2)
    r = run("seen", "--limit", "1")
    assert r.exit_code == 0, r.output
    assert len(json.loads(r.stdout)) == 1
    assert len(json.loads(run("seen").stdout)) == 2  # default limit 100
    assert run("seen", "--limit", "101").exit_code == 2  # vidIQ takes at most 100


def test_cli_pick_proposal_from_a_file(cli_store, tmp_path):
    f = tmp_path / "proposal.json"
    f.write_text(json.dumps({"mode": "recreate", "hook": NASTY, "concept": NASTY}), encoding="utf-8")
    args = pick_args(B1)
    args[args.index("--proposal")] = "--proposal-file"
    args[args.index("--proposal-file") + 1] = str(f)
    r = run("pick", *args)
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["proposal"]["hook"] == NASTY
    both = pick_args(B2, **{"--proposal": "{}"}) + ["--proposal-file", str(f)]
    r = run("pick", *both)
    assert r.exit_code == 2 and "--proposal" in r.output
    f.write_text("{not json")
    bad = pick_args(D2)
    bad[bad.index("--proposal")] = "--proposal-file"
    bad[bad.index("--proposal-file") + 1] = str(f)
    assert run("pick", *bad).exit_code == 2
    assert len(cli_store.list_favorites()) == 1


def test_cli_mark_breakdown_and_note_from_files(cli_store, tmp_path):
    f = pick(cli_store, B1)
    decide(cli_store, f.id, "approve", "", "rule")
    bd, note = tmp_path / "bd.md", tmp_path / "note.txt"
    bd.write_text("## beats\n" + NASTY + "\n", encoding="utf-8")
    note.write_text(NASTY + "\n", encoding="utf-8")
    r = run("mark", f.id, "--status", "analysed", "--breakdown-file", str(bd), "--note-file", str(note))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["breakdown_md"] == "## beats\n" + NASTY and out["note"] == NASTY
    r = run("mark", f.id, "--status", "analysed", "--breakdown", "x", "--breakdown-file", str(bd))
    assert r.exit_code == 2 and "--breakdown" in r.output
    assert run("mark", f.id, "--status", "analysed", "--note-file", str(tmp_path / "nope")).exit_code == 2


def test_cli_decide_reason_from_a_file(cli_store, tmp_path):
    d4 = pick(cli_store, D4)
    f = tmp_path / "reason.txt"
    f.write_text(NASTY + "\n", encoding="utf-8")
    r = run("decide", d4.id, "--decision", "approve", "--reason-file", str(f), "--by", "analyst")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["proposal"]["decision"]["reason"] == NASTY
    o4 = pick(cli_store, O4)
    r = run("decide", o4.id, "--decision", "skip", "--reason", "x", "--reason-file", str(f), "--by", "analyst")
    assert r.exit_code == 2 and "--reason" in r.output
    r = run("decide", o4.id, "--reason-file", str(f))  # a reason without --decision means nothing
    assert r.exit_code == 2


# ---- the owner's instructions from the terminal's "Make it" sheet (migration 0007 decide_pick) -------------

OWNER = {"owner_note": "slow-mo on the drop", "owner_mode": "dropin", "owner_presence": "star"}


def owner_approved(store, spec=B1, slug=None):
    """What decide_pick writes: an approved pick whose proposal carries the owner's note, mode and presence."""
    f = pick(store, spec, **({"character_slug": slug} if slug else {}))
    return store.update_favorite(
        f.id, status="approved",
        proposal={**f.proposal, **OWNER, "decision": {"decision": "approve", "by": "owner", "reason": None}},
    )


def test_fav_list_next_hands_the_daily_run_the_owners_note_mode_and_presence(cli_store):
    f = owner_approved(cli_store)
    (row,) = json.loads(run("list", "--next", "1", "--character", "reginald").stdout)
    assert row["id"] == f.id
    assert {k: row["proposal"][k] for k in OWNER} == OWNER  # the skill reads proposal.owner_note / owner_mode / owner_presence
    (same,) = json.loads(run("list", "--status", "approved").stdout)
    assert same["proposal"]["owner_note"] == "slow-mo on the drop"


def test_a_decision_after_the_owners_sheet_keeps_the_owners_instructions():
    store = make_store()
    f = owner_approved(store)
    again = decide(store, f.id, "approve", "", "rule")
    assert {k: again.proposal[k] for k in OWNER} == OWNER
    held = mark_favorite(store, f.id, "analysed", breakdown_md="beats")
    assert {k: held.proposal[k] for k in OWNER} == OWNER  # a status change never rewrites the proposal


def test_both_makes_one_clip_per_character_from_the_same_video():
    """decide_pick(also_character) files a sibling row for the other character: each has its own queue."""
    store = make_store()
    mine = owner_approved(store, B1, "reginald")
    twin = store.add_favorite(Favorite(
        url=mine.url, platform=mine.platform, creator_handle=mine.creator_handle, views=mine.views, outlier_x=mine.outlier_x,
        origin=mine.origin, character_slug="biscuit", proposal=dict(mine.proposal), scores=dict(mine.scores),
        total_score=mine.total_score, status="approved",
    ))
    assert [f.id for f in next_favorites(store, 5, "reginald")] == [mine.id]
    assert [f.id for f in next_favorites(store, 5, "biscuit")] == [twin.id]
    assert twin.proposal["owner_note"] == "slow-mo on the drop"
    # two rows, one video: vidIQ's exclude list names it once, so the 100-id cap is not wasted on duplicates
    assert seen_ids(store, 100) == ["Dde-rPWCOC6"]


def test_seen_ids_cap_counts_distinct_videos():
    store = make_store()
    a, b = pick(store, B1), pick(store, D2)
    twin = store.add_favorite(Favorite(url=a.url, platform=a.platform, character_slug="biscuit", status="approved"))
    for f, days in ((b, 3), (a, 2), (twin, 1)):
        aged(store, f.id, days)
    assert seen_ids(store, 2) == ["Dde-rPWCOC6", "7688386199270001953"]  # not [a, a]: the twin adds no new id


# ---- the pick card: tier, theme, thumbnail, props and music (migration 0008) ---------------------------------

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def days_ago(n: float) -> str:
    return (NOW - timedelta(days=n)).isoformat()


@pytest.mark.parametrize(
    ("proposal", "outlier_x", "tier"),
    [
        # a Genjutsu gallery clip is a gallery pick whatever its numbers (source kind or preset)
        ({"source_kind": "higgsfield_library", "posted_at": days_ago(2)}, 900, "gallery"),
        ({"preset_id": "hf-preset-1"}, None, "gallery"),
        ({"preset_id": "   "}, 12, "viral_now"),  # a blank preset is no preset
        # big outlier, posted within 14 days: viral now
        ({"posted_at": days_ago(3)}, 100, "viral_now"),
        ({"posted_at": days_ago(14)}, 1393, "viral_now"),
        # early and climbing: posted within 4 days with an outlier of 5 or more (but under 100)
        ({"posted_at": days_ago(1)}, 5, "rising"),
        ({"posted_at": days_ago(4)}, 44.6, "rising"),
        ({"posted_at": days_ago(1)}, 4.9, "viral_now"),  # not enough outlier to be "rising"
        ({"posted_at": days_ago(6)}, 44.6, "viral_now"),  # too old for rising, not old enough for iconic
        # famous and old: months to years
        ({"posted_at": days_ago(91)}, 3.0, "iconic"),
        ({"posted_at": days_ago(400)}, 2000, "iconic"),
        ({"posted_at": days_ago(90)}, 3.0, "viral_now"),  # "older than 90 days" is strict
        # the rules are in order: a fresh mega-outlier is viral now, not rising
        ({"posted_at": days_ago(2)}, 1000, "viral_now"),
        # no age known: the fallback
        ({}, None, "viral_now"),
        ({"posted_at": "not a date"}, 50, "viral_now"),
        ({"age_days": 120}, 10, "iconic"),  # the scan's `age_days` works as well as a date
        ({"age_days": 2}, 8, "rising"),
    ],
)
def test_default_tier_follows_the_owners_rules(proposal, outlier_x, tier):
    assert favorites.default_tier(proposal, outlier_x, NOW) == tier


def test_default_tier_agrees_with_the_terminals_on_the_shared_cases():
    """terminal/src/lib/parity-cases.json is read by the terminal's defaultTier tests too: one list, two implementations."""
    path = Path(__file__).resolve().parents[1] / "terminal" / "src" / "lib" / "parity-cases.json"
    cases = json.loads(path.read_text())
    now = datetime.fromisoformat(cases["now"].replace("Z", "+00:00"))
    assert len(cases["tier"]) >= 10
    for c in cases["tier"]:
        proposal = {"source_kind": "higgsfield_library"} if c["gallery"] else {}
        if c["days_ago"] is not None:
            proposal["posted_at"] = (now - timedelta(days=c["days_ago"])).isoformat()
        assert favorites.default_tier(proposal, c["outlier_x"], now) == c["expect"], c


def test_the_four_tiers_have_exactly_the_owners_keys_and_labels():
    assert favorites.TIER_LABELS == {
        "iconic": "Broke the internet", "viral_now": "Viral now", "rising": "Up and coming", "gallery": "Ready to drop in",
    }
    assert favorites.TIERS == ("iconic", "viral_now", "rising", "gallery")  # the order the terminal shows them in


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("tier", "famous"), ("tier", 3), ("tier", ""),
        ("theme", ""), ("theme", "x" * 61), ("theme", 5),
        ("thumbnail_url", "http://cdn.example.com/a.jpg"), ("thumbnail_url", "ftp://x/a.jpg"), ("thumbnail_url", "https://"),
        ("thumbnail_url", "https://cdn.example.com/a b.jpg"), ("thumbnail_url", "javascript:alert(1)"), ("thumbnail_url", "//cdn.example.com/a.jpg"),
        ("thumbnail_url", 7), ("thumbnail_url", "https://" + "a" * 2100 + ".com/x.jpg"),
        ("preview_url", "http://cdn.example.com/a.mp4"), ("preview_url", "https://cdn.example.com/a.png"),
        ("preview_url", "https://cdn.example.com/page.html"),
        ("posted_at", "last tuesday"), ("posted_at", 20261001),
        ("owner_music", "spotify"),
        ("owner_props", "gold chain"), ("owner_props", ["a", "b", "c", "d"]), ("owner_props", [""]), ("owner_props", ["x" * 41]),
        ("owner_props", [3]),
    ],
)
def test_a_pick_card_field_that_is_malformed_is_refused_at_the_door(key, bad):
    store = make_store()
    with pytest.raises(ValueError, match=key):
        pick(store, B1, proposal={"mode": "recreate", key: bad})
    assert store.list_favorites() == []


def test_a_well_formed_card_is_stored_as_given():
    store = make_store()
    card = {
        "mode": "recreate", "tier": "iconic", "theme": "deadpan at work", "posted_at": "2025-06-01",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "preview_url": "https://d1.cloudfront.net/gallery/abc.mp4?Expires=123&Signature=x",
    }
    f = pick(store, B1, proposal=card)
    assert {k: f.proposal[k] for k in card} == card


def test_the_card_fields_are_validated_when_a_proposal_is_marked_too():
    store = make_store()
    f = decide(store, pick(store, B1).id, "approve", "ok", "analyst")
    with pytest.raises(ValueError, match="thumbnail_url"):
        mark_favorite(store, f.id, "analysed", proposal={**f.proposal, "thumbnail_url": "http://x/a.jpg"})
    ok = mark_favorite(store, f.id, "analysed", proposal={**f.proposal, "thumbnail_url": "https://x.example/a.jpg"})
    assert ok.proposal["thumbnail_url"] == "https://x.example/a.jpg"


def test_fav_list_exposes_the_tier_the_analyst_set_and_the_one_it_derived(cli_store, monkeypatch):
    monkeypatch.setattr(favorites, "now_london", lambda: NOW)
    pick(cli_store, B1, proposal={"mode": "recreate", "tier": "iconic", "theme": "deadpan at work"})
    pick(cli_store, D2, proposal={"mode": "dropin", "posted_at": days_ago(1)})
    rows = {r["creator_handle"]: r for r in json.loads(run("list", "--status", "new").stdout)}
    set_by_analyst = rows["@eatfryhaven"]
    assert (set_by_analyst["tier"], set_by_analyst["tier_label"], set_by_analyst["tier_derived"]) == ("iconic", "Broke the internet", False)
    derived = rows["@tillandsialover"]
    assert (derived["tier"], derived["tier_label"], derived["tier_derived"]) == ("viral_now", "Viral now", True)  # 1177x
    assert set_by_analyst["proposal"]["theme"] == "deadpan at work"  # the theme rides in the proposal


def test_fav_list_derives_rising_and_gallery_when_the_analyst_set_nothing(cli_store, monkeypatch):
    monkeypatch.setattr(favorites, "now_london", lambda: NOW)
    pick(cli_store, D4, proposal={"mode": "recreate", "posted_at": days_ago(2)})  # 131.8x, 2 days old: viral now
    pick(cli_store, O4, proposal={"mode": "recreate", "posted_at": days_ago(3)})  # 3.8x: not rising, viral now by fallback
    pick(cli_store, B2, proposal={"mode": "recreate", "preset_id": "hf-1", "thumbnail_url": "https://t.example/x.jpg"})
    tiers = {r["creator_handle"]: r["tier"] for r in json.loads(run("list", "--status", "new").stdout)}
    assert tiers == {"@banana.the.wiener": "viral_now", "@theeuropeankid": "viral_now", "@drink321coffee": "gallery"}


def test_fav_pick_files_the_card_from_the_proposal_file(cli_store, tmp_path):
    r = run("pick", *pick_args_in_file(
        tmp_path, D2, tier="viral_now", theme="pet with a human job", posted_at="2026-10-01",
        thumbnail_url="https://p16.tiktokcdn.com/obj/x.jpg",
    ))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["tier"], out["proposal"]["theme"], out["proposal"]["thumbnail_url"]) == (
        "viral_now", "pet with a human job", "https://p16.tiktokcdn.com/obj/x.jpg",
    )


def test_fav_pick_refuses_an_insecure_thumbnail_without_storing_anything(cli_store, tmp_path):
    r = run("pick", *pick_args_in_file(tmp_path, B1, thumbnail_url="http://insecure.example/a.jpg"))
    assert r.exit_code == 2 and "thumbnail_url" in r.output
    assert cli_store.list_favorites() == []


def test_fav_list_hands_the_daily_run_the_owners_props_and_music(cli_store):
    f = owner_approved(cli_store)
    cli_store.update_favorite(f.id, proposal={**f.proposal, "owner_props": ["tiny gold chain", "aviator shades"], "owner_music": "original"})
    (row,) = json.loads(run("list", "--next", "1", "--character", "reginald").stdout)
    assert row["proposal"]["owner_props"] == ["tiny gold chain", "aviator shades"]  # the skill dresses him in them
    assert row["proposal"]["owner_music"] == "original"


# ---- Genjutsu gallery picks: no platform URL (owner decision 2026-10-05: gallery clips are filed daily as backups) -----------


GAL = dict(platform="higgsfield", creator_handle=None, views=None, outlier_x=None, character_slug="biscuit",
           judged=(7, 8, 9, 8), proposal={"mode": "dropin", "preset_id": "hf-genjutsu-pets-04", "thumbnail_url": "https://d1.cloudfront.net/t/a.jpg",
                                          "preview_url": "https://d1.cloudfront.net/p/a.mp4", "tier": "gallery", "theme": "skilled upright dance"})


def gallery_pick(store, spec=GAL, **over):
    spec = {**spec, **over}
    fresh, fit, feas, sat = spec["judged"]
    return add_pick(
        store, spec.get("url", ""), spec["platform"], spec["creator_handle"], spec["views"], spec["outlier_x"], spec["character_slug"],
        spec["proposal"], freshness=fresh, fit=fit, feasibility=feas, saturation=sat,
    )


def test_a_gallery_pick_is_keyed_by_its_preset_not_by_a_platform_url():
    store = make_store()
    f = gallery_pick(store)
    assert f.url == "higgsfield-preset:hf-genjutsu-pets-04" and f.platform == "higgsfield"
    assert f.proposal["preset_id"] == "hf-genjutsu-pets-04" and f.status == "new" and f.total_score is not None
    again = gallery_pick(store)
    assert again.id == f.id and len(store.list_favorites()) == 1  # one preset is one pick: a rescan never doubles it


def test_a_gallery_pick_needs_a_preset_id_and_refuses_a_made_up_url():
    store = make_store()
    for proposal in ({"mode": "dropin"}, {"preset_id": ""}, {"preset_id": "  "}, {"preset_id": 5}, {"preset_id": "has space"}):
        with pytest.raises(ValueError, match="preset_id"):
            gallery_pick(store, proposal=proposal)
    with pytest.raises(ValueError, match="gallery"):
        gallery_pick(store, url="https://www.tiktok.com/@x/video/1")  # a platform URL is not a gallery pick's key
    assert store.list_favorites() == []


def test_a_gallery_pick_is_a_gallery_tier_pick_and_vidiq_is_not_told_to_exclude_it():
    store = make_store()
    f = gallery_pick(store, proposal={**GAL["proposal"], "tier": None})
    pick(store, D2)
    assert favorites.default_tier(f.proposal, f.outlier_x, NOW) == "gallery"
    assert seen_ids(store, 10) == ["7688386199270001953"]  # only platform ids go to excludeContentIds


def test_fav_pick_files_a_gallery_clip_from_the_proposal_file_without_a_url(cli_store, tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(GAL["proposal"]))
    r = run("pick", "--platform", "higgsfield", "--views", "0", "--outlier-x", "0", "--character", "biscuit",
            "--freshness", "7", "--fit", "8", "--feasibility", "9", "--saturation", "8", "--proposal-file", str(f))  # fmt: skip
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["url"] == "higgsfield-preset:hf-genjutsu-pets-04" and out["tier"] == "gallery" and out["duplicate"] is False
    assert out["proposal"]["preview_url"] == "https://d1.cloudfront.net/p/a.mp4"

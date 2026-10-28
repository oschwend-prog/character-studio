"""``studio hits``: the cloud hits job (terminal v3 spec section 10; plan Task 6). No network, ever: the ScrapeCreators client is
driven through an ``httpx.MockTransport`` that answers with the trimmed real-shape responses of ``tests/fixtures/scrapecreators``
(from the API's own OpenAPI examples), and every test counts what it would have spent (the free account has about 100 credits).
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from typer.testing import CliRunner

from studio import drop, hits, lunar
from studio.cli import app
from studio.config import LONDON
from studio.hits import ScrapeCreators, ScrapeCreatorsError, hit_score, parse_instagram, parse_tiktok
from studio.models import Body, Character, Favorite, Hit, HitSpend, Run, RunKind
from studio.store import MemoryStore

FIX = Path(__file__).resolve().parent / "fixtures" / "scrapecreators"
NOW = datetime(2026, 10, 8, 6, 30, tzinfo=LONDON)
KEY = "sc-test-key-0123456789"
CONFIG = {
    "hits": {
        "daily_credit_cap": 45, "download_cap_per_day": 2, "auto_file_per_character": 3, "auto_file_general": 3,
        "keywords": {"franz": ["dog dance", "dachshund", "dog trend"], "reginald": ["dance trend", "deadpan dance", "butler"],
                     "lenny": ["boss on the phone", "office dance", "dance challenge"]},
        "general": {"keywords": ["viral dance", "dance trend", "trend challenge", "funny dance"], "tiktok_regions": ["GB", "US"],
                    "instagram_trending": True},
    }
}  # fmt: skip


def fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def roster_store(*, franz="live", reginald="live", lenny="live") -> MemoryStore:
    store = MemoryStore()
    store.add_character(Character(slug="franz", name="Franz", status=franz, bodies=[Body.biped, Body.quadruped]))
    store.add_character(Character(slug="lenny", name="Lenny Gold", status=lenny, bodies=[Body.biped]))
    store.add_character(Character(slug="reginald", name="Reginald", status=reginald, bodies=[Body.biped]))
    return store


# ---- a TikTok and an Instagram item in the API's own shape, varied ------------------------------------------------------------------


def tt_item(n: int = 1, *, views=1_000_000, followers=50_000, days=1.0, seconds=12.0, handle=None, photo=False, ad=False, desc=None) -> dict:
    item = copy.deepcopy(fixture("tiktok_search_keyword")["search_item_list"][0])
    aweme = str(7_400_000_000_000_000_000 + n)
    handle = handle or f"dancer{n}"
    posted = NOW - timedelta(days=days)
    item.update(aweme_id=aweme, url=f"https://www.tiktok.com/@{handle}/video/{aweme}", create_time=int(posted.timestamp()))
    item["create_time_utc"] = posted.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    item["statistics"]["play_count"] = views
    item["author"].update(unique_id=handle, follower_count=followers)
    item["video"]["duration"] = int(seconds * 1000)
    item["is_ad"] = ad
    if desc is not None:
        item["desc"] = desc
    if photo:
        item["image_post_info"] = copy.deepcopy(fixture("tiktok_trending_feed")["aweme_list"][0]["image_post_info"])
        item["url"] = f"https://www.tiktok.com/@{handle}/photo/{aweme}"
    return item


def ig_item(n: int = 1, *, likes=20_000, followers=40_000, days=1.0, seconds=12.0, handle=None) -> dict:
    item = copy.deepcopy(fixture("instagram_reels_search")["reels"][0])
    code = f"DTest{n:04d}x"
    item.update(shortcode=code, url=f"https://www.instagram.com/reel/{code}/", video_duration=seconds, like_count=likes)
    item["taken_at"] = (NOW - timedelta(days=days)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    item["owner"].update(username=handle or f"reeler{n}", follower_count=followers)
    return item


class FakeAPI:
    """The ScrapeCreators API as an ``httpx.MockTransport``: each path answers from a queue (a dict, an int status, or a
    callable), else a default page; every request is recorded (path, params, headers)."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.queues: dict[str, list] = {}
        self.media = b""
        self.charge = 1
        self.media_routes: dict[str, object] = {}  # a media URL -> its own answer (a redirect, an error)

    def answer(self, path: str, *bodies) -> None:
        self.queues.setdefault(path, []).extend(bodies)

    def default(self, path: str) -> dict:
        head = {"success": True, "credits_remaining": 90, "credits_charged": self.charge}
        if path == "/v1/tiktok/search/keyword":
            return {**head, "search_item_list": [], "cursor": 0}
        if path == "/v1/tiktok/get-trending-feed":
            return {**head, "aweme_list": []}
        if path == "/v2/instagram/reels/search":
            return {**head, "reels": []}
        if path == "/v1/instagram/reels/trending":
            return {**head, "data": {"reels": []}}
        raise AssertionError(f"unexpected path {path}")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host != "api.scrapecreators.com":
            routed = self.media_routes.get(str(request.url))
            if routed is not None:
                return routed(request) if callable(routed) else routed
            return httpx.Response(200, content=self.media, headers={"content-type": "video/mp4"})
        queue = self.queues.get(request.url.path)
        body = queue.pop(0) if queue else self.default(request.url.path)
        if callable(body):
            body = body(request)
        if isinstance(body, httpx.Response):
            return body
        if isinstance(body, int):
            return httpx.Response(body, json={"success": False, "message": "nope"})
        return httpx.Response(200, json=body)

    def client(self, key: str = KEY, **kw) -> ScrapeCreators:
        return ScrapeCreators(key, http=httpx.Client(transport=httpx.MockTransport(self)), **kw)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests if r.url.host == "api.scrapecreators.com"]


def page(path: str, items: list[dict], credits: int = 1) -> dict:
    head = {"success": True, "credits_remaining": 90, "credits_charged": credits}
    if path == "/v1/tiktok/search/keyword":
        return {**head, "search_item_list": items, "cursor": 10}
    if path == "/v1/tiktok/get-trending-feed":
        return {**head, "aweme_list": items}
    if path == "/v2/instagram/reels/search":
        return {**head, "reels": items}
    return {**head, "data": {"reels": items}}


TT_SEARCH, TT_TREND, IG_SEARCH, IG_TREND = (
    "/v1/tiktok/search/keyword", "/v1/tiktok/get-trending-feed", "/v2/instagram/reels/search", "/v1/instagram/reels/trending",
)


# ---- the client --------------------------------------------------------------------------------------------------------------------


def test_the_client_asks_the_documented_endpoints_with_the_key_header_only():
    api = FakeAPI()
    sc = api.client()
    sc.tiktok_keyword("dog dance")
    sc.instagram_reels("dog dance")
    sc.instagram_trending()
    sc.tiktok_trending("GB")
    got = [(r.url.path, {k: v[0] for k, v in parse_qs(urlsplit(str(r.url)).query).items()}) for r in api.requests]
    assert got == [
        (TT_SEARCH, {"query": "dog dance", "date_posted": "this-week", "sort_by": "most-liked", "trim": "true"}),
        (IG_SEARCH, {"query": "dog dance", "date_posted": "last-week"}),
        (IG_TREND, {}),
        (TT_TREND, {"region": "GB", "trim": "true"}),
    ]
    for r in api.requests:
        assert r.method == "GET" and str(r.url).startswith("https://api.scrapecreators.com/") and r.headers["x-api-key"] == KEY
    assert KEY not in repr(sc)


def test_a_refusal_is_an_error_with_its_status_and_never_the_key():
    api = FakeAPI()
    api.answer(TT_SEARCH, 401, {"success": False, "message": f"bad key {KEY}"}, lambda r: httpx.Response(200, text="<html>"))
    sc = api.client()
    with pytest.raises(ScrapeCreatorsError) as e:
        sc.tiktok_keyword("x")
    assert e.value.status == 401 and KEY not in str(e.value)
    with pytest.raises(ScrapeCreatorsError) as e:  # success: false
        sc.tiktok_keyword("x")
    assert KEY not in str(e.value) and "***" in str(e.value)
    with pytest.raises(ScrapeCreatorsError):  # not JSON
        sc.tiktok_keyword("x")


def test_the_key_comes_from_the_environment_only():
    assert ScrapeCreators.from_env({}) is None and ScrapeCreators.from_env({"SCRAPECREATORS_API_KEY": "  "}) is None
    assert isinstance(ScrapeCreators.from_env({"SCRAPECREATORS_API_KEY": KEY}), ScrapeCreators)
    with pytest.raises(ValueError):
        ScrapeCreators("")


def test_credits_charged_is_what_a_call_costs_and_one_when_the_answer_does_not_say():
    assert hits.credits_of({"credits_charged": 2}) == 2
    assert hits.credits_of({}) == 1 and hits.credits_of({"credits_charged": "x"}) == 1 and hits.credits_of({"credits_charged": 0}) == 0


# ---- parsing both platforms ------------------------------------------------------------------------------------------------------------


def test_a_tiktok_search_result_becomes_a_hit():
    item = fixture("tiktok_search_keyword")["search_item_list"][0]
    hit = parse_tiktok(item, keyword="dance trend", character="reginald")
    assert isinstance(hit, Hit) and hit.platform == "tiktok"
    assert hit.url == "https://www.tiktok.com/@thatgreygentlemanitdxz/video/7268287584244124971"
    assert hit.creator_handle == "@thatgreygentlemanitdxz" and hit.followers == 147630
    assert (hit.views, hit.likes, hit.comments, hit.shares, hit.saves) == (1282645, 481608, 187, 2721, 6978)
    assert hit.posted_at == datetime(2023, 8, 17, 13, 48, 40, tzinfo=timezone.utc)
    assert hit.caption == "Tìm 'musclesandnursing'" and hit.duration_s == pytest.approx(22.874)
    assert hit.thumbnail_url.startswith("https://p16-sign.tiktokcdn-us.com/") and hit.sound is None  # the trimmed answer has no music
    assert (hit.keyword, hit.character_slug, hit.status) == ("dance trend", "reginald", "new")
    assert hit.reach == pytest.approx(1282645 / 147630)


def test_an_instagram_search_result_becomes_a_hit_with_no_views():
    item = fixture("instagram_reels_search")["reels"][0]
    hit = parse_instagram(item, keyword="dog dance", character="franz")
    assert hit.platform == "instagram" and hit.url == "https://www.instagram.com/reel/DOq6eV6iIgD/"
    assert hit.creator_handle == "@fetchmycamera_" and hit.followers == 188406
    assert hit.views is None and hit.reach is None  # Instagram's search gives no play count: never guessed into the record
    assert (hit.likes, hit.comments, hit.shares, hit.saves) == (3487, 90, None, None)
    assert hit.posted_at == datetime(2025, 9, 16, 16, 56, 45, tzinfo=timezone.utc)
    assert hit.sound == "Smiling Heart" and hit.duration_s == pytest.approx(75.7) and len(hit.caption) == 300
    assert hit.thumbnail_url.startswith("https://scontent-sjc3-1.cdninstagram.com/")


def test_an_instagram_trending_reel_becomes_a_general_hit():
    item = fixture("instagram_reels_trending")["data"]["reels"][0]
    hit = parse_instagram(item, keyword="instagram trending", character=None)
    assert hit.url == "https://www.instagram.com/reel/DYt13O8gLoE/" and hit.creator_handle == "@creator"
    assert (hit.views, hit.likes, hit.comments, hit.followers, hit.reach) == (456789, 12345, 123, None, None)
    assert hit.character_slug is None and hit.thumbnail_url == "https://scontent.cdninstagram.com/v/t51.2885-15/example.jpg"
    assert hit.posted_at == datetime(2026, 1, 2, 18, 32, 11, tzinfo=timezone.utc)


def test_photo_carousels_ads_and_odd_links_are_skipped_at_parse():
    assert parse_tiktok(fixture("tiktok_trending_feed")["aweme_list"][0], keyword="t", character=None) == "photo"
    assert parse_tiktok(tt_item(photo=True), keyword="t", character=None) == "photo"
    assert parse_tiktok(tt_item(ad=True), keyword="t", character=None) == "ad"
    odd = tt_item()
    odd["url"] = "https://vm.tiktok.com/ZMabc/"
    odd["author"]["unique_id"] = None
    assert parse_tiktok(odd, keyword="t", character=None) == "bad_url"
    reel = ig_item()
    reel["is_video"] = False
    assert parse_instagram(reel, keyword="t", character=None) == "photo"
    carousel = fixture("instagram_reels_trending")["data"]["reels"][0] | {"media_type": 8}
    assert parse_instagram(carousel, keyword="t", character=None) == "photo"
    paid = ig_item() | {"is_paid_partnership": True}
    assert parse_instagram(paid, keyword="t", character=None) == "ad"


def test_a_follower_count_of_zero_is_unknown_not_infinite_reach():
    hit = parse_tiktok(tt_item(followers=0), keyword="t", character=None)
    assert hit.followers is None and hit.reach is None


def test_long_and_old_videos_are_skipped():
    fine = parse_tiktok(tt_item(seconds=59.9, days=13.9), keyword="t", character=None)
    assert hits.skip_reason(fine, NOW) is None
    assert hits.skip_reason(parse_tiktok(tt_item(seconds=61), keyword="t", character=None), NOW) == "too_long"
    assert hits.skip_reason(parse_instagram(fixture("instagram_reels_search")["reels"][0], keyword="t", character=None), NOW) == "too_long"
    assert hits.skip_reason(parse_tiktok(tt_item(days=14.5), keyword="t", character=None), NOW) == "too_old"


# ---- the score ----------------------------------------------------------------------------------------------------------------------


def scored(**kw) -> int:
    return hit_score(parse_tiktok(tt_item(**kw), keyword="t", character=None), NOW)


def test_the_score_puts_reach_over_raw_views_and_fresh_over_old():
    small_account = scored(views=300_000, followers=10_000)  # 30x its followers
    big_account = scored(views=3_000_000, followers=3_000_000)  # 10x the views, 1x its followers
    assert small_account > big_account
    assert scored(days=1) > scored(days=6) > scored(days=12)
    assert scored(views=5_000_000) > scored(views=50_000)  # same reach band, more views: hotter
    for kw in ({}, {"views": 10**9, "followers": 1, "days": 0}, {"views": 0, "followers": 10**9, "days": 40}):
        assert 0 <= scored(**kw) <= 100
    assert scored(views=10**9, followers=1, days=0) == 100


def test_without_views_the_likes_stand_in_for_the_score_only():
    reel = parse_instagram(ig_item(likes=50_000, followers=20_000), keyword="t", character=None)
    assert reel.views is None and reel.reach is None
    assert hit_score(reel, NOW) == hit_score(parse_tiktok(tt_item(views=500_000, followers=20_000), keyword="t", character=None), NOW)


# ---- the pull -------------------------------------------------------------------------------------------------------------------


def test_the_plan_takes_the_trending_feeds_then_each_characters_keywords_in_turn_then_the_broad_searches():
    store = roster_store(lenny="paused")
    plan = [c.label for c in hits.plan_calls(store, hits.hits_config(CONFIG))]
    assert plan[:3] == ["tiktok trending GB", "tiktok trending US", "instagram trending"]
    assert plan[3:8] == [
        "tiktok search 'dog dance' (franz)", "instagram search 'dog dance' (franz)",
        "tiktok search 'dance trend' (reginald)", "instagram search 'dance trend' (reginald)", "tiktok search 'viral dance'",
    ]
    assert not any("lenny" in p for p in plan)  # a paused character is not searched for
    full = hits.plan_calls(roster_store(), hits.hits_config(CONFIG))
    assert len(full) == 3 + 3 * 3 * 2 + 4 == 25  # exactly the day's search budget: 45 less 2 downloads of 10


def test_pull_keeps_new_hits_updates_known_ones_and_counts_the_skips():
    store = roster_store()
    api = FakeAPI()
    known = store.upsert_hit(Hit(platform="tiktok", url=f"https://www.tiktok.com/@dancer2/video/{7_400_000_000_000_000_002}",
                                 views=10, followers=50_000, status="dismissed", created_at=NOW - timedelta(days=2),
                                 last_seen=NOW - timedelta(days=2)))[0]  # fmt: skip
    api.answer(TT_TREND, page(TT_TREND, [fixture("tiktok_trending_feed")["aweme_list"][0], tt_item(1, desc="a recipe, not a dance")]))
    api.answer(TT_SEARCH, page(TT_SEARCH, [tt_item(2, views=900_000), tt_item(3, seconds=90), tt_item(4, days=20), tt_item(1)]))
    api.answer(IG_SEARCH, page(IG_SEARCH, [ig_item(5)]))
    out = hits.pull(store, api.client(), CONFIG, NOW)
    assert out["calls"] == 25 and out["credits"] == out["day_credits"] == 25 and out["stopped"] is None and out["errors"] == []
    assert out["kept"] == 2 and out["updated"] == 1
    assert out["skipped"] == {"photo": 1, "too_long": 1, "too_old": 1, "duplicate": 1}
    by_url = {h.url: h for h in store.list_hits()}
    general = by_url[f"https://www.tiktok.com/@dancer1/video/{7_400_000_000_000_000_001}"]
    assert general.character_slug is None and general.keyword == "tiktok trending GB"  # kept whatever its topic
    assert by_url["https://www.instagram.com/reel/DTest0005x/"].character_slug == "franz"
    again = store.get_hit(known.id)
    assert again.views == 900_000 and again.status == "dismissed" and again.last_seen == NOW  # numbers refreshed, status kept
    assert again.created_at == NOW - timedelta(days=2) and again.score == hit_score(again, NOW) > 0
    assert again.character_slug == "franz" and again.keyword == "dog dance"  # a general or older hit learns who found it


def capped(cap: int, downloads: int = 0) -> dict:
    return {"hits": {**CONFIG["hits"], "daily_credit_cap": cap, "download_cap_per_day": downloads}}


def test_the_daily_credit_cap_stops_the_run_mid_way():
    api = FakeAPI()
    out = hits.pull(roster_store(), api.client(), capped(3), NOW)
    assert (out["calls"], out["credits"], out["stopped"]) == (3, 3, "cap") and len(api.paths()) == 3
    api = FakeAPI()
    api.charge = 2  # a call that costs more counts what it cost
    out = hits.pull(roster_store(), api.client(), capped(5), NOW)
    assert (out["calls"], out["credits"], out["stopped"]) == (3, 6, "cap")
    out = hits.pull(roster_store(), FakeAPI().client(), capped(0), NOW)
    assert (out["calls"], out["credits"], out["stopped"]) == (0, 0, "cap")
    out = hits.pull(roster_store(), FakeAPI().client(), capped(25, downloads=2), NOW)  # 25 less 2 downloads of 10: 5 searches
    assert (out["calls"], out["credits"], out["stopped"]) == (5, 5, "cap")


def test_the_days_spend_carries_over_to_a_second_run_and_resets_the_next_london_day():
    store = roster_store()
    late = datetime(2026, 10, 8, 23, 30, tzinfo=LONDON)  # 22:30 UTC: still the 8th in London
    first = hits.pull(store, FakeAPI().client(), capped(8), NOW)
    assert (first["calls"], first["credits"], first["day_credits"], first["stopped"]) == (8, 8, 8, "cap")
    api = FakeAPI()
    second = hits.pull(store, api.client(), capped(8), late)  # the same London day: it starts from what the first spent
    assert (second["calls"], second["credits"], second["day_credits"], second["stopped"]) == (0, 0, 8, "cap") and api.paths() == []
    spend = store.get_hit_spend(NOW.date())
    assert (spend.search_credits, spend.download_credits, spend.downloads) == (8, 0, 0)
    api = FakeAPI()
    next_day = hits.pull(store, api.client(), capped(8), late + timedelta(hours=1))  # 00:30 on the 9th in London: a new day
    assert (next_day["calls"], next_day["day_credits"]) == (8, 8) and len(api.paths()) == 8
    assert store.get_hit_spend(datetime(2026, 10, 9).date()).search_credits == 8


def test_downloads_made_today_count_into_the_day_and_the_searches_keep_their_share():
    store = roster_store()
    store.add_hit_spend(NOW.date(), download_credits=10, downloads=1)  # one copy fetched by the night's drop sweep
    out = hits.pull(store, FakeAPI().client(), CONFIG, NOW)
    assert (out["calls"], out["credits"], out["day_credits"]) == (25, 25, 35)  # 45: 10 spent, 10 kept for the last download
    assert hits.download_refusal(store.get_hit_spend(NOW.date()), hits.hits_config(CONFIG)) is None
    store.add_hit_spend(NOW.date(), download_credits=10, downloads=1)
    assert "download_cap_per_day" in hits.download_refusal(store.get_hit_spend(NOW.date()), hits.hits_config(CONFIG))


def test_a_creator_kept_three_times_in_thirty_days_is_skipped():
    store = roster_store()
    for n, age in ((1, 3), (2, 10), (3, 40)):  # two in the last 30 days, one older
        store.upsert_hit(Hit(platform="tiktok", url=f"https://www.tiktok.com/@busy/video/{n}", creator_handle="@busy",
                             created_at=NOW - timedelta(days=age), last_seen=NOW - timedelta(days=age)))  # fmt: skip
    api = FakeAPI()
    api.answer(TT_TREND, page(TT_TREND, [tt_item(11, handle="busy"), tt_item(12, handle="busy"), tt_item(13, handle="other")]))
    out = hits.pull(store, api.client(), CONFIG, NOW)
    assert out["kept"] == 2 and out["skipped"] == {"creator": 1}  # the third in 30 days is kept, the fourth is not
    assert len([h for h in store.list_hits() if h.creator_handle == "@busy"]) == 4


def test_a_refused_key_stops_the_run_and_other_errors_are_listed():
    api = FakeAPI()
    api.answer(TT_TREND, 500)
    api.answer(IG_TREND, 401)
    out = hits.pull(roster_store(), api.client(), CONFIG, NOW)
    assert out["calls"] == 1 and len(api.paths()) == 3 and out["stopped"] is None
    assert [e["call"] for e in out["errors"]] == ["tiktok trending GB", "instagram trending"]
    assert "401" in out["errors"][1]["error"] and KEY not in json.dumps(out)


# ---- auto-filing ------------------------------------------------------------------------------------------------------------------


def stored(
    store, n: int, character: str | None, score: int, *, platform="tiktok", status="new", posted_days=1.0, seen_days=0.0,
    sound=None, caption=None, views=None,
) -> Hit:
    """A stored hit whose score today follows ``score`` (its views grow with it: auto_file ranks by the score of today)."""
    url = f"https://www.tiktok.com/@maker{n}/video/{900 + n}" if platform == "tiktok" else f"https://www.instagram.com/reel/DAuto{n:03d}/"
    return store.upsert_hit(Hit(
        platform=platform, url=url, creator_handle=f"@maker{n}", character_slug=character, score=score, status=status,
        views=views if views is not None else int(10 ** (4 + 3 * score / 100)), posted_at=NOW - timedelta(days=posted_days),
        created_at=NOW, last_seen=NOW - timedelta(days=seen_days), sound=sound, caption=caption,
    ))[0]  # fmt: skip


def test_auto_file_takes_each_live_characters_best_new_hits_up_to_the_cap():
    store = roster_store()
    reg = [stored(store, n, "reginald", score) for n, score in ((1, 40), (2, 90), (3, 70), (4, 80), (5, 10))]
    stored(store, 6, "reginald", 99, status="dismissed")  # "Not for us": never filed
    filed = hits.auto_file(store, CONFIG, NOW)
    assert [f["hit_id"] for f in filed] == [reg[1].id, reg[3].id, reg[2].id]  # best score first, 3 a day
    for f in filed:
        pick = store.get_favorite(f["pick_id"])
        d = pick.proposal["drop"]
        assert f["character"] == pick.character_slug == "reginald" and d["character_by"] == "studio"  # the check may move it
        assert d["state"] == "checking" and d["kind"] == "link" and d["auto_filed"] is True and pick.status == "approved"
        assert d["hit"] == {"id": f["hit_id"], "lane": "reginald"} and pick.url == store.get_hit(f["hit_id"]).url
        assert store.get_hit(f["hit_id"]).status == "dropped"
    assert {p["pick_id"] for p in drop.pending(store, now=NOW)} == {f["pick_id"] for f in filed}  # the drop sweep takes them
    assert hits.auto_file(store, CONFIG, NOW + timedelta(hours=2)) == []  # the same day: the 3 are used up
    assert [f["hit_id"] for f in hits.auto_file(store, CONFIG, NOW + timedelta(days=1))] == [reg[0].id, reg[4].id]


def test_auto_file_never_files_a_link_twice_and_a_paused_character_is_skipped():
    store = roster_store(lenny="paused")
    first, second = stored(store, 1, "reginald", 90), stored(store, 2, "reginald", 80)
    store.add_favorite(Favorite(url=first.url, platform="tiktok", character_slug="franz", status="skipped"))  # already a pick
    lenny = stored(store, 3, "lenny", 99)
    filed = hits.auto_file(store, CONFIG, NOW)
    assert [f["hit_id"] for f in filed] == [second.id]
    assert store.get_hit(first.id).status == "dropped" and len(store.list_favorites(url=first.url)) == 1  # not filed again
    assert store.get_hit(lenny.id).status == "new" and not store.list_favorites(url=lenny.url)  # Lenny is paused


def test_general_hits_are_filed_with_no_character_and_do_not_count_against_a_characters_cap():
    store = roster_store()
    general = [stored(store, n, None, score, platform="instagram") for n, score in ((1, 95), (2, 94), (3, 93), (4, 92))]
    franz = [stored(store, n, "franz", 50) for n in (5, 6, 7)]
    filed = hits.auto_file(store, CONFIG, NOW)
    lanes = [(f["hit_id"], f["character"]) for f in filed]
    assert lanes[:3] == [(h.id, "franz") for h in franz] and lanes[3:] == [(h.id, None) for h in general[:3]]
    for f in filed[3:]:
        pick = store.get_favorite(f["pick_id"])
        d = pick.proposal["drop"]
        assert d["character_by"] == "studio" and d["hit"]["lane"] == "general" and d["auto_filed"] is True
        assert f["provisional"] == pick.character_slug == drop.provisional(store)  # waits under the studio's provisional one
    assert store.get_hit(general[3].id).status == "new"


def test_a_filed_drop_is_tagged_auto_filed_for_learning_and_its_versions_keep_the_tag():
    store = roster_store()
    hit = stored(store, 1, "reginald", 80)
    (f,) = hits.auto_file(store, {"hits": {**CONFIG["hits"], "auto_file_general": 0}}, NOW)
    pick = store.get_favorite(f["pick_id"])
    tags = drop.learn_tags(pick, pick.proposal["drop"], {"hook": "x", "part": "featured"}, version_index=1)
    assert tags["source_kind"] == "auto_filed" and hit.url == pick.url


# ---- the CLI ------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = roster_store()
    monkeypatch.setattr(hits, "open_store", lambda: store)
    monkeypatch.setattr(hits, "load_scan", lambda path=None: CONFIG)
    monkeypatch.setattr(hits, "now_london", lambda: NOW)
    monkeypatch.delenv("LUNARCRUSH_API_KEY", raising=False)  # the gate is off unless a test turns it on
    return store


def test_cli_pull_without_the_key_exits_0_with_a_notice(cli_store, monkeypatch):
    monkeypatch.delenv("SCRAPECREATORS_API_KEY", raising=False)
    r = CliRunner().invoke(app, ["hits", "pull"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["calls"] == 0 and out["filed"] == [] and "SCRAPECREATORS_API_KEY" in out["skipped_run"]
    assert "::notice::" in r.stderr and cli_store.list_hits() == []


def test_cli_pull_out_of_credits_is_a_warning_not_a_red_run(cli_store, monkeypatch):
    # 13-14 Oct the hits job went red every day for an account with no credits left (HTTP 402 on the first call): that is the
    # owner's top-up, not a broken job. A refused key or any other first-call failure still exits 1.
    api = FakeAPI()
    api.answer(TT_TREND, 402)  # the very first call: no credits left
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    r = CliRunner().invoke(app, ["hits", "pull"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["stopped"] == "out_of_credits" and out["calls"] == 0 and "::warning::" in r.stderr
    api = FakeAPI()
    api.answer(TT_TREND, 401)  # a refused key: still red
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    assert CliRunner().invoke(app, ["hits", "pull"]).exit_code == 1


def pulls(store):
    """The ``hits`` runs that are a pull's outcome (``details.pull``), oldest first."""
    return [r for r in store.list_runs(kind="hits") if "pull" in r.details]


def test_a_pull_out_of_credits_leaves_a_line_for_studio_health_though_the_run_is_green(cli_store, monkeypatch):
    """ScrapeCreators answered HTTP 402 from about 11 Oct and nothing recorded it: the job exits 0 on purpose (a warning, not a red run),
    so the outcome is logged as a ``hits`` run that ``studio health`` reads (``health._scrapecreators_problem``)."""
    api = FakeAPI()
    api.answer(TT_TREND, 402)
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    r = CliRunner().invoke(app, ["hits", "pull"])
    assert r.exit_code == 0, r.output
    (line,) = pulls(cli_store)
    assert line.status.value == "error" and line.summary == "Pull: ScrapeCreators is out of credits"
    assert line.started_at == NOW and line.finished_at == NOW
    pull = line.details["pull"]
    assert (pull["day"], pull["calls"], pull["credits"], pull["kept"], pull["stopped"], pull["errors"]) == ("2026-10-08", 0, 0, 0, "out_of_credits", 1)
    assert "402" in pull["error"]
    assert "lunar" not in line.details and hits.lunar_calls_today(cli_store, NOW.date()) == 0  # not a LunarCrush line


def test_every_pull_logs_its_outcome_and_a_healthy_one_is_ok(cli_store, monkeypatch):
    api = FakeAPI()
    api.answer(TT_SEARCH, page(TT_SEARCH, [tt_item(1, views=2_000_000, followers=20_000)]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    r = CliRunner().invoke(app, ["hits", "pull"])
    assert r.exit_code == 0, r.output
    (line,) = pulls(cli_store)
    assert line.status.value == "ok" and line.summary == "Pull: 25 calls, 1 new hits"
    pull = line.details["pull"]
    assert (pull["calls"], pull["kept"], pull["stopped"], pull["errors"], pull["error"]) == (25, 1, None, 0, None)
    assert pull["credits"] == json.loads(r.stdout)["credits"]


def test_a_refused_key_logs_an_error_line_without_the_credits_reason(cli_store, monkeypatch):
    api = FakeAPI()
    api.answer(TT_TREND, 401)
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    assert CliRunner().invoke(app, ["hits", "pull"]).exit_code == 1  # still a red run
    (line,) = pulls(cli_store)
    assert line.status.value == "error" and line.summary == "Pull: no call worked" and line.details["pull"]["stopped"] is None


def test_record_pull_reads_the_outcome_of_a_pull_not_the_pull_itself():
    store = roster_store()
    base = {"calls": 3, "credits": 3, "kept": 2, "updated": 0, "skipped": {}, "errors": []}
    hits.record_pull(store, NOW, {**base, "stopped": "cap"})  # the day's credit cap: a normal stop
    hits.record_pull(store, NOW, {**base, "stopped": "out_of_credits", "errors": [{"call": "x", "error": "  HTTP 402:\n" + "z" * 400}]})
    hits.record_pull(store, NOW, {**base, "calls": 0, "stopped": None, "errors": [{"call": "x", "error": "HTTP 500"}]})
    cap, mid_run, none_worked = pulls(store)
    assert (cap.status.value, cap.details["pull"]["stopped"]) == ("budget_stop", "cap")
    assert mid_run.status.value == "error" and mid_run.details["pull"]["calls"] == 3  # out of credits part-way through the run
    assert mid_run.details["pull"]["error"].startswith("HTTP 402: zzz") and len(mid_run.details["pull"]["error"]) == 200
    assert none_worked.status.value == "error" and none_worked.details["pull"]["stopped"] is None
    assert hits.lunar_calls_today(store, NOW.date()) == 0


def test_a_dry_run_and_a_run_without_the_key_log_nothing(cli_store, monkeypatch):
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: pytest.fail("no client in a dry run")))
    assert CliRunner().invoke(app, ["hits", "pull", "--dry-run"]).exit_code == 0
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: None))
    assert CliRunner().invoke(app, ["hits", "pull"]).exit_code == 0
    assert cli_store.list_runs(kind="hits") == []


def test_a_pull_whose_line_cannot_be_written_still_stands(cli_store, monkeypatch, caplog):
    api = FakeAPI()
    api.answer(TT_SEARCH, page(TT_SEARCH, [tt_item(1, views=2_000_000, followers=20_000)]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    monkeypatch.setattr(hits, "record_pull", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("database is down")))
    with caplog.at_level(logging.WARNING, logger="studio.hits"):
        r = CliRunner().invoke(app, ["hits", "pull"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["kept"] == 1 and len(cli_store.list_hits()) == 1
    assert "could not be logged" in caplog.text and "database is down" not in caplog.text


def test_cli_pull_dry_run_prints_the_plan_and_calls_nothing(cli_store, monkeypatch):
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: pytest.fail("no client in a dry run")))
    r = CliRunner().invoke(app, ["hits", "pull", "--dry-run"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["dry_run"] is True and (out["cap"], out["search_budget"], out["download_cap"]) == (45, 25, 2)
    assert len(out["plan"]) == 25 and out["plan"][0] == "tiktok trending GB" and cli_store.get_hit_spend(NOW.date()).total == 0


def test_cli_pull_pulls_then_files_and_prints_both(cli_store, monkeypatch):
    api = FakeAPI()
    api.answer(TT_SEARCH, page(TT_SEARCH, [tt_item(1, views=2_000_000, followers=20_000)]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    r = CliRunner().invoke(app, ["hits", "pull"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["kept"] == 1 and out["calls"] == 25 and len(out["filed"]) == 1 and out["filed"][0]["character"] == "franz"
    assert set(out["filed"][0]) == {"hit_id", "pick_id", "character", "provisional"}
    r = CliRunner().invoke(app, ["hits", "list", "--status", "dropped"])
    assert r.exit_code == 0 and [h["url"] for h in json.loads(r.stdout)] == [cli_store.list_hits()[0].url]


def test_scan_json_carries_the_hits_block_the_brief_names():
    cfg = hits.hits_config(hits.load_scan())
    assert (cfg["daily_credit_cap"], cfg["download_cap_per_day"], cfg["auto_file_per_character"], cfg["auto_file_general"]) == (
        45, 2, 3, 3)
    assert (cfg["auto_file_max_waiting"], cfg["lunar_daily_cap"]) == (20, 40)  # task 18: the brake and the LunarCrush cap
    assert cfg["keywords"] == {
        "franz": ["dog dance", "dachshund", "dog trend"], "reginald": ["dance trend", "deadpan dance", "butler"],
        "lenny": ["boss on the phone", "office dance", "dance challenge"],
    }  # fmt: skip
    assert cfg["general_keywords"] == ["viral dance", "dance trend", "trend challenge", "funny dance"]
    assert cfg["tiktok_regions"] == ["GB", "US"] and cfg["instagram_trending"] is True
    budget = hits.search_limit(HitSpend(day=NOW.date()), cfg)
    assert budget == 45 - 2 * hits.DOWNLOAD_CREDITS == 25 and len(hits.plan_calls(roster_store(), cfg)) <= budget  # the plan fits
    for bad in ({"daily_credit_cap": -1}, {"download_cap_per_day": "2"}):
        with pytest.raises(ValueError):
            hits.hits_config({"hits": bad})
    assert (hits.hits_config({})["daily_credit_cap"], hits.hits_config({})["download_cap_per_day"]) == (45, 2)  # the defaults


# ---- one post's hosted copy (the fetch fallback of a dropped link) --------------------------------------------------------------------

TT_VIDEO, IG_POST = "/v2/tiktok/video", "/v1/instagram/post"
VIDEO_URL = "https://www.tiktok.com/@branttakes/video/7545933721589910798"


def test_download_post_asks_for_that_one_post_with_download_media_and_fetches_the_copy_without_the_key(tmp_path):
    api = FakeAPI()
    api.media = b"\x00\x00\x00\x18ftypmp42 a small video"
    api.answer(TT_VIDEO, fixture("tiktok_video"))
    dest = tmp_path / "in" / "pick.mp4"
    got = api.client().download_post(VIDEO_URL, "tiktok", dest)
    first, second = api.requests
    assert first.url.path == TT_VIDEO and first.headers["x-api-key"] == KEY
    assert {k: v[0] for k, v in parse_qs(urlsplit(str(first.url)).query).items()} == {"url": VIDEO_URL, "download_media": "true"}
    no_watermark = fixture("tiktok_video")["aweme_detail"]["video"]["download_no_watermark_addr"]["url_list"][0]
    assert str(second.url) == no_watermark and "x-api-key" not in second.headers  # our key never leaves for the media host
    assert dest.read_bytes() == api.media and got == {"credits": 1, "media_url": no_watermark, "bytes": len(api.media)}
    assert not list(dest.parent.glob(".*.part"))


def test_the_hosted_copy_is_preferred_wherever_the_answer_carries_it_and_never_a_watermarked_one():
    answer = fixture("tiktok_video")
    hosted = "https://abcd.supabase.co/storage/v1/object/public/media/7545933721589910798.mp4"
    assert hits.media_url({**answer, "media": {"video": hosted, "cover": "https://abcd.supabase.co/x/cover.jpg"}}, "tiktok") == hosted
    marked = copy.deepcopy(answer)
    del marked["aweme_detail"]["video"]["download_no_watermark_addr"]
    with pytest.raises(ScrapeCreatorsError, match="watermark"):
        hits.media_url(marked, "tiktok")  # has_watermark is true and there is no clean copy
    marked["aweme_detail"]["video"]["has_watermark"] = False
    assert hits.media_url(marked, "tiktok") == answer["aweme_detail"]["video"]["play_addr"]["url_list"][0]
    post = fixture("instagram_post")
    assert hits.media_url(post, "instagram") == post["data"]["xdt_shortcode_media"]["video_url"]
    insecure = copy.deepcopy(post)
    insecure["data"]["xdt_shortcode_media"]["video_url"] = "http://scontent.cdninstagram.com/v.mp4"
    with pytest.raises(ScrapeCreatorsError, match="no video"):
        hits.media_url(insecure, "instagram")


def test_a_failed_or_oversized_copy_leaves_no_file(tmp_path, monkeypatch):
    api = FakeAPI()
    api.media = b"x" * 64
    api.answer(IG_POST, fixture("instagram_post"))
    monkeypatch.setattr(hits, "MEDIA_MAX_BYTES", 10)
    dest = tmp_path / "pick.mp4"
    with pytest.raises(ScrapeCreatorsError, match="over"):
        api.client().download_post("https://www.instagram.com/reel/DLDXI0fylTC/", "instagram", dest)
    assert not dest.exists() and not list(tmp_path.glob(".*"))
    api.answer(IG_POST, 404)
    with pytest.raises(ScrapeCreatorsError) as e:
        api.client().download_post("https://www.instagram.com/reel/DLDXI0fylTC/", "instagram", dest)
    assert e.value.status == 404
    with pytest.raises(ScrapeCreatorsError, match="no single-post download"):
        api.client().download_post("https://www.youtube.com/shorts/abcdefghijk", "youtube", dest)
    assert not dest.exists()


def test_an_unreadable_item_is_skipped_and_the_run_goes_on():
    store = roster_store()
    api = FakeAPI()
    odd = tt_item(1)
    odd["create_time"] = 10**20  # a date no clock can hold
    api.answer(TT_TREND, page(TT_TREND, [odd, tt_item(2)]))
    out = hits.pull(store, api.client(), CONFIG, NOW)
    assert out["kept"] == 1 and out["skipped"] == {"unreadable": 1} and out["calls"] == 25


def test_cli_list_filters_by_lane_and_status(cli_store):
    stored(cli_store, 1, None, 90)
    stored(cli_store, 2, "lenny", 80)
    stored(cli_store, 3, "lenny", 70, status="dismissed")
    general = json.loads(CliRunner().invoke(app, ["hits", "list", "--general"]).stdout)
    assert [h["character_slug"] for h in general] == [None]
    lenny = json.loads(CliRunner().invoke(app, ["hits", "list", "--character", "lenny", "--status", "new"]).stdout)
    assert [h["score"] for h in lenny] == [80]
    assert [h["score"] for h in json.loads(CliRunner().invoke(app, ["hits", "list", "--limit", "2"]).stdout)] == [90, 80]



# ---- the day's one-post downloads (controller ruling 2026-10-08: hits.download_cap_per_day) ------------------------------------------


def budgeted(api: FakeAPI, store=None, config=CONFIG, at=NOW) -> hits.DownloadBudget:
    return hits.DownloadBudget(api.client(), store or roster_store(), config, clock=lambda: at)


def test_a_download_is_counted_into_the_day_as_soon_as_the_api_answered(tmp_path):
    api = FakeAPI()
    api.media = b"video bytes"
    paid = fixture("tiktok_video") | {"credits_charged": 10}
    api.answer(TT_VIDEO, paid, paid)
    store = roster_store()
    budget = budgeted(api, store)
    assert budget.download_post(VIDEO_URL, "tiktok", tmp_path / "a.mp4")["credits"] == 10
    spend = store.get_hit_spend(NOW.date())
    assert (spend.search_credits, spend.download_credits, spend.downloads) == (0, 10, 1)
    api.media = b""  # the copy's own download fails: the API's credits were spent all the same
    with pytest.raises(ScrapeCreatorsError, match="empty"):
        budget.download_post(VIDEO_URL, "tiktok", tmp_path / "b.mp4")
    assert (store.get_hit_spend(NOW.date()).download_credits, store.get_hit_spend(NOW.date()).downloads) == (20, 2)


def test_a_download_over_the_days_cap_is_refused_without_calling_scrapecreators(tmp_path):
    store = roster_store()
    store.add_hit_spend(NOW.date(), download_credits=20, downloads=2)
    api = FakeAPI()
    with pytest.raises(ScrapeCreatorsError, match="download_cap_per_day"):
        budgeted(api, store).download_post(VIDEO_URL, "tiktok", tmp_path / "a.mp4")
    full = roster_store()
    full.add_hit_spend(NOW.date(), search_credits=40)  # 40 of 45: no room for a download of 10
    with pytest.raises(ScrapeCreatorsError, match="daily_credit_cap"):
        budgeted(api, full).download_post(VIDEO_URL, "tiktok", tmp_path / "a.mp4")
    assert api.requests == [] and not (tmp_path / "a.mp4").exists()
    tomorrow = NOW + timedelta(days=1)
    api.answer(TT_VIDEO, fixture("tiktok_video"))
    api.media = b"video"
    assert budgeted(api, store, at=tomorrow).download_post(VIDEO_URL, "tiktok", tmp_path / "a.mp4")["bytes"] == 5  # a new day


def test_the_drop_job_gets_the_budget_only_with_the_key(monkeypatch):
    store = roster_store()
    assert hits.download_budget(store, CONFIG) is None  # no SCRAPECREATORS_API_KEY in a test
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", KEY)
    budget = hits.download_budget(store, CONFIG)
    assert isinstance(budget, hits.DownloadBudget) and isinstance(budget.client, ScrapeCreators) and budget.store is store



# ---- review fix round 1 -------------------------------------------------------------------------------------------------------------


def test_a_weeks_old_or_long_unseen_hit_is_never_filed_whatever_its_stored_score():
    store = roster_store()
    old = stored(store, 1, "reginald", 99, posted_days=20)  # a hit of three weeks ago: its stored score is from then
    unseen = stored(store, 2, "reginald", 98, seen_days=4)  # no pull has seen it for 4 days
    store.update_hit(old.id, score=100)
    fresh = stored(store, 3, "reginald", 30)
    undated = stored(store, 4, "reginald", 20)
    store.update_hit(undated.id, posted_at=None)
    filed = hits.auto_file(store, {"hits": {**CONFIG["hits"], "auto_file_general": 0}}, NOW)
    assert [f["hit_id"] for f in filed] == [fresh.id, undated.id]
    assert store.get_hit(old.id).status == store.get_hit(unseen.id).status == "new"
    assert hits.fileable(stored(store, 5, None, 50, posted_days=13.9, seen_days=2.9), NOW) is True


def test_an_account_out_of_credits_stops_the_pull():
    api = FakeAPI()
    api.answer(TT_TREND, page(TT_TREND, [tt_item(1)]), 402)
    out = hits.pull(roster_store(), api.client(), CONFIG, NOW)
    assert out["stopped"] == "out_of_credits" and out["calls"] == 1 and len(api.paths()) == 2 and out["kept"] == 1
    assert "402" in out["errors"][0]["error"]


def test_the_hosted_copy_is_never_taken_from_what_the_creator_writes_nor_from_a_private_address():
    answer = fixture("tiktok_video")
    planted = "https://evil.supabase.co/storage/v1/object/public/x/planted.mp4"
    for key in ("author", "caption", "desc"):
        doc = copy.deepcopy(answer)
        doc["aweme_detail"][key] = {"bio": planted, "avatar": planted} if key == "author" else planted
        doc[key] = {"nested": {"link": planted}}
        assert hits.media_url(doc, "tiktok") != planted  # the documented no-watermark address instead
    post = fixture("instagram_post")
    for bad in ("https://127.0.0.1/v.mp4", "https://[::1]/v.mp4", "https://localhost/v.mp4", "https://cdn.localhost/v.mp4",
                "https://10.0.0.5/v.mp4", "https://intranet/v.mp4"):  # fmt: skip
        doc = copy.deepcopy(post)
        doc["data"]["xdt_shortcode_media"]["video_url"] = bad
        with pytest.raises(ScrapeCreatorsError, match="no video"):
            hits.media_url(doc, "instagram")
    owner = copy.deepcopy(post)
    owner["data"]["xdt_shortcode_media"]["owner"]["profile"] = "https://x.supabase.co/a/b.mp4"
    assert hits.media_url(owner, "instagram") == post["data"]["xdt_shortcode_media"]["video_url"]


def test_redirects_are_followed_by_hand_three_at_most_each_a_public_https_hop(tmp_path):
    api = FakeAPI()
    api.media = b"the video"
    start = fixture("instagram_post")["data"]["xdt_shortcode_media"]["video_url"]
    hops = ["https://cdn-a.example.com/1.mp4", "https://cdn-b.example.com/2.mp4", "https://cdn-c.example.com/3.mp4"]
    api.media_routes[start] = httpx.Response(302, headers={"location": hops[0]})
    api.media_routes[hops[0]] = httpx.Response(301, headers={"location": hops[1]})
    api.media_routes[hops[1]] = httpx.Response(307, headers={"location": hops[2]})
    api.answer(IG_POST, fixture("instagram_post"))
    got = api.client().download_post("https://www.instagram.com/reel/DLDXI0fylTC/", "instagram", tmp_path / "a.mp4")
    assert got["bytes"] == len(api.media) and (tmp_path / "a.mp4").read_bytes() == api.media
    assert [str(r.url) for r in api.requests[1:]] == [start, *hops] and all("x-api-key" not in r.headers for r in api.requests[1:])
    api.media_routes[hops[2]] = httpx.Response(302, headers={"location": "https://cdn-d.example.com/4.mp4"})  # a 4th redirect
    for bad_hop, why in ((None, "redirects more than 3"), ("http://cdn-e.example.com/5.mp4", "not a public https"),
                         ("https://169.254.169.254/latest", "not a public https")):  # fmt: skip
        if bad_hop is not None:  # the third redirect goes somewhere it may not
            api.media_routes[hops[1]] = httpx.Response(302, headers={"location": bad_hop})
        api.answer(IG_POST, fixture("instagram_post"))
        with pytest.raises(ScrapeCreatorsError, match=why):
            api.client().download_post("https://www.instagram.com/reel/DLDXI0fylTC/", "instagram", tmp_path / "b.mp4")
        assert not (tmp_path / "b.mp4").exists() and not list(tmp_path.glob(".*.part"))
    assert not any(r.url.host in ("cdn-e.example.com", "169.254.169.254") for r in api.requests)  # never even asked


def test_the_hosted_copys_download_has_a_total_deadline(tmp_path):
    api = FakeAPI()
    api.media = b"x" * 1024
    api.answer(IG_POST, fixture("instagram_post"), fixture("instagram_post"))
    ticks = iter([0.0, 100.0, 301.0])  # the start, the hop, the network read that ends past 300 s
    client = api.client(clock=lambda: next(ticks))
    with pytest.raises(ScrapeCreatorsError, match="took over 300 s"):
        client.download_post("https://www.instagram.com/reel/DLDXI0fylTC/", "instagram", tmp_path / "a.mp4")
    assert not (tmp_path / "a.mp4").exists() and not list(tmp_path.glob(".*.part"))
    # a slow redirect: the deadline is checked at the top of every hop, before the next address is even asked
    start = fixture("instagram_post")["data"]["xdt_shortcode_media"]["video_url"]
    api.media_routes[start] = httpx.Response(302, headers={"location": "https://cdn-slow.example.com/1.mp4"})
    ticks = iter([0.0, 10.0, 301.0])  # the start, the first hop, the second hop
    client = api.client(clock=lambda: next(ticks))
    with pytest.raises(ScrapeCreatorsError, match="took over 300 s"):
        client.download_post("https://www.instagram.com/reel/DLDXI0fylTC/", "instagram", tmp_path / "b.mp4")
    assert not any(r.url.host == "cdn-slow.example.com" for r in api.requests) and not (tmp_path / "b.mp4").exists()


# ---- the brake: auto-filing stops while a backlog of drops waits (task 18) -----------------------------------------------------------------------


def waiting_drop(store, n: int, state: str = "ready", status: str = "approved", **drop_fields) -> Favorite:
    """A drop in ``state`` (a link at ``status``): the owner's own or an auto-filed one (``auto_filed=True``), the brake counts both."""
    return store.add_favorite(Favorite(
        url=f"https://www.tiktok.com/@owner{n}/video/{5000 + n}", platform="tiktok", origin="owner", character_slug="franz",
        status=status, proposal={"drop": {"state": state, "kind": "link", "at": NOW.isoformat(), "reason": None, **drop_fields}},
    ))  # fmt: skip


def backlog(store, count: int) -> None:
    for n in range(count):
        waiting_drop(store, n, ("uploading", "checking", "waiting", "ready")[n % 4])


def test_an_auto_filed_link_the_cloud_could_not_fetch_is_not_on_the_owners_list_so_it_does_not_brake():
    store = roster_store()
    stuck = {"auto_filed": True, "fetch_days": ["2026-10-07"], "reason": "the link could not be fetched in the cloud"}
    waiting_drop(store, 1, "waiting", **stuck)  # no clip yet; the cloud retries it and drops it after 3 days
    waiting_drop(store, 2, "waiting", **{**stuck, "fetch_days": ["2026-10-06", "2026-10-07", "2026-10-08"]})
    waiting_drop(store, 3, "waiting")  # the owner's own pasted link the cloud could not fetch: on his list, it counts
    for n, state in enumerate(("uploading", "checking", "ready"), start=4):
        waiting_drop(store, n, state, auto_filed=True)  # an auto-filed drop that has a clip (or is being fetched and checked) counts
    assert hits.waiting_drops(store) == 4


def test_the_drops_that_wait_are_those_filed_and_not_yet_sent_to_be_made():
    store = roster_store()
    for n, state in enumerate(("uploading", "checking", "waiting", "ready")):
        waiting_drop(store, n, state)  # waiting: counted
    waiting_drop(store, 10, "blocked")  # can never be made
    waiting_drop(store, 11, "failed")  # retried by the sweep or the owner's Try again
    waiting_drop(store, 12, "making", status="queued")  # the owner said Make it
    waiting_drop(store, 13, "made", status="made")
    waiting_drop(store, 14, "ready", status="skipped")  # skipped by the owner, or dropped after 3 days unfetched
    store.add_favorite(Favorite(url="https://www.tiktok.com/@plain/video/1", platform="tiktok", status="approved"))  # not a drop
    assert hits.waiting_drops(store) == 4


@pytest.mark.parametrize("waiting, braked, files", [(16, False, 3), (19, True, 1), (20, True, 0), (21, True, 0)])
def test_auto_file_stops_once_20_drops_wait_counting_its_own_filings(waiting, braked, files):
    store = roster_store()
    backlog(store, waiting)
    for n in range(1, 5):
        stored(store, n, "reginald", 100 - n)
    run = hits.file_hits(store, CONFIG, NOW)
    assert (run["braked"], run["waiting"], run["max_waiting"]) == (braked, waiting, 20)
    assert len(run["filed"]) == files
    assert sum(h.status == "new" for h in store.list_hits()) == 4 - files  # the rest wait for tomorrow's run
    assert hits.waiting_drops(store) == waiting + files


def test_the_brake_is_read_from_the_config_and_zero_stops_the_filing():
    store = roster_store()
    backlog(store, 3)
    stored(store, 1, "reginald", 80)
    assert hits.file_hits(store, {"hits": {**CONFIG["hits"], "auto_file_max_waiting": 3}}, NOW)["braked"] is True
    assert hits.file_hits(store, {"hits": {**CONFIG["hits"], "auto_file_max_waiting": 4}}, NOW)["braked"] is False
    assert hits.hits_config({})["auto_file_max_waiting"] == 20 and hits.hits_config({})["lunar_daily_cap"] == 40
    for bad in ({"auto_file_max_waiting": -1}, {"lunar_daily_cap": "40"}):
        with pytest.raises(ValueError):
            hits.hits_config({"hits": bad})


def test_a_braked_run_asks_lunarcrush_nothing():
    store = roster_store()
    backlog(store, 20)
    stored(store, 1, "reginald", 80, sound="Patient Zero")
    gate = StubGate()
    assert hits.file_hits(store, CONFIG, NOW, gate=gate)["braked"] is True and gate.asked == []


def test_the_waiting_drops_are_counted_again_after_a_filing_so_the_next_run_sees_them():
    store = roster_store()
    backlog(store, 19)
    for n in range(1, 4):
        stored(store, n, "reginald", 90 - n)
    assert len(hits.auto_file(store, CONFIG, NOW)) == 1 and hits.waiting_drops(store) == 20
    stored(store, 9, "reginald", 99)
    assert hits.file_hits(store, CONFIG, NOW + timedelta(days=1))["braked"] is True


# ---- the trend-freshness gate in the filing (task 18; research 3.2, rule P5) ---------------------------------------------------------------------


class StubGate(lunar.TrendGate):
    """A gate answering from a table of readings (by lower-case key) and noting every key it was asked about."""

    def __init__(self, readings=None):
        super().__init__(None)
        self.readings = readings or {}
        self.asked: list[str] = []
        self.as_ofs: list[date | None] = []

    @property
    def enabled(self) -> bool:
        return True

    def read(self, key: str, as_of: date | None = None) -> lunar.Reading:
        self.asked.append(key)
        self.as_ofs.append(as_of)
        return self.readings.get(key, lunar.Reading("unknown", reason="stub"))

    def summary(self):
        return {"enabled": True, "keys": len(set(self.asked)), "calls": len(self.asked), "stages": {}}


def drop_of(store, entry) -> dict:
    return store.get_favorite(entry["pick_id"]).proposal["drop"]


def test_a_dead_trend_is_not_filed_it_is_counted_and_its_room_goes_to_the_next_hit():
    store = roster_store()
    old = stored(store, 1, "reginald", 90, sound="Hot Dog Dance")
    new = [stored(store, n, "reginald", s, sound=name) for n, s, name in ((2, 80, "Gangnam Style"), (3, 70, "Patient Zero"), (4, 60, "Single Ladies"))]
    gate = StubGate({
        "hot dog dance": lunar.Reading("dead", 14), "gangnam style": lunar.Reading("rising", 0),
        "patient zero": lunar.Reading("fading", 5), "single ladies": lunar.Reading("peak", 1),
    })  # fmt: skip
    run = hits.file_hits(store, CONFIG, NOW, gate=gate)
    assert [f["hit_id"] for f in run["filed"]] == [h.id for h in new] and run["skipped_dead"] == 1 and run["braked"] is False
    assert store.get_hit(old.id).status == "new" and not store.list_favorites(url=old.url)  # not filed, not dismissed
    assert gate.asked == ["hot dog dance", "gangnam style", "patient zero", "single ladies"]  # the ranking is untouched by the readings
    rising, fading, peak = (drop_of(store, f) for f in run["filed"])
    assert (rising["trend_stage"], rising["days_since_trend_peak"], rising["sound_rising"]) == ("rising", 0, True)
    assert (fading["trend_stage"], fading["days_since_trend_peak"], fading["sound_rising"]) == ("fading", 5, False)
    assert (peak["trend_stage"], peak["days_since_trend_peak"], peak["sound_rising"]) == ("peak", 1, False)
    assert run["trend"]["calls"] == 4


def test_a_dead_trend_under_a_fifth_of_its_peak_is_dismissed_with_its_reason_and_not_asked_about_again():
    store = roster_store()
    gone = stored(store, 1, "reginald", 90, sound="Hot Dog Dance")
    sinking = stored(store, 2, "reginald", 80, sound="Old Dance")
    unsure = stored(store, 3, "reginald", 70, sound="Odd Dance")
    alive = stored(store, 4, "reginald", 60, sound="Gangnam Style")
    gate = StubGate({
        "hot dog dance": lunar.Reading("dead", 14, ratio=0.1), "old dance": lunar.Reading("dead", 9, ratio=0.35),
        "odd dance": lunar.Reading("dead", 11), "gangnam style": lunar.Reading("rising", 0, ratio=1.0),
    })  # fmt: skip
    run = hits.file_hits(store, CONFIG, NOW, gate=gate)
    assert [f["hit_id"] for f in run["filed"]] == [alive.id] and run["skipped_dead"] == 3
    assert store.get_hit(gone.id).status == "dismissed"  # a clear case: not asked about again tomorrow
    assert store.get_hit(sinking.id).status == "new" and store.get_hit(unsure.id).status == "new"  # a doubtful one may recover; no ratio: no verdict
    assert run["dismissed"] == [{"hit_id": gone.id, "reason": "dead trend: 14 days past its peak, now at 10% of it"}]
    again = StubGate({"old dance": lunar.Reading("dead", 10, ratio=0.3), "odd dance": lunar.Reading("dead", 12)})
    hits.file_hits(store, CONFIG, NOW + timedelta(hours=1), gate=again)
    assert "hot dog dance" not in again.asked and again.asked == ["old dance", "odd dance"]


def test_the_filed_drops_trend_keys_are_the_ones_the_tag_builder_reads():
    store = roster_store()
    stored(store, 1, "reginald", 90, sound="Gangnam Style")
    stored(store, 2, "reginald", 80, sound="Patient Zero")
    gate = StubGate({"gangnam style": lunar.Reading("rising", 0), "patient zero": lunar.Reading("fading", 6)})
    first, second = hits.file_hits(store, CONFIG, NOW, gate=gate)["filed"]
    for entry, stage, days, rising in ((first, "rising", 0, True), (second, "fading", 6, False)):
        pick = store.get_favorite(entry["pick_id"])
        tags = drop.learn_tags(pick, pick.proposal["drop"], {"hook": "x", "part": "featured"}, version_index=1)
        assert (tags["trend_stage"], tags["days_since_trend_peak"], tags["sound_rising"]) == (stage, days, rising)


def test_without_a_reading_the_hit_is_filed_as_before_with_the_stage_unknown():
    store = roster_store()
    stored(store, 1, "reginald", 90, sound="Patient Zero")  # a key, but the gate is off
    stored(store, 2, "reginald", 80)  # no key to ask about at all
    run = hits.file_hits(store, CONFIG, NOW, gate=lunar.TrendGate(None))
    assert len(run["filed"]) == 2 and run["skipped_dead"] == 0
    for entry in run["filed"]:
        d = drop_of(store, entry)
        assert d["trend_stage"] == "unknown" and "days_since_trend_peak" not in d and d["sound_rising"] is False
        pick = store.get_favorite(entry["pick_id"])
        tags = drop.learn_tags(pick, d, {"hook": "x", "part": "featured"}, version_index=1)
        assert (tags["trend_stage"], tags["days_since_trend_peak"], tags["sound_rising"]) == ("none", None, False)  # as today


def test_no_gate_at_all_leaves_the_drop_exactly_as_it_was():
    store = roster_store()
    stored(store, 1, "reginald", 90, sound="Patient Zero")
    (f,) = hits.auto_file(store, CONFIG, NOW)
    d = drop_of(store, f)
    assert not ({"trend_stage", "days_since_trend_peak", "sound_rising"} & set(d))


def test_a_gate_that_raises_anything_never_stops_the_filing(caplog):
    class Broken(StubGate):
        def read(self, key, as_of=None):
            raise OSError(84, "Value too large to be stored in data type")

    store = roster_store()
    for n in (1, 2):
        stored(store, n, "reginald", 90 - n, sound=f"Sound {n}")
    with caplog.at_level(logging.WARNING, logger="studio.hits"):
        run = hits.file_hits(store, CONFIG, NOW, gate=Broken())
    assert len(run["filed"]) == 2 and run["skipped_dead"] == 0
    assert {drop_of(store, f)["trend_stage"] for f in run["filed"]} == {"unknown"} and "OSError" in caplog.text


def test_a_reading_that_failed_files_the_hit_with_the_stage_unknown():
    store = roster_store()
    stored(store, 1, "reginald", 90, sound="Patient Zero")
    gate = StubGate()  # every reading is unknown
    run = hits.file_hits(store, CONFIG, NOW, gate=gate)
    assert len(run["filed"]) == 1 and drop_of(store, run["filed"][0])["trend_stage"] == "unknown"


def test_the_sound_is_the_key_else_a_keyword_of_the_character_in_the_caption_and_only_a_sound_can_be_rising():
    store = roster_store()
    stored(store, 1, "franz", 90, sound="original sound - maker1", caption="my dachshund doing the dance #dogdance")
    stored(store, 2, "reginald", 80, sound="Original audio", caption="nothing to see")  # no key: not asked
    stored(store, 3, None, 70, sound=None, caption="Viral Dance of the week", platform="instagram")  # a general keyword
    gate = StubGate({"dog dance": lunar.Reading("rising", 0), "viral dance": lunar.Reading("rising", 0)})
    run = hits.file_hits(store, CONFIG, NOW, gate=gate)
    assert gate.asked == ["dog dance", "viral dance"]  # franz's list order: "dog dance" is before "dachshund"
    assert [drop_of(store, f)["sound_rising"] for f in run["filed"]] == [False, False, False]  # a caption trend is not a rising sound
    assert [drop_of(store, f)["trend_stage"] for f in run["filed"]] == ["rising", "unknown", "rising"]


def test_events_are_trend_names_too():
    store = roster_store()
    stored(store, 1, "reginald", 90, sound=None, caption="paris fashion week energy")
    gate = StubGate({"paris fashion week": lunar.Reading("fading", 3)})
    run = hits.file_hits(store, CONFIG, NOW, gate=gate, events=["paris fashion week"])
    assert gate.asked == ["paris fashion week"] and drop_of(store, run["filed"][0])["trend_stage"] == "fading"


def test_a_classic_skips_the_check():
    store = roster_store()
    stored(store, 1, "reginald", 90, sound="Gangnam Style", views=80_000_000)  # tier iconic: 50M views or more
    gate = StubGate({"gangnam style": lunar.Reading("dead", 30)})
    run = hits.file_hits(store, CONFIG, NOW, gate=gate)
    assert gate.asked == [] and len(run["filed"]) == 1 and run["skipped_dead"] == 0
    assert drop_of(store, run["filed"][0])["trend_stage"] == "classic"


def test_only_the_hits_about_to_be_filed_are_asked_about_and_a_known_pick_is_not():
    store = roster_store()
    known = stored(store, 1, "reginald", 95, sound="Already Picked")
    store.add_favorite(Favorite(url=known.url, platform="tiktok", character_slug="franz", status="skipped"))
    for n, s in ((2, 90), (3, 80), (4, 70), (5, 60), (6, 50)):
        stored(store, n, "reginald", s, sound=f"Sound {n}")
    gate = StubGate()
    run = hits.file_hits(store, CONFIG, NOW, gate=gate)
    assert len(run["filed"]) == 3 and gate.asked == ["sound 2", "sound 3", "sound 4"]  # no call for the pick or the 2 over the cap


def test_a_key_is_checked_once_for_the_run_however_many_hits_ride_it():
    class Client:
        def __init__(self):
            self.calls, self.asked = 0, []

        def keyword_time_series(self, keyword):
            self.calls += 1
            self.asked.append(keyword)
            return (lunar_fixture("keyword_time_series_single_ladies"))

        def scrub(self, text):
            return text

    store = roster_store()
    for n in (1, 2, 3):
        stored(store, n, "reginald", 90 - n, sound="Single Ladies")
    client = Client()
    run = hits.file_hits(store, CONFIG, NOW, gate=lunar.TrendGate(client))
    assert client.asked == ["single ladies"] and client.calls == 1
    assert {drop_of(store, f)["trend_stage"] for f in run["filed"]} == {"fading"} and run["trend"]["keys"] == 1
    assert {drop_of(store, f)["days_since_trend_peak"] for f in run["filed"]} == {4}


def test_a_trend_whose_series_stopped_weeks_ago_is_unknown_so_it_is_filed_not_skipped_dismissed_or_called_a_peak():
    class Client:
        calls = 1

        def keyword_time_series(self, keyword):  # 8 to 13 Sep, a peak on 11-12 Sep, nothing since
            rows = "".join(f"| 2026-09-{8 + i:02d} | {v} |\n" for i, v in enumerate([100, 200, 5000, 30_000, 12_000, 6000]))
            return "| time | tiktok_interactions |\n|---|---|\n" + rows

        def scrub(self, text):
            return text

    store = roster_store()
    small = stored(store, 1, "reginald", 90, sound="Small Dance")
    run = hits.file_hits(store, CONFIG, NOW, gate=lunar.TrendGate(Client()))  # NOW is 8 Oct: the latest full day is 7 Oct
    assert run["skipped_dead"] == 0 and run["dismissed"] == [] and run["trend"]["stages"] == {"unknown": 1}
    assert [f["hit_id"] for f in run["filed"]] == [small.id] and drop_of(store, run["filed"][0])["trend_stage"] == "unknown"
    assert store.get_hit(small.id).status == "dropped"


def test_a_real_dead_trend_under_a_fifth_of_its_peak_is_dismissed_through_the_whole_gate():
    class Client:
        calls = 1

        def keyword_time_series(self, keyword):  # patient zero ends on 7 Oct: the day before NOW, nothing padded
            return lunar_fixture("keyword_time_series_patient_zero")

        def scrub(self, text):
            return text

    store = roster_store()
    gone = stored(store, 1, "reginald", 90, sound="Patient Zero")
    run = hits.file_hits(store, CONFIG, NOW, gate=lunar.TrendGate(Client()))
    assert run["skipped_dead"] == 1 and run["filed"] == [] and store.get_hit(gone.id).status == "dismissed"
    assert run["dismissed"][0]["reason"].startswith("dead trend: 9 days past its peak, now at ")


def test_the_gate_is_asked_as_of_yesterday_in_london():
    store = roster_store()
    stored(store, 1, "reginald", 90, sound="Small Dance")
    gate = StubGate()
    hits.file_hits(store, CONFIG, NOW, gate=gate)
    assert gate.as_ofs == [date(2026, 10, 7)]
    assert hits.trend_as_of(datetime(2026, 10, 8, 0, 30, tzinfo=LONDON)) == date(2026, 10, 7)
    assert hits.trend_as_of(datetime(2026, 10, 7, 23, 30, tzinfo=timezone.utc)) == date(2026, 10, 7)  # 00:30 on 8 Oct in London (BST)


def lunar_fixture(name: str) -> str:
    return (Path(__file__).resolve().parent / "fixtures" / "lunarcrush" / f"{name}.md").read_text(encoding="utf-8")


# ---- the CLI: the brake, the gate and the probe -----------------------------------------------------------------------------------------------------


def test_cli_pull_says_what_the_brake_and_the_gate_did(cli_store, monkeypatch):
    api = FakeAPI()
    api.answer(TT_SEARCH, page(TT_SEARCH, [tt_item(1, views=2_000_000, followers=20_000)]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    out = json.loads(CliRunner().invoke(app, ["hits", "pull"]).stdout)
    assert (out["braked"], out["waiting"], out["skipped_dead"]) == (False, 0, 0)
    assert out["trend"] == {"enabled": False, "keys": 0, "calls": 0, "stages": {}}  # no LUNARCRUSH_API_KEY: the gate is off
    (entry,) = out["filed"]
    d = cli_store.get_favorite(entry["pick_id"]).proposal["drop"]
    assert d["trend_stage"] == "unknown" and d["sound_rising"] is False


def test_cli_pull_is_braked_by_a_backlog_and_says_so(cli_store, monkeypatch):
    backlog(cli_store, 20)
    api = FakeAPI()
    api.answer(TT_SEARCH, page(TT_SEARCH, [tt_item(1, views=2_000_000, followers=20_000)]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    r = CliRunner().invoke(app, ["hits", "pull"])
    out = json.loads(r.stdout)
    assert r.exit_code == 0 and out["kept"] == 1 and out["filed"] == [] and out["braked"] is True and out["waiting"] == 20
    assert "::notice::" in r.stderr and "20" in r.stderr


def test_cli_pull_gives_the_gate_the_key_and_the_runs_cap(cli_store, monkeypatch):
    seen = {}

    def gate(cls, *, cap=40, env=None, **kw):
        seen["cap"] = cap
        return StubGate({"patient zero": lunar.Reading("dead", 12)})

    monkeypatch.setattr(lunar.TrendGate, "from_env", classmethod(gate))
    monkeypatch.setattr(hits, "load_scan", lambda path=None: {"hits": {**CONFIG["hits"], "lunar_daily_cap": 7}})
    api = FakeAPI()
    item = tt_item(1, views=2_000_000, followers=20_000)
    item.setdefault("music", {})["title"] = "Patient Zero"
    api.answer(TT_SEARCH, page(TT_SEARCH, [item]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    out = json.loads(CliRunner().invoke(app, ["hits", "pull"]).stdout)
    assert seen["cap"] == 7 and out["skipped_dead"] == 1 and out["filed"] == []


def lunar_run(store, day: date, calls: int, **over):
    """A `hits` run line as the pull writes it after the gate made `calls` calls on London `day`."""
    return store.add_run(Run(
        kind=RunKind.hits, status="ok", started_at=NOW, finished_at=NOW, summary=f"LunarCrush: {calls} calls",
        details={"lunar": {"day": day.isoformat(), "calls": calls, "keys": calls, "stages": {}}, **over},
    ))  # fmt: skip


def lunar_lines(store):
    """The ``hits`` runs that carry LunarCrush calls (every pull also logs its outcome as one: ``details.pull``)."""
    return [r for r in store.list_runs(kind="hits") if "lunar" in r.details]


def test_the_lunar_calls_of_a_london_day_are_counted_from_the_runs_the_pull_logs():
    store = roster_store()
    today = NOW.date()
    lunar_run(store, today, 12)
    lunar_run(store, today, 9)
    lunar_run(store, today - timedelta(days=1), 40)  # yesterday's are not today's
    store.add_run(Run(kind=RunKind.daily, status="ok", started_at=NOW, details={"lunar": {"day": today.isoformat(), "calls": 99}}))
    store.add_run(Run(kind=RunKind.hits, status="ok", started_at=NOW, details={"lunar": {"day": today.isoformat(), "calls": "many"}}))
    store.add_run(Run(kind=RunKind.hits, status="ok", started_at=NOW, details={"lunar": "odd"}))
    assert hits.lunar_calls_today(store, today) == 21 and hits.lunar_calls_today(store, today + timedelta(days=1)) == 0


@pytest.mark.parametrize("spent, left", [(0, 40), (30, 10), (40, 0), (55, 0)])
def test_the_lunar_cap_is_the_london_days_not_the_runs_so_a_second_run_gets_what_is_left(cli_store, monkeypatch, spent, left):
    seen = {}

    def gate(cls, *, cap=40, env=None, **kw):
        seen["cap"] = cap
        return StubGate()

    monkeypatch.setattr(lunar.TrendGate, "from_env", classmethod(gate))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: FakeAPI().client()))
    if spent:
        lunar_run(cli_store, NOW.date(), spent)
    assert CliRunner().invoke(app, ["hits", "pull"]).exit_code == 0
    assert seen["cap"] == left


def test_a_pull_that_asked_lunarcrush_logs_its_calls_for_the_day(cli_store, monkeypatch):
    gate = StubGate({"patient zero": lunar.Reading("fading", 5)})
    monkeypatch.setattr(lunar.TrendGate, "from_env", classmethod(lambda cls, *, cap=40, env=None, **kw: gate))
    api = FakeAPI()
    item = tt_item(1, views=2_000_000, followers=20_000)
    item.setdefault("music", {})["title"] = "Patient Zero"
    api.answer(TT_SEARCH, page(TT_SEARCH, [item]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    assert CliRunner().invoke(app, ["hits", "pull"]).exit_code == 0
    (logged,) = lunar_lines(cli_store)
    assert logged.status.value == "ok" and logged.summary == "LunarCrush: 1 call on 2026-10-08"
    assert logged.details["lunar"] == {"day": "2026-10-08", "calls": 1, "keys": 1, "stages": {}}
    assert hits.lunar_calls_today(cli_store, NOW.date()) == 1


def test_a_pull_with_the_gate_off_or_no_call_made_logs_no_line(cli_store, monkeypatch):
    api = FakeAPI()
    api.answer(TT_SEARCH, page(TT_SEARCH, [tt_item(1, views=2_000_000, followers=20_000)]))
    monkeypatch.setattr(ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: api.client()))
    assert CliRunner().invoke(app, ["hits", "pull"]).exit_code == 0  # no LUNARCRUSH_API_KEY: the gate is off
    assert lunar_lines(cli_store) == []


def test_cli_pull_without_the_scrapecreators_key_reports_the_new_fields_too(cli_store, monkeypatch):
    monkeypatch.delenv("SCRAPECREATORS_API_KEY", raising=False)
    out = json.loads(CliRunner().invoke(app, ["hits", "pull"]).stdout)
    assert out["braked"] is False and out["skipped_dead"] == 0 and out["filed"] == []


class ProbeClient:
    def __init__(self, answer: str):
        self.answer, self.asked = answer, []

    def keyword_time_series(self, keyword):
        self.asked.append(keyword)
        return self.answer

    def scrub(self, text):
        return text


def probe(monkeypatch, answer: str | None):
    client = ProbeClient(answer) if answer is not None else None
    monkeypatch.setattr(lunar.LunarCrush, "from_env", classmethod(lambda cls, env=None, **kw: client))
    return CliRunner().invoke(app, ["hits", "lunar-probe", "Single Ladies"]), client


def test_lunar_probe_prints_the_parsed_curve_and_the_stage(monkeypatch):
    r, client = probe(monkeypatch, lunar_fixture("keyword_time_series_single_ladies"))
    out = json.loads(r.stdout)
    assert r.exit_code == 0 and client.asked == ["Single Ladies"] and out["keyword"] == "Single Ladies"
    assert (out["stage"], out["days_since_trend_peak"], out["peak_day"], out["source"]) == ("fading", 4, "2026-10-03", "tiktok")
    assert len(out["curve"]) == 30 and out["curve"][-1]["day"] == "2026-10-07" and out["curve"][-1]["interactions"] == 289_927
    assert set(out["curve"][0]) == {"day", "interactions", "smoothed"}


def test_lunar_probe_prints_the_raw_head_of_an_answer_it_cannot_read(monkeypatch):
    r, _ = probe(monkeypatch, "Z" * 500)
    out = json.loads(r.stdout)
    assert r.exit_code == 1 and out["raw_head"] == "Z" * 300 and out["stage"] == "unreadable" and "no table" in out["error"]


def test_lunar_probe_says_so_when_a_call_fails_and_never_without_a_key(monkeypatch):
    class Refused(ProbeClient):
        def keyword_time_series(self, keyword):
            raise lunar.LunarError("LunarCrush answered HTTP 401: nope", status=401)

    client = Refused("")
    monkeypatch.setattr(lunar.LunarCrush, "from_env", classmethod(lambda cls, env=None, **kw: client))
    r = CliRunner().invoke(app, ["hits", "lunar-probe", "x"])
    assert r.exit_code == 1 and "HTTP 401" in json.loads(r.stdout)["error"]
    r, _ = probe(monkeypatch, None)
    assert r.exit_code == 2 and "LUNARCRUSH_API_KEY" in r.stderr


def test_lunar_probe_says_when_the_curve_has_no_signal(monkeypatch):
    flat = "| time | tiktok_interactions |\n|---|---|\n" + "".join(f"| 2026-10-0{d} | 0 |\n" for d in range(1, 8))
    r, _ = probe(monkeypatch, flat)
    out = json.loads(r.stdout)
    assert r.exit_code == 0 and out["stage"] == "unknown" and "no signal" in out["reason"] and len(out["curve"]) == 7

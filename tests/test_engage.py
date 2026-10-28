"""``studio engage``: the daily comment drafts (targets from the stored hits, the drafts the daily run saves, the day's list).

Everything runs on ``MemoryStore``. The owner posts the comments by hand: nothing here posts, so there is no network to fake.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio import engage
from studio.cli import app
from studio.config import LONDON
from studio.models import Account, Character, Hit, Run, RunKind, RunStatus
from studio.store import MemoryStore

NOW = datetime(2026, 10, 28, 9, 30, tzinfo=LONDON)
DAY = "2026-10-28"
POST = "https://www.instagram.com/reel/DeFNvlUJ_WE/"


def roster() -> MemoryStore:
    store = MemoryStore()
    for slug, name, status in (("franz", "Franz", "live"), ("reginald", "Reginald", "live"), ("lenny", "Lenny Gold", "live"),
                               ("biscuit", "Biscuit", "retired")):  # fmt: skip
        store.upsert_character(Character(slug=slug, name=name, status=status))
    for slug, handle in (("franz", "franz.unimpressed"), ("reginald", "reginald.thebutler"), ("lenny", "lennygold.agent")):
        store.upsert_account(Account(character_slug=slug, platform="instagram", handle=handle))
    return store


def hit(store: MemoryStore, n: int, handle: str, *, character: str | None = "franz", platform: str = "instagram", followers: int | None = None,
        score: int = 50, caption: str | None = None, posted_days: int = 3) -> Hit:  # fmt: skip
    return store.upsert_hit(Hit(
        platform=platform, url=f"https://www.instagram.com/reel/Hit{n}/" if platform == "instagram" else f"https://www.tiktok.com/@x/video/{n}",
        creator_handle=handle, followers=followers, score=score, character_slug=character, caption=caption or f"caption {n}",
        posted_at=NOW - timedelta(days=posted_days),
    ))[0]  # fmt: skip


def draft(handle: str = "@godivathedachshund", comment: str = "He walks like he pays rent on the whole floor.", character: str = "franz",
          post_url: str = POST) -> dict[str, str]:  # fmt: skip
    return {"character": character, "handle": handle, "post_url": post_url, "comment": comment}


def day_row(store: MemoryStore, day: str, drafts: list[dict[str, str]]) -> Run:
    d = datetime.fromisoformat(day).date()
    return store.add_run(Run(kind=RunKind.comment_drafts, status=RunStatus.ok, started_at=datetime(d.year, d.month, d.day, 12, tzinfo=LONDON),
                             finished_at=NOW, details={"day": day, "drafts": drafts}))  # fmt: skip


@pytest.fixture
def store(monkeypatch) -> MemoryStore:
    s = roster()
    monkeypatch.setattr(engage, "open_store", lambda: s)
    monkeypatch.setattr(engage, "now_london", lambda: NOW)
    return s


def run(*args: str):
    return CliRunner().invoke(app, ["engage", *args])


def save(tmp_path: Path, *drafts: dict | str, name: str = "d.json"):
    f = tmp_path / name
    f.write_text(json.dumps({"drafts": list(drafts)}), encoding="utf-8")
    return run("save", str(f))


def rows(store: MemoryStore) -> list[Run]:
    return store.list_runs(kind=RunKind.comment_drafts)


# ---- targets -------------------------------------------------------------------------------------


def test_targets_are_the_characters_instagram_handles_best_followers_first(store):
    hit(store, 1, "@small", followers=1_000)
    hit(store, 2, "@big", followers=2_500_000)
    hit(store, 3, "@middle", followers=80_000)
    r = run("targets", "--character", "franz")
    assert r.exit_code == 0, r.output
    assert [t["handle"] for t in json.loads(r.output)] == ["@big", "@middle", "@small"]
    assert json.loads(r.output)[0] == {"handle": "@big", "followers": 2_500_000, "url": "https://www.instagram.com/reel/Hit2/", "caption": "caption 2"}


def test_targets_default_to_five_and_n_limits_them(store):
    for i in range(8):
        hit(store, i, f"@acct{i}", followers=1000 + i)
    assert len(json.loads(run("targets", "--character", "franz").output)) == 5
    assert [t["handle"] for t in json.loads(run("targets", "--character", "franz", "--n", "2").output)] == ["@acct7", "@acct6"]
    assert run("targets", "--character", "franz", "--n", "0").exit_code == 2


def test_instagram_gives_no_followers_so_the_best_hit_score_orders_them_and_followers_print_as_null(store):
    hit(store, 1, "@low", score=30)
    hit(store, 2, "@high", score=80)
    hit(store, 3, "@counted", score=10, followers=500)  # a known count beats an unknown one
    out = json.loads(run("targets", "--character", "franz").output)
    assert [t["handle"] for t in out] == ["@counted", "@high", "@low"]
    assert out[1]["followers"] is None


def test_one_row_per_handle_with_its_best_hit_and_its_biggest_follower_count(store):
    hit(store, 1, "@maker", followers=10_000, score=20, caption="old and weak")
    hit(store, 2, "@Maker", followers=40_000, score=90, caption="the best one")  # case does not make a second handle
    hit(store, 3, "maker", followers=None, score=40, caption="no at-sign")
    out = json.loads(run("targets", "--character", "franz").output)
    assert out == [{"handle": "@Maker", "followers": 40_000, "url": "https://www.instagram.com/reel/Hit2/", "caption": "the best one"}]


def test_only_this_characters_instagram_hits_with_a_handle_count(store):
    hit(store, 1, "@mine")
    hit(store, 2, "@tiktok_one", platform="tiktok")
    hit(store, 3, "@reginalds", character="reginald")
    hit(store, 4, "@general", character=None)
    hit(store, 5, None)
    hit(store, 6, "@")
    assert [t["handle"] for t in json.loads(run("targets", "--character", "franz").output)] == ["@mine"]
    assert [t["handle"] for t in json.loads(run("targets", "--character", "reginald").output)] == ["@reginalds"]


def test_a_handle_drafted_for_him_in_the_last_seven_days_is_skipped_for_him_only(store):
    for i, handle in enumerate(("@fresh", "@monday", "@seven", "@eight", "@shared")):
        hit(store, i, handle, followers=10 - i)
    hit(store, 20, "@shared", character="reginald", followers=3)
    day_row(store, "2026-10-26", [draft("@monday"), draft("@Shared"), draft("@shared", character="reginald")])
    day_row(store, "2026-10-21", [draft("@seven")])  # 7 days before today: still inside the week
    day_row(store, "2026-10-20", [draft("@eight")])  # 8 days before: free again
    assert [t["handle"] for t in json.loads(run("targets", "--character", "franz").output)] == ["@fresh", "@eight"]
    assert [t["handle"] for t in json.loads(run("targets", "--character", "reginald").output)] == []


def test_todays_own_drafts_do_not_hide_the_targets_so_a_rerun_is_the_same_list(store):
    hit(store, 1, "@a", followers=2)
    hit(store, 2, "@b", followers=1)
    first = run("targets", "--character", "franz").output
    day_row(store, DAY, [draft("@a"), draft("@b")])
    assert run("targets", "--character", "franz").output == first


def test_targets_refuses_a_character_that_is_not_live_or_unknown(store):
    for who in ("biscuit", "nobody"):
        r = run("targets", "--character", who)
        assert r.exit_code == 2 and "not live" in r.output


def test_no_hits_is_an_empty_list_not_an_error(store):
    r = run("targets", "--character", "lenny")
    assert r.exit_code == 0 and json.loads(r.output) == []


# ---- save ----------------------------------------------------------------------------------------


def test_save_writes_one_run_row_for_the_london_day(store, tmp_path):
    r = save(tmp_path, draft(), draft("godiva", "Bold of a sausage to own the lighting.", post_url="https://instagram.com/p/abc/"),
             draft("@jamiemiller", "The butler would like a word about the choreography.", "reginald"))  # fmt: skip
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {"day": DAY, "saved": {"franz": 2, "reginald": 1}, "kept": {}, "total": 3}
    (row,) = rows(store)
    assert row.kind is RunKind.comment_drafts and row.status is RunStatus.ok
    assert row.started_at == datetime(2026, 10, 28, 12, tzinfo=LONDON) and row.finished_at == NOW
    assert row.details["day"] == DAY
    assert [(d["character"], d["handle"]) for d in row.details["drafts"]] == [("franz", "@godivathedachshund"), ("franz", "@godiva"), ("reginald", "@jamiemiller")]
    assert set(row.details["drafts"][0]) == {"character", "handle", "post_url", "comment"}
    assert "franz 2" in row.summary and "reginald 1" in row.summary


def test_saving_the_same_day_again_replaces_those_characters_and_keeps_the_others(store, tmp_path):
    save(tmp_path, draft("@a", "first franz"), draft("@b", "first franz two"), draft("@c", "first reginald", "reginald"))
    r = save(tmp_path, draft("@z", "second franz", "franz"), name="d2.json")
    assert json.loads(r.output) == {"day": DAY, "saved": {"franz": 1}, "kept": {"reginald": 1}, "total": 2}
    (row,) = rows(store)  # updated in place: still one row
    assert [(d["character"], d["comment"]) for d in row.details["drafts"]] == [("reginald", "first reginald"), ("franz", "second franz")]


def test_saving_a_new_day_adds_a_new_row_and_leaves_the_old_one(store, tmp_path, monkeypatch):
    save(tmp_path, draft())
    monkeypatch.setattr(engage, "now_london", lambda: NOW + timedelta(days=1))
    save(tmp_path, draft("@other", "Different day, same unbothered face."))
    assert sorted(r.details["day"] for r in rows(store)) == [DAY, "2026-10-29"]


def test_a_comment_of_exactly_200_characters_is_fine_201_is_not(store, tmp_path):
    assert save(tmp_path, draft(comment="a" * 200)).exit_code == 0
    r = save(tmp_path, draft(comment="a" * 201), name="long.json")
    assert r.exit_code == 2 and "201 characters" in r.output and "200" in r.output


@pytest.mark.parametrize(
    ("comment", "why"),
    [
        ("", "missing or empty"),
        ("   ", "missing or empty"),
        ("Great one, see https://example.com/me", "link"),
        ("Great one, see http://x.io", "link"),
        ("Great one www.mysite.net", "link"),
        ("Great one mysite.com", "link"),
        ("Love this #dachshund", "hashtag"),
        ("#1 sausage", "hashtag"),
        ("Hello @franz.unimpressed hello", "our own account"),
        ("franz.unimpressed approves", "our own account"),
        ("From the desk of LennyGold.Agent", "our own account"),
        ("Follow me for more", "self-promotion"),
        ("Come follow my page", "self-promotion"),
        ("Check my page for the sequel", "self-promotion"),
        ("check out my profile", "self-promotion"),
        ("Link in bio", "self-promotion"),
        ("link in my bio!", "self-promotion"),
        ("DM me", "self-promotion"),
    ],
)
def test_save_refuses_a_bad_comment_with_exit_2_and_writes_nothing(store, tmp_path, comment, why):
    r = save(tmp_path, draft("@fine", "A perfectly good comment about the lighting.", post_url=POST), draft(comment=comment))
    assert r.exit_code == 2 and why in r.output, r.output
    assert rows(store) == []  # the good draft in the same file is not written either


def test_a_normal_comment_with_punctuation_emoji_and_a_mention_of_someone_else_is_fine(store, tmp_path):
    assert save(tmp_path, draft(comment="Not me crying at 'the pause' again, @godivathedachshund you did it again. Nice one!! 🐾")).exit_code == 0


def test_save_refuses_a_character_that_is_not_live_or_unknown(store, tmp_path):
    for who in ("biscuit", "nobody"):
        r = save(tmp_path, draft(character=who), name=f"{who}.json")
        assert r.exit_code == 2 and f"character '{who}' is not live" in r.output
    assert rows(store) == []


@pytest.mark.parametrize("post_url", ["", "http://www.instagram.com/p/x/", "https://evil.com/p/x/", "https://notinstagram.com/p/x", "javascript:alert(1)",
                                      "https://instagram.com.evil.com/p/x"])  # fmt: skip
def test_save_refuses_a_post_url_that_is_not_an_https_instagram_link(store, tmp_path, post_url):
    r = save(tmp_path, draft(post_url=post_url))
    assert r.exit_code == 2 and ("post_url" in r.output), r.output
    assert rows(store) == []


def test_save_lists_every_problem_at_once_and_names_the_draft(store, tmp_path):
    r = save(tmp_path, draft(comment="Follow us"), draft("@two", "ok one"), draft("@three", "tags #no", "reginald"))
    assert r.exit_code == 2
    assert "draft 1 (franz @godivathedachshund)" in r.output and "draft 3 (reginald @three)" in r.output and "draft 2" not in r.output


def test_save_refuses_a_second_draft_for_the_same_account(store, tmp_path):
    r = save(tmp_path, draft("@Same", "one"), draft("same", "two"))
    assert r.exit_code == 2 and "same account" in r.output


def test_save_refuses_a_missing_field_a_non_object_and_an_empty_list(store, tmp_path):
    bad = draft()
    del bad["handle"]
    r = save(tmp_path, bad)
    assert r.exit_code == 2 and "handle is missing" in r.output
    assert save(tmp_path, "just text", name="s.json").exit_code == 2
    assert save(tmp_path, name="e.json").exit_code == 2


def test_save_refuses_an_unreadable_or_invalid_file(store, tmp_path):
    assert run("save", str(tmp_path / "nope.json")).exit_code == 2
    f = tmp_path / "bad.json"
    f.write_text("{not json", encoding="utf-8")
    r = run("save", str(f))
    assert r.exit_code == 2 and "not valid JSON" in r.output
    f.write_text('["drafts"]', encoding="utf-8")
    assert run("save", str(f)).exit_code == 2


def test_the_handle_is_stored_with_an_at_sign_and_the_comment_trimmed(store, tmp_path):
    save(tmp_path, draft("plainhandle", "  Spaces around.  "))
    assert [(d["handle"], d["comment"]) for d in rows(store)[0].details["drafts"]] == [("@plainhandle", "Spaces around.")]


def test_what_save_wrote_hides_the_handle_from_the_next_targets_for_a_week(store, tmp_path, monkeypatch):
    hit(store, 1, "@godivathedachshund", followers=5)
    hit(store, 2, "@other", followers=1)
    save(tmp_path, draft("@godivathedachshund"))
    for days, expected in ((1, ["@other"]), (7, ["@other"]), (8, ["@godivathedachshund", "@other"])):
        monkeypatch.setattr(engage, "now_london", lambda d=days: NOW + timedelta(days=d))
        assert [t["handle"] for t in json.loads(run("targets", "--character", "franz").output)] == expected, days


# ---- show ----------------------------------------------------------------------------------------


def test_show_prints_todays_drafts_by_default_and_any_day_with_day(store, tmp_path):
    save(tmp_path, draft(), draft("@c", "Hello there, Reginald here.", "reginald"))
    day_row(store, "2026-10-20", [draft("@old", "an older one")])
    today = json.loads(run("show").output)
    assert today["day"] == DAY and [d["handle"] for d in today["drafts"]] == ["@godivathedachshund", "@c"]
    old = json.loads(run("show", "--day", "2026-10-20").output)
    assert old == {"day": "2026-10-20", "drafts": [draft("@old", "an older one")]}


def test_show_a_day_without_drafts_is_an_empty_list_and_a_bad_day_is_refused(store):
    r = run("show", "--day", "2026-09-01")
    assert r.exit_code == 0 and json.loads(r.output) == {"day": "2026-09-01", "drafts": []}
    assert run("show", "--day", "yesterday").exit_code == 2
    assert json.loads(run("show").output) == {"day": DAY, "drafts": []}


def test_the_group_lists_its_three_commands_and_needs_no_database_for_help():
    r = CliRunner().invoke(app, ["engage", "--help"])
    assert r.exit_code == 0 and all(c in r.output for c in ("targets", "save", "show"))


def test_the_run_kind_is_registered():
    assert RunKind.comment_drafts == "comment_drafts"

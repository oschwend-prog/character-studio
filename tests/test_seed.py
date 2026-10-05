"""`studio seed`: characters + accounts from characters/*/refs.json, and the batch-1 Viral Picks."""

import copy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio import seed
from studio.cli import app
from studio.favorites import auto_decision, next_favorites, score_pick
from studio.models import Body, Character, Platform
from studio.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
PICKS_DOC = ROOT / "docs" / "launch" / "viral-picks-2026-10-04.md"

BISCUIT = {
    "slug": "biscuit",
    "name": "Biscuit",
    "bodies": ["biped", "quadruped"],
    "masters": {"biped": "42f579b9-3da3-42ff-af47-98d758112743", "quadruped": "d863df81-54f8-45df-9676-cf44338d07fa"},
    "closeup": "7798e2bc-d0bd-492d-8d7f-a96063150c4f",
    "closeup_center": [536, 732],
    "blue_eye_xy": [301, 960],
    "avatar": "assets/avatars/biscuit.png",
    "accounts": [
        {"platform": "tiktok", "handle": None, "postiz_integration_id": None, "dropin_share": 0.70},
        {"platform": "instagram", "handle": None, "postiz_integration_id": None, "dropin_share": 0.40},
    ],
}
REGINALD = {
    "slug": "reginald",
    "name": "Reginald",
    "bodies": ["biped"],
    "masters": {"biped": "6b1625b1-b2e3-4292-ba35-4aac86e6b6e4", "quadruped": None},
    "closeup": None,
    "closeup_center": None,
    "blue_eye_xy": None,
    "avatar": "assets/avatars/reginald.png",
    "accounts": [
        {"platform": "tiktok", "handle": None, "postiz_integration_id": None, "dropin_share": 0.70},
        {"platform": "instagram", "handle": None, "postiz_integration_id": None, "dropin_share": 0.40},
    ],
}


def write_refs(tmp_path: Path, *refs: dict) -> Path:
    for r in refs:
        d = tmp_path / r["slug"]
        d.mkdir(exist_ok=True)
        (d / "refs.json").write_text(json.dumps(r))
    return tmp_path


def write_in(tmp_path: Path, folder: str, ref: dict) -> Path:
    """A refs.json under ``tmp_path/folder`` whatever its slug says (for the slug-mismatch case)."""
    (tmp_path / folder).mkdir(exist_ok=True)
    (tmp_path / folder / "refs.json").write_text(json.dumps(ref))
    return tmp_path


def refs(base: dict, **over) -> dict:
    out = copy.deepcopy(base)
    out.update(over)
    return out


# ---- characters and accounts -------------------------------------------------------------------


def test_seed_creates_characters_and_skips_null_accounts(tmp_path):
    store = MemoryStore()
    report = seed.seed_characters(store, write_refs(tmp_path, BISCUIT, REGINALD))

    assert [(c.slug, c.name, c.status) for c in store.characters()] == [
        ("biscuit", "Biscuit", "designing"),
        ("reginald", "Reginald", "designing"),
    ]
    assert store.characters()[0].bodies == [Body.biped, Body.quadruped]
    assert store.characters()[1].bodies == [Body.biped]
    assert store.accounts() == []  # no handle yet: nothing to insert (accounts.handle is NOT NULL)
    assert sorted((s["character"], s["platform"]) for s in report.skipped) == [
        ("biscuit", "instagram"), ("biscuit", "tiktok"),
        ("reginald", "instagram"), ("reginald", "tiktok"),
    ]
    assert all("handle" in s["reason"] for s in report.skipped)


def test_seed_upserts_accounts_with_the_explicit_share_per_platform(tmp_path):
    accounts = [
        {"platform": "tiktok", "handle": "@biscuit.odd", "postiz_integration_id": "pz-t", "dropin_share": None},
        {"platform": "instagram", "handle": "biscuit.odd", "postiz_integration_id": None, "dropin_share": None},
    ]
    store = MemoryStore()
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, accounts=accounts)))

    tiktok, insta = store.accounts("biscuit")[1], store.accounts("biscuit")[0]
    assert (insta.platform, insta.handle, insta.dropin_share) == (Platform.instagram, "biscuit.odd", 0.40)
    assert (tiktok.platform, tiktok.handle, tiktok.dropin_share) == (Platform.tiktok, "@biscuit.odd", 0.70)
    assert (tiktok.postiz_integration_id, insta.postiz_integration_id) == ("pz-t", None)
    assert tiktok.mode == insta.mode == "approval"


def test_an_explicit_share_in_refs_wins_on_the_first_insert(tmp_path):
    accounts = [{"platform": "instagram", "handle": "b", "postiz_integration_id": None, "dropin_share": 0.25}]
    store = MemoryStore()
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, accounts=accounts)))
    assert store.accounts("biscuit")[0].dropin_share == 0.25


def test_seeding_twice_changes_nothing_and_a_later_seed_fills_in_the_ids(tmp_path):
    store = MemoryStore()
    d = write_refs(tmp_path, BISCUIT)
    seed.seed_characters(store, d)
    seed.seed_characters(store, d)
    assert len(store.characters()) == 1 and store.accounts() == []

    accounts = [
        {"platform": "tiktok", "handle": "@biscuit.odd", "postiz_integration_id": None, "dropin_share": 0.70},
        {"platform": "instagram", "handle": None, "postiz_integration_id": None, "dropin_share": 0.40},
    ]
    write_refs(tmp_path, refs(BISCUIT, accounts=accounts))
    seed.seed_characters(store, tmp_path)
    first = store.accounts("biscuit")[0]
    accounts[0]["postiz_integration_id"] = "pz-1"  # the owner pastes the id in later
    write_refs(tmp_path, refs(BISCUIT, accounts=accounts))
    seed.seed_characters(store, tmp_path)
    after = store.accounts("biscuit")
    assert len(after) == 1 and after[0].id == first.id and after[0].postiz_integration_id == "pz-1"


def test_reseeding_does_not_undo_the_instagram_guard_or_autopilot(tmp_path):
    accounts = [{"platform": "instagram", "handle": "b", "postiz_integration_id": "pz", "dropin_share": 0.40}]
    store = MemoryStore()
    d = write_refs(tmp_path, refs(BISCUIT, accounts=accounts))
    seed.seed_characters(store, d)
    acct = store.accounts("biscuit")[0]
    store.update_account(acct.id, dropin_share=0.2, mode="auto")
    seed.seed_characters(store, d)
    again = store.accounts("biscuit")[0]
    assert (again.dropin_share, again.mode) == (0.2, "auto")


def test_status_comes_from_refs_so_going_live_is_one_edit_and_a_reseed(tmp_path):
    store = MemoryStore()
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, status="live")))
    assert store.characters()[0].status == "live"
    seed.seed_characters(store, write_refs(tmp_path, BISCUIT))  # edited back: designing again
    assert store.characters()[0].status == "designing"


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"slug": "other"}, "slug"),  # folder name is the slug
        ({"name": ""}, "name"),
        ({"bodies": ["biped", "winged"]}, "bodies"),
        ({"bodies": []}, "bodies"),
        ({"masters": {"biped": None, "quadruped": "d863df81-54f8-45df-9676-cf44338d07fa"}}, "master"),
        ({"status": "Live"}, "status"),
        ({"closeup_center": [1]}, "closeup_center"),
        ({"accounts": [{"platform": "myspace", "handle": None, "postiz_integration_id": None, "dropin_share": None}]}, "platform"),
        ({"accounts": [BISCUIT["accounts"][0], BISCUIT["accounts"][0]]}, "twice"),
        ({"accounts": [{"platform": "tiktok", "handle": "b", "postiz_integration_id": None, "dropin_share": 1.5}]}, "dropin_share"),
    ],
)
def test_bad_refs_are_refused_before_anything_is_written(tmp_path, over, message):
    store = MemoryStore()
    write_refs(tmp_path, refs(REGINALD))
    d = write_in(tmp_path, "biscuit", refs(BISCUIT, **over))
    with pytest.raises(ValueError, match=message):
        seed.seed_characters(store, d)
    assert store.characters() == []  # reginald was fine, but the run is all or nothing


def test_refs_that_are_not_json_are_refused(tmp_path):
    (tmp_path / "biscuit").mkdir()
    (tmp_path / "biscuit" / "refs.json").write_text("{nope")
    with pytest.raises(ValueError, match="refs.json"):
        seed.load_refs(tmp_path)


def test_an_empty_characters_folder_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no refs.json"):
        seed.load_refs(tmp_path)


def test_the_shipped_refs_files_load_and_match_the_brief():
    loaded = {r["slug"]: r for r in seed.load_refs(seed.DEFAULT_CHARACTERS_DIR)}
    assert sorted(loaded) == ["biscuit", "reginald"]
    b, r = loaded["biscuit"], loaded["reginald"]
    assert b["masters"] == BISCUIT["masters"] and b["closeup"] == BISCUIT["closeup"]
    assert (b["closeup_center"], b["blue_eye_xy"], b["bodies"]) == ([536, 732], [301, 960], ["biped", "quadruped"])
    assert r["masters"]["biped"] == REGINALD["masters"]["biped"] and r["masters"]["quadruped"] is None
    assert r["closeup"] is None and r["bodies"] == ["biped"]
    for c in (b, r):
        assert c["status"] == "designing"  # flipped to live at go-live (Task 16)
        assert {a["platform"]: a["dropin_share"] for a in c["accounts"]} == {"tiktok": 0.70, "instagram": 0.40}
        assert all(a["handle"] is None and a["postiz_integration_id"] is None for a in c["accounts"])
        assert (ROOT / c["avatar"]).parent.is_dir()


def test_seeding_the_shipped_refs_creates_two_characters_and_no_accounts():
    store = MemoryStore()
    report = seed.seed_characters(store, seed.DEFAULT_CHARACTERS_DIR)
    assert [c.slug for c in store.characters()] == ["biscuit", "reginald"]
    assert store.accounts() == [] and len(report.skipped) == 4


# ---- CLI: seed + seed status -----------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(seed, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["seed", *args])


def test_cli_seed_prints_what_it_did(cli_store, tmp_path):
    accounts = [{"platform": "tiktok", "handle": "@b", "postiz_integration_id": "pz", "dropin_share": 0.7}]
    d = write_refs(tmp_path, refs(BISCUIT, accounts=accounts, status="live"), REGINALD)
    r = run("--characters-dir", str(d))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert [(c["slug"], c["status"]) for c in out["characters"]] == [("biscuit", "live"), ("reginald", "designing")]
    assert [(a["character"], a["platform"], a["handle"], a["connected"]) for a in out["accounts"]] == [
        ("biscuit", "tiktok", "@b", True)
    ]
    assert len(out["skipped_accounts"]) == 2  # reginald has no handles yet; biscuit lists only tiktok


def test_cli_seed_refuses_bad_refs_with_exit_2(cli_store, tmp_path):
    r = run("--characters-dir", str(write_in(tmp_path, "biscuit", refs(BISCUIT, slug="x"))))
    assert r.exit_code == 2 and "slug" in r.output
    assert cli_store.characters() == []


def test_cli_seed_status_lists_each_character_with_its_status_and_accounts(cli_store, tmp_path):
    accounts = [{"platform": "tiktok", "handle": "@b", "postiz_integration_id": "pz", "dropin_share": 0.7}]
    seed.seed_characters(cli_store, write_refs(tmp_path, refs(BISCUIT, accounts=accounts, status="live"), REGINALD))
    r = run("status")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert [(c["slug"], c["status"], c["live"]) for c in out] == [("biscuit", "live", True), ("reginald", "designing", False)]
    assert out[0]["accounts"] == [
        {"platform": "tiktok", "handle": "@b", "connected": True, "mode": "approval", "dropin_share": 0.7}
    ]
    assert out[1]["accounts"] == []


# ---- batch-1 picks: parsing --------------------------------------------------------------------


@pytest.fixture(scope="module")
def doc() -> str:
    return PICKS_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows(doc):
    return {r.id: r for r in seed.parse_picks(doc)}


def test_the_doc_yields_all_17_picks_in_rank_order(doc):
    parsed = seed.parse_picks(doc)
    assert [r.id for r in parsed] == [
        "B1", "B2", "D2", "D6", "D4", "D1", "B3", "D5", "O1", "O5", "D3", "B4", "B5", "B6", "O3", "O2", "O4",
    ]


def test_every_scored_total_is_reproduced_by_the_code(rows):
    for r in rows.values():
        got = score_pick(r.outlier_x, r.views, **r.judged)
        assert got["total"] == r.total, r.id


def test_b1_carries_every_field_of_the_brief(rows):
    b1 = rows["B1"]
    assert b1.url == "https://www.instagram.com/reel/Dde-rPWCOC6/" and b1.platform == "instagram"
    assert b1.creator == "@eatfryhaven" and b1.views == 43_400_000 and b1.outlier_x == 1393.0
    assert b1.character == "reginald" and b1.total == 92
    assert b1.judged == {"freshness": 8, "fit": 10, "feasibility": 9, "saturation": 7}
    p = b1.proposal
    assert (p["mode"], p["hook"], p["prop"]) == ("recreate", "first day as head butler", "silver tray + teapot")
    assert "Pours tea with spy gravity" in p["concept"]
    assert "orchestral swell" in p["enhancement"] and "slow-mo" in p["enhancement"]
    assert "needs" not in p


def test_creators_come_from_the_note_or_else_from_the_tiktok_url(rows):
    assert rows["D2"].creator == "@tillandsialover"  # tiktok url
    assert rows["D3"].creator == "@bellvtrix.ai"  # note "(@bellvtrix.ai, made with Genjutsu)"
    assert rows["D4"].creator == "@banana.the.wiener"  # note has no handle
    assert rows["B6"].creator == "@realmrmotivator"
    assert rows["O5"].creator == "@fruitgram.tv"


def test_views_and_outliers_parse_k_m_and_thousands_separators(rows):
    assert (rows["B6"].views, rows["B6"].outlier_x) == (349_700, 291.0)
    assert (rows["B2"].views, rows["B2"].outlier_x) == (5_600_000, 3475.0)
    assert (rows["D3"].views, rows["D3"].outlier_x) == (17_400_000, 44.6)


def test_drop_in_picks_say_so_and_the_rest_recreate(rows):
    assert rows["D2"].proposal["mode"] == "dropin" and rows["B3"].proposal["mode"] == "dropin"
    assert "else Recreate" in rows["D2"].proposal["mode_note"]
    assert [r.proposal["mode"] for r in rows.values() if r.id not in ("D2", "B3", "O1", "O2", "O3", "O4", "O5")] == [
        "recreate"
    ] * 10


def test_needs_follow_the_bodies_and_the_talking_lane(rows):
    multi = {i for i, r in rows.items() if r.proposal.get("needs") == "multi_body"}
    talking = {i for i, r in rows.items() if r.proposal.get("needs") == "talking_lane"}
    assert multi == {"D1", "D3", "B4", "B5", "B6"}
    assert talking == {"O1", "O2", "O3", "O4", "O5"}


def test_props_and_the_outsider_button_lines(rows):
    assert rows["D4"].proposal.get("prop") is None  # the doc says "—"
    assert rows["D1"].proposal["prop"] == "tiny crown"
    assert rows["O1"].proposal["button_line"] == "I requested it flat. It arrived round."
    assert "mode" not in rows["O1"].proposal  # the talking lane has no mode column: nothing invented


def test_enhancements_attach_only_to_a_pick_with_a_row_of_its_own(rows):
    assert "stamps a tiny" in rows["D6"].proposal["enhancement"]
    assert "enhancement" in rows["D1"].proposal
    for i in ("D3", "B4", "B5", "B6", "O1", "O2"):
        assert "enhancement" not in rows[i].proposal  # shared rows hold an order note, not an enhancement


def test_decisions_by_rule_for_80_plus_and_analyst_below(rows):
    approved = {i: (r.decision, r.by) for i, r in rows.items() if r.decision == "approve"}
    assert approved == {
        "B1": ("approve", "rule"), "B2": ("approve", "rule"), "D2": ("approve", "rule"),
        "D6": ("approve", "rule"), "D4": ("approve", "analyst"), "B3": ("approve", "analyst"),
        "D5": ("approve", "analyst"),
    }
    held = {i for i, r in rows.items() if r.decision == "hold"}
    assert held == {"D1", "D3", "B4", "B5", "B6", "O1", "O2", "O3", "O4", "O5"}
    assert "Biggest outlier in every scan" in rows["B1"].reason
    assert "multi-body test passes by 10 Oct" in rows["D1"].reason and "3 bodies are untested" in rows["D1"].reason
    assert "pre-approved for the Outsider launch" in rows["O5"].reason


# ---- batch-1 picks: loading ---------------------------------------------------------------------


def seeded() -> MemoryStore:
    store = MemoryStore()
    store.upsert_character(Character(slug="biscuit", name="Biscuit", bodies=["biped", "quadruped"]))
    store.upsert_character(Character(slug="reginald", name="Reginald", bodies=["biped"]))
    return store


def snapshot(store: MemoryStore) -> list[dict]:
    return [vars(f).copy() for f in store.list_favorites()]


def test_seed_picks_loads_17_with_the_recorded_decisions(doc):
    store = seeded()
    summary = seed.seed_picks(store, doc)
    favs = {f.url: f for f in store.list_favorites()}
    assert len(favs) == 17
    assert summary["created"] == 17 and summary["approved"] == 7 and summary["held"] == 10

    b1 = favs["https://www.instagram.com/reel/Dde-rPWCOC6/"]
    assert (b1.status, b1.total_score, b1.character_slug, b1.origin) == ("approved", 92.0, "reginald", "scan")
    assert b1.proposal["decision"]["by"] == "rule" and "Biggest outlier" in b1.proposal["decision"]["reason"]
    assert (b1.views, b1.outlier_x, b1.creator_handle) == (43_400_000, 1393.0, "@eatfryhaven")
    assert b1.scores["feasibility"] == 9 and b1.scores["virality"] == 10.0

    d4 = favs["https://www.tiktok.com/@banana.the.wiener/video/7673905586383113503"]
    assert d4.status == "approved" and d4.proposal["decision"]["by"] == "analyst"
    assert "cheapest clip" in d4.proposal["decision"]["reason"]

    assert sorted(f.status for f in favs.values()).count("approved") == 7
    assert sorted(f.status for f in favs.values()).count("new") == 10


def test_held_picks_stay_new_with_a_hold_reason_and_a_valid_needs(doc):
    store = seeded()
    seed.seed_picks(store, doc)
    held = [f for f in store.list_favorites() if f.status == "new"]
    assert len(held) == 10
    for f in held:
        assert f.proposal["needs"] in ("multi_body", "talking_lane")
        assert f.proposal["hold_reason"] and f.proposal["decision"]["decision"] == "hold"
        assert auto_decision(f) == "hold"  # the standing rule agrees: it is blocked, not low-scoring
    d1 = next(f for f in held if f.url.endswith("Dd9QM6WKSfJ/"))
    assert d1.proposal["needs"] == "multi_body" and "10 Oct" in d1.proposal["hold_reason"]


def test_rule_approvals_are_ones_the_rule_itself_would_approve(doc):
    store = seeded()
    seed.seed_picks(store, doc)
    for f in store.list_favorites(status="approved"):
        if f.proposal["decision"]["by"] == "rule":
            assert f.total_score >= 80 and f.scores["feasibility"] >= 7


def test_the_outsider_is_not_a_seeded_character_so_those_picks_are_unmatched(doc):
    store = seeded()
    seed.seed_picks(store, doc)
    outsiders = [f for f in store.list_favorites() if f.proposal.get("needs") == "talking_lane"]
    assert len(outsiders) == 5
    assert all(f.character_slug is None and f.proposal["intended_character"] == "outsider" for f in outsiders)
    others = [f for f in store.list_favorites() if f.proposal.get("needs") != "talking_lane"]
    assert all(f.character_slug in ("biscuit", "reginald") for f in others)
    assert all("intended_character" not in f.proposal for f in others)


def test_a_seeded_outsider_character_gets_its_picks_matched(doc):
    store = seeded()
    store.upsert_character(Character(slug="outsider", name="The Outsider", bodies=["biped"]))
    seed.seed_picks(store, doc)
    assert sum(f.character_slug == "outsider" for f in store.list_favorites()) == 5


def test_re_running_changes_nothing(doc):
    store = seeded()
    seed.seed_picks(store, doc)
    before = snapshot(store)
    summary = seed.seed_picks(store, doc)
    assert snapshot(store) == before
    assert summary["created"] == 0 and summary["approved"] == 0 and summary["held"] == 0
    assert summary["existing"] == 17


def test_a_pick_the_owner_skipped_is_never_resurrected(doc):
    store = seeded()
    seed.seed_picks(store, doc)
    b2 = store.list_favorites(url="https://www.instagram.com/reel/DdZCANpDgI2/")[0]
    store.update_favorite(b2.id, status="skipped")
    seed.seed_picks(store, doc)
    assert store.get_favorite(b2.id).status == "skipped"


def test_a_held_pick_that_was_approved_later_stays_approved(doc):
    store = seeded()
    seed.seed_picks(store, doc)
    d1 = store.list_favorites(url="https://www.instagram.com/reel/Dd9QM6WKSfJ/")[0]
    store.update_favorite(d1.id, status="approved")
    seed.seed_picks(store, doc)
    assert store.get_favorite(d1.id).status == "approved"


def test_production_order_is_the_docs_rank_order_so_each_character_starts_with_its_best(doc):
    store = seeded()
    seed.seed_picks(store, doc)
    queue = next_favorites(store, 10)
    reginald = [f.url for f in queue if f.character_slug == "reginald"]
    biscuit = [f.url for f in queue if f.character_slug == "biscuit"]
    assert [u.rstrip("/").rsplit("/", 1)[-1] for u in reginald] == ["Dde-rPWCOC6", "DdZCANpDgI2", "DcREZSzowjZ"]  # B1 B2 B3
    assert [u.rstrip("/").rsplit("/", 1)[-1] for u in biscuit] == [
        "7688386199270001953", "Dd1koUkoXgq", "7673905586383113503", "7679128537311251734",
    ]  # D2 D6 D4 D5
    assert len(queue) == 7


# ---- batch-1 picks: the doc is checked, not trusted ----------------------------------------------


def test_a_changed_total_in_the_doc_is_caught_and_nothing_is_written(doc):
    bad = doc.replace("| 1 | B1 | reginald | **92** |", "| 1 | B1 | reginald | **91** |")
    assert bad != doc
    store = seeded()
    with pytest.raises(ValueError, match="B1.*total"):
        seed.seed_picks(store, bad)
    assert store.list_favorites() == []


def test_an_unknown_decision_row_is_caught(doc):
    bad = doc.replace("| B1 | ✅ approved (auto) |", "| B1 | ❓ maybe |")
    with pytest.raises(ValueError, match="B1.*decision"):
        seed.parse_picks(bad)


def test_an_auto_marker_that_disagrees_with_the_total_is_caught(doc):
    bad = doc.replace("| D4 | ✅ approved (analyst) |", "| D4 | ✅ approved (auto) |")
    with pytest.raises(ValueError, match="D4"):
        seed.parse_picks(bad)


def test_a_pick_without_a_decision_row_is_caught(doc):
    bad = "\n".join(line for line in doc.splitlines() if not line.startswith("| D5 | ✅"))
    with pytest.raises(ValueError, match="D5"):
        seed.parse_picks(bad)


def test_a_hold_that_does_not_match_the_needs_is_caught(doc):
    bad = doc.replace("| D1 | ⏸ hold", "| D1 | ✅ approved (analyst)")
    with pytest.raises(ValueError, match="D1"):
        seed.parse_picks(bad)


def test_a_garbled_row_is_a_clear_error(doc):
    bad = doc.replace("| B2 | https://www.instagram.com/reel/DdZCANpDgI2/ (@drink321coffee, barista POV) | 5.6M · 3,475× |",
                      "| B2 | https://www.instagram.com/reel/DdZCANpDgI2/ (@drink321coffee, barista POV) |")
    with pytest.raises(ValueError, match="B2|cells"):
        seed.parse_picks(bad)


def test_a_document_with_no_picks_is_an_error():
    with pytest.raises(ValueError, match="no pick"):
        seed.parse_picks("# nothing here\n")


# ---- CLI: seed picks -----------------------------------------------------------------------------


def test_cli_seed_picks_prints_a_summary_and_is_idempotent(cli_store):
    seed.seed_characters(cli_store, seed.DEFAULT_CHARACTERS_DIR)
    r = run("picks", str(PICKS_DOC))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["picks"], out["created"], out["approved"], out["held"]) == (17, 17, 7, 10)
    again = json.loads(run("picks", str(PICKS_DOC)).stdout)
    assert (again["created"], again["existing"]) == (0, 17)
    assert len(cli_store.list_favorites()) == 17


def test_cli_seed_picks_missing_file_exits_2(cli_store, tmp_path):
    r = run("picks", str(tmp_path / "nope.md"))
    assert r.exit_code == 2 and "no such file" in r.output


def test_cli_seed_picks_bad_doc_exits_2_and_writes_nothing(cli_store, tmp_path):
    f = tmp_path / "x.md"
    f.write_text("# nothing here\n")
    r = run("picks", str(f))
    assert r.exit_code == 2 and cli_store.list_favorites() == []

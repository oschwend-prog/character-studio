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
    "masters": {"biped": "e07675a2-38a5-4325-8326-1de2e0d326ba", "quadruped": "d863df81-54f8-45df-9676-cf44338d07fa"},
    "closeup": "4f7fc954-4dca-491a-bb72-d1781a063c06",
    "closeup_center": [584, 738],
    "blue_eye_xy": [251, 559],
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
    "masters": {"biped": "6c445225-cf07-462f-b5da-8494381e7e58", "quadruped": None},
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
    tmp_path.mkdir(exist_ok=True)
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


def test_seed_writes_the_setup_the_terminal_shows(tmp_path):
    """characters.setup = {closeup: bool, planned_handles: {tiktok, instagram}} straight from refs.json (migration 0007)."""
    store = MemoryStore()
    biscuit = refs(BISCUIT, accounts=[
        {"platform": "tiktok", "handle": None, "planned_handle": "@biscuit.moves", "postiz_integration_id": None},
        {"platform": "instagram", "handle": None, "postiz_integration_id": None},
    ])
    seed.seed_characters(store, write_refs(tmp_path, biscuit, REGINALD))
    by = {c.slug: c for c in store.characters()}
    assert by["biscuit"].setup == {"closeup": True, "planned_handles": {"tiktok": "@biscuit.moves", "instagram": None}}
    assert by["reginald"].setup == {"closeup": False, "planned_handles": {"tiktok": None, "instagram": None}}


TRAITS = {
    "energy": "bouncy and puppy-cute",
    "comedy": "wholesome ego",
    "best_formats": ["slick dance", "eye loop", "hits every beat"],
    "settings": ["sunlit room", "dance studio", "kitchen"],
    "moves": ["upright dance", "head snap", "paw gestures"],
    "props": ["gold chain", "shades", "tiny crown"],
    "music": "afro house, 118-124 BPM",
    "never": ["clumsy moves", "barking", "exposed belly"],
}


BISCUIT_GADGETS = [
    ("aviator shades", "the reveal, he lowers them on the drop to show the odd eyes"),
    ("gold chain", "swagger energy, comment bait"),
    ("tiny crown", "lead-dancer / king ego captions"),
    ("terry headband + wristbands", "gym and workout trends"),
    ("mini white hi-tops", "footwork shots, sporty look"),
    # the owner's name has a space either side of "+": 41 characters, one over a chip / owner prop, so it is written without them
    ("chunky retro sneakers (baby-blue+white)", "sneakerhead / drip-check trends, close-up on the footwork"),
    ("light-up LED sneakers", "night dance shots: every step glows on the beat"),
    ("baby-blue bucket hat", "streetwear drip trends"),
    ("cream puffer vest", "autumn/winter drip"),
    ("hot-dog-bun costume", "Halloween (seasonal)"),
    ("Santa hat", "Christmas (seasonal)"),
]
REGINALD_GADGETS = [
    ("silver tray + teapot", 'his signature, "not a drop spilled" rewatch bait'),
    ("sweatband under the quiff", "gym/dance gag, the quiff still doesn't move"),
    ("aviators over his glasses", "cool-butler reveal, double-glasses gag"),
    ("gold pocket watch", '"4pm. tea." timing gags, Tea Tuesday series'),
    ("black umbrella", "iconic routines (Singin' in the Rain), cane"),
    ("feather duster", "microphone gag, cleaning-day trends"),
    ("candelabra", "Halloween / Wednesday"),
]


def test_seed_writes_the_traits_card_into_the_setup(tmp_path):
    """characters.setup.traits = refs.json traits, verbatim: the terminal's Traits card and the daily run's fit scoring read it."""
    store = MemoryStore()
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, traits=TRAITS), REGINALD))
    by = {c.slug: c for c in store.characters()}
    assert by["biscuit"].setup["traits"] == TRAITS
    assert "traits" not in by["reginald"].setup  # a character without a card has none (not an empty one)
    assert by["biscuit"].setup["closeup"] is True  # the rest of the setup is unchanged


SHEETS = {"biped": "a81a474c-4c7f-4bcd-9b23-43a822c7c004", "quadruped": "aad0f3d0-9694-4148-acbe-eb1f4bf34891"}


def test_seed_writes_the_character_sheets_into_the_setup(tmp_path):
    """Higgsfield best practice: the character sheet goes to Genjutsu as the reference image next to the master."""
    store = MemoryStore()
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, sheets=SHEETS), REGINALD))
    by = {c.slug: c for c in store.characters()}
    assert by["biscuit"].setup["sheets"] == SHEETS
    assert "sheets" not in by["reginald"].setup  # a character without a sheet has none


@pytest.mark.parametrize(
    ("sheets", "message"),
    [
        ("a81a474c", "sheets"),  # not an object
        ({"winged": "x"}, "winged"),  # a body that does not exist
        ({"biped": ""}, "biped"),
        ({"biped": 5}, "biped"),
        ({"quadruped": "aad0f3d0"}, "quadruped"),  # Reginald is biped only: a quadruped sheet names a body he does not have
    ],
)
def test_a_malformed_sheets_object_is_refused_before_anything_is_written(tmp_path, sheets, message):
    store = MemoryStore()
    ref = refs(REGINALD, sheets=sheets)
    with pytest.raises(ValueError, match=message):
        seed.seed_characters(store, write_refs(tmp_path, ref))
    assert store.characters() == []


def test_a_prop_is_a_plain_string_or_a_name_with_its_viral_job(tmp_path):
    """owner 2026-10-05: gadgets should help characters go viral, so a prop may say what it is for."""
    props = ["gold chain", {"name": "aviator shades", "job": "the reveal: lowers them on the drop"}]
    store = MemoryStore()
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, traits={**TRAITS, "props": props})))
    assert store.characters()[0].setup["traits"]["props"] == props  # both shapes survive the seed verbatim
    assert seed.prop_names({"props": props}) == ["gold chain", "aviator shades"]


def test_a_reseed_replaces_the_traits(tmp_path):
    store = MemoryStore()
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, traits=TRAITS)))
    seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, traits={**TRAITS, "energy": "calm"})))
    assert store.characters()[0].setup["traits"]["energy"] == "calm"


@pytest.mark.parametrize(
    ("traits", "message"),
    [
        ("calm", "traits"),  # not an object
        ({**TRAITS, "energy": ""}, "energy"),
        ({**TRAITS, "comedy": 5}, "comedy"),
        ({**TRAITS, "music": "x" * 161}, "music"),
        ({k: v for k, v in TRAITS.items() if k != "never"}, "never"),  # every key is needed
        ({**TRAITS, "vibe": "chill"}, "vibe"),  # and no others
        ({**TRAITS, "props": []}, "props"),
        ({**TRAITS, "moves": "dance"}, "moves"),  # a bare string is not a list
        ({**TRAITS, "settings": ["ok", ""]}, "settings"),
        ({**TRAITS, "best_formats": ["a"] * 9}, "best_formats"),
        ({**TRAITS, "never": ["x" * 81]}, "never"),
        ({**TRAITS, "props": ["x" * 41]}, "props"),  # a prop becomes a Make-it chip: at most 40 characters
        ({**TRAITS, "moves": [3]}, "moves"),
        ({**TRAITS, "props": [{"name": "gold chain"}]}, "props"),  # an object prop needs its job too
        ({**TRAITS, "props": [{"name": "", "job": "swagger"}]}, "props"),
        ({**TRAITS, "props": [{"name": "x" * 41, "job": "swagger"}]}, "props"),
        ({**TRAITS, "props": [{"name": "gold chain", "job": "x" * 121}]}, "props"),
        ({**TRAITS, "props": [{"name": "gold chain", "job": "swagger", "price": 5}]}, "props"),  # no other keys
        ({**TRAITS, "props": [{"name": "gold chain", "job": 4}]}, "props"),
        ({**TRAITS, "props": ["chain"] * 13}, "props"),
        ({**TRAITS, "moves": [{"name": "dance", "job": "x"}]}, "moves"),  # only props carry a job
    ],
)
def test_a_malformed_traits_card_is_refused_before_anything_is_written(tmp_path, traits, message):
    store = MemoryStore()
    with pytest.raises(ValueError, match=message):
        seed.seed_characters(store, write_refs(tmp_path, refs(BISCUIT, traits=traits)))
    assert store.characters() == []


def test_the_setup_names_the_real_handle_once_the_account_exists_and_follows_the_closeup(tmp_path):
    store = MemoryStore()
    accounts = [
        {"platform": "tiktok", "handle": "@real.one", "planned_handle": "@first.choice", "postiz_integration_id": "pz"},
        {"platform": "instagram", "handle": None, "planned_handle": "plan.ig", "postiz_integration_id": None},
    ]
    d = write_refs(tmp_path, refs(REGINALD, closeup=None, accounts=accounts))
    seed.seed_characters(store, d)
    assert store.characters()[0].setup == {"closeup": False, "planned_handles": {"tiktok": "@real.one", "instagram": "plan.ig"}}
    write_refs(tmp_path, refs(REGINALD, closeup="cu-job", accounts=accounts))  # the close-up lands: a re-seed flips it
    seed.seed_characters(store, tmp_path)
    assert store.characters()[0].setup["closeup"] is True


def test_a_planned_handle_must_be_a_string_or_null(tmp_path):
    bad = refs(BISCUIT, accounts=[{"platform": "tiktok", "handle": None, "planned_handle": 7, "postiz_integration_id": None}])
    with pytest.raises(ValueError, match="planned_handle"):
        seed.seed_characters(MemoryStore(), write_refs(tmp_path, bad))


def test_the_repos_own_refs_plan_the_first_choice_handles_of_the_social_pages_kit():
    """docs/launch/social-pages.md: first choice for each character; the file is the single source for the terminal."""
    by = {r["slug"]: r for r in seed.load_refs()}
    planned = {s: {a["platform"]: a.get("planned_handle") for a in by[s]["accounts"]} for s in by}
    assert planned["biscuit"] == {"tiktok": "@biscuit.moves", "instagram": "biscuit.moves"}
    assert planned["reginald"] == {"tiktok": "@reginald.thebutler", "instagram": "reginald.thebutler"}


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


FRANZ_KIT = {
    "pill": {"fill": "#F4EBDD", "fill_alpha": 255, "text": "#1F2A44", "font": "PlayfairDisplay-Italic-Variable.ttf", "weight": "Medium", "radius": 34},
    "entrance": "fade_rise",
    "hook_edit": "push_in",
    "tone": "warm",
}


def test_a_valid_style_block_loads_untouched(tmp_path):
    (loaded,) = seed.load_refs(write_refs(tmp_path, refs(REGINALD, style=FRANZ_KIT)))
    assert loaded["style"] == FRANZ_KIT
    (plain,) = seed.load_refs(write_refs(tmp_path / "plain", REGINALD))
    assert "style" not in plain, "a character without a kit has none"


@pytest.mark.parametrize(
    ("style", "message"),
    [
        ({**FRANZ_KIT, "pill": {**FRANZ_KIT["pill"], "fill": "cream"}}, r"style\.pill.*fill"),  # a bad hex
        ({**FRANZ_KIT, "pill": {**FRANZ_KIT["pill"], "text": "#1F2A4"}}, r"style\.pill.*text"),
        ({**FRANZ_KIT, "entrance": "spin"}, "entrance"),  # an unknown entrance
        ({**FRANZ_KIT, "hook_edit": "wobble"}, "hook_edit"),
        ({**FRANZ_KIT, "tone": "neon"}, "tone"),
        ({**FRANZ_KIT, "pill": {**FRANZ_KIT["pill"], "font": "Nope-Regular.ttf"}}, r"font.*assets/fonts"),  # a font that is not committed
        ({**FRANZ_KIT, "pill": {**FRANZ_KIT["pill"], "font": "../../README.md"}}, "font"),
        ({**FRANZ_KIT, "pill": {**FRANZ_KIT["pill"], "case": "title"}}, "case"),
        ({**FRANZ_KIT, "pill": {**FRANZ_KIT["pill"], "colour": "#FFFFFF"}}, "colour"),  # a key that is not in the kit
        ({**FRANZ_KIT, "voice": "posh"}, "voice"),
        ({"pill": "dark"}, r"style\.pill"),
        ("dark", "style"),
        ([], "style"),
    ],
)
def test_style_block_is_validated(tmp_path, style, message):
    store = MemoryStore()
    d = write_refs(tmp_path, refs(REGINALD, style=style))
    with pytest.raises(ValueError, match=message):
        seed.seed_characters(store, d)
    assert store.characters() == []


def test_a_kit_may_name_only_some_of_its_parts():
    ok = seed.validate_style({"entrance": "slam"}, Path("x/refs.json"))
    assert ok == {"entrance": "slam"}  # the pill, hook edit and tone stay at today's defaults
    assert seed.validate_style({}, Path("x/refs.json")) == {}


def test_the_roster_kits_load():
    """Franz, Reginald and Lenny carry their kit in refs.json, the DJ's (parked, no refs.json) sits in characters/dj/style.json."""
    loaded = {r["slug"]: r for r in seed.load_refs(seed.DEFAULT_CHARACTERS_DIR)}
    assert "dj" not in loaded, "no refs.json: the seed ignores the DJ's folder"
    assert "style" not in loaded["biscuit"], "retired Biscuit keeps today's pill"
    f, r, ln = (loaded[s]["style"] for s in ("franz", "reginald", "lenny"))
    assert f == FRANZ_KIT  # cream card, navy italic serif, round corners; fades and rises; slow push-in; warm
    assert r == {
        "pill": {"fill": "#0E0F12", "text": "#F2F0EA", "border": ["#E8E6E1", 2], "font": "CormorantSC-Medium.ttf", "weight": None,
                 "case": "smallcaps", "tracking": 3, "radius": 6},
        "entrance": "none", "hook_edit": "pause", "tone": "cool",
    }
    assert ln == {
        "pill": {"fill": "#E8B931", "fill_alpha": 255, "text": "#141414", "font": "Oswald-Variable.ttf", "weight": "Bold", "case": "upper", "radius": 16},
        "entrance": "slam", "hook_edit": "punch_in", "tone": "golden",
    }
    dj_path = seed.DEFAULT_CHARACTERS_DIR / "dj" / "style.json"
    dj = seed.validate_style(json.loads(dj_path.read_text()), dj_path)
    assert dj == {
        "pill": {"fill": "#E6FF00", "fill_alpha": 255, "text": "#111111", "font": "Anton-Regular.ttf", "weight": None, "case": "upper", "shear": 0.2,
                 "tilt_deg": -4, "block": ["#FF7A00", 10, 10], "radius": 12},
        "entrance": "word_pop", "hook_edit": "drop_flash", "tone": "punchy",
    }


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
    # the roster of 2026-10-06: Franz and Lenny Gold joined (designing, no accounts yet); Biscuit is retired but kept
    assert sorted(loaded) == ["biscuit", "franz", "lenny", "reginald"]
    b, r = loaded["biscuit"], loaded["reginald"]
    assert b["masters"] == BISCUIT["masters"] and b["closeup"] == BISCUIT["closeup"]
    assert (b["closeup_center"], b["blue_eye_xy"], b["bodies"]) == ([584, 738], [251, 559], ["biped", "quadruped"])
    # owner 2026-10-06: the exaggerated gpt_image_2_5 canon, upscaled to 2K (4fb61254 = upscale of 42772b6a)
    assert r["masters"]["biped"] == "4fb61254-cc90-4393-b71d-e2f9886400ad" and r["masters"]["quadruped"] is None
    # 2026-10-06: the new head-and-shoulders close-up from the canon master (replaces 6bf83e23, the old short quiff);
    # an identity reference only, so the eye-zoom pixel pins are gone (masters end on the dance, closeup: null)
    assert r["closeup"] == "1afe9ed7-3bfd-463c-9595-2af133c748ba" and r["bodies"] == ["biped"]
    assert (r["closeup_center"], r["blue_eye_xy"]) == (None, None)
    assert b["status"] == "paused"  # retired 2026-10-06 (C5: Franz is the one dachshund)
    for c in (b, r):
        assert c["status"] in ("designing", "paused", "live")  # Reginald went live on 2026-10-07 (owner: first posts)
        # owner decision 2026-10-05: Drop-in is the default for every video, so every account starts at 1.00
        assert {a["platform"]: a["dropin_share"] for a in c["accounts"]} == {"tiktok": 1.0, "instagram": 1.0}
        # an account the owner has created carries its real handle (and, once connected, its Postiz id); the rest stay null
        assert all(a["handle"] is None or isinstance(a["handle"], str) for a in c["accounts"])
        assert all(a["handle"] for a in c["accounts"] if a["postiz_integration_id"])  # an id without a handle would not seed
        assert (ROOT / c["avatar"]).parent.is_dir()


def test_the_shipped_refs_carry_the_character_sheets_the_owner_made():
    by = {r["slug"]: r["sheets"] for r in seed.load_refs(seed.DEFAULT_CHARACTERS_DIR)}
    assert by["biscuit"] == SHEETS
    assert by["reginald"] == {"biped": "44af3625-5f3e-47c4-bf62-f723cf8fbe24"}  # the canon turnaround, 2026-10-06


def test_the_shipped_refs_keep_the_real_live_accounts():
    """The live handles and Postiz ids are the owner's real values: a change to the shares or traits must not touch them."""
    by = {r["slug"]: {a["platform"]: a for a in r["accounts"]} for r in seed.load_refs(seed.DEFAULT_CHARACTERS_DIR)}
    # 2026-10-06: Instagram biscuit.moves was renamed franz.unimpressed and its Postiz connection moved to Franz
    assert by["franz"]["instagram"]["handle"] == "franz.unimpressed"
    assert by["franz"]["instagram"]["postiz_integration_id"] == "cmuv24qx600brql0yuylht0gj"
    assert by["biscuit"]["instagram"]["handle"] == "biscuit.moves" and by["biscuit"]["instagram"]["postiz_integration_id"] is None
    assert by["reginald"]["instagram"]["handle"] == "reginald.thebutler"
    assert by["reginald"]["instagram"]["postiz_integration_id"] == "cmuv2mx9s00kxql0y8k92piif"
    assert by["biscuit"]["tiktok"]["handle"] is None and by["reginald"]["tiktok"]["handle"] is None


def test_the_shipped_refs_carry_a_traits_card_that_fits_the_bible():
    loaded = {r["slug"]: r["traits"] for r in seed.load_refs(seed.DEFAULT_CHARACTERS_DIR)}
    assert sorted(loaded) == ["biscuit", "franz", "lenny", "reginald"]
    for slug, t in loaded.items():
        assert set(t) == set(seed.TRAIT_TEXT_KEYS) | set(seed.TRAIT_LIST_KEYS), slug
        for key in seed.TRAIT_LIST_KEYS:
            assert 3 <= len(t[key]) <= (12 if key == "props" else 6), (slug, key)  # short phrases, a handful each
    b, r = loaded["biscuit"], loaded["reginald"]
    assert "bouncy" in b["energy"] and "puppy" in b["energy"] and "ego" in b["comedy"]
    assert "calm" in r["energy"] and "deadpan" in r["comedy"] and "quiff" in r["comedy"]
    assert "never smiles" not in " ".join(r["never"]) and any("smil" in n for n in r["never"])  # the bible's rules are in the card
    assert any("quiff" in n for n in r["never"]) and any("belly" in n for n in b["never"])
    # the gadgets and the viral job each one does (owner 2026-10-05), exactly
    assert [(p["name"], p["job"]) for p in b["props"]] == BISCUIT_GADGETS
    assert [(p["name"], p["job"]) for p in r["props"]] == REGINALD_GADGETS
    assert all(len(p["name"]) <= 40 for p in b["props"] + r["props"])  # each name is a Make-it chip
    assert "afro house" in b["music"] and "orchestral" in r["music"]


def test_seeding_the_shipped_refs_puts_the_traits_into_the_database():
    store = MemoryStore()
    seed.seed_characters(store, seed.DEFAULT_CHARACTERS_DIR)
    assert all(c.setup["traits"]["props"] for c in store.characters())


def test_seeding_the_shipped_refs_creates_the_roster_and_exactly_the_accounts_that_have_a_handle():
    refs_ = seed.load_refs(seed.DEFAULT_CHARACTERS_DIR)
    with_handle = {(r["slug"], a["platform"]) for r in refs_ for a in r["accounts"] if a["handle"]}
    store = MemoryStore()
    report = seed.seed_characters(store, seed.DEFAULT_CHARACTERS_DIR)
    assert [c.slug for c in store.characters()] == ["biscuit", "franz", "lenny", "reginald"]
    assert {(a.character_slug, a.platform.value) for a in store.accounts()} == with_handle
    total = sum(len(r["accounts"]) for r in refs_)
    assert len(store.accounts()) + len(report.skipped) == total  # every account is either seeded or reported as not there yet


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


def test_cli_seed_status_hands_the_daily_run_each_characters_traits(cli_store, tmp_path):
    seed.seed_characters(cli_store, write_refs(tmp_path, refs(BISCUIT, traits=TRAITS), REGINALD))
    out = {c["slug"]: c for c in json.loads(run("status").stdout)}
    assert out["biscuit"]["traits"] == TRAITS  # fit is scored against this card
    assert out["reginald"]["traits"] is None


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


# ---- Drop a video: the public reference images and the like-for-like rule (plan 2026-10-06) -------------------------

CDN = "https://d8j0ntlcm91z4.cloudfront.net/user_x/"
URLS = {
    "master_biped": f"{CDN}m_b.png", "sheet_biped": f"{CDN}s_b.png",
    "master_quadruped": f"{CDN}m_q.png", "sheet_quadruped": f"{CDN}s_q.png", "closeup": f"{CDN}c.png",
}


def test_reference_images_pick_the_master_and_sheet_of_the_stars_body_then_the_closeup(tmp_path):
    loaded = {r["slug"]: r for r in seed.load_refs(write_refs(tmp_path, refs(BISCUIT, reference_urls=URLS), REGINALD))}
    b = loaded["biscuit"]
    assert seed.reference_images(b, "quadruped") == [URLS["master_quadruped"], URLS["sheet_quadruped"], URLS["closeup"]]
    assert seed.reference_images(b, Body.biped) == [URLS["master_biped"], URLS["sheet_biped"], URLS["closeup"]]
    with pytest.raises(ValueError, match="no reference_urls.master_biped"):
        seed.reference_images(loaded["reginald"], "biped")  # this test's Reginald has none
    with pytest.raises(ValueError, match="no quadruped body"):
        seed.reference_images(refs(REGINALD, reference_urls={"master_biped": URLS["master_biped"]}), "quadruped")


@pytest.mark.parametrize(
    ("urls", "message"),
    [
        ("https://x.example/a.png", "reference_urls must be an object"),
        ({"master_biped": "http://x.example/a.png"}, "must be an https URL"),
        ({"master_biped": "https://x.example/a b.png"}, "must be an https URL"),
        ({"master_biped": "https:///a.png"}, "must be an https URL"),
        ({"master_quadruped": f"{CDN}q.png"}, "reference_urls.master_quadruped: not one of"),  # Reginald has no quadruped body
        ({"avatar": f"{CDN}a.png"}, "reference_urls.avatar: not one of"),
    ],
)
def test_a_malformed_reference_url_is_refused_before_anything_is_written(tmp_path, urls, message):
    store = MemoryStore()
    with pytest.raises(ValueError, match=message):
        seed.seed_characters(store, write_refs(tmp_path, BISCUIT, refs(REGINALD, reference_urls=urls)))
    assert store.characters() == []


@pytest.mark.parametrize(
    "swap",
    [
        "butler",
        {"noun": "butler"},
        {"noun": "butler", "stars": []},
        {"noun": "butler", "stars": ["human"]},
        {"noun": "", "stars": ["person"]},
        {"noun": "butler", "stars": ["person", "person"]},
        {"noun": "butler", "stars": ["person"], "extra": 1},
    ],
)
def test_a_malformed_swap_rule_is_refused(tmp_path, swap):
    with pytest.raises(ValueError, match="swap must be"):
        seed.load_refs(write_refs(tmp_path, BISCUIT, refs(REGINALD, swap=swap)))


def test_the_shipped_refs_carry_the_public_reference_images_and_the_like_for_like_rule():
    """The cloud Object swap sends these as image_urls: Reginald replaces a person, Biscuit a dog or small animal."""
    loaded = {r["slug"]: r for r in seed.load_refs(seed.DEFAULT_CHARACTERS_DIR)}
    b, r = loaded["biscuit"], loaded["reginald"]
    assert set(b["reference_urls"]) == set(URLS)
    assert set(r["reference_urls"]) == {"master_biped", "sheet_biped", "closeup"}
    for ref in (b, r):
        for body in ref["bodies"]:
            images = seed.reference_images(ref, body)
            assert len(images) == 3 and all(seed.is_https_url(u) for u in images)
            # the image is the one of the job id refs.json names: the master, the sheet and the close-up of that body
            assert ref["masters"][body] in images[0] and ref["sheets"][body] in images[1] and ref["closeup"] in images[2]
    assert b["swap"] == {"noun": "dog", "stars": ["dog", "animal"]}
    assert r["swap"] == {"noun": "butler", "stars": ["person"]}

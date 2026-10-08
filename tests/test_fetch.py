"""``studio.fetch``: the clip of an APPROVED pick is fetched once (yt-dlp, public, no login, no cookies), catalogued as an
``owner_inbox`` source in our Storage, and deleted again once the master is approved or posted (owner decisions 2026-10-05).

yt-dlp is never run here: the runner is a fake that writes a small synthetic video where the command says to, so the
command line, the guards, the bookkeeping and the cleanup are all tested without a network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio import fetch, sources
from studio.cli import app
from studio.fetch import FETCH_MAX_SECONDS, fetch_pick_clip, purge_clip, purge_pending, ytdlp_command
from studio.models import Body, Character, Clip, Favorite, Mode, SourceKind
from studio.storage import LocalStorage, StorageError
from studio.store import MemoryStore

TIKTOK = "https://www.tiktok.com/@tillandsialover/video/7688386199270001953"


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


@pytest.fixture
def clip_file(synth_video) -> Path:
    return synth_video(w=320, h=568, dur=5, audio=False)


class FakeYtDlp:
    """A runner that records its command and writes ``clip`` to the ``-o`` template (``%(ext)s`` -> mp4), or fails."""

    def __init__(self, clip: Path | None, *, returncode: int = 0, stderr: str = "", write: bool = True, raises: Exception | None = None):
        self.clip, self.returncode, self.stderr, self.write, self.raises = clip, returncode, stderr, write, raises
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if self.raises:
            raise self.raises
        if self.write and self.clip is not None and self.returncode == 0:
            template = cmd[cmd.index("-o") + 1]
            target = Path(template.replace("%(ext)s", "mp4").replace("%%", "%"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.clip, target)
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


def approved_pick(store, *, url=TIKTOK, status="approved", slug="biscuit", proposal=None, platform="tiktok", creator="@tillandsialover"):
    return store.add_favorite(Favorite(
        url=url, platform=platform, creator_handle=creator, status=status, character_slug=slug,
        proposal={"mode": "dropin", "hook": "he hits every beat", **(proposal or {})},
    ))


@pytest.fixture
def world(tmp_path):
    return make_store(), LocalStorage(tmp_path / "store"), tmp_path / "inbox" / "fetched"


# ---- the command line ------------------------------------------------------------------------------------------------


def test_the_yt_dlp_command_is_explicit_public_and_ends_with_the_one_url():
    cmd = ytdlp_command(TIKTOK, "/x/inbox/fetched/abc.%(ext)s")
    assert cmd[0] == "yt-dlp" and cmd[-2:] == ["--", TIKTOK]  # `--`: a URL can never be read as an option
    for flag in ("--ignore-config", "--no-cookies", "--no-cookies-from-browser", "--no-playlist"):
        assert flag in cmd, flag
    assert cmd[cmd.index("-o") + 1] == "/x/inbox/fetched/abc.%(ext)s"
    for forbidden in ("--cookies", "--cookies-from-browser", "--username", "-u", "--password", "-p", "--netrc", "--video-password", "--proxy"):
        assert forbidden not in cmd, forbidden  # no login, no cookies, nothing of the owner's
    assert cmd[cmd.index("--match-filters") + 1] == f"duration<={int(FETCH_MAX_SECONDS)}"
    assert sum(1 for part in cmd if part.startswith("http")) == 1  # one clip at a time


# ---- fetching ---------------------------------------------------------------------------------------------------------


def test_fetching_an_approved_pick_downloads_catalogues_and_links_it(world, clip_file):
    store, storage, out_dir = world
    pick = approved_pick(store)
    runner = FakeYtDlp(clip_file)

    result = fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir, body="quadruped")

    assert len(runner.calls) == 1 and runner.calls[0][-1] == TIKTOK
    local = out_dir / f"{pick.id}.mp4"
    assert local.is_file() and result["file"] == str(local) and result["fetched"] is True and result["already"] is False
    source = store.list_sources()[0]
    assert (source.kind, source.body, source.bodies) == (SourceKind.owner_inbox, Body.quadruped, 1)
    assert source.storage_path == source.url and source.storage_path.startswith("owner_inbox/") and source.storage_path.endswith(".mp4")
    assert source.credit_handle == "@tillandsialover" and source.duration_s == pytest.approx(5.0, abs=0.1)
    assert (source.has_watermark, source.has_overlay, source.has_minors) == (None, None, None)  # looked at next, never assumed clean
    assert storage.download("sources", source.storage_path, out_dir / "back.mp4").read_bytes() == local.read_bytes()
    linked = store.get_favorite(pick.id)
    assert linked.source_id == source.id and linked.status == "approved"
    marker = linked.proposal["fetched"]
    assert marker["source_id"] == source.id and marker["storage_path"] == source.storage_path and "at" in marker and "purged_at" not in marker
    assert linked.proposal["hook"] == "he hits every beat"  # the rest of the proposal is untouched
    assert result["source_id"] == source.id and result["pick_id"] == pick.id and result["duration_s"] == pytest.approx(5.0, abs=0.1)


def test_a_percent_sign_in_the_folder_is_not_a_template_field(tmp_path, clip_file):
    store, storage = make_store(), LocalStorage(tmp_path / "store")
    odd = tmp_path / "100%done" / "fetched"
    pick = approved_pick(store)
    runner = FakeYtDlp(clip_file)
    fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=odd)
    assert runner.calls[0][runner.calls[0].index("-o") + 1] == f"{tmp_path}/100%%done/fetched/{pick.id}.%(ext)s"
    assert (odd / f"{pick.id}.mp4").is_file()


def test_a_bad_body_is_refused_before_anything_is_downloaded(world, clip_file):
    store, storage, out_dir = world
    pick = approved_pick(store)
    runner = FakeYtDlp(clip_file)
    with pytest.raises(ValueError):
        fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir, body="octopus")
    with pytest.raises(ValueError, match="bodies"):
        fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir, bodies=0)
    assert runner.calls == []


def test_an_analysed_pick_is_fetched_too(world, clip_file):
    store, storage, out_dir = world
    pick = approved_pick(store, status="analysed")
    assert fetch_pick_clip(store, storage, pick.id, runner=FakeYtDlp(clip_file), out_dir=out_dir)["fetched"] is True
    assert store.get_favorite(pick.id).status == "analysed"


def test_a_youtube_and_an_instagram_pick_are_fetchable_with_their_canonical_url(world, clip_file):
    store, storage, out_dir = world
    yt = approved_pick(store, url="https://www.youtube.com/watch?v=9bZkp7q19f0&t=42s", platform="youtube", slug="reginald")
    ig = approved_pick(store, url="https://www.instagram.com/reel/Dde-rPWCOC6/", platform="instagram", slug="reginald")
    for pick, expected in ((yt, "https://www.youtube.com/watch?v=9bZkp7q19f0"), (ig, "https://www.instagram.com/reel/Dde-rPWCOC6/")):
        runner = FakeYtDlp(clip_file)
        fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir)
        assert runner.calls[0][-1] == expected


@pytest.mark.parametrize("status", ["new", "skipped", "queued", "made"])
def test_only_an_approved_pick_is_fetched(world, clip_file, status):
    store, storage, out_dir = world
    pick = approved_pick(store, status=status)
    runner = FakeYtDlp(clip_file)
    with pytest.raises(ValueError, match=f"is {status}"):
        fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir)
    assert runner.calls == [] and store.list_sources() == [] and not out_dir.exists()  # nothing was downloaded, nothing stored


def test_a_gallery_pick_an_unknown_pick_and_a_non_platform_url_are_refused(world, clip_file):
    store, storage, out_dir = world
    runner = FakeYtDlp(clip_file)
    gallery = approved_pick(store, url="higgsfield-preset:hf-1", platform="higgsfield", creator=None, proposal={"preset_id": "hf-1"})
    with pytest.raises(ValueError, match="gallery"):
        fetch_pick_clip(store, storage, gallery.id, runner=runner, out_dir=out_dir)
    odd = approved_pick(store, url="https://example.com/clip.mp4", platform="tiktok")
    with pytest.raises(ValueError, match="supported"):
        fetch_pick_clip(store, storage, odd.id, runner=runner, out_dir=out_dir)
    with pytest.raises(KeyError):
        fetch_pick_clip(store, storage, "00000000-0000-4000-8000-000000000000", runner=runner, out_dir=out_dir)
    assert runner.calls == []


def test_a_pick_the_owner_wants_recreated_or_gave_a_clip_for_needs_no_fetch(world, clip_file):
    store, storage, out_dir = world
    runner = FakeYtDlp(clip_file)
    recreate = approved_pick(store, proposal={"owner_mode": "recreate"})
    with pytest.raises(ValueError, match="Recreate"):
        fetch_pick_clip(store, storage, recreate.id, runner=runner, out_dir=out_dir)
    attached = approved_pick(store, url="https://www.tiktok.com/@a/video/1", proposal={"owner_clip_path": "owner/x/1.mp4"})
    with pytest.raises(ValueError, match="attached"):
        fetch_pick_clip(store, storage, attached.id, runner=runner, out_dir=out_dir)
    assert runner.calls == []


def test_fetching_twice_downloads_once(world, clip_file):
    store, storage, out_dir = world
    pick = approved_pick(store)
    runner = FakeYtDlp(clip_file)
    first = fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir)
    again = fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir)
    assert len(runner.calls) == 1 and again["already"] is True and again["source_id"] == first["source_id"]
    assert len(store.list_sources()) == 1


def test_the_other_characters_pick_of_the_same_video_shares_the_one_download(world, clip_file):
    """"Both" files a sibling pick with the same URL: one video is fetched once and one source serves both."""
    store, storage, out_dir = world
    a = approved_pick(store, slug="biscuit")
    b = approved_pick(store, slug="reginald")
    runner = FakeYtDlp(clip_file)
    first = fetch_pick_clip(store, storage, a.id, runner=runner, out_dir=out_dir)
    second = fetch_pick_clip(store, storage, b.id, runner=runner, out_dir=out_dir)
    assert len(runner.calls) == 1 and second["source_id"] == first["source_id"] and second["already"] is True
    assert store.get_favorite(b.id).source_id == first["source_id"] and len(store.list_sources()) == 1
    assert "fetched" in store.get_favorite(b.id).proposal


# ---- when yt-dlp cannot do it: the pick becomes a Recreate ----------------------------------------------------------------


def assert_recreate_fallback(store, storage, out_dir, pick, result, reason_part):
    assert result["fetched"] is False and result["pick_marked"] == "recreate" and reason_part in result["reason"]
    after = store.get_favorite(pick.id)
    assert after.proposal["mode"] == "recreate" and reason_part in after.proposal["fetch_failed"]["reason"]
    assert after.status == pick.status and after.source_id is None and "fetched" not in after.proposal
    assert store.list_sources() == []
    assert not list(out_dir.glob("*")) if out_dir.exists() else True  # no half-downloaded file is left behind
    assert not (Path(storage.root) / "sources").exists() or not list((Path(storage.root) / "sources").rglob("*.mp4"))


def test_a_failed_download_marks_the_pick_recreate_and_keeps_its_status(world):
    store, storage, out_dir = world
    pick = approved_pick(store, proposal={"owner_mode": "dropin"})
    runner = FakeYtDlp(None, returncode=1, stderr="ERROR: [TikTok] 768: Unable to extract webpage video data\nlogin required")
    result = fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir)
    assert_recreate_fallback(store, storage, out_dir, pick, result, "login required")
    assert store.get_favorite(pick.id).proposal["owner_mode"] == "dropin"  # what the owner chose is kept as chosen


def test_without_the_fallback_a_failed_download_raises_and_leaves_the_pick_alone(world):
    """A dropped link (studio drop process) waits and is tried again by the Mac: it is never turned into a Recreate."""
    store, storage, out_dir = world
    pick = approved_pick(store)
    runner = FakeYtDlp(None, returncode=1, stderr="ERROR: login required")
    with pytest.raises(fetch.FetchFailed, match="login required"):
        fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir, fall_back=False)
    after = store.get_favorite(pick.id)
    assert after.proposal == pick.proposal and after.source_id is None and store.list_sources() == []
    assert not list(out_dir.glob("*")) if out_dir.exists() else True


def test_yt_dlp_missing_a_timeout_or_no_file_are_failures_too(world, clip_file):
    store, storage, out_dir = world
    for i, runner in enumerate((
        FakeYtDlp(None, raises=FileNotFoundError("yt-dlp")),
        FakeYtDlp(None, raises=subprocess.TimeoutExpired("yt-dlp", 300)),
        FakeYtDlp(clip_file, write=False),  # exit 0 and no file: the duration filter skipped it, or it was a playlist
    )):
        pick = approved_pick(store, url=f"https://www.tiktok.com/@a/video/{i + 1}")
        result = fetch_pick_clip(store, storage, pick.id, runner=runner, out_dir=out_dir)
        assert result["fetched"] is False and result["pick_marked"] == "recreate", i
        assert store.get_favorite(pick.id).proposal["mode"] == "recreate"
    assert store.list_sources() == []


def test_a_file_that_is_not_a_video_or_is_too_long_is_discarded(world, clip_file, tmp_path, monkeypatch):
    store, storage, out_dir = world
    notvideo = tmp_path / "junk.mp4"
    notvideo.write_text("<html>blocked</html>")
    pick = approved_pick(store)
    result = fetch_pick_clip(store, storage, pick.id, runner=FakeYtDlp(notvideo), out_dir=out_dir)
    assert result["fetched"] is False and not (out_dir / f"{pick.id}.mp4").exists()
    monkeypatch.setattr(fetch, "FETCH_MAX_SECONDS", 3.0)  # the 5 s clip is now "too long"
    other = approved_pick(store, url="https://www.tiktok.com/@a/video/2")
    result = fetch_pick_clip(store, storage, other.id, runner=FakeYtDlp(clip_file), out_dir=out_dir)
    assert result["fetched"] is False and "long" in result["reason"] and not (out_dir / f"{other.id}.mp4").exists()
    assert store.list_sources() == []


def test_a_failed_upload_is_a_storage_error_not_a_yt_dlp_failure_and_keeps_nothing(world, clip_file):
    """Our own Storage refusing the file is infrastructure: it is reported (exit 2), the pick is not marked Recreate for it."""
    store, storage, out_dir = world

    class Refusing(LocalStorage):
        def upload(self, bucket, path, file):
            raise StorageError("storage POST sources/x failed: HTTP 413: too big", 413)

    pick = approved_pick(store)
    with pytest.raises(StorageError, match="413"):
        fetch_pick_clip(store, Refusing(storage.root), pick.id, runner=FakeYtDlp(clip_file), out_dir=out_dir)
    assert store.list_sources() == [] and not (out_dir / f"{pick.id}.mp4").exists()
    after = store.get_favorite(pick.id)
    assert after.proposal["mode"] == "dropin" and "fetch_failed" not in after.proposal and after.source_id is None


# ---- the CLI ----------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch, tmp_path, world, clip_file):
    store, storage, out_dir = world
    monkeypatch.setattr(sources, "open_store", lambda: store)
    monkeypatch.setattr(fetch, "open_store", lambda: store)
    monkeypatch.setattr(fetch, "open_storage", lambda: storage)
    monkeypatch.setattr(fetch, "FETCHED_DIR", out_dir)
    runner = FakeYtDlp(clip_file)
    monkeypatch.setattr(fetch, "_run_ytdlp", runner)
    return store, storage, out_dir, runner


def run(*args: str):
    return CliRunner().invoke(app, ["source", *args])


def test_cli_fetch_prints_the_source_and_exits_0(cli):
    store, storage, out_dir, runner = cli
    pick = approved_pick(store)
    r = run("fetch", "--pick", pick.id, "--body", "quadruped")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["fetched"] is True and out["pick_id"] == pick.id and out["body"] == "quadruped" and out["dropin_eligible"] is False
    assert out["file"] == str(out_dir / f"{pick.id}.mp4") and len(runner.calls) == 1


def test_cli_fetch_refuses_bulk_unapproved_and_unknown_picks_with_exit_2(cli):
    store, storage, out_dir, runner = cli
    a, b = approved_pick(store), approved_pick(store, url="https://www.tiktok.com/@b/video/2")
    assert run("fetch", "--pick", a.id, "--pick", b.id).exit_code == 2  # one clip at a time
    assert run("fetch").exit_code == 2
    new = approved_pick(store, url="https://www.tiktok.com/@c/video/3", status="new")
    r = run("fetch", "--pick", new.id)
    assert r.exit_code == 2 and "approved" in r.output
    assert run("fetch", "--pick", "00000000-0000-4000-8000-000000000000").exit_code == 2
    assert runner.calls == []


def test_cli_fetch_exits_1_with_the_fallback_when_yt_dlp_fails(cli, monkeypatch):
    store, storage, out_dir, runner = cli
    monkeypatch.setattr(fetch, "_run_ytdlp", FakeYtDlp(None, returncode=1, stderr="ERROR: private video"))
    pick = approved_pick(store)
    r = run("fetch", "--pick", pick.id)
    assert r.exit_code == 1, r.output
    out = json.loads(r.stdout)
    assert out["fetched"] is False and out["pick_marked"] == "recreate" and "private video" in out["reason"]
    assert store.get_favorite(pick.id).proposal["mode"] == "recreate"


# ---- purge: once the master is approved or posted, the fetched clip goes ----------------------------------------------------


def fetched_and_made(store, storage, out_dir, clip_file, *, state="posted", slug="biscuit", url=TIKTOK):
    """A pick that was fetched, trimmed into a child source and made into a clip in ``state``."""
    pick = approved_pick(store, url=url, slug=slug)
    fetch_pick_clip(store, storage, pick.id, runner=FakeYtDlp(clip_file), out_dir=out_dir)
    parent = store.list_sources()[-1]
    child = sources.trim_source(store, storage, parent.id, 0.0, 4.0, file=out_dir / f"{pick.id}.mp4")
    clip = store.add_clip(Clip(character_slug=slug, mode=Mode.dropin, state=state, source_id=child.id))
    store.update_favorite(pick.id, status="made", clip_id=clip.id)
    return store.get_favorite(pick.id), parent, child, clip


def objects(storage) -> set[str]:
    return {str(p.relative_to(Path(storage.root) / "sources")) for p in (Path(storage.root) / "sources").rglob("*.mp4")}


def test_purge_removes_the_fetched_file_and_both_storage_objects(world, clip_file):
    store, storage, out_dir = world
    pick, parent, child, clip = fetched_and_made(store, storage, out_dir, clip_file)
    assert (out_dir / f"{pick.id}.mp4").is_file() and len(objects(storage)) == 2

    result = purge_clip(store, storage, clip.id, fetched_dir=out_dir, renders_dir=out_dir.parent / "renders")

    assert not (out_dir / f"{pick.id}.mp4").exists() and objects(storage) == set()
    assert sorted(result["storage_deleted"]) == sorted([parent.storage_path, child.storage_path])
    assert result["files_deleted"] == [str(out_dir / f"{pick.id}.mp4")] and result["already"] is False
    assert store.list_sources(id=parent.id)[0].storage_path is None and store.list_sources(id=child.id)[0].storage_path is None
    assert "purged_at" in store.get_favorite(pick.id).proposal["fetched"]
    assert store.get_favorite(pick.id).status == "made"  # the pick and the clip themselves are untouched
    assert store.get_clip(clip.id).state.value == "posted"


def test_purge_is_idempotent(world, clip_file):
    store, storage, out_dir = world
    _, _, _, clip = fetched_and_made(store, storage, out_dir, clip_file)
    purge_clip(store, storage, clip.id, fetched_dir=out_dir)
    again = purge_clip(store, storage, clip.id, fetched_dir=out_dir)
    assert again["already"] is True and again["storage_deleted"] == [] and again["files_deleted"] == []


def test_purge_also_removes_the_contact_sheets_of_the_clips(world, clip_file, tmp_path):
    store, storage, out_dir = world
    _, parent, child, clip = fetched_and_made(store, storage, out_dir, clip_file)
    renders = tmp_path / "renders"
    pick_id = store.list_favorites(clip_id=clip.id)[0].id
    for sid in (parent.id, child.id, pick_id):  # the two sources, and the downloaded file analysed directly (named by the pick)
        (renders / sid).mkdir(parents=True)
        (renders / sid / "analysis.png").write_bytes(b"png")
    (renders / "keep").mkdir()
    (renders / "keep" / "analysis.png").write_bytes(b"png")
    purge_clip(store, storage, clip.id, fetched_dir=out_dir, renders_dir=renders)
    assert not (renders / parent.id).exists() and not (renders / child.id).exists() and not (renders / pick_id).exists()
    assert (renders / "keep" / "analysis.png").is_file()  # only the sheets of this clip's sources


@pytest.mark.parametrize("state", ["approved", "scheduled", "posted", "dropped"])
def test_purge_runs_once_the_master_is_approved_or_posted_or_the_clip_dropped(world, clip_file, state):
    store, storage, out_dir = world
    _, _, _, clip = fetched_and_made(store, storage, out_dir, clip_file, state=state)
    assert purge_clip(store, storage, clip.id, fetched_dir=out_dir)["already"] is False


@pytest.mark.parametrize("state", ["planned", "generating", "generated", "qa_failed", "qa_passed", "mastered", "awaiting_approval", "rejected"])
def test_purge_waits_while_the_clip_is_still_being_made_or_judged(world, clip_file, state):
    store, storage, out_dir = world
    pick, _, _, clip = fetched_and_made(store, storage, out_dir, clip_file, state=state)
    with pytest.raises(ValueError, match=state):
        purge_clip(store, storage, clip.id, fetched_dir=out_dir)
    assert (out_dir / f"{pick.id}.mp4").is_file() and len(objects(storage)) == 2  # nothing was deleted


def test_purge_never_touches_a_clip_that_was_not_fetched(world, clip_file, tmp_path):
    """The owner's own attached clip (owner/<pick>/<file>) is theirs: a clip made from it has nothing to purge."""
    store, storage, out_dir = world
    pick = approved_pick(store, proposal={"owner_clip_path": "owner/p/1.mp4"})
    storage.upload("sources", "owner/p/1.mp4", clip_file)
    source = sources.add_source(store, "owner_inbox", "owner/p/1.mp4", "biped", 1, 5.0, storage_path="owner/p/1.mp4")
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.dropin, state="posted", source_id=source.id))
    store.update_favorite(pick.id, status="made", clip_id=clip.id, source_id=source.id)
    result = purge_clip(store, storage, clip.id, fetched_dir=out_dir)
    assert result["storage_deleted"] == [] and result["files_deleted"] == []
    assert "owner/p/1.mp4" in objects(storage) and store.list_sources(id=source.id)[0].storage_path == "owner/p/1.mp4"


def test_purge_keeps_the_shared_download_until_the_other_charactes_clip_is_done_too(world, clip_file):
    store, storage, out_dir = world
    a, parent, child_a, clip_a = fetched_and_made(store, storage, out_dir, clip_file, slug="biscuit")
    b = approved_pick(store, slug="reginald")
    fetch_pick_clip(store, storage, b.id, runner=FakeYtDlp(clip_file), out_dir=out_dir)  # shares the parent source
    clip_b = store.add_clip(Clip(character_slug="reginald", mode=Mode.dropin, state="mastered", source_id=parent.id))
    store.update_favorite(b.id, status="queued", clip_id=clip_b.id)

    first = purge_clip(store, storage, clip_a.id, fetched_dir=out_dir)
    assert parent.storage_path in objects(storage) and child_a.storage_path not in objects(storage)  # the shared one stays
    assert first["storage_kept"] == [parent.storage_path] and (out_dir / f"{a.id}.mp4").exists() is False

    store.update_clip(clip_b.id, state="posted")
    second = purge_clip(store, storage, clip_b.id, fetched_dir=out_dir)
    assert objects(storage) == set() and parent.storage_path in second["storage_deleted"]


def test_a_dropped_clip_whose_pick_was_returned_keeps_the_download_for_the_next_attempt(world, clip_file):
    store, storage, out_dir = world
    pick, parent, child, clip = fetched_and_made(store, storage, out_dir, clip_file, state="dropped")
    store.update_favorite(pick.id, status="approved")  # the daily run returned the pick: it will be made again
    result = purge_clip(store, storage, clip.id, fetched_dir=out_dir)
    assert result["already"] is True and result["kept_for_retry"] == [pick.id] and result["storage_deleted"] == []
    assert (out_dir / f"{pick.id}.mp4").is_file() and len(objects(storage)) == 2
    assert "purged_at" not in store.get_favorite(pick.id).proposal["fetched"]
    # and fetching it again does not download again
    assert fetch_pick_clip(store, storage, pick.id, runner=FakeYtDlp(None, returncode=1), out_dir=out_dir)["already"] is True


def test_purge_pending_sweeps_what_is_done_and_leaves_what_is_not(world, clip_file):
    store, storage, out_dir = world
    done, parent_done, child_done, clip_done = fetched_and_made(store, storage, out_dir, clip_file, url=TIKTOK)
    busy, parent_busy, _, clip_busy = fetched_and_made(
        store, storage, out_dir, clip_file, state="mastered", slug="reginald", url="https://www.tiktok.com/@b/video/2"
    )
    skipped = approved_pick(store, url="https://www.tiktok.com/@c/video/3")
    fetch_pick_clip(store, storage, skipped.id, runner=FakeYtDlp(clip_file), out_dir=out_dir)
    store.update_favorite(skipped.id, status="skipped")
    plain = approved_pick(store, url="https://www.tiktok.com/@d/video/4")  # never fetched: nothing to do for it

    result = purge_pending(store, storage, fetched_dir=out_dir)

    assert [r["clip_id"] for r in result["clips"]] == [clip_done.id] and [r["pick_id"] for r in result["skipped_picks"]] == [skipped.id]
    assert result["already"] is False
    gone = {parent_done.storage_path, child_done.storage_path, store.get_favorite(skipped.id).proposal["fetched"]["storage_path"]}
    assert gone.isdisjoint(objects(storage)) and parent_busy.storage_path in objects(storage)  # the clip still being judged keeps its source
    assert (out_dir / f"{busy.id}.mp4").is_file() and not (out_dir / f"{done.id}.mp4").exists() and not (out_dir / f"{skipped.id}.mp4").exists()
    assert store.get_favorite(plain.id).source_id is None
    again = purge_pending(store, storage, fetched_dir=out_dir)
    assert again == {"clips": [], "skipped_picks": [], "already": True}  # idempotent
    store.update_clip(clip_busy.id, state="approved")
    assert [r["clip_id"] for r in purge_pending(store, storage, fetched_dir=out_dir)["clips"]] == [clip_busy.id]  # once it is approved


def test_purge_reports_a_clip_that_does_not_exist(world):
    store, storage, out_dir = world
    with pytest.raises(KeyError):
        purge_clip(store, storage, "00000000-0000-4000-8000-000000000000", fetched_dir=out_dir)


def test_cli_purge(cli, clip_file):
    store, storage, out_dir, runner = cli
    pick, parent, child, clip = fetched_and_made(store, storage, out_dir, clip_file)
    r = run("purge", "--clip", clip.id)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["clip_id"] == clip.id and len(out["storage_deleted"]) == 2 and objects(storage) == set()
    assert json.loads(run("purge", "--clip", clip.id).stdout)["already"] is True  # idempotent
    assert run("purge", "--clip", "00000000-0000-4000-8000-000000000000").exit_code == 2
    mastered = store.add_clip(Clip(character_slug="biscuit", mode=Mode.dropin, state="mastered"))
    refused = run("purge", "--clip", mastered.id)
    assert refused.exit_code == 2 and "mastered" in refused.output


def test_cli_purge_pending_and_the_one_of_rule(cli, clip_file):
    store, storage, out_dir, runner = cli
    pick, parent, child, clip = fetched_and_made(store, storage, out_dir, clip_file)
    r = run("purge", "--pending")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert [c["clip_id"] for c in out["clips"]] == [clip.id] and objects(storage) == set()
    assert json.loads(run("purge", "--pending").stdout)["already"] is True
    assert run("purge").exit_code == 2  # neither
    assert run("purge", "--pending", "--clip", clip.id).exit_code == 2  # both


# ---- a version of a drop (terminal v3): one clip, up to three characters, one download -------------------------------------------


def test_source_kept_for_unmade_version(world, clip_file):
    """A version shares its root's full clip (no second download): the clip stays while the version is still to be made, and
    goes once the version is done too (the version carries the root's fetched marker, as the "Both" pick of a video does)."""
    from studio import drop

    store, storage, out_dir = world
    store.add_character(Character(slug="lenny", name="Lenny Gold", status="live", bodies=[Body.biped]))
    star = {"kind": "person", "body": "biped", "description": "the man in the grey suit", "x_center": 0.5, "full_body": True, "child": False}
    root = approved_pick(store, slug="reginald", proposal={"drop": {"state": "checking", "kind": "link", "character_by": "owner"}})
    fetch_pick_clip(store, storage, root.id, runner=FakeYtDlp(clip_file), out_dir=out_dir)
    parent = store.list_sources()[-1]
    child = sources.trim_source(store, storage, parent.id, 0.0, 4.0, file=out_dir / f"{root.id}.mp4")
    root_clip = store.add_clip(Clip(character_slug="reginald", mode=Mode.dropin, state="posted", source_id=child.id))
    root = store.get_favorite(root.id)
    made = {**root.proposal["drop"], "state": "made", "star": star, "source_id": parent.id}
    store.update_favorite(root.id, status="made", clip_id=root_clip.id, proposal={**root.proposal, "drop": made})

    version = drop.copy_drop(store, root.id, "lenny")
    assert version.source_id == parent.id and version.proposal["fetched"]["source_id"] == parent.id
    assert fetch._still_needed(store, parent.id, store.get_favorite(root.id), root_clip.id) is True
    first = purge_clip(store, storage, root_clip.id, fetched_dir=out_dir)
    assert first["storage_kept"] == [parent.storage_path] and parent.storage_path in objects(storage)

    v_child = sources.trim_source(store, storage, parent.id, 0.0, 4.0)
    v_clip = store.add_clip(Clip(character_slug="lenny", mode=Mode.dropin, state="posted", source_id=v_child.id))
    store.update_favorite(version.id, status="made", clip_id=v_clip.id)
    assert fetch._still_needed(store, parent.id, store.get_favorite(version.id), v_clip.id) is False
    second = purge_clip(store, storage, v_clip.id, fetched_dir=out_dir)
    assert parent.storage_path in second["storage_deleted"] and objects(storage) == set()

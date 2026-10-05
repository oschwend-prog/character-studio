import json
from pathlib import Path

import httpx
import pytest
import typer

from studio.cli_support import EXIT_USAGE, open_storage
from studio.storage import LocalStorage, Storage, StorageError, SupabaseStorage

BASE = "https://proj.supabase.co"
KEY = "sb-service-key-DO-NOT-LEAK"


def video(tmp_path: Path, data: bytes = b"\x00\x01video-bytes\xff" * 1000, name: str = "clip.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


class Recorder:
    """An httpx ``MockTransport`` that records every request and answers from ``handler``."""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []
        self.handler = handler or (lambda request: httpx.Response(200, json={"Key": "ok"}))
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(request.read())
        return self.handler(request)


def supabase(rec: Recorder) -> SupabaseStorage:
    return SupabaseStorage(BASE, KEY, transport=rec.transport)


# ---- LocalStorage --------------------------------------------------------------------------


def test_local_roundtrip(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    src = video(tmp_path)
    assert storage.upload("sources", "owner_inbox/a.mp4", src) == "owner_inbox/a.mp4"
    got = storage.download("sources", "owner_inbox/a.mp4", tmp_path / "out" / "deep" / "a.mp4")
    assert got == tmp_path / "out" / "deep" / "a.mp4"
    assert got.read_bytes() == src.read_bytes()
    assert storage.signed_url("sources", "owner_inbox/a.mp4").startswith("file://")


def test_local_is_a_storage_and_supabase_too():
    assert isinstance(LocalStorage("/nowhere"), Storage)
    assert isinstance(SupabaseStorage(BASE, KEY), Storage)


def test_local_upload_overwrites_like_upsert(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    storage.upload("clips", "m.mp4", video(tmp_path, b"first"))
    storage.upload("clips", "m.mp4", video(tmp_path, b"second"))
    assert storage.download("clips", "m.mp4", tmp_path / "d.mp4").read_bytes() == b"second"


def test_local_buckets_are_separate(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    storage.upload("sources", "x.mp4", video(tmp_path, b"s"))
    with pytest.raises(StorageError) as exc:
        storage.download("clips", "x.mp4", tmp_path / "d.mp4")
    assert exc.value.status == 404
    assert not (tmp_path / "d.mp4").exists()


def test_local_missing_object_is_a_storage_error(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    with pytest.raises(StorageError, match="clips/nope.mp4"):
        storage.download("clips", "nope.mp4", tmp_path / "d.mp4")
    with pytest.raises(StorageError, match="clips/nope.mp4"):
        storage.signed_url("clips", "nope.mp4")


@pytest.mark.parametrize(
    "bucket, path",
    [
        ("sources", "../escape.mp4"),
        ("sources", "a/../../escape.mp4"),
        ("sources", "/abs.mp4"),
        ("sources", ""),
        ("sources", "a//b.mp4"),
        ("", "a.mp4"),
        ("so/urces", "a.mp4"),
        ("..", "a.mp4"),
    ],
)
def test_bad_bucket_or_path_is_rejected_by_both_backends(tmp_path, bucket, path):
    src = video(tmp_path)
    rec = Recorder()
    for storage in (LocalStorage(tmp_path / "store"), supabase(rec)):
        with pytest.raises(ValueError):
            storage.upload(bucket, path, src)
        with pytest.raises(ValueError):
            storage.download(bucket, path, tmp_path / "d.mp4")
        with pytest.raises(ValueError):
            storage.signed_url(bucket, path)
        with pytest.raises(ValueError):
            storage.delete(bucket, path)
    assert rec.requests == []  # nothing left the machine
    assert not (tmp_path / "escape.mp4").exists()


def test_signed_url_needs_a_positive_expiry(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    storage.upload("clips", "m.mp4", video(tmp_path))
    for bad in (0, -5):
        with pytest.raises(ValueError, match="expires_s"):
            storage.signed_url("clips", "m.mp4", bad)
        with pytest.raises(ValueError, match="expires_s"):
            supabase(Recorder()).signed_url("clips", "m.mp4", bad)


# ---- SupabaseStorage: request shape ----------------------------------------------------------


def test_supabase_requests_shape(tmp_path):
    src = video(tmp_path)
    data = src.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=data)
        if request.url.path.startswith("/storage/v1/object/sign/"):
            return httpx.Response(200, json={"signedURL": "/object/sign/clips/m.mp4?token=T0K3N"})
        return httpx.Response(200, json={"Key": "sources/owner_inbox/a.mp4"})

    rec = Recorder(handler)
    storage = supabase(rec)

    assert storage.upload("sources", "owner_inbox/a.mp4", src) == "owner_inbox/a.mp4"
    up = rec.requests[0]
    assert (up.method, up.url.path) == ("POST", "/storage/v1/object/sources/owner_inbox/a.mp4")
    assert up.headers["authorization"] == f"Bearer {KEY}"
    assert up.headers["apikey"] == KEY
    assert up.headers["x-upsert"] == "true"
    assert up.headers["content-type"] == "video/mp4"
    assert up.headers["content-length"] == str(len(data))
    assert "transfer-encoding" not in up.headers
    assert rec.bodies[0] == data

    out = storage.download("sources", "owner_inbox/a.mp4", tmp_path / "back.mp4")
    dl = rec.requests[1]
    assert (dl.method, dl.url.path) == ("GET", "/storage/v1/object/sources/owner_inbox/a.mp4")
    assert dl.headers["authorization"] == f"Bearer {KEY}" and dl.headers["apikey"] == KEY
    assert out.read_bytes() == data

    url = storage.signed_url("clips", "m.mp4", 3600)
    sg = rec.requests[2]
    assert (sg.method, sg.url.path) == ("POST", "/storage/v1/object/sign/clips/m.mp4")
    assert sg.headers["authorization"] == f"Bearer {KEY}" and sg.headers["apikey"] == KEY
    assert json.loads(rec.bodies[2]) == {"expiresIn": 3600}
    assert url == f"{BASE}/storage/v1/object/sign/clips/m.mp4?token=T0K3N"


def test_signed_url_default_expiry_is_a_day():
    rec = Recorder(lambda r: httpx.Response(200, json={"signedURL": "/object/sign/c/m.mp4?token=t"}))
    supabase(rec).signed_url("c", "m.mp4")
    assert json.loads(rec.bodies[0]) == {"expiresIn": 86400}


@pytest.mark.parametrize(
    "signed, expected",
    [
        ("/object/sign/c/m.mp4?token=t", f"{BASE}/storage/v1/object/sign/c/m.mp4?token=t"),
        ("/storage/v1/object/sign/c/m.mp4?token=t", f"{BASE}/storage/v1/object/sign/c/m.mp4?token=t"),
        ("object/sign/c/m.mp4?token=t", f"{BASE}/storage/v1/object/sign/c/m.mp4?token=t"),
        ("https://cdn.example.com/x?token=t", "https://cdn.example.com/x?token=t"),
    ],
)
def test_signed_url_handles_every_shape_supabase_returns(signed, expected):
    rec = Recorder(lambda r: httpx.Response(200, json={"signedURL": signed}))
    assert supabase(rec).signed_url("c", "m.mp4") == expected


def test_signed_url_without_signedurl_is_an_error():
    rec = Recorder(lambda r: httpx.Response(200, json={"error": "weird"}))
    with pytest.raises(StorageError, match="signedURL"):
        supabase(rec).signed_url("c", "m.mp4")


def test_base_url_trailing_slash_is_tolerated(tmp_path):
    rec = Recorder()
    SupabaseStorage(BASE + "/", KEY, transport=rec.transport).upload("c", "m.mp4", video(tmp_path))
    assert rec.requests[0].url.path == "/storage/v1/object/c/m.mp4"
    assert str(rec.requests[0].url).startswith(BASE + "/storage/")


def test_paths_are_percent_encoded(tmp_path):
    rec = Recorder()
    supabase(rec).upload("c", "owner inbox/a b#1.mp4", video(tmp_path))
    raw = rec.requests[0].url.raw_path.decode()
    assert raw == "/storage/v1/object/c/owner%20inbox/a%20b%231.mp4"


def test_unknown_extension_uploads_as_octet_stream(tmp_path):
    rec = Recorder()
    supabase(rec).upload("c", "blob.zzzunknown", video(tmp_path, name="blob.zzzunknown"))
    assert rec.requests[0].headers["content-type"] == "application/octet-stream"


def test_upload_missing_file_raises_before_any_request(tmp_path):
    rec = Recorder()
    with pytest.raises(FileNotFoundError):
        supabase(rec).upload("c", "m.mp4", tmp_path / "ghost.mp4")
    assert rec.requests == []


# ---- SupabaseStorage: failures -----------------------------------------------------------------


def test_non_2xx_raises_with_status_and_body(tmp_path):
    rec = Recorder(lambda r: httpx.Response(413, json={"message": "The object exceeded the maximum allowed size"}))
    storage = supabase(rec)
    with pytest.raises(StorageError) as exc:
        storage.upload("sources", "a.mp4", video(tmp_path))
    assert exc.value.status == 413
    assert "413" in str(exc.value) and "exceeded the maximum allowed size" in str(exc.value)
    assert "POST" in str(exc.value) and "sources/a.mp4" in str(exc.value)

    rec = Recorder(lambda r: httpx.Response(404, json={"error": "not_found", "message": "Object not found"}))
    with pytest.raises(StorageError, match="404.*Object not found"):
        supabase(rec).download("sources", "a.mp4", tmp_path / "d.mp4")

    rec = Recorder(lambda r: httpx.Response(400, text="bad request"))
    with pytest.raises(StorageError, match="400.*bad request"):
        supabase(rec).signed_url("sources", "a.mp4")


def test_error_messages_never_carry_the_key(tmp_path):
    rec = Recorder(lambda r: httpx.Response(401, json={"message": "Invalid JWT"}))
    storage = supabase(rec)
    errors = []
    for call in (
        lambda: storage.upload("sources", "a.mp4", video(tmp_path)),
        lambda: storage.download("sources", "a.mp4", tmp_path / "d.mp4"),
        lambda: storage.signed_url("sources", "a.mp4"),
    ):
        with pytest.raises(StorageError) as exc:
            call()
        errors.append(str(exc.value))
    assert all(KEY not in e for e in errors)


def test_repr_hides_the_key():
    storage = SupabaseStorage(BASE, KEY)
    assert KEY not in repr(storage) and KEY not in str(storage)
    assert BASE in repr(storage)


def test_transport_failure_is_a_storage_error(tmp_path):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    rec = Recorder(boom)
    with pytest.raises(StorageError, match="no route to host"):
        supabase(rec).upload("c", "a.mp4", video(tmp_path))
    with pytest.raises(StorageError, match="no route to host"):
        supabase(rec).signed_url("c", "a.mp4")


def test_failed_download_leaves_no_partial_file(tmp_path):
    dest = tmp_path / "d.mp4"
    dest.write_bytes(b"previous good file")
    rec = Recorder(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(StorageError):
        supabase(rec).download("c", "a.mp4", dest)
    assert dest.read_bytes() == b"previous good file"
    assert [p.name for p in tmp_path.iterdir()] == ["d.mp4"]  # no stray temp file


def test_download_cut_off_midway_leaves_no_partial_file(tmp_path):
    class Dies(httpx.SyncByteStream):
        def __iter__(self):
            yield b"half of a vid"
            raise httpx.ReadError("connection reset by peer")

    dest = tmp_path / "d.mp4"
    dest.write_bytes(b"previous good file")
    rec = Recorder(lambda r: httpx.Response(200, stream=Dies()))
    with pytest.raises(StorageError, match="connection reset by peer"):
        supabase(rec).download("c", "a.mp4", dest)
    assert dest.read_bytes() == b"previous good file"  # not replaced by the truncated bytes
    assert [p.name for p in tmp_path.iterdir()] == ["d.mp4"]  # and the temp file is gone

    fresh = tmp_path / "sub" / "fresh.mp4"
    with pytest.raises(StorageError):
        supabase(rec).download("c", "a.mp4", fresh)
    assert not fresh.exists() and list(fresh.parent.iterdir()) == []


def test_blank_url_or_key_is_refused():
    for url, key in (("", KEY), (BASE, ""), ("  ", KEY)):
        with pytest.raises(ValueError):
            SupabaseStorage(url, key)


# ---- open_storage (CLI plumbing) ------------------------------------------------------------


def test_open_storage_without_env_exits_2_and_names_the_variables(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(typer.Exit) as exc:
        open_storage()
    assert exc.value.exit_code == EXIT_USAGE == 2
    err = capsys.readouterr().err
    assert "SUPABASE_URL" in err and "SUPABASE_SERVICE_KEY" in err


def test_open_storage_with_only_one_variable_still_exits_2(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", BASE)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(typer.Exit) as exc:
        open_storage()
    assert exc.value.exit_code == 2
    assert "SUPABASE_SERVICE_KEY" in capsys.readouterr().err


def test_open_storage_with_env_returns_supabase_storage_and_never_prints_the_key(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", BASE)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", KEY)
    storage = open_storage()
    assert isinstance(storage, SupabaseStorage)  # constructing never connects
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err + repr(storage)


# ---- delete: idempotent, for `studio source purge` ----------------------------------------------------------------------


def test_local_delete_removes_the_object_and_is_idempotent(tmp_path):
    storage = LocalStorage(tmp_path / "store")
    storage.upload("sources", "owner_inbox/a.mp4", video(tmp_path))
    storage.upload("sources", "owner_inbox/b.mp4", video(tmp_path))
    storage.delete("sources", "owner_inbox/a.mp4")
    with pytest.raises(StorageError):
        storage.download("sources", "owner_inbox/a.mp4", tmp_path / "d.mp4")
    storage.delete("sources", "owner_inbox/a.mp4")  # already gone: no error
    storage.delete("clips", "never-was.mp4")
    assert storage.download("sources", "owner_inbox/b.mp4", tmp_path / "b.mp4").is_file()  # nothing else was touched


def test_supabase_delete_sends_one_authenticated_delete_and_treats_404_as_done():
    rec = Recorder(lambda request: httpx.Response(200, json=[]))
    supabase(rec).delete("sources", "owner_inbox/a b.mp4")
    (request,) = rec.requests
    assert request.method == "DELETE" and request.url.raw_path.decode() == "/storage/v1/object/sources/owner_inbox/a%20b.mp4"
    assert request.headers["authorization"] == f"Bearer {KEY}" and request.headers["apikey"] == KEY
    gone = Recorder(lambda request: httpx.Response(404, json={"error": "not_found"}))
    supabase(gone).delete("sources", "owner_inbox/a.mp4")  # no raise


def test_supabase_delete_failures_are_storage_errors_that_never_leak_the_key():
    refused = Recorder(lambda request: httpx.Response(403, json={"message": "not allowed"}))
    with pytest.raises(StorageError, match="DELETE sources/x.mp4") as exc:
        supabase(refused).delete("sources", "x.mp4")
    assert exc.value.status == 403 and KEY not in str(exc.value)

    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(StorageError, match="DELETE sources/x.mp4") as exc:
        supabase(Recorder(boom)).delete("sources", "x.mp4")
    assert KEY not in str(exc.value)

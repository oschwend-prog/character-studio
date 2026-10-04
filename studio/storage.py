"""Media storage: the ``Storage`` protocol, its Supabase Storage client and a local fake.

Media never lives in git or in Postgres: sources and master clips sit in two private Supabase
buckets, ``sources`` and ``clips``. Everything that moves a file (inbox ingest, mastering,
publishing) talks to this protocol, so tests run on ``LocalStorage`` and production on
``SupabaseStorage``.

* ``upload(bucket, path, file) -> str`` stores ``file`` at ``path`` (an existing object is
  overwritten) and returns ``path``, the bucket-relative key to keep in the database.
* ``download(bucket, path, dest) -> Path`` writes the object to ``dest`` (parents are created; a
  failed download never leaves a partial file) and returns ``dest``.
* ``signed_url(bucket, path, expires_s=86400) -> str`` is a time-limited link anyone can fetch,
  for handing a clip to Postiz.

A ``bucket`` is one plain name; a ``path`` is relative with ``/``-separated, non-empty segments
and no ``.`` / ``..``. Anything else is a ``ValueError`` before any I/O. A missing file or a
failed request is a ``StorageError`` that carries the HTTP ``status`` when there was one.

``SupabaseStorage`` talks to the Storage REST API with the service key. The key is only ever sent
as the ``Authorization`` / ``apikey`` headers: it never appears in an error message, a repr or
output. The upload streams from disk with an explicit ``Content-Length`` (no chunked encoding).
"""

from __future__ import annotations

import contextlib
import mimetypes
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import quote

import httpx

DEFAULT_EXPIRES_S = 86_400
_CHUNK = 1024 * 1024
_BODY_CHARS = 500
# Generous write/read for tens of MB over a home connection; connect and pool stay short.
_TIMEOUT = httpx.Timeout(30.0, write=600.0, read=600.0)


class StorageError(RuntimeError):
    """A storage call failed. ``status`` is the HTTP status (404 for a missing local object)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@runtime_checkable
class Storage(Protocol):
    def upload(self, bucket: str, path: str, file: Path | str) -> str: ...

    def download(self, bucket: str, path: str, dest: Path | str) -> Path: ...

    def signed_url(self, bucket: str, path: str, expires_s: int = DEFAULT_EXPIRES_S) -> str: ...


def _check_target(bucket: str, path: str) -> None:
    if not bucket or "/" in bucket or bucket in {".", ".."} or "\x00" in bucket:
        raise ValueError(f"bucket must be one plain name, got {bucket!r}")
    parts = path.split("/")
    if not path or "\x00" in path or any(p in {"", ".", ".."} for p in parts):
        raise ValueError(
            f"path must be relative with non-empty segments and no '.' or '..', got {path!r}"
        )


def _check_expiry(expires_s: int) -> None:
    if expires_s <= 0:
        raise ValueError(f"expires_s must be positive, got {expires_s!r}")


def _read_chunks(file: Path) -> Iterator[bytes]:
    with file.open("rb") as f:
        while chunk := f.read(_CHUNK):
            yield chunk


@contextlib.contextmanager
def _partial_file(dest: Path) -> Iterator[Path]:
    """A temp file beside ``dest`` that replaces it only when the block finishes cleanly."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class LocalStorage:
    """Buckets as folders under ``root``: the test double for ``SupabaseStorage``."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _object(self, bucket: str, path: str) -> Path:
        _check_target(bucket, path)
        return self.root / bucket / path

    def _existing(self, bucket: str, path: str) -> Path:
        target = self._object(bucket, path)
        if not target.is_file():
            raise StorageError(f"storage object not found: {bucket}/{path}", 404)
        return target

    def upload(self, bucket: str, path: str, file: Path | str) -> str:
        target = self._object(bucket, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        return path

    def download(self, bucket: str, path: str, dest: Path | str) -> Path:
        source = self._existing(bucket, path)
        dest = Path(dest)
        with _partial_file(dest) as tmp:
            shutil.copyfile(source, tmp)
        return dest

    def signed_url(self, bucket: str, path: str, expires_s: int = DEFAULT_EXPIRES_S) -> str:
        _check_expiry(expires_s)
        return self._existing(bucket, path).resolve().as_uri()


class SupabaseStorage:
    """Supabase Storage over its REST API, authenticated with the project's service key."""

    def __init__(
        self,
        url: str,
        service_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        url = url.strip().rstrip("/")
        if not url or not service_key.strip():
            raise ValueError("SupabaseStorage needs a project url and a service key")
        self._root = url
        self._key = service_key.strip()
        self._client = httpx.Client(transport=transport, timeout=_TIMEOUT)

    def __repr__(self) -> str:
        return f"SupabaseStorage(url={self._root!r})"

    def close(self) -> None:
        self._client.close()

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "apikey": self._key}

    def _endpoint(self, kind: str, bucket: str, path: str) -> str:
        _check_target(bucket, path)
        return f"{self._root}/storage/v1/object/{kind}{quote(bucket, safe='')}/{quote(path, safe='/')}"

    @staticmethod
    def _fail(method: str, bucket: str, path: str, response: httpx.Response) -> StorageError:
        body = response.text.strip()[:_BODY_CHARS]
        return StorageError(
            f"storage {method} {bucket}/{path} failed: HTTP {response.status_code}: {body}",
            response.status_code,
        )

    @staticmethod
    def _unreachable(method: str, bucket: str, path: str, error: httpx.HTTPError) -> StorageError:
        return StorageError(f"storage {method} {bucket}/{path} failed: {error}")

    def upload(self, bucket: str, path: str, file: Path | str) -> str:
        endpoint = self._endpoint("", bucket, path)
        file = Path(file)
        size = file.stat().st_size  # a missing file fails here, before any request
        headers = {
            **self._auth(),
            "x-upsert": "true",
            "Content-Type": mimetypes.guess_type(file.name)[0] or "application/octet-stream",
            "Content-Length": str(size),  # explicit, so the stream is not sent chunked
        }
        try:
            response = self._client.post(endpoint, headers=headers, content=_read_chunks(file))
        except httpx.HTTPError as e:
            raise self._unreachable("POST", bucket, path, e) from e
        if not response.is_success:
            raise self._fail("POST", bucket, path, response)
        return path

    def download(self, bucket: str, path: str, dest: Path | str) -> Path:
        endpoint = self._endpoint("", bucket, path)
        dest = Path(dest)
        try:
            with self._client.stream("GET", endpoint, headers=self._auth()) as response:
                if not response.is_success:
                    response.read()
                    raise self._fail("GET", bucket, path, response)
                with _partial_file(dest) as tmp, tmp.open("wb") as out:
                    for chunk in response.iter_bytes(_CHUNK):
                        out.write(chunk)
        except httpx.HTTPError as e:
            raise self._unreachable("GET", bucket, path, e) from e
        return dest

    def signed_url(self, bucket: str, path: str, expires_s: int = DEFAULT_EXPIRES_S) -> str:
        _check_expiry(expires_s)
        endpoint = self._endpoint("sign/", bucket, path)
        try:
            response = self._client.post(endpoint, headers=self._auth(), json={"expiresIn": expires_s})
        except httpx.HTTPError as e:
            raise self._unreachable("POST sign", bucket, path, e) from e
        if not response.is_success:
            raise self._fail("POST sign", bucket, path, response)
        try:
            signed = response.json()["signedURL"]
        except (ValueError, KeyError, TypeError):
            signed = None
        if not isinstance(signed, str) or not signed:
            raise StorageError(
                f"storage sign {bucket}/{path}: response had no signedURL: "
                f"{response.text.strip()[:_BODY_CHARS]}",
                response.status_code,
            )
        if signed.startswith(("http://", "https://")):
            return signed
        if not signed.startswith("/"):
            signed = f"/{signed}"
        if not signed.startswith("/storage/v1/"):
            signed = f"/storage/v1{signed}"
        return f"{self._root}{signed}"

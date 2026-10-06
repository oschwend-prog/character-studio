"""The Instagram post behind a saved file, read from its name alone (owner 2026-10-06: "keep our snapinsta process and align
it with yt-dlp", easily and efficiently).

The owner saves clips with snapinsta and drops the files in the terminal. Snapinsta names each file after the post:
``SnapInsta-Ai_<media pk>_<owner user id>.mp4`` (most files) or ``SnapInsta-Ai_<shortcode>.mp4``; a second copy of the same
file gets `` 2`` before the extension. The media pk and the shortcode are the same number (the shortcode is the pk in base 64
with Instagram's alphabet), so the post link ``https://www.instagram.com/reel/<shortcode>/`` is rebuilt here without any
network call: a file drop then records the same post link and id as a pasted link, and the same post dropped twice is
recognised by its ``post_id``.

Nothing is fetched here. A name that does not match returns None (a file from anywhere else stays a plain file drop).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_INDEX = {ch: i for i, ch in enumerate(IG_ALPHABET)}
SHORTCODE_MAX = 14  # today's codes are 11 characters; a little room for growth, never a long random name

_PREFIX = r"snapinsta[a-z.\-]*_"
_COPY = r"(?: \(?\d{1,3}\)?)?"  # "name 2.mp4" or "name (2).mp4": a second copy of the same file
_EXT = r"\.(?:mp4|mov|m4v)"
_BY_PK = re.compile(rf"^{_PREFIX}(\d{{6,25}})_(\d{{1,20}}){_COPY}{_EXT}$", re.IGNORECASE)
_BY_CODE = re.compile(rf"^{_PREFIX}([A-Za-z0-9_-]{{5,{SHORTCODE_MAX}}}){_COPY}{_EXT}$", re.IGNORECASE)


@dataclass(frozen=True)
class PostRef:
    """The post a file came from. ``post_id`` is the media pk as text (the duplicate key); ``owner_id`` is the numeric
    account id snapinsta puts in the name (not a handle: the handle comes from the post's details or the owner)."""

    platform: str
    post_id: str
    shortcode: str
    url: str
    owner_id: str | None = None


def ig_shortcode(pk: int) -> str:
    """The shortcode of an Instagram media pk (base 64, Instagram's alphabet)."""
    if pk <= 0:
        raise ValueError(f"not a media pk: {pk}")
    out = ""
    while pk:
        pk, digit = divmod(pk, 64)
        out = IG_ALPHABET[digit] + out
    return out


def ig_pk(shortcode: str) -> int:
    """The media pk of an Instagram shortcode; ``ValueError`` for a character outside the alphabet."""
    if not shortcode:
        raise ValueError("an empty shortcode")
    pk = 0
    for ch in shortcode:
        if ch not in _INDEX:
            raise ValueError(f"not a shortcode: {shortcode!r}")
        pk = pk * 64 + _INDEX[ch]
    return pk


def _ref(pk: int, owner_id: str | None) -> PostRef:
    code = ig_shortcode(pk)
    return PostRef("instagram", str(pk), code, f"https://www.instagram.com/reel/{code}/", owner_id)


def from_file_name(name: str) -> PostRef | None:
    """The Instagram post a snapinsta file name points to, or None when the name is not one of its patterns."""
    base = (name or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if m := _BY_PK.match(base):
        return _ref(int(m.group(1)), m.group(2))
    if (m := _BY_CODE.match(base)) and not m.group(1).isdigit():
        return _ref(ig_pk(m.group(1)), None)
    return None

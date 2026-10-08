"""The text of a post: caption + AI disclosure + hashtags, and its length limit.

Lives apart from ``studio.publish`` so the ``clip set --caption`` check and the publisher use ONE rule
(``studio.publish`` imports ``studio.clips``, so ``studio.clips`` cannot import it back).

``compose_content(caption, hashtags)`` is the exact text posted: the caption, the AI disclosure line, a
blank line, the hashtags. The disclosure (``AI_DISCLOSURE``) is appended unless that EXACT string is
already in the caption: a caption that merely mentions "AI-generated" in some other way still gets it, so
the standard line is always visible and cannot be suppressed (or cut) by wording. The result may not
exceed ``CAPTION_LIMIT`` characters (TikTok and Instagram both stop at 2,200): longer raises
``ValueError``, it is never silently trimmed, so the disclosure and the hashtags can never be the part
that gets cut. Length is counted in UTF-16 code units (an emoji is 2), the stricter of the two ways a
platform may count.

Hashtags (owner's caption playbook, 2026-10-05): at most ``HASHTAG_LIMIT`` (5, Instagram's cap) after ``clean_tags``,
and never one of ``BANNED_HASHTAGS`` (#fyp, #foryou, #foryoupage, #viral, #explore: they reach nobody, case-insensitive).
Both raise ``ValueError`` naming the limit or the tag; ``clip set`` turns it into exit 2 like the length. The terminal
mirrors this rule (``composeContent`` in terminal/src/lib/captions.ts; terminal/src/lib/parity-cases.json ``captions`` holds
the cases both sides must agree on).

**The series tag** (terminal v3 spec section 11, item 3): each character has his own series hashtag (``characters/<slug>/refs.json``
``style.series_tag``: Franz ``#sausagecomingthrough``, Reginald ``#asyouwere``, Lenny ``#yourewelcome``; ``check_series_tag``
is the one rule for it, the seed uses it). ``with_series_tag(caption, hashtags, tag)`` is what the publisher posts: the clip's
hashtags plus the series tag at the end, only when there is room: never a sixth hashtag, never past ``CAPTION_LIMIT``, never
twice (case-insensitive), never a refused one; otherwise the clip's hashtags exactly as they are. ``compose_content`` itself is
unchanged (the terminal mirrors it), so the clip's own text and the terminal's preview stay the owner's.
"""

from __future__ import annotations

import re
from typing import Any

# Every post carries a visible AI disclosure, whatever the platform: on Instagram it is the only one
# (the label is not an API setting there); on TikTok it backs up ``video_made_with_ai``.
AI_DISCLOSURE = "AI-generated character 🤖"

CAPTION_LIMIT = 2200
HASHTAG_LIMIT = 5  # Instagram's cap
BANNED_HASHTAGS = frozenset({"fyp", "foryou", "foryoupage", "viral", "explore"})
SERIES_TAG = re.compile(r"#[A-Za-z0-9_]{1,60}")  # one hashtag: #, then letters, digits or _ (no spaces, no second tag)


def caption_length(text: str) -> int:
    """The length of ``text`` in UTF-16 code units (what a platform's character limit may count)."""
    return len(text.encode("utf-16-le")) // 2


def clean_tags(hashtags: list[str]) -> list[str]:
    """Hashtags with their ``#``, trimmed, empty ones dropped, de-duplicated (case-insensitive)."""
    tags: list[str] = []
    seen: set[str] = set()
    for raw in hashtags:
        tag = raw.strip().lstrip("#").strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(f"#{tag}")
    return tags


def compose_content(caption: str, hashtags: list[str]) -> str:
    """The post text (see the module docstring). ``ValueError`` when it is over ``CAPTION_LIMIT``, has more than
    ``HASHTAG_LIMIT`` hashtags or one of ``BANNED_HASHTAGS``."""
    text = caption.strip()
    if AI_DISCLOSURE not in text:
        text = f"{text}\n\n{AI_DISCLOSURE}" if text else AI_DISCLOSURE
    tags = clean_tags(hashtags)
    for tag in tags:
        if tag[1:].lower() in BANNED_HASHTAGS:
            raise ValueError(
                f"hashtag {tag} is refused: {', '.join('#' + t for t in sorted(BANNED_HASHTAGS))} reach nobody "
                f"(use the moment, the niche, the format and #oddeyes)"
            )
    if len(tags) > HASHTAG_LIMIT:
        raise ValueError(
            f"{len(tags)} hashtags, over the limit of {HASHTAG_LIMIT} (Instagram's cap): keep the moment, the niche, "
            f"the format and #oddeyes"
        )
    content = f"{text}\n\n{' '.join(tags)}" if tags else text
    if (n := caption_length(content)) > CAPTION_LIMIT:
        raise ValueError(
            f"the post text is {n} characters with the AI disclosure and hashtags, over the "
            f"{CAPTION_LIMIT} limit: shorten the caption by {n - CAPTION_LIMIT} or more"
        )
    return content


def check_series_tag(tag: Any) -> str:
    """A character's series tag (``refs.json`` ``style.series_tag``), trimmed: ONE hashtag (``#`` then 1-60 letters, digits or
    ``_``) that is not one of ``BANNED_HASHTAGS``; else ``ValueError`` naming ``series_tag``."""
    clean = tag.strip() if isinstance(tag, str) else None
    if clean is None or not SERIES_TAG.fullmatch(clean):
        raise ValueError(f"series_tag must be one hashtag such as #asyouwere (# then letters, digits or _), got {tag!r:.70}")
    if clean[1:].lower() in BANNED_HASHTAGS:
        raise ValueError(f"series_tag {clean} is refused: it reaches nobody")
    return clean


def with_series_tag(caption: str, hashtags: list[str], series_tag: str | None) -> list[str]:
    """The hashtags to post: ``hashtags`` plus ``series_tag`` at the end when there is room (see the module docstring), else
    ``hashtags`` as they are. Never raises: a clip whose own text is refused keeps that refusal for ``compose_content``."""
    if not series_tag:
        return list(hashtags)
    tags = clean_tags(hashtags)
    key = series_tag.strip().lstrip("#").lower()
    if len(tags) >= HASHTAG_LIMIT or any(t[1:].lower() == key for t in tags):
        return list(hashtags)
    candidate = [*hashtags, series_tag]
    try:
        compose_content(caption, candidate)  # the limit, the dead tags and the hashtag cap, exactly as they will be posted
    except ValueError:
        return list(hashtags)
    return candidate

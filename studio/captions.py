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
"""

from __future__ import annotations

# Every post carries a visible AI disclosure, whatever the platform: on Instagram it is the only one
# (the label is not an API setting there); on TikTok it backs up ``video_made_with_ai``.
AI_DISCLOSURE = "AI-generated character 🤖"

CAPTION_LIMIT = 2200


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
    """The post text (see the module docstring). ``ValueError`` when it is over ``CAPTION_LIMIT``."""
    text = caption.strip()
    if AI_DISCLOSURE not in text:
        text = f"{text}\n\n{AI_DISCLOSURE}" if text else AI_DISCLOSURE
    tags = clean_tags(hashtags)
    content = f"{text}\n\n{' '.join(tags)}" if tags else text
    if (n := caption_length(content)) > CAPTION_LIMIT:
        raise ValueError(
            f"the post text is {n} characters with the AI disclosure and hashtags, over the "
            f"{CAPTION_LIMIT} limit: shorten the caption by {n - CAPTION_LIMIT} or more"
        )
    return content

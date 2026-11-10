"""Text normalisation helpers shared by the matcher and the file namer.

Everything here is deliberately dependency free and side effect free so it can be
unit tested without touching the network.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Tokens that describe a *variant* of a recording rather than the recording
# itself. They are stripped before comparing two titles so that
# "Song (Remastered 2011)" and "Song" are recognised as the same master.
VARIANT_TOKENS = {
    "remaster",
    "remastered",
    "deluxe",
    "expanded",
    "edition",
    "version",
    "explicit",
    "clean",
    "mono",
    "stereo",
    "bonus",
    "anniversary",
    "original",
    "mix",
    "edit",
    "radio",
    "album",
    "single",
    "lp",
    "ep",
    "feat",
    "featuring",
    "ft",
    "with",
    "prod",
    "produced",
    "official",
    "video",
    "audio",
    "lyrics",
    "lyric",
    "hd",
    "hq",
    "4k",
    "mv",
    "m/v",
    "officialvideo",
    "officialaudio",
    "officialmusicvideo",
    "audioonly",
    "visualizer",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_AMP_RE = re.compile(r"\s*&\s*")
_FEAT_RE = re.compile(
    r"\s*[\(\[](?:feat|ft|featuring|with)\b[^)\]]*[\)\]]", re.IGNORECASE
)
_FEAT_BARE_RE = re.compile(
    r"\s+[-–—]?\s*\b(?:feat|ft|featuring)\b\.?\s*:?.*$", re.IGNORECASE
)


def strip_accents(value: str) -> str:
    """Replace accented characters with their ASCII base form."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(value: str) -> str:
    """Lowercase, de-accent and collapse whitespace."""
    if not value:
        return ""
    lowered = strip_accents(value).lower()
    lowered = lowered.replace("’", "'").replace("‘", "'")
    return _WS_RE.sub(" ", lowered).strip()


def strip_variants(value: str) -> str:
    """Drop bracketed suffixes such as ``(Remastered 2011)`` or ``[Official Audio]``."""
    if not value:
        return ""
    return _WS_RE.sub(" ", _PAREN_RE.sub(" ", value)).strip()


def strip_feat(value: str) -> str:
    """Remove ``feat. X`` style annotations from a title."""
    if not value:
        return ""
    without_brackets = _FEAT_RE.sub(" ", value)
    without_brackets = _FEAT_BARE_RE.sub("", without_brackets)
    return _WS_RE.sub(" ", without_brackets).strip()


def tokenize(value: str) -> list[str]:
    """Split a normalised string into comparable word tokens."""
    cleaned = normalize(value)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    cleaned = _AMP_RE.sub(" and ", cleaned)
    tokens = [t for t in cleaned.split() if t]
    return [t for t in tokens if t not in VARIANT_TOKENS]


def core_title(value: str) -> str:
    """Normalised, variant free title used for equality checks."""
    tokens = tokenize(strip_feat(strip_variants(value)))
    return " ".join(tokens)


def similarity(left: str, right: str) -> float:
    """Blended token and character similarity in the 0..1 range."""
    a = core_title(left)
    b = core_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    ratio = SequenceMatcher(None, a, b).ratio()

    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if a_tokens and b_tokens:
        jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    else:
        jaccard = 0.0

    containment = 1.0 if (a in b or b in a) else 0.0

    return max(ratio * 0.55 + jaccard * 0.45, containment * 0.92)


def contains_phrase(haystack: str, needle: str) -> bool:
    """True when every token of ``needle`` appears in ``haystack``."""
    needle_tokens = tokenize(needle)
    if not needle_tokens:
        return False
    haystack_tokens = set(tokenize(haystack))
    return all(token in haystack_tokens for token in needle_tokens)


def safe_filename(value: str, replacement: str = "-") -> str:
    """Turn an arbitrary title into something Windows and POSIX accept."""
    cleaned = strip_accents(value)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', replacement, cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip(" .")
    return cleaned or "untitled"


def truncate(value: str, limit: int) -> str:
    """Shorten a string without cutting a word in half where avoidable."""
    if len(value) <= limit:
        return value
    cut = value[:limit]
    if " " in cut:
        head = cut.rsplit(" ", 1)[0]
        if len(head) >= limit * 0.6:
            return head
    return cut.strip()

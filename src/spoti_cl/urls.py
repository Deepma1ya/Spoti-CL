"""Parsing of every Spotify link shape the tool accepts."""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Entity kinds we can resolve.
KINDS = ("track", "album", "playlist", "artist", "show", "episode", "user")

_URI_RE = re.compile(r"^spotify:(?P<kind>[a-z]+):(?P<id>[A-Za-z0-9]+)", re.IGNORECASE)
_URL_RE = re.compile(
    r"^(?:https?://)?(?:open|play)\.spotify\.com/(?P<kind>[a-z]+)/(?P<id>[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_EMBED_RE = re.compile(
    r"^(?:https?://)?open\.spotify\.com/embed/(?P<kind>[a-z]+)/(?P<id>[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_BARE_ID_RE = re.compile(r"^(?P<id>[A-Za-z0-9]{22})$")

#: Some kinds share a resolver with another kind.
_KIND_ALIASES = {
    "show": "show",
    "episode": "episode",
    "user": "playlist",
    "playlist": "playlist",
}


@dataclass(frozen=True, slots=True)
class SpotifyRef:
    """A parsed pointer to a Spotify entity."""

    kind: str
    id: str

    @property
    def uri(self) -> str:
        return f"spotify:{self.kind}:{self.id}"

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/{self.kind}/{self.id}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.url


class SpotifyLinkError(ValueError):
    """Raised when a string does not look like anything Spotify related."""


def parse_link(value: str, default_kind: str = "track") -> SpotifyRef:
    """Turn a URL, a ``spotify:`` URI or a bare id into a :class:`SpotifyRef`.

    ``default_kind`` is used for bare 22 character ids, where the kind cannot be
    derived from the string itself.
    """
    if not value or not value.strip():
        raise SpotifyLinkError("empty link")

    raw = value.strip().strip("<>\"'")
    # Drop query strings and fragments such as "?si=abc123".
    raw = raw.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    for pattern in (_EMBED_RE, _URI_RE, _URL_RE):
        match = pattern.match(raw)
        if match:
            kind = match.group("kind").lower()
            if kind not in KINDS:
                raise SpotifyLinkError(f"unsupported Spotify entity: {kind!r}")
            return SpotifyRef(kind=_KIND_ALIASES.get(kind, kind), id=match.group("id"))

    bare = _BARE_ID_RE.match(raw)
    if bare:
        return SpotifyRef(kind=default_kind, id=bare.group("id"))

    raise SpotifyLinkError(
        f"cannot parse {value!r} - expected a Spotify link, a spotify: URI or a 22 character id"
    )


def is_spotify_link(value: str) -> bool:
    """True when :func:`parse_link` would succeed."""
    try:
        parse_link(value)
    except SpotifyLinkError:
        return False
    return True

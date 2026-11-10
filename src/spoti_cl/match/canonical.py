"""Cross reference a recording through free, key less music databases.

The ISRC of a track is the fingerprint of a *recording*. Looking it up in
Deezer or MusicBrainz gives us a canonical title and artist name for the same
master, which makes matching far more reliable than trusting the string that
Spotify happens to display (titles carry "Remastered", "Version", live takes
and typographic noise).

MusicBrainz also answers a title + artist query, which is what we fall back to
when Spotify does not hand out an ISRC.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx

from ..textutil import strip_feat, strip_variants

DEEZER_BY_ISRC = "https://api.deezer.com/track/isrc:{isrc}"
MUSICBRAINZ_SEARCH = "https://musicbrainz.org/ws/2/recording"

#: MusicBrainz asks for a descriptive user agent with contact details.
MB_USER_AGENT = "spoti-cl/0.1 (https://github.com/; anonymous)"

#: MusicBrainz allows one request per second. Anything faster gets a 503.
_MB_LOCK = threading.Lock()
_MB_LAST_CALL = 0.0
_MB_MIN_INTERVAL = 1.05


@dataclass(slots=True)
class Canonical:
    """Canonical metadata for a recording."""

    title: str
    artist: str
    album: str = ""
    duration_ms: int = 0
    isrc: str = ""
    source: str = ""

    @property
    def artist_label(self) -> str:
        return self.artist


def _throttle_musicbrainz() -> None:
    global _MB_LAST_CALL
    with _MB_LOCK:
        wait = _MB_MIN_INTERVAL - (time.monotonic() - _MB_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _MB_LAST_CALL = time.monotonic()


def _quote(value: str) -> str:
    return value.replace('"', " ").strip()


# ------------------------------------------------------------------ by ISRC
def lookup_isrc(
    isrc: str,
    http: httpx.Client | None = None,
    timeout: float = 15.0,
) -> Canonical | None:
    """Look up ``isrc`` in Deezer and MusicBrainz, Deezer first."""
    if not isrc:
        return None

    client = http or httpx.Client(timeout=timeout, follow_redirects=True)
    owned = http is None
    try:
        canonical = _lookup_deezer(isrc, client, timeout)
        if canonical:
            return canonical
        return _lookup_musicbrainz_isrc(isrc, client, timeout)
    finally:
        if owned:
            client.close()


def _lookup_deezer(isrc: str, http: httpx.Client, timeout: float) -> Canonical | None:
    try:
        response = http.get(
            DEEZER_BY_ISRC.format(isrc=isrc),
            timeout=timeout,
            headers={"User-Agent": "spoti-cl/0.1"},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not isinstance(payload, dict) or payload.get("error") or not payload.get("title"):
        return None

    artist = (payload.get("artist") or {}).get("name") or ""
    if not artist:
        return None
    return Canonical(
        title=payload.get("title", ""),
        artist=artist,
        album=(payload.get("album") or {}).get("title") or "",
        duration_ms=int(payload.get("duration") or 0) * 1000,
        isrc=str(payload.get("isrc") or ""),
        source="deezer",
    )


def _musicbrainz_get(
    client: httpx.Client,
    params: dict[str, str],
    timeout: float,
    attempts: int = 3,
) -> dict | None:
    """GET the MusicBrainz search endpoint, retrying through the 503s.

    MusicBrainz answers 503 when it is being hammered, and the rate limit is
    global - another process running this tool counts against it too - so a
    short backoff is the difference between a lookup and no lookup.
    """
    for attempt in range(attempts):
        _throttle_musicbrainz()
        try:
            response = client.get(
                MUSICBRAINZ_SEARCH,
                params=params,
                timeout=timeout,
                headers={"User-Agent": MB_USER_AGENT, "Accept": "application/json"},
            )
        except (httpx.HTTPError, ValueError):
            return None
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                return None
            return payload if isinstance(payload, dict) else None
        if response.status_code not in (429, 503):
            return None
        time.sleep(1.5 * (attempt + 1))
    return None


def _lookup_musicbrainz_isrc(
    isrc: str, http: httpx.Client, timeout: float
) -> Canonical | None:
    payload = _musicbrainz_get(
        http, {"query": f"isrc:{isrc}", "fmt": "json", "limit": 5}, timeout
    )
    if not payload:
        return None
    recordings = payload.get("recordings") or []
    if not recordings:
        return None
    return _canonical_from_recording(recordings[0], "musicbrainz")


# ------------------------------------------------------------ by title/artist
def lookup_recording(
    title: str,
    artist: str,
    duration_ms: int = 0,
    http: httpx.Client | None = None,
    timeout: float = 15.0,
) -> Canonical | None:
    """Find the recording that matches a title and artist.

    The duration is used both to narrow the MusicBrainz query and to pick the
    right recording when several masters share a title - a live take and the
    studio cut have the same name but not the same length.
    """
    if not title or not artist:
        return None

    client = http or httpx.Client(timeout=timeout, follow_redirects=True)
    owned = http is None
    try:
        query = f'recording:"{_quote(title)}" AND artist:"{_quote(artist)}"'
        # "Song (feat. X)" and "Song - Remastered 2011" never match a
        # database entry, so the annotations come off first.
        plain = strip_feat(strip_variants(title))
        if plain and plain != title:
            query = f'recording:"{_quote(plain)}" AND artist:"{_quote(artist)}"'

        payload = _musicbrainz_get(
            client, {"query": query, "fmt": "json", "limit": 25}, timeout
        )
        if not payload:
            return None

        recordings = payload.get("recordings") or []
        if not recordings:
            return None

        best = _pick_closest(recordings, duration_ms)
        if best is None:
            return None
        return _canonical_from_recording(best, "musicbrainz")
    finally:
        if owned:
            client.close()


def _pick_closest(recordings: list[dict], duration_ms: int) -> dict | None:
    """Pick the recording whose length is closest to the Spotify duration."""
    if not duration_ms:
        return recordings[0]

    tolerance = max(8000, int(duration_ms * 0.05))
    scored: list[tuple[float, dict]] = []
    for recording in recordings:
        length = int(recording.get("length") or 0)
        if not length:
            continue
        delta = abs(length - duration_ms)
        if delta > tolerance:
            continue
        scored.append((delta, recording))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _canonical_from_recording(recording: dict, source: str) -> Canonical:
    artists = [
        entry.get("name", "")
        for entry in (recording.get("artist-credit") or [])
        if entry.get("name")
    ]
    releases = recording.get("releases") or []
    album = releases[0].get("title", "") if releases else ""
    isrcs = recording.get("isrcs") or []
    return Canonical(
        title=recording.get("title", "") or recording.get("name", ""),
        artist=", ".join(artists),
        album=album,
        duration_ms=int(recording.get("length") or 0),
        isrc=str(isrcs[0]) if isrcs else "",
        source=source,
    )

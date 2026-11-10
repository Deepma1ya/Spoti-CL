"""The matching engine: Spotify track in, best YouTube video out."""

from __future__ import annotations

import threading

import httpx

from ..cache import Cache
from ..config import Config
from ..models import Candidate, Match, Track
from .canonical import Canonical, lookup_isrc, lookup_recording
from .candidates import search_candidates
from .score import score_candidate

#: A score this high is good enough to stop looking.
GOOD_ENOUGH = 0.80


class MatchError(RuntimeError):
    """Raised when no candidate clears the acceptance bar."""


class Matcher:
    """Finds the video that carries a given Spotify recording."""

    def __init__(
        self,
        config: Config,
        cache: Cache | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.cache = cache or Cache()
        self._http = http or httpx.Client(timeout=15.0, follow_redirects=True)
        self._lock = threading.RLock()
        self._memo: dict[str, Match] = {}

    # ------------------------------------------------------------- canonical
    def canonical_for(self, track: Track) -> Canonical | None:
        """Cross reference the recording to get a canonical title and artist.

        The ISRC path is exact but the Web API rarely hands one out to an
        anonymous caller, so a MusicBrainz title and artist lookup is the
        fallback. Results are cached, and MusicBrainz is rate limited to one
        request per second, so this is only called when a plain search fails.
        """
        key = track.isrc or f"{track.primary_artist}|{track.name}|{track.duration_ms}"
        cached = self.cache.get(f"canonical:{key}", ttl=180 * 24 * 3600)
        if cached:
            return Canonical(**cached)

        canonical: Canonical | None = None
        if track.isrc:
            canonical = lookup_isrc(track.isrc, self._http)
        if canonical is None:
            try:
                canonical = lookup_recording(
                    track.name,
                    track.primary_artist,
                    track.duration_ms,
                    self._http,
                )
            except httpx.HTTPError:
                canonical = None

        if canonical is not None:
            # MusicBrainz often knows the ISRC of the master even when the
            # anonymous Spotify API refuses to hand it over - but only trust it
            # when the lengths agree, otherwise it is a different release of
            # the same song.
            if canonical.isrc and not track.isrc:
                delta = abs(canonical.duration_ms - track.duration_ms)
                if not canonical.duration_ms or delta <= 3000:
                    track.isrc = canonical.isrc
            self.cache.set(
                f"canonical:{key}",
                {
                    "title": canonical.title,
                    "artist": canonical.artist,
                    "album": canonical.album,
                    "duration_ms": canonical.duration_ms,
                    "isrc": canonical.isrc,
                    "source": canonical.source,
                },
                ttl=180 * 24 * 3600,
            )
        return canonical

    # ----------------------------------------------------------------- query
    def queries_for(self, track: Track, canonical: Canonical | None) -> list[str]:
        """Ordered list of search strings, best guess first."""
        artist = track.primary_artist
        title = track.name
        queries: list[str] = []

        if canonical and canonical.artist and canonical.title:
            queries.append(f"{canonical.artist} - {canonical.title}")
        if artist and title:
            queries.append(f"{artist} - {title}")
        if canonical and canonical.artist and title:
            queries.append(f"{canonical.artist} {title}")
        if artist and title:
            queries.append(f"{artist} {title} official audio")
        if canonical and canonical.title:
            queries.append(f"{canonical.title} {canonical.artist} audio")
        if title:
            queries.append(f"{artist} {title}".strip())

        seen: set[str] = set()
        unique: list[str] = []
        for query in queries:
            cleaned = " ".join(query.split())
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                unique.append(cleaned)
        return unique

    # ---------------------------------------------------------------- search
    def _search(self, query: str) -> list[Candidate]:
        return search_candidates(
            query,
            limit=self.config.search_results,
            timeout=self.config.match_timeout,
            cookie_file=self.config.cookie_file,
            proxy=self.config.proxy,
        )

    def _best_of(self, track: Track, query: str, canonical: Canonical | None) -> Match | None:
        best: Match | None = None
        for candidate in self._search(query):
            score = score_candidate(track, candidate, canonical)
            if best is None or score > best.score:
                best = Match(
                    track=track,
                    candidate=candidate,
                    score=score,
                    query=query,
                    canonical_source=canonical.source if canonical else "",
                )
        return best

    def match(self, track: Track, canonical: Canonical | None = None) -> Match:
        """Find the best video for ``track``.

        The plain title and artist search runs first. Only when that does not
        produce a convincing hit do we pay for a MusicBrainz lookup and search
        again with the canonical names.

        Raises :class:`MatchError` when nothing scores high enough.
        """
        best: Match | None = None

        for query in self.queries_for(track, None):
            found = self._best_of(track, query, None)
            if found and (best is None or found.score > best.score):
                best = found
            if best and best.score >= GOOD_ENOUGH:
                return best

        if canonical is None:
            canonical = self.canonical_for(track)
        if canonical is not None:
            for query in self.queries_for(track, canonical):
                if query in self.queries_for(track, None):
                    continue
                found = self._best_of(track, query, canonical)
                if found and (best is None or found.score > best.score):
                    best = found
                if best and best.score >= GOOD_ENOUGH:
                    return best

        if best is None:
            raise MatchError(f"no YouTube results for {track.artist_label} - {track.name}")
        if best.score < self.config.min_score:
            raise MatchError(
                f"best candidate for {track.artist_label} - {track.name} scored "
                f"{best.score:.2f} (minimum {self.config.min_score:.2f}): {best.candidate.title!r}"
            )
        return best

    # ----------------------------------------------------------------- cache
    def find(self, track: Track) -> Match:
        """Cached variant of :meth:`match`."""
        with self._lock:
            memo = self._memo.get(track.id)
            if memo is not None:
                return memo

            stored = self.cache.get(f"match:{track.id}", ttl=30 * 24 * 3600)
            if stored:
                candidate = Candidate(
                    video_id=stored["video_id"],
                    title=stored.get("title", ""),
                    duration=stored.get("duration"),
                    uploader=stored.get("uploader", ""),
                    channel=stored.get("channel", ""),
                )
                match = Match(
                    track=track,
                    candidate=candidate,
                    score=float(stored.get("score", 0.0)),
                    query=stored.get("query", ""),
                    canonical_source=stored.get("canonical_source", ""),
                )
                self._memo[track.id] = match
                return match

            match = self.match(track)
            self.cache.set(
                f"match:{track.id}",
                {
                    "video_id": match.video_id,
                    "title": match.candidate.title,
                    "duration": match.candidate.duration,
                    "uploader": match.candidate.uploader,
                    "channel": match.candidate.channel,
                    "score": match.score,
                    "query": match.query,
                    "canonical_source": match.canonical_source,
                },
                ttl=30 * 24 * 3600,
            )
            self._memo[track.id] = match
            return match

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass

"""The public facade - the surface a bot or another program should use.

>>> from spoti_cl import SpotiCL
>>> app = SpotiCL()
>>> tracks = app.tracks("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from collections.abc import Iterator

import httpx

from .audio.download import DownloadOptions, DownloadOutcome, download_many
from .audio.stream import StreamInfo, iter_audio
from .cache import Cache
from .config import Config
from .match.engine import Match, MatchError, Matcher
from .models import Collection, Track
from .spotify.client import SpotifyClient
from .spotify.resolve import Resolver
from .spotify.session import SpotifySession
from .urls import SpotifyLinkError, SpotifyRef, parse_link


class SpotiCL:
    """One object that owns every moving part of the tool."""

    def __init__(
        self,
        config: Config | None = None,
        cache: Cache | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self.config = config or Config.load()
        self.cache = cache or Cache()
        self.http = http or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": self.config.user_agent},
        )
        self.session = SpotifySession(self.http, self.cache, self.config.user_agent)
        self.client = SpotifyClient(self.session)
        self.resolver = Resolver(self.client)
        self.matcher = Matcher(self.config, self.cache, self.http)

    # ------------------------------------------------------------- resolving
    def resolve(self, link: str | SpotifyRef) -> Track | Collection:
        """Resolve a Spotify link into a track or a collection."""
        ref = link if isinstance(link, SpotifyRef) else parse_link(link)
        return self.resolver.resolve(ref)

    def tracks(self, link: str | SpotifyRef) -> list[Track]:
        """Return the tracks behind any Spotify link."""
        resolved = self.resolve(link)
        if isinstance(resolved, Track):
            return [resolved]
        return resolved.tracks

    def search(self, query: str, limit: int = 10) -> list[Track]:
        """Search the Spotify catalogue."""
        return self.resolver.search_tracks(query, limit)

    def search_playlists(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the Spotify catalogue for playlists."""
        return self.resolver.search_playlists(query, limit)

    # -------------------------------------------------------------- matching
    def match(self, track: Track) -> Match:
        """Find the best YouTube source for a track."""
        return self.matcher.find(track)

    def match_all(self, tracks: list[Track]) -> list[Match]:
        """Match a batch of tracks, skipping the ones that cannot be matched."""
        matches: list[Match] = []
        for track in tracks:
            try:
                matches.append(self.matcher.find(track))
            except MatchError:
                continue
        return matches

    # ------------------------------------------------------------ downloading
    def download(
        self,
        link: str | SpotifyRef,
        output_dir: str | Path = "downloads",
        *,
        fmt: str | None = None,
        quality: int | None = None,
        workers: int | None = None,
        overwrite: bool = False,
        limit: int | None = None,
        on_result=None,
    ) -> list[DownloadOutcome]:
        """Resolve, match and download a link."""
        tracks = self.tracks(link)
        if limit is not None:
            tracks = tracks[:limit]

        options = DownloadOptions(
            output_dir=Path(output_dir),
            fmt=fmt or self.config.format,
            quality=quality or self.config.quality,
            embed_cover=self.config.embed_cover,
            embed_metadata=self.config.embed_metadata,
            overwrite=overwrite,
            cookie_file=self.config.cookie_file,
            proxy=self.config.proxy,
            timeout=self.config.match_timeout,
        )

        matches: list[Match] = []
        for track in tracks:
            try:
                matches.append(self.matcher.find(track))
            except MatchError:
                continue

        return download_many(
            matches,
            options,
            workers=workers or self.config.threads,
            on_result=on_result,
            http=self.http,
        )

    # -------------------------------------------------------------- streaming
    def stream_info(self, link: str | SpotifyRef) -> StreamInfo:
        """Resolve the direct media URL for the first track of a link."""
        tracks = self.tracks(link)
        if not tracks:
            raise RuntimeError("nothing to stream")
        match = self.matcher.find(tracks[0])
        from .audio.stream import extract_media_url

        return extract_media_url(match, self.config)

    def stream(self, link: str | SpotifyRef) -> Iterator[bytes]:
        """Yield the audio bytes of the first track of a link."""
        tracks = self.tracks(link)
        if not tracks:
            raise RuntimeError("nothing to stream")
        match = self.matcher.find(tracks[0])
        return iter_audio(match, self.config, http=self.http)

    # ----------------------------------------------------------------- misc
    def close(self) -> None:
        try:
            self.matcher.close()
        finally:
            try:
                self.http.close()
            except Exception:
                pass

    def __enter__(self) -> SpotiCL:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = [
    "SpotiCL",
    "Match",
    "MatchError",
    "SpotifyLinkError",
    "DownloadOutcome",
]

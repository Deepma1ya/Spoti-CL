"""Data model shared by the resolver, the matcher and the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Artist:
    name: str
    id: str | None = None
    uri: str | None = None


@dataclass(slots=True)
class Track:
    """A single recording as Spotify describes it."""

    id: str
    name: str
    artists: list[Artist] = field(default_factory=list)
    album: str = ""
    album_id: str = ""
    duration_ms: int = 0
    isrc: str = ""
    track_number: int = 0
    disc_number: int = 0
    explicit: bool = False
    cover_url: str = ""
    release_date: str = ""
    url: str = ""
    popularity: int = 0

    @property
    def artist_names(self) -> list[str]:
        return [a.name for a in self.artists if a.name]

    @property
    def primary_artist(self) -> str:
        return self.artist_names[0] if self.artist_names else ""

    @property
    def artist_label(self) -> str:
        return ", ".join(self.artist_names)

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "artists": [a.name for a in self.artists],
            "album": self.album,
            "album_id": self.album_id,
            "duration_ms": self.duration_ms,
            "isrc": self.isrc,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "explicit": self.explicit,
            "cover_url": self.cover_url,
            "release_date": self.release_date,
            "url": self.url or f"https://open.spotify.com/track/{self.id}",
        }


@dataclass(slots=True)
class Collection:
    """A playlist, an album or an artist top-tracks bundle."""

    kind: str
    id: str
    name: str
    tracks: list[Track] = field(default_factory=list)
    owner: str = ""
    description: str = ""
    cover_url: str = ""
    url: str = ""
    total_tracks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "description": self.description,
            "cover_url": self.cover_url,
            "url": self.url,
            "total_tracks": self.total_tracks or len(self.tracks),
            "tracks": [t.to_dict() for t in self.tracks],
        }


@dataclass(slots=True)
class Candidate:
    """A YouTube video that might carry the recording we are looking for."""

    video_id: str
    title: str
    duration: float | None = None
    uploader: str = ""
    channel: str = ""
    view_count: int = 0
    url: str = ""

    def __post_init__(self) -> None:
        if not self.url and self.video_id:
            self.url = f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def source(self) -> str:
        return f"{self.uploader} {self.channel}".strip()


@dataclass(slots=True)
class Match:
    """The chosen source for a track, plus the reasoning behind it."""

    track: Track
    candidate: Candidate
    score: float
    query: str = ""
    canonical_source: str = ""

    @property
    def video_id(self) -> str:
        return self.candidate.video_id

    @property
    def url(self) -> str:
        return self.candidate.url

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track.to_dict(),
            "video_id": self.video_id,
            "url": self.url,
            "source_title": self.candidate.title,
            "source_uploader": self.candidate.uploader,
            "source_duration": self.candidate.duration,
            "score": round(self.score, 4),
            "query": self.query,
            "canonical_source": self.canonical_source,
        }

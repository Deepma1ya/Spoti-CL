"""Turn raw Spotify payloads into the models used across the tool."""

from __future__ import annotations

from typing import Any

from ..models import Artist, Collection, Track
from ..urls import SpotifyRef
from .client import SpotifyApiError, SpotifyClient
from .session import SpotifyAuthError


def _best_image(sources: Any) -> str:
    """Pick the largest image from a Spotify image list."""
    if not isinstance(sources, list):
        return ""
    best_url = ""
    best_area = -1
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url") or ""
        width = int(source.get("width") or 0)
        height = int(source.get("height") or 0)
        area = width * height
        if url and area > best_area:
            best_area = area
            best_url = url
    return best_url


def _uri_id(uri: str) -> str:
    return uri.rsplit(":", 1)[-1] if uri else ""


def _artists_from_items(items: Any) -> list[Artist]:
    artists: list[Artist] = []
    if isinstance(items, dict):
        items = items.get("items") or []
    if not isinstance(items, list):
        return artists
    for item in items:
        if not isinstance(item, dict):
            continue
        profile = item.get("profile") or {}
        name = profile.get("name") or item.get("name") or ""
        if not name:
            continue
        uri = item.get("uri") or ""
        artists.append(Artist(name=name, id=_uri_id(uri) or None, uri=uri or None))
    return artists


def track_from_web_api(payload: dict[str, Any]) -> Track:
    """Build a :class:`Track` from a ``/v1/tracks/{id}`` payload."""
    artists = [
        Artist(
            name=entry.get("name", ""),
            id=entry.get("id"),
            uri=entry.get("uri"),
        )
        for entry in payload.get("artists") or []
    ]
    album = payload.get("album") or {}
    images = album.get("images") or []
    return Track(
        id=payload.get("id", ""),
        name=payload.get("name", ""),
        artists=artists,
        album=album.get("name", ""),
        album_id=album.get("id", ""),
        duration_ms=int(payload.get("duration_ms") or 0),
        isrc=str((payload.get("external_ids") or {}).get("isrc") or ""),
        track_number=int((album.get("tracks") or {}).get("items") and 0 or 0),
        disc_number=int(payload.get("disc_number") or 0),
        explicit=bool(payload.get("explicit")),
        cover_url=_best_image(images),
        release_date=album.get("release_date", ""),
        url=f"https://open.spotify.com/track/{payload.get('id', '')}",
        popularity=int(payload.get("popularity") or 0),
    )


def _playlist_cover(playlist: dict[str, Any]) -> str:
    """Dig the playlist artwork out of wherever Spotify put it."""
    visual = playlist.get("visualIdentity") or {}
    cover = _best_image((visual.get("image") or {}).get("sources"))
    if cover:
        return cover

    attributes: dict[str, str] = {}
    for attribute in playlist.get("attributes") or []:
        if isinstance(attribute, dict) and attribute.get("key"):
            attributes[str(attribute["key"])] = str(attribute.get("value") or "")
    if attributes.get("image_url"):
        return attributes["image_url"]
    if attributes.get("header_image_url_desktop"):
        return attributes["header_image_url_desktop"]

    for entry in (playlist.get("images") or {}).get("items") or []:
        if not isinstance(entry, dict):
            continue
        cover = _best_image(entry.get("sources") or [])
        if cover:
            return cover
    return ""


def track_from_track_union(union: dict[str, Any]) -> Track:
    """Build a :class:`Track` from a PathFinder ``trackUnion`` payload."""
    uri = union.get("uri") or ""
    album = union.get("albumOfTrack") or {}
    duration = (union.get("duration") or {}).get("totalMilliseconds") or 0
    artists = _artists_from_items(union.get("firstArtist") or {})
    artists += _artists_from_items(union.get("otherArtists") or {})
    return Track(
        id=_uri_id(uri) or str(union.get("id") or ""),
        name=union.get("name", ""),
        artists=artists,
        album=album.get("name", ""),
        album_id=_uri_id(album.get("uri", "")) or str(album.get("id") or ""),
        duration_ms=int(duration),
        track_number=int(union.get("trackNumber") or 0),
        explicit=(union.get("contentRating") or {}).get("label") == "EXPLICIT",
        cover_url=_best_image((album.get("coverArt") or {}).get("sources")),
        release_date=(album.get("date") or {}).get("isoString", "")[:10],
        url=f"https://open.spotify.com/track/{_uri_id(uri)}",
    )


def track_from_playlist_item(item: dict[str, Any]) -> Track | None:
    """Build a :class:`Track` from one entry of a PathFinder playlist page."""
    data = (item.get("itemV2") or {}).get("data")
    if not isinstance(data, dict):
        v3 = ((item.get("itemV3") or {}).get("data")) or {}
        identity = v3.get("identityTrait") or {}
        contributors = identity.get("contributors") or {}
        parent = identity.get("contentHierarchyParent") or {}
        parent_identity = parent.get("identityTrait") or {}
        uri = v3.get("uri") or ""
        duration = ((v3.get("consumptionExperienceTrait") or {}).get("duration") or {}).get(
            "seconds", 0
        )
        artists = [
            Artist(name=entry.get("name", ""), id=_uri_id(entry.get("uri", "")) or None)
            for entry in (contributors.get("items") or [])
        ]
        if not uri:
            return None
        return Track(
            id=_uri_id(uri),
            name=identity.get("name", ""),
            artists=artists,
            album=parent_identity.get("name", ""),
            album_id=_uri_id(parent.get("uri", "")),
            duration_ms=int(duration or 0) * 1000,
            url=f"https://open.spotify.com/track/{_uri_id(uri)}",
        )

    if data.get("__typename") not in (None, "Track"):
        # Episodes and podcasts live in the same list - skip them.
        if data.get("__typename") != "Track":
            return None

    uri = data.get("uri") or ""
    album_of_track = data.get("albumOfTrack") or {}
    duration = (data.get("trackDuration") or {}).get("totalMilliseconds") or 0
    return Track(
        id=_uri_id(uri),
        name=data.get("name", ""),
        artists=_artists_from_items(data.get("artists") or {}),
        album=album_of_track.get("name", ""),
        album_id=_uri_id(album_of_track.get("uri", "")),
        duration_ms=int(duration),
        track_number=int(data.get("trackNumber") or 0),
        disc_number=int(data.get("discNumber") or 0),
        explicit=(data.get("contentRating") or {}).get("label") == "EXPLICIT",
        cover_url=_best_image(album_of_track.get("coverArt", {}).get("sources")),
        release_date=(album_of_track.get("date") or {}).get("isoString", "")[:10],
        url=f"https://open.spotify.com/track/{_uri_id(uri)}",
    )


def track_from_album_item(item: dict[str, Any]) -> Track | None:
    """Build a :class:`Track` from one entry of a PathFinder album page."""
    data = item.get("track") or item
    uri = data.get("uri") or ""
    if not uri:
        return None
    duration = (data.get("duration") or {}).get("totalMilliseconds") or 0
    return Track(
        id=_uri_id(uri),
        name=data.get("name", ""),
        artists=_artists_from_items(data.get("artists") or {}),
        duration_ms=int(duration),
        track_number=int(data.get("trackNumber") or 0),
        disc_number=int(data.get("discNumber") or 0),
        url=f"https://open.spotify.com/track/{_uri_id(uri)}",
    )


def track_from_embed(entity: dict[str, Any]) -> Track | None:
    """Build a :class:`Track` from an embed page track entry."""
    uri = entity.get("uri") or ""
    if not uri:
        return None
    return Track(
        id=_uri_id(uri),
        name=entity.get("title") or entity.get("name") or "",
        artists=[Artist(name=entity.get("subtitle", ""))] if entity.get("subtitle") else [],
        duration_ms=int(entity.get("duration") or 0),
        url=f"https://open.spotify.com/track/{_uri_id(uri)}",
    )


class Resolver:
    """High level resolution of a :class:`SpotifyRef` into tracks."""

    def __init__(self, client: SpotifyClient) -> None:
        self.client = client

    def resolve(self, ref: SpotifyRef, with_isrc: bool = False) -> Track | Collection:
        """Resolve any supported reference.

        A bare id carries no kind, so a track is assumed - but when that id
        turns out to be a playlist, album or artist, the other resolvers are
        tried before giving up.
        """
        if ref.kind == "track":
            try:
                union = self.client.get_track(ref.id)
            except (SpotifyApiError, SpotifyAuthError) as exc:
                union = {}
                track_error: Exception | None = exc
            else:
                track_error = None

            if union.get("uri") and union.get("name"):
                track = track_from_track_union(union)
                if with_isrc and not track.isrc:
                    track.isrc = self.client.track_isrc(ref.id)
                return track

            # The id was not a track after all - try the other kinds, but only
            # accept a result that actually carries something.
            for resolver in (self.resolve_playlist, self.resolve_album, self.resolve_artist):
                try:
                    candidate = resolver(ref.id)
                except Exception:
                    continue
                if isinstance(candidate, Collection) and candidate.tracks:
                    return candidate
            if track_error is not None:
                raise track_error
            raise ValueError(f"{ref.id} is not a track, playlist, album or artist")

        if ref.kind == "album":
            return self.resolve_album(ref.id)
        if ref.kind == "playlist":
            return self.resolve_playlist(ref.id)
        if ref.kind == "artist":
            return self.resolve_artist(ref.id)
        raise ValueError(f"cannot resolve Spotify entity of kind {ref.kind!r}")

    def resolve_track(self, track_id: str, with_isrc: bool = True) -> Track:
        """Resolve one track through PathFinder."""
        union = self.client.get_track(track_id)
        track = track_from_track_union(union)
        if with_isrc and not track.isrc:
            track.isrc = self.client.track_isrc(track_id)
        return track

    def resolve_album(self, album_id: str) -> Collection:
        """Resolve every track of an album."""
        album = self.client.get_album(album_id)
        tracks = [
            track
            for track in (
                track_from_album_item(item) for item in (album.get("tracksV2") or {}).get("items", [])
            )
            if track is not None
        ]
        for track in tracks:
            track.album = album.get("name", "") or track.album
            track.album_id = album_id
            track.cover_url = track.cover_url or _best_image(
                (album.get("coverArt") or {}).get("sources")
            )
            track.release_date = track.release_date or (album.get("date") or {}).get(
                "isoString", ""
            )[:10]
        artists = _artists_from_items(album.get("artists") or {})
        return Collection(
            kind="album",
            id=album_id,
            name=album.get("name", ""),
            tracks=tracks,
            owner=artists[0].name if artists else "",
            description=(album.get("copyright") or {}).get("text", "")
            if isinstance(album.get("copyright"), dict)
            else str(album.get("copyright") or ""),
            cover_url=_best_image((album.get("coverArt") or {}).get("sources")),
            url=f"https://open.spotify.com/album/{album_id}",
            total_tracks=len(tracks),
        )

    def resolve_playlist(self, playlist_id: str) -> Collection:
        """Resolve every track of a playlist."""
        playlist = self.client.get_playlist(playlist_id)
        content = playlist.get("content") or {}
        tracks = [
            track
            for track in (
                track_from_playlist_item(item) for item in content.get("items") or []
            )
            if track is not None
        ]
        owner = ((playlist.get("ownerV2") or {}).get("data") or {})
        return Collection(
            kind="playlist",
            id=playlist_id,
            name=playlist.get("name", ""),
            tracks=tracks,
            owner=owner.get("name", ""),
            description=playlist.get("description", ""),
            cover_url=_playlist_cover(playlist),
            url=f"https://open.spotify.com/playlist/{playlist_id}",
            total_tracks=int(content.get("totalCount") or len(tracks)),
        )

    def resolve_artist(self, artist_id: str) -> Collection:
        """Resolve the top tracks of an artist."""
        entity = self.client.get_artist_top_tracks(artist_id)
        tracks = [
            track
            for track in (
                track_from_embed(item) for item in entity.get("trackList") or []
            )
            if track is not None
        ]
        return Collection(
            kind="artist",
            id=artist_id,
            name=entity.get("name", ""),
            tracks=tracks,
            description=entity.get("subtitle", ""),
            cover_url=_best_image(
                ((entity.get("visualIdentity") or {}).get("image") or {}).get("sources")
            ),
            url=f"https://open.spotify.com/artist/{artist_id}",
            total_tracks=len(tracks),
        )

    def search_tracks(self, query: str, limit: int = 10) -> list[Track]:
        """Search the Spotify catalogue for tracks."""
        payload = self.client.search(query, "track", limit)
        tracks: list[Track] = []
        for entry in (payload.get("tracks") or {}).get("items") or []:
            track = track_from_web_api(entry)
            if track.id:
                tracks.append(track)
        return tracks

    def search_playlists(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the Spotify catalogue for playlists."""
        payload = self.client.search(query, "playlist", limit)
        found: list[dict[str, Any]] = []
        for entry in (payload.get("playlists") or {}).get("items") or []:
            if not entry or not entry.get("id"):
                continue
            found.append(
                {
                    "id": entry.get("id", ""),
                    "name": entry.get("name", ""),
                    "owner": (entry.get("owner") or {}).get("display_name", ""),
                    "total_tracks": (entry.get("tracks") or {}).get("total", 0),
                    "url": f"https://open.spotify.com/playlist/{entry.get('id', '')}",
                }
            )
        return found

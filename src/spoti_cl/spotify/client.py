"""Thin client over the anonymous Spotify endpoints.

Two APIs are used side by side:

* the public Web API (``api.spotify.com/v1``) with an anonymous embed token -
  it is the only place that exposes the ISRC of a recording;
* the PathFinder GraphQL gateway (``api-partner.spotify.com``) - it serves
  complete playlist and album contents, which the Web API hides from
  anonymous callers.
"""

from __future__ import annotations

from typing import Any

import httpx

from .session import SpotifySession

PATHFINDER_URL = "https://api-partner.spotify.com/pathfinder/v1/query"
WEB_API = "https://api.spotify.com/v1"

PLAYLIST_PAGE_SIZE = 100
ALBUM_PAGE_SIZE = 50


class SpotifyApiError(RuntimeError):
    """Raised when Spotify answers with an error payload."""


class SpotifyClient:
    """Reads Spotify metadata with an anonymous session."""

    def __init__(self, session: SpotifySession) -> None:
        self.session = session

    # --------------------------------------------------------------- plumbing
    def _headers(self, token: str) -> dict[str, str]:
        return {
            "User-Agent": self.session.user_agent,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def pathfinder(
        self,
        operation: str,
        variables: dict[str, Any],
        token: str | None = None,
        *,
        refresh_hashes: bool = False,
    ) -> dict[str, Any]:
        """Run a PathFinder GraphQL operation and return its ``data`` block."""
        import json

        bearer = token or self.session.access_token()
        digest = self.session.hash_for(operation, refresh=refresh_hashes)
        extensions = json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": digest}}, separators=(",", ":")
        )
        params = {
            "operationName": operation,
            "variables": json.dumps(variables, separators=(",", ":")),
            "extensions": extensions,
        }
        response = self.session.http.get(
            PATHFINDER_URL, params=params, headers=self._headers(bearer)
        )
        if response.status_code == 400 and "PersistedQueryNotFound" in response.text:
            # The bundle we cached has been rotated upstream - refresh and retry.
            digest = self.session.hash_for(operation, refresh=True)
            extensions = json.dumps(
                {"persistedQuery": {"version": 1, "sha256Hash": digest}},
                separators=(",", ":"),
            )
            params["extensions"] = extensions
            response = self.session.http.get(
                PATHFINDER_URL, params=params, headers=self._headers(bearer)
            )
        if response.status_code >= 400:
            raise SpotifyApiError(
                f"pathfinder {operation} failed with HTTP {response.status_code}: {response.text[:300]}"
            )
        payload = response.json()
        errors = payload.get("errors")
        if errors:
            message = errors[0].get("message", "unknown error")
            raise SpotifyApiError(f"pathfinder {operation} failed: {message}")
        return payload.get("data") or {}

    def web_api(self, path: str, token: str | None = None) -> dict[str, Any]:
        """GET a path on the public Web API, retrying through the throttles."""
        import time

        bearer = token or self.session.access_token()
        last_error = ""
        for attempt in range(3):
            try:
                response = self.session.http.get(
                    f"{WEB_API}{path}", headers=self._headers(bearer)
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                time.sleep(1.0 * (attempt + 1))
                continue
            if response.status_code == 200:
                return response.json()
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            time.sleep(1.0 * (attempt + 1))
        raise SpotifyApiError(f"web api {path} failed - {last_error}")

    # ---------------------------------------------------------------- tracks
    def get_track(self, track_id: str) -> dict[str, Any]:
        """Return the PathFinder payload for a single track.

        The Web API is deliberately not used here: anonymous tokens get a
        429 from ``/v1/tracks/{id}`` while PathFinder keeps serving.
        """
        token = self.session.token_for(track_id, "track")
        data = self.pathfinder(
            "getTrack", {"uri": f"spotify:track:{track_id}"}, token
        )
        return data.get("trackUnion") or {}

    def track_isrc(self, track_id: str) -> str:
        """Return the ISRC of a track, or an empty string when unavailable.

        The Web API throttles anonymous callers hard, so this is best effort -
        the matcher falls back to a title and artist lookup when it fails.
        """
        token = self.session.token_for(track_id, "track")
        try:
            payload = self.web_api(f"/tracks/{track_id}", token)
        except (SpotifyApiError, httpx.HTTPError):
            return ""
        return str((payload.get("external_ids") or {}).get("isrc") or "")

    # -------------------------------------------------------------- playlists
    def get_playlist(self, playlist_id: str, token: str | None = None) -> dict[str, Any]:
        """Return the full PathFinder payload for a playlist."""
        bearer = token or self.session.token_for(playlist_id, "playlist")
        variables = {
            "uri": f"spotify:playlist:{playlist_id}",
            "offset": 0,
            "limit": PLAYLIST_PAGE_SIZE,
            "enableWatchFeedEntrypoint": False,
        }
        data = self.pathfinder("fetchPlaylist", variables, bearer)
        playlist = data.get("playlistV2") or {}
        content = playlist.get("content") or {}
        items = list(content.get("items") or [])
        if not playlist.get("name") and not items:
            raise SpotifyApiError(f"{playlist_id} is not a playlist")
        total = int(content.get("totalCount") or len(items))

        # Page through the rest when the playlist is longer than one page.
        offset = PLAYLIST_PAGE_SIZE
        while len(items) < total and offset < total:
            variables["offset"] = offset
            variables["limit"] = PLAYLIST_PAGE_SIZE
            page = self.pathfinder("fetchPlaylist", variables, bearer)
            page_content = ((page.get("playlistV2") or {}).get("content")) or {}
            page_items = list(page_content.get("items") or [])
            if not page_items:
                break
            items.extend(page_items)
            offset += len(page_items)

        content["items"] = items
        playlist["content"] = content
        return playlist

    # ---------------------------------------------------------------- albums
    def get_album(self, album_id: str, token: str | None = None) -> dict[str, Any]:
        """Return the full PathFinder payload for an album."""
        bearer = token or self.session.token_for(album_id, "album")
        variables = {
            "uri": f"spotify:album:{album_id}",
            "locale": "",
            "offset": 0,
            "limit": ALBUM_PAGE_SIZE,
        }
        data = self.pathfinder("getAlbum", variables, bearer)
        album = data.get("albumUnion") or {}
        tracks = (album.get("tracksV2") or {})
        items = list(tracks.get("items") or [])
        total = int(tracks.get("totalCount") or len(items))
        offset = ALBUM_PAGE_SIZE
        while len(items) < total and offset < total:
            variables["offset"] = offset
            page = self.pathfinder("getAlbum", variables, bearer)
            page_tracks = ((page.get("albumUnion") or {}).get("tracksV2")) or {}
            page_items = list(page_tracks.get("items") or [])
            if not page_items:
                break
            items.extend(page_items)
            offset += len(page_items)
        tracks["items"] = items
        album["tracksV2"] = tracks
        return album

    # --------------------------------------------------------------- artists
    def search(self, query: str, kind: str = "track", limit: int = 10) -> dict[str, Any]:
        """Search the Spotify catalogue through the public Web API."""
        from urllib.parse import quote

        token = self.session.access_token()
        return self.web_api(
            f"/search?q={quote(query)}&type={kind}&limit={limit}", token
        )

    def get_artist_overview(self, artist_id: str, token: str | None = None) -> dict[str, Any]:
        """Return the PathFinder payload describing an artist."""
        bearer = token or self.session.token_for(artist_id, "artist")
        variables = {"uri": f"spotify:artist:{artist_id}", "locale": ""}
        data = self.pathfinder("queryArtistOverview", variables, bearer)
        return data.get("artistUnion") or data.get("artist") or {}

    def get_artist_top_tracks(self, artist_id: str) -> dict[str, Any]:
        """Return the embed payload of an artist page (top tracks)."""
        state = self.session._fetch_embed_state(artist_id, "artist")
        page_props = (state.get("props") or {}).get("pageProps") or {}
        embedded = (page_props.get("state") or {}).get("data") or {}
        return embedded.get("entity") or {}

"""Anonymous Spotify session handling.

Two moving parts live here:

``access_token``
    The web player hands out a short lived bearer token to anybody that loads
    an embed page. No client id, no OAuth code, no user credentials.

``persisted hashes``
    Spotify's PathFinder GraphQL gateway only accepts queries that are
    registered by hash. The hashes are published inside the public web player
    bundle, so they are extracted at runtime instead of being hardcoded - a
    rotated upstream bundle never breaks the tool.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any

import httpx

from ..cache import Cache

EMBED_TRACK_URL = "https://open.spotify.com/embed/track/{id}"

#: A well known track used to mint a session token when we do not yet have an
#: entity of our own to load (plain text search for example).
BOOTSTRAP_TRACK_ID = "4cOdK2wGLETKBW3PvgPWqT"

TOKEN_TTL = 30 * 60
HASH_TTL = 6 * 3600

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)
_OP_HASH_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_\.]*)","(query|mutation)","([0-9a-f]{64})"')
_SCRIPT_SRC_RE = re.compile(r'src="(https://[^"]+\.js)"')

#: Hashes as of the last release. They are only a fallback: the live table is
#: refreshed from the web player bundle whenever it is stale or a query is
#: rejected with ``PersistedQueryNotFound``.
FALLBACK_HASHES: dict[str, str] = {
    "fetchPlaylist": "21ea11a6ac75a5f3e01fd365d29c18e0a4a8b7dc09f89bbb5d73910190c6acaf",
    "fetchPlaylistContents": "21ea11a6ac75a5f3e01fd365d29c18e0a4a8b7dc09f89bbb5d73910190c6acaf",
    "fetchPlaylistMetadata": "21ea11a6ac75a5f3e01fd365d29c18e0a4a8b7dc09f89bbb5d73910190c6acaf",
    "getTrack": "e7b1bf4e95cb3d733d48b442f93006e9712fd504e8b88d7a82e6e3bac9306a6b",
    "getTrackName": "3dee761788854e8dd9239e13ce0d712da031fb8c2036f096a1c765062b410660",
    "getAlbum": "0b6ce3511e1b02e4a40fa95440f992acbe85080eb308af9194322d708fc1914f",
    "queryAlbumTracks": "0b6ce3511e1b02e4a40fa95440f992acbe85080eb308af9194322d708fc1914f",
    "getAlbumNameAndTracks": "8628ad33de3267d7bef516c76a746979a5f98891a2c9eaff3dfec828abdcd983",
    "getArtistNameAndTracks": "0adaf1a1a8a94c7ed095639c4d9456d2b1cfac16ac511d5dd2b01b6dd89f748a",
    "queryArtistOverview": "eafb1620d783ece118e72fbfede2b0064483e029d3c1aafafa1c2de0e25a89e7",
    "queryTrackArtists": "ee2b038198f5e62c679c3996584d9249bbee55fe69fc212271c56492a022c798",
    "queryAlbumTrackUris": "a2a17981f8439ca1798f56260277d9d7800ec0ca7040053b564e0f975d8aa344",
    "queryShowMetadataV2": "b475447846f37cc426add800b995a7859c169c53c72b62de6338c0c40a5dacea",
    "queryPodcastEpisodes": "3539d746cf882f3909660de40b4ef472b3f5893a0761d617c282541de5d412c5",
    "getEpisodeName": "508f9db2e7dc340c338950dc67a6045ee1406703646f23b760986fa689c239b1",
    "getEpisodeOrChapter": "5f77db47e5a2ce6680330bb61317aa09e17ddd1d189513cb218e7cd3e43288be",
    "getPodcastOrBookName": "631676b4cf1eb7c93d1133e3f1f17e5bfe8d6a5e2fb9560148bac61f1531f267",
    "searchSuggestions": "f244254b94c0e824d458ac216e0f8406a73f2f69a9ff52831a2f78fa774ff6ce",
    "assistedCurationSearch": "f78953bf9207d73493c27284103f5aeb6e728876d5793851bf79bc706127ff70",
    "assistedCurationSearchAlbum": "e33489c81fdab1986d8b785fb9bf13993a2d5ff171190c575963f97e525870fe",
    "assistedCurationSearchArtist": "a562324cea8976b4d51f08cee971bb180ce9279c947d27e0814675220b160cf7",
}


class SpotifyAuthError(RuntimeError):
    """Raised when an anonymous session cannot be established."""


class SpotifySession:
    """Holds the anonymous bearer token and the GraphQL hash table."""

    def __init__(
        self,
        http: httpx.Client,
        cache: Cache,
        user_agent: str = "",
    ) -> None:
        self.http = http
        self.cache = cache
        self.user_agent = user_agent
        self._token: str | None = None
        self._hashes: dict[str, str] | None = None
        self._lock = threading.RLock()

    # --------------------------------------------------------------- helpers
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if extra:
            headers.update(extra)
        return headers

    def _fetch_embed_state(self, entity_id: str, kind: str = "track") -> dict[str, Any]:
        url = f"https://open.spotify.com/embed/{kind}/{entity_id}"
        response = self.http.get(url, headers=self._headers())
        response.raise_for_status()
        match = _NEXT_DATA_RE.search(response.text)
        if not match:
            raise SpotifyAuthError(f"no embed payload found for {kind}/{entity_id}")
        return json.loads(match.group(1))

    # ----------------------------------------------------------------- token
    def access_token(self, refresh: bool = False) -> str:
        """Return an anonymous bearer token, minting a new one when needed."""
        with self._lock:
            if self._token and not refresh:
                return self._token

            cached = self.cache.get("session_token", ttl=TOKEN_TTL)
            if cached and not refresh:
                self._token = str(cached)
                return self._token

            state = self._fetch_embed_state(BOOTSTRAP_TRACK_ID, "track")
            token = self._extract_token(state)
            self._token = token
            self.cache.set("session_token", token, ttl=TOKEN_TTL)
            return token

    def token_for(self, entity_id: str, kind: str = "track") -> str:
        """Return a token minted from a specific embed page.

        Embed tokens are scoped to the page that issued them, so using the
        entity's own page keeps us inside the free tier of the API.
        """
        with self._lock:
            cached = self.cache.get(f"session_token:{kind}:{entity_id}", ttl=TOKEN_TTL)
            if cached:
                return str(cached)
            state = self._fetch_embed_state(entity_id, kind)
            token = self._extract_token(state)
            self.cache.set(f"session_token:{kind}:{entity_id}", token, ttl=TOKEN_TTL)
            return token

    @staticmethod
    def _extract_token(state: dict[str, Any]) -> str:
        try:
            session = state["props"]["pageProps"]["state"]["settings"]["session"]
            token = session.get("accessToken")
            if token:
                return str(token)
        except (KeyError, TypeError):
            pass
        raise SpotifyAuthError("embed page did not contain an access token")

    # ---------------------------------------------------------------- hashes
    def hashes(self, refresh: bool = False) -> dict[str, str]:
        """Return the persisted query hash table."""
        with self._lock:
            if self._hashes and not refresh:
                return self._hashes

            cached = self.cache.get("query_hashes", ttl=HASH_TTL)
            if cached and not refresh:
                self._hashes = {**FALLBACK_HASHES, **dict(cached)}
                return self._hashes

            try:
                live = self._discover_hashes()
            except (httpx.HTTPError, ValueError):
                live = {}
            merged = {**FALLBACK_HASHES, **live}
            self._hashes = merged
            if live:
                self.cache.set("query_hashes", live, ttl=HASH_TTL)
            return merged

    def _discover_hashes(self) -> dict[str, str]:
        """Pull the hash table out of the public web player bundle."""
        page = self.http.get("https://open.spotify.com/", headers=self._headers())
        page.raise_for_status()
        scripts = [m.group(1) for m in _SCRIPT_SRC_RE.finditer(page.text)]
        bundle = next((s for s in scripts if "web-player" in s and s.endswith(".js")), "")
        if not bundle:
            return {}

        hashes: dict[str, str] = {}
        bundle_text = self.http.get(bundle, headers=self._headers()).text
        for match in _OP_HASH_RE.finditer(bundle_text):
            name, _kind, digest = match.groups()
            hashes[name] = digest
        return hashes

    def hash_for(self, operation: str, refresh: bool = False) -> str:
        """Return the persisted query hash for ``operation``."""
        table = self.hashes(refresh=refresh)
        digest = table.get(operation)
        if not digest:
            table = self.hashes(refresh=True)
            digest = table.get(operation)
        if not digest:
            raise SpotifyAuthError(
                f"no persisted query hash known for {operation!r}; the web player bundle changed shape"
            )
        return digest

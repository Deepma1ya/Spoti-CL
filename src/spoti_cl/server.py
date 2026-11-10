"""A small HTTP service that exposes the tool to bots and other programs.

Endpoints
---------
``GET /health``              liveness probe
``GET /resolve?url=...``     JSON manifest of a track, album or playlist
``GET /search?q=...``        JSON list of Spotify tracks or playlists
``GET /audio?url=...``       the audio itself, streamed (Range aware)

The audio endpoint is the interesting one: a Discord bot can pipe it straight
into ffmpeg and into a voice channel without ever touching the file system.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .api import SpotiCL
from .audio.stream import extract_media_url
from .config import Config
from .match.engine import MatchError

VERSION = "0.1.0"


class _Handler(BaseHTTPRequestHandler):
    server_version = f"spoti-cl/{VERSION}"
    app: SpotiCL

    # --------------------------------------------------------------- helpers
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _query(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        return {key: values[0] for key, values in params.items() if values}

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    # ---------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/") or "/"
        params = self._query()
        try:
            if route in ("/", "/health"):
                self._json({"status": "ok", "version": VERSION})
            elif route == "/resolve":
                self._resolve(params)
            elif route == "/search":
                self._search(params)
            elif route == "/audio":
                self._audio(params)
            else:
                self._error(f"unknown endpoint {route!r}", HTTPStatus.NOT_FOUND)
        except MatchError as exc:
            self._error(str(exc), HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pragma: no cover - defensive
            self._error(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _resolve(self, params: dict[str, str]) -> None:
        url = params.get("url") or params.get("link") or ""
        if not url:
            self._error("missing url parameter")
            return
        resolved = self.app.resolve(url)
        payload = resolved.to_dict()
        payload["source"] = "spotify"
        self._json(payload)

    def _search(self, params: dict[str, str]) -> None:
        query = params.get("q") or params.get("query") or ""
        if not query:
            self._error("missing q parameter")
            return
        try:
            limit = int(params.get("limit", "10"))
        except ValueError:
            limit = 10

        kind = (params.get("type") or "track").lower()
        if kind == "playlist":
            results = self.app.search_playlists(query, limit)
            self._json({"query": query, "type": kind, "count": len(results), "playlists": results})
            return

        tracks = self.app.search(query, limit)
        self._json(
            {
                "query": query,
                "type": kind,
                "count": len(tracks),
                "tracks": [t.to_dict() for t in tracks],
            }
        )

    def _audio(self, params: dict[str, str]) -> None:
        url = params.get("url") or params.get("link") or ""
        if not url:
            self._error("missing url parameter")
            return

        tracks = self.app.tracks(url)
        if not tracks:
            self._error("no tracks found", HTTPStatus.NOT_FOUND)
            return

        track = tracks[0]
        match = self.app.matcher.find(track)
        info = extract_media_url(match, self.app.config)

        headers = {"User-Agent": self.app.config.user_agent}
        headers.update(info.headers)
        range_header = self.headers.get("Range")
        if range_header:
            headers["Range"] = range_header

        with self.app.http.stream("GET", info.media_url, headers=headers) as response:
            self.send_response(response.status_code)
            self.send_header(
                "Content-Type", response.headers.get("content-type", info.mime)
            )
            length = response.headers.get("content-length")
            if length:
                self.send_header("Content-Length", length)
            content_range = response.headers.get("content-range")
            if content_range:
                self.send_header("Content-Range", content_range)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Spotify-Id", track.id)
            self.send_header("X-Spotify-Title", _header(track.name))
            self.send_header("X-Spotify-Artist", _header(track.artist_label))
            self.send_header("X-Spotify-Album", _header(track.album))
            self.send_header("X-Spotify-Duration", str(int(track.duration_seconds)))
            self.send_header("X-Spotify-Cover", _header(track.cover_url))
            self.send_header("X-Spotify-Url", _header(track.url))
            self.send_header("X-Match-Score", f"{match.score:.3f}")
            self.send_header("X-Match-Id", match.video_id)
            if params.get("download"):
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{_header(track.name)}.mp3"',
                )
            self.end_headers()
            for chunk in response.iter_bytes(64 * 1024):
                self.wfile.write(chunk)


def _header(value: str) -> str:
    """Make a string safe for an HTTP header."""
    return value.encode("ascii", "ignore").decode("ascii").replace("\r", " ").replace("\n", " ")


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    config: Config | None = None,
    verbose: bool = False,
) -> None:
    """Run the HTTP service until interrupted."""
    app = SpotiCL(config=config)

    class Handler(_Handler):
        pass

    Handler.app = app  # type: ignore[attr-defined]

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.verbose = verbose  # type: ignore[attr-defined]
    bound_host, bound_port = httpd.server_address[:2]
    print(f"spoti-cl serving on http://{bound_host}:{bound_port}")
    print("  GET /health              liveness")
    print("  GET /resolve?url=...     json manifest")
    print("  GET /search?q=...        json search")
    print("  GET /audio?url=...       audio stream")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.shutdown()
        httpd.server_close()
        app.close()


class BackgroundServer:
    """Run the service in a thread - handy for tests and for bots."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, config: Config | None = None):
        self.app = SpotiCL(config=config)

        class Handler(_Handler):
            pass

        Handler.app = self.app  # type: ignore[attr-defined]
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.httpd.verbose = False  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> BackgroundServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.close()

    def __enter__(self) -> BackgroundServer:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

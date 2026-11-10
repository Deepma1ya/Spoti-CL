"""Streaming resolved audio straight to a pipe or an HTTP response."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Iterator

import httpx

from ..config import Config
from ..models import Match

MIME_BY_EXT = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "aac": "audio/aac",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "flac": "audio/flac",
    "wav": "audio/wav",
}

CHUNK_SIZE = 64 * 1024


@dataclass(slots=True)
class StreamInfo:
    """Everything a consumer needs to know about a stream."""

    media_url: str
    extension: str = "m4a"
    mime: str = "audio/mp4"
    content_length: int = 0
    headers: dict[str, str] = None  # type: ignore[assignment]
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0
    cover_url: str = ""
    spotify_id: str = ""

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}


def _build_ytdlp_options(config: Config) -> dict[str, Any]:
    from ..match.candidates import build_options

    options = build_options(
        timeout=config.match_timeout,
        cookie_file=config.cookie_file,
        proxy=config.proxy,
        extra={
            "skip_download": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "format_sort": ["abr", "asr", "size"],
        },
    )
    return options


def extract_media_url(match: Match, config: Config) -> StreamInfo:
    """Resolve the direct media URL for a matched video."""
    import yt_dlp

    options = _build_ytdlp_options(config)
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(match.url, download=False)

    if not info:
        raise RuntimeError(f"yt-dlp could not resolve {match.url}")

    media_url = info.get("url") or ""
    if not media_url:
        raise RuntimeError(f"no direct media URL for {match.url}")

    extension = (info.get("ext") or "m4a").lower()
    track = match.track
    return StreamInfo(
        media_url=media_url,
        extension=extension,
        mime=MIME_BY_EXT.get(extension, "application/octet-stream"),
        content_length=int(info.get("filesize") or info.get("filesize_approx") or 0),
        headers=dict(info.get("http_headers") or {}),
        title=track.name,
        artist=track.artist_label,
        album=track.album,
        duration=track.duration_seconds,
        cover_url=track.cover_url,
        spotify_id=track.id,
    )


def iter_audio(
    match: Match,
    config: Config,
    http: httpx.Client | None = None,
    info: StreamInfo | None = None,
) -> Iterator[bytes]:
    """Yield the audio payload of a matched track in chunks."""
    stream = info or extract_media_url(match, config)
    client = http or httpx.Client(timeout=60.0, follow_redirects=True)
    owned = http is None
    try:
        headers = {"User-Agent": config.user_agent}
        headers.update(stream.headers)
        with client.stream("GET", stream.media_url, headers=headers) as response:
            if response.status_code >= 400:
                raise RuntimeError(
                    f"media server answered HTTP {response.status_code} for {match.video_id}"
                )
            if not stream.content_length:
                stream.content_length = int(response.headers.get("content-length") or 0)
            yield from response.iter_bytes(CHUNK_SIZE)
    finally:
        if owned:
            client.close()


def stream_to_stdout(
    match: Match,
    config: Config,
    sink=None,
    http: httpx.Client | None = None,
) -> int:
    """Write the audio payload to ``sink`` (stdout by default)."""
    import sys

    target = sink or sys.stdout.buffer
    written = 0
    for chunk in iter_audio(match, config, http=http):
        target.write(chunk)
        written += len(chunk)
    try:
        target.flush()
    except Exception:
        pass
    return written


def stream_local_file(path: Path, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    """Yield the content of a local file in chunks."""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            yield chunk

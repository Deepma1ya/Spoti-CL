"""Downloading audio through yt-dlp, with tagging and cover art."""

from __future__ import annotations

import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable, Iterable

from ..config import Config
from ..models import Match, Track
from ..textutil import safe_filename, truncate
from .tags import fetch_cover, guess_mime, write_tags

#: Codecs that need an ffmpeg post processing pass.
TRANSCODE_CODECS = {
    "mp3": ("mp3", 320),
    "flac": ("flac", 0),
    "opus": ("opus", 160),
    "m4a": ("m4a", 0),
    "aac": ("aac", 256),
    "wav": ("wav", 0),
}


@dataclass(slots=True)
class DownloadOptions:
    output_dir: Path
    fmt: str = "best"
    quality: int = 320
    embed_cover: bool = True
    embed_metadata: bool = True
    overwrite: bool = False
    cookie_file: str = ""
    proxy: str = ""
    timeout: int = 25
    extra_opts: dict = field(default_factory=dict)


@dataclass(slots=True)
class DownloadOutcome:
    track: Track
    path: Path | None = None
    skipped: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.error == ""


def target_name(track: Track, extension: str) -> str:
    """Build the on disk file name for a track."""
    artist = safe_filename(truncate(track.primary_artist or "Unknown", 80))
    title = safe_filename(truncate(track.name, 120))
    return f"{artist} - {title}.{extension}"


def _postprocessors(fmt: str, quality: int) -> list[dict]:
    codec = TRANSCODE_CODECS.get(fmt.lower())
    if not codec:
        return []
    name, default_quality = codec
    preferred = quality if name == "mp3" else default_quality
    return [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": name,
            "preferredquality": str(preferred),
        }
    ]


def download_match(
    match: Match,
    options: DownloadOptions,
    http=None,
) -> DownloadOutcome:
    """Download one matched track and write tags into it."""
    import yt_dlp

    track = match.track
    options.output_dir.mkdir(parents=True, exist_ok=True)

    ytdlp_options: dict = {
        "format": "bestaudio/best",
        "format_sort": ["abr", "asr", "size"],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "nocheckcertificate": True,
        "socket_timeout": options.timeout,
        "retries": 5,
        "fragment_retries": 5,
        "overwrites": options.overwrite,
        "postprocessors": _postprocessors(options.fmt, options.quality),
    }
    if options.cookie_file:
        ytdlp_options["cookiefile"] = options.cookie_file
    if options.proxy:
        ytdlp_options["proxy"] = options.proxy
    ytdlp_options.update(options.extra_opts)

    temp_dir = Path(tempfile.mkdtemp(prefix="spoti-cl-"))
    try:
        ytdlp_options["outtmpl"] = str(temp_dir / "%(id)s.%(ext)s")
        try:
            with yt_dlp.YoutubeDL(ytdlp_options) as ydl:
                info = ydl.extract_info(match.url, download=True)
        except Exception as exc:  # yt-dlp raises a zoo of its own errors
            return DownloadOutcome(track=track, error=str(exc))

        produced = _find_output(temp_dir, info)
        if produced is None:
            return DownloadOutcome(track=track, error="yt-dlp produced no file")

        extension = produced.suffix.lstrip(".").lower()
        final_path = options.output_dir / target_name(track, extension)
        if final_path.exists():
            if not options.overwrite:
                return DownloadOutcome(track=track, path=final_path, skipped=True)
            try:
                final_path.unlink()
            except OSError:
                pass

        shutil.move(str(produced), str(final_path))

        if options.embed_metadata or options.embed_cover:
            cover_bytes = None
            if options.embed_cover and track.cover_url:
                cover_bytes = fetch_cover(track.cover_url, http)
            write_tags(
                final_path,
                track,
                cover=cover_bytes,
                cover_mime=guess_mime(cover_bytes) if cover_bytes else "image/jpeg",
            )

        return DownloadOutcome(track=track, path=final_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _find_output(temp_dir: Path, info) -> Path | None:
    """Locate the file yt-dlp actually produced inside the scratch directory."""
    if info and info.get("requested_downloads"):
        for entry in info["requested_downloads"]:
            path = Path(entry.get("filepath") or "")
            if path.exists():
                return path
    candidates = [
        p for p in temp_dir.iterdir() if p.is_file() and p.suffix.lower() != ".part"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def download_many(
    matches: Iterable[Match],
    options: DownloadOptions,
    *,
    workers: int = 4,
    on_result: Callable[[DownloadOutcome], None] | None = None,
    http=None,
) -> list[DownloadOutcome]:
    """Download a batch of matches, in parallel."""
    items = list(matches)
    if not items:
        return []

    outcomes: list[DownloadOutcome] = []
    if workers <= 1:
        for match in items:
            outcome = download_match(match, options, http=http)
            outcomes.append(outcome)
            if on_result:
                on_result(outcome)
        return outcomes

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_match, m, options, http): m for m in items}
        for future in as_completed(futures):
            match = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:
                outcome = DownloadOutcome(track=match.track, error=str(exc))
            outcomes.append(outcome)
            if on_result:
                on_result(outcome)
    return outcomes


def options_from_config(config: Config, output_dir: Path, **overrides) -> DownloadOptions:
    """Build :class:`DownloadOptions` from the user configuration."""
    options = DownloadOptions(
        output_dir=output_dir,
        fmt=config.format,
        quality=config.quality,
        embed_cover=config.embed_cover,
        embed_metadata=config.embed_metadata,
        cookie_file=config.cookie_file,
        proxy=config.proxy,
        timeout=config.match_timeout,
    )
    for key, value in overrides.items():
        if value is not None and hasattr(options, key):
            setattr(options, key, value)
    return options

"""YouTube candidate discovery through yt-dlp."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..models import Candidate

#: yt-dlp writes its own cache; point it next to ours so everything lives in
#: one place that can be wiped with a single command.
def ytdlp_cache_dir() -> Path:
    override = os.environ.get("SPOTICL_CACHE_DIR")
    if override:
        return Path(override) / "ytdlp"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "spoti-cl" / "cache" / "ytdlp"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "spoti-cl" / "ytdlp"


def build_options(
    *,
    timeout: int = 25,
    cookie_file: str = "",
    proxy: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the base yt-dlp option dictionary."""
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": True,
        "nocheckcertificate": True,
        "socket_timeout": timeout,
        "retries": 5,
        "fragment_retries": 5,
        "cachedir": str(ytdlp_cache_dir()),
        "paths": {"home": str(ytdlp_cache_dir())},
    }
    if cookie_file:
        options["cookiefile"] = cookie_file
    if proxy:
        options["proxy"] = proxy
    if extra:
        options.update(extra)
    return options


def search_candidates(
    query: str,
    *,
    limit: int = 8,
    timeout: int = 25,
    cookie_file: str = "",
    proxy: str = "",
) -> list[Candidate]:
    """Run a YouTube search and return flat candidate records."""
    import yt_dlp

    options = build_options(
        timeout=timeout,
        cookie_file=cookie_file,
        proxy=proxy,
        extra={
            "extract_flat": "in_playlist",
            "skip_download": True,
        },
    )
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            payload = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception:
        return []

    if not payload:
        return []

    entries = payload.get("entries") or []
    candidates: list[Candidate] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        video_id = entry.get("id") or ""
        if not video_id:
            continue
        duration = entry.get("duration")
        candidates.append(
            Candidate(
                video_id=video_id,
                title=entry.get("title") or "",
                duration=float(duration) if duration else None,
                uploader=entry.get("uploader") or entry.get("channel") or "",
                channel=entry.get("channel") or entry.get("uploader") or "",
                view_count=int(entry.get("view_count") or 0),
                url=entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            )
        )
    return candidates

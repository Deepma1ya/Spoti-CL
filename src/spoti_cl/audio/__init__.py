"""Downloading, tagging and streaming audio."""

from __future__ import annotations

from .download import (
    DownloadOptions,
    DownloadOutcome,
    download_many,
    download_match,
    options_from_config,
)
from .stream import StreamInfo, extract_media_url, iter_audio, stream_to_stdout
from .tags import fetch_cover, write_tags

__all__ = [
    "DownloadOptions",
    "DownloadOutcome",
    "download_match",
    "download_many",
    "options_from_config",
    "StreamInfo",
    "extract_media_url",
    "iter_audio",
    "stream_to_stdout",
    "fetch_cover",
    "write_tags",
]

"""Writing tags and cover art into the downloaded file."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx

from ..models import Track


def fetch_cover(url: str, http: httpx.Client | None = None) -> bytes | None:
    """Download cover art, returning ``None`` when it is unavailable."""
    if not url:
        return None
    client = http or httpx.Client(timeout=20.0, follow_redirects=True)
    owned = http is None
    try:
        response = client.get(url, headers={"User-Agent": "spoti-cl/0.1"})
        if response.status_code != 200 or not response.content:
            return None
        return response.content
    except httpx.HTTPError:
        return None
    finally:
        if owned:
            client.close()


def _tag_values(track: Track) -> dict[str, Any]:
    return {
        "title": track.name,
        "artist": track.artist_label,
        "album": track.album or "",
        "albumartist": track.artist_label,
        "date": track.release_date[:4] if track.release_date else "",
        "tracknumber": str(track.track_number) if track.track_number else "",
        "discnumber": str(track.disc_number) if track.disc_number else "",
        "isrc": track.isrc or "",
        "comment": track.url or f"https://open.spotify.com/track/{track.id}",
    }


def write_tags(
    path: Path,
    track: Track,
    cover: bytes | None = None,
    cover_mime: str = "image/jpeg",
) -> bool:
    """Write metadata (and optionally cover art) into ``path``.

    Returns ``True`` when tags were written, ``False`` when the container is
    not supported or the file could not be tagged.
    """
    values = _tag_values(track)
    suffix = path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _write_mp3(path, values, cover, cover_mime)
        if suffix in (".flac",):
            return _write_flac(path, values, cover, cover_mime)
        if suffix in (".m4a", ".mp4", ".aac"):
            return _write_mp4(path, values, cover)
        if suffix in (".opus", ".ogg", ".webm"):
            return _write_vorbis(path, values, cover, cover_mime)
    except Exception:
        return False
    return False


def _write_mp3(
    path: Path,
    values: dict[str, Any],
    cover: bytes | None,
    cover_mime: str,
) -> bool:
    from mutagen.id3 import (
        APIC,
        ID3,
        ID3NoHeaderError,
        TALB,
        TDRC,
        TIT2,
        TPE1,
        TPE2,
        TRCK,
        TXXX,
    )
    from mutagen.mp3 import MP3

    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
    except Exception:
        return False

    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=values["title"]))
    if values["artist"]:
        tags.add(TPE1(encoding=3, text=values["artist"]))
        tags.add(TPE2(encoding=3, text=values["albumartist"]))
    if values["album"]:
        tags.add(TALB(encoding=3, text=values["album"]))
    if values["date"]:
        tags.add(TDRC(encoding=3, text=values["date"]))
    if values["tracknumber"]:
        tags.add(TRCK(encoding=3, text=values["tracknumber"]))
    if values["isrc"]:
        tags.add(TXXX(encoding=3, desc="ISRC", text=values["isrc"]))
    if values["comment"]:
        tags.add(TXXX(encoding=3, desc="SPOTIFY_URL", text=values["comment"]))
    if cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=cover_mime, type=3, desc="Cover", data=cover))

    tags.save(str(path), v2_version=3)
    MP3(path)  # touch the file so the mtime reflects the tag write
    return True


def _write_flac(
    path: Path,
    values: dict[str, Any],
    cover: bytes | None,
    cover_mime: str,
) -> bool:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(path)
    audio["title"] = values["title"]
    if values["artist"]:
        audio["artist"] = values["artist"]
        audio["albumartist"] = values["albumartist"]
    if values["album"]:
        audio["album"] = values["album"]
    if values["date"]:
        audio["date"] = values["date"]
    if values["tracknumber"]:
        audio["tracknumber"] = values["tracknumber"]
    if values["isrc"]:
        audio["isrc"] = values["isrc"]
    if values["comment"]:
        audio["comment"] = values["comment"]

    if cover:
        picture = Picture()
        picture.type = 3
        picture.mime = cover_mime
        picture.desc = "Cover"
        picture.data = cover
        audio.clear_pictures()
        audio.add_picture(picture)

    audio.save()
    return True


def _set(container, key: str, value: Any) -> bool:
    """Set a tag, ignoring containers that refuse the key."""
    try:
        container[key] = value
        return True
    except Exception:
        return False


def _write_mp4(path: Path, values: dict[str, Any], cover: bytes | None) -> bool:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    if values["title"]:
        _set(audio, "\xa9nam", [values["title"]])
    if values["artist"]:
        _set(audio, "\xa9ART", [values["artist"]])
        _set(audio, "aART", [values["albumartist"]])
    if values["album"]:
        _set(audio, "\xa9alb", [values["album"]])
    if values["date"]:
        _set(audio, "\xa9day", [values["date"]])
    if values["tracknumber"]:
        _set(audio, "trkn", [(int(values["tracknumber"]), 0)])
    if values["isrc"]:
        # Freeform atoms carry raw bytes, not text.
        _set(audio, "----:com.apple.iTunes:ISRC", [values["isrc"].encode("utf-8")])
    if values["comment"]:
        _set(audio, "----:com.apple.iTunes:SPOTIFY_URL", [values["comment"].encode("utf-8")])
    if cover:
        _set(audio, "covr", [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)])

    audio.save()
    return True


def _write_vorbis(
    path: Path,
    values: dict[str, Any],
    cover: bytes | None,
    cover_mime: str,
) -> bool:
    from mutagen.flac import Picture

    if path.suffix.lower() == ".opus":
        from mutagen.oggopus import OggOpus

        audio: Any = OggOpus(path)
    elif path.suffix.lower() == ".ogg":
        from mutagen.oggvorbis import OggVorbis

        audio = OggVorbis(path)
    else:
        from mutagen.webm import WebM

        audio = WebM(path)

    audio["title"] = values["title"]
    if values["artist"]:
        audio["artist"] = values["artist"]
        audio["albumartist"] = values["albumartist"]
    if values["album"]:
        audio["album"] = values["album"]
    if values["date"]:
        audio["date"] = values["date"]
    if values["tracknumber"]:
        audio["tracknumber"] = values["tracknumber"]
    if values["isrc"]:
        audio["isrc"] = values["isrc"]
    if values["comment"]:
        audio["comment"] = values["comment"]

    if cover and hasattr(audio, "add_picture"):
        picture = Picture()
        picture.type = 3
        picture.mime = cover_mime
        picture.desc = "Cover"
        picture.data = cover
        audio.clear_pictures()
        audio.add_picture(picture)

    audio.save()
    return True


def guess_mime(data: bytes) -> str:
    """Sniff the mime type of an image blob."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def image_bytes(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)

"""User configuration: defaults, config file and environment overrides."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

CONFIG_ENV = "SPOTICL_CONFIG"

DEFAULTS: dict[str, Any] = {
    # "best" keeps the source container untouched (no re-encode).
    # "mp3", "flac", "opus", "m4a" and "wav" transcode with ffmpeg.
    "format": "best",
    "quality": 320,
    "threads": 4,
    "output": "downloads",
    "embed_cover": True,
    "embed_metadata": True,
    "lyrics": False,
    "match_timeout": 25,
    "search_results": 8,
    "cookie_file": "",
    "proxy": "",
    "min_score": 0.62,
    "prefer_original": True,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def config_path() -> Path:
    """Location of the JSON config file."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "spoti-cl" / "config.json"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "spoti-cl" / "config.json"


@dataclass(slots=True)
class Config:
    format: str = DEFAULTS["format"]
    quality: int = DEFAULTS["quality"]
    threads: int = DEFAULTS["threads"]
    output: str = DEFAULTS["output"]
    embed_cover: bool = DEFAULTS["embed_cover"]
    embed_metadata: bool = DEFAULTS["embed_metadata"]
    lyrics: bool = DEFAULTS["lyrics"]
    match_timeout: int = DEFAULTS["match_timeout"]
    search_results: int = DEFAULTS["search_results"]
    cookie_file: str = DEFAULTS["cookie_file"]
    proxy: str = DEFAULTS["proxy"]
    min_score: float = DEFAULTS["min_score"]
    prefer_original: bool = DEFAULTS["prefer_original"]
    user_agent: str = DEFAULTS["user_agent"]

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Build a config from the defaults, the config file and the environment."""
        data = dict(DEFAULTS)
        target = path or config_path()
        try:
            if target.exists():
                loaded = json.loads(target.read_text("utf-8"))
                if isinstance(loaded, dict):
                    known = {f.name for f in fields(cls)}
                    data.update({k: v for k, v in loaded.items() if k in known})
        except (OSError, ValueError):
            pass

        env_map = {
            "SPOTICL_FORMAT": ("format", str),
            "SPOTICL_QUALITY": ("quality", int),
            "SPOTICL_THREADS": ("threads", int),
            "SPOTICL_OUTPUT": ("output", str),
            "SPOTICL_PROXY": ("proxy", str),
            "SPOTICL_COOKIES": ("cookie_file", str),
            "SPOTICL_MIN_SCORE": ("min_score", float),
        }
        for env_name, (field, caster) in env_map.items():
            raw = os.environ.get(env_name)
            if raw is None or raw == "":
                continue
            try:
                data[field] = caster(raw)
            except ValueError:
                continue

        return cls(**data)

    def save(self, path: Path | None = None) -> Path:
        """Write the current config to disk and return the path."""
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2), "utf-8")
        return target

"""spoti-cl - Spotify links in, high quality audio out.

No Spotify client id. No OAuth. No ads. No account.
"""

from __future__ import annotations

from .api import SpotiCL
from .config import Config
from .models import Candidate, Collection, Match, Track
from .urls import SpotifyLinkError, SpotifyRef, parse_link

__version__ = "0.1.0"

__all__ = [
    "SpotiCL",
    "Config",
    "Track",
    "Collection",
    "Match",
    "Candidate",
    "SpotifyRef",
    "SpotifyLinkError",
    "parse_link",
    "__version__",
]

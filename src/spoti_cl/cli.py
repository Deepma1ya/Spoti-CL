"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .api import SpotiCL
from .config import Config
from .match.engine import MatchError
from .models import Collection, Track
from .urls import SpotifyLinkError, parse_link

BANNER = "spoti-cl"


class ShellUsageError(Exception):
    """Raised by the interactive parser instead of exiting the process."""


class ShellExit(Exception):
    """Raised when the interactive parser wants to stop the shell."""


class _InteractiveParser(argparse.ArgumentParser):
    """An argument parser that reports problems instead of killing the shell."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ShellUsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        if message:
            print(message, file=sys.stderr)
        raise ShellExit(status)


# --------------------------------------------------------------------- output
def _supports_colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stderr.isatty()


class Printer:
    """Tiny console helper - everything goes to stderr except payloads."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.colour = _supports_colour()

    def _paint(self, text: str, code: str) -> str:
        if not self.colour:
            return text
        return f"\033[{code}m{text}\033[0m"

    def info(self, message: str) -> None:
        print(message, file=sys.stderr)

    def good(self, message: str) -> None:
        print(f"{self._paint('ok', '32')} {message}", file=sys.stderr)

    def warn(self, message: str) -> None:
        print(f"{self._paint('!!', '33')} {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        print(f"{self._paint('xx', '31')} {message}", file=sys.stderr)

    def debug(self, message: str) -> None:
        if self.verbose:
            print(f"{self._paint('..', '90')} {message}", file=sys.stderr)


def _duration(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _format_track_line(index: int, track: Track) -> str:
    artists = track.artist_label or "unknown artist"
    return f"{index:>3}. {artists} - {track.name}  [{_duration(track.duration_seconds)}]"


# ------------------------------------------------------------------- commands
def _acquire_app(args: argparse.Namespace, config: Config) -> tuple[SpotiCL, bool]:
    """Return the app to work with and whether we have to close it.

    The interactive shell injects a warm session through ``args._app`` so the
    token and the caches stay hot between commands.
    """
    injected = getattr(args, "_app", None)
    if injected is not None:
        return injected, False
    return SpotiCL(config=config), True


def cmd_info(args: argparse.Namespace, printer: Printer) -> int:
    app, owned = _acquire_app(args, Config.load())
    try:
        resolved = app.resolve(args.link)
        if args.json:
            print(json.dumps(resolved.to_dict(), indent=2, ensure_ascii=False))
            return 0
        if isinstance(resolved, Track):
            _print_track(printer, resolved)
        else:
            _print_collection(printer, resolved)
        return 0
    finally:
        if owned:
            app.close()


def _print_track(printer: Printer, track: Track) -> None:
    printer.info(f"{track.name}")
    printer.info(f"  artists  : {track.artist_label}")
    printer.info(f"  album    : {track.album}")
    printer.info(f"  duration : {_duration(track.duration_seconds)}")
    printer.info(f"  isrc     : {track.isrc or '-'}")
    printer.info(f"  track    : {track.track_number or '-'}")
    printer.info(f"  url      : {track.url}")


def _print_collection(printer: Printer, collection: Collection) -> None:
    printer.info(f"{collection.name}  [{collection.kind}]")
    if collection.owner:
        printer.info(f"  owner  : {collection.owner}")
    printer.info(f"  tracks : {collection.total_tracks or len(collection.tracks)}")
    for index, track in enumerate(collection.tracks, start=1):
        printer.info("  " + _format_track_line(index, track))


def cmd_get(args: argparse.Namespace, printer: Printer) -> int:
    config = Config.load()
    output_dir = Path(args.output or config.output).expanduser()
    app, owned = _acquire_app(args, config)
    failures = 0
    try:
        tracks = app.tracks(args.link)
        if not tracks:
            printer.error("nothing to download")
            return 1
        if args.limit:
            tracks = tracks[: args.limit]

        printer.info(f"{len(tracks)} track(s) queued -> {output_dir}")
        options_fmt = args.format or config.format
        quality = args.quality or config.quality
        printer.info(f"format={options_fmt} quality={quality}")

        if args.isrc:
            # Spotify refuses to hand out ISRCs to anonymous callers, so the
            # recording is cross referenced through MusicBrainz instead.
            printer.info("resolving ISRCs through MusicBrainz (one request per second)")
            for track in tracks:
                canonical = app.matcher.canonical_for(track)
                if canonical and canonical.isrc:
                    track.isrc = canonical.isrc

        results = []
        for track in tracks:
            try:
                match = app.matcher.find(track)
            except MatchError as exc:
                failures += 1
                printer.warn(f"no match: {track.artist_label} - {track.name} ({exc})")
                continue
            printer.debug(
                f"match {track.name!r} -> {match.video_id} score={match.score:.2f} "
                f"query={match.query!r}"
            )
            results.append(match)

        from .audio.download import DownloadOptions, download_many

        options = DownloadOptions(
            output_dir=output_dir,
            fmt=options_fmt,
            quality=quality,
            embed_cover=config.embed_cover and not args.no_cover,
            embed_metadata=config.embed_metadata and not args.no_tags,
            overwrite=args.overwrite,
            cookie_file=config.cookie_file,
            proxy=config.proxy,
            timeout=config.match_timeout,
        )

        def report(outcome) -> None:
            nonlocal failures
            if outcome.error:
                failures += 1
                printer.error(f"{outcome.track.name}: {outcome.error}")
            elif outcome.skipped:
                printer.info(f"skip  {outcome.path}")
            else:
                printer.good(str(outcome.path))

        download_many(
            results,
            options,
            workers=args.threads or config.threads,
            on_result=report,
            http=app.http,
        )
        return 1 if failures else 0
    finally:
        if owned:
            app.close()


def cmd_stream(args: argparse.Namespace, printer: Printer) -> int:
    config = Config.load()
    app, owned = _acquire_app(args, config)
    try:
        tracks = app.tracks(args.link)
        if not tracks:
            printer.error("nothing to stream")
            return 1
        match = app.matcher.find(tracks[0])
        printer.debug(f"stream {match.video_id} score={match.score:.2f}")

        from .audio.stream import extract_media_url, stream_to_stdout

        if sys.stdout.isatty() or getattr(args, "_interactive", False):
            # A terminal cannot swallow raw audio - hand over the direct URL
            # and the metadata instead.
            info = extract_media_url(match, app.config)
            printer.info(f"{tracks[0].artist_label} - {tracks[0].name}")
            printer.info(f"  duration : {_duration(tracks[0].duration_seconds)}")
            printer.info(f"  mime    : {info.mime}")
            printer.info(f"  media   : {info.media_url[:110]}...")
            printer.info("")
            printer.info("pipe it with:")
            printer.info(
                f"  spoti-cl stream \"{args.link}\" | ffmpeg -i pipe:0 -f s16le -ar 48000 pipe:1"
            )
            return 0

        written = stream_to_stdout(match, app.config, http=app.http)
        printer.info(f"streamed {written} bytes")
        return 0
    finally:
        if owned:
            app.close()


def cmd_serve(args: argparse.Namespace, printer: Printer) -> int:
    from .server import serve

    serve(args.host, args.port, config=Config.load(), verbose=args.verbose)
    return 0


def cmd_search(args: argparse.Namespace, printer: Printer) -> int:
    app, owned = _acquire_app(args, Config.load())
    try:
        if args.type == "playlist":
            results = app.search_playlists(args.query, args.limit)
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
                return 0
            for entry in results:
                printer.info(
                    f"{entry['name']}  [{entry['total_tracks']} tracks]  by {entry['owner']}"
                )
                printer.info(f"     {entry['url']}")
            return 0

        tracks = app.search(args.query, args.limit)
        if args.json:
            print(json.dumps([t.to_dict() for t in tracks], indent=2, ensure_ascii=False))
            return 0
        for index, track in enumerate(tracks, start=1):
            printer.info(_format_track_line(index, track))
            printer.info(f"     {track.url}")
        return 0
    finally:
        if owned:
            app.close()


def cmd_doctor(args: argparse.Namespace, printer: Printer) -> int:
    """Check that everything the tool depends on is in place."""
    ok = True
    printer.info(f"{BANNER} doctor")

    try:
        import yt_dlp

        printer.good(f"yt-dlp {yt_dlp.version.__version__}")
    except Exception as exc:
        ok = False
        printer.error(f"yt-dlp missing: {exc}")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        version = subprocess.run(
            [ffmpeg, "-version"], capture_output=True, text=True, check=False
        ).stdout.splitlines()[0]
        printer.good(version)
    else:
        ok = False
        printer.error("ffmpeg not found - needed for mp3/flac conversion")

    try:
        import mutagen

        printer.good(f"mutagen {mutagen.version_string}")
    except Exception as exc:
        ok = False
        printer.error(f"mutagen missing: {exc}")

    app = SpotiCL(config=Config.load())
    try:
        ref = parse_link(args.link)
        resolved = app.resolve(ref)
        if isinstance(resolved, Track):
            printer.good(f"spotify metadata ok: {resolved.name}")
        else:
            printer.good(
                f"spotify metadata ok: {resolved.name} ({len(resolved.tracks)} tracks)"
            )
    except Exception as exc:
        ok = False
        printer.error(f"spotify metadata failed: {exc}")
    finally:
        app.close()

    return 0 if ok else 1


def cmd_config(args: argparse.Namespace, printer: Printer) -> int:
    config = Config.load()
    if args.set:
        for pair in args.set:
            if "=" not in pair:
                printer.error(f"expected key=value, got {pair!r}")
                return 1
            key, value = pair.split("=", 1)
            if not hasattr(config, key):
                printer.error(f"unknown config key {key!r}")
                return 1
            current = getattr(config, key)
            try:
                if isinstance(current, bool):
                    value = value.lower() in ("1", "true", "yes", "on")
                elif isinstance(current, int):
                    value = int(value)
                elif isinstance(current, float):
                    value = float(value)
            except ValueError:
                printer.error(f"invalid value for {key}: {value!r}")
                return 1
            setattr(config, key, value)
        path = config.save()
        printer.good(f"saved {path}")
        return 0

    print(json.dumps(config.__dict__ if hasattr(config, "__dict__") else {
        f: getattr(config, f) for f in config.__slots__
    }, indent=2))
    return 0


# --------------------------------------------------------------------- parser
def build_parser(interactive: bool = False) -> argparse.ArgumentParser:
    """Build the command line parser.

    In interactive mode the parser raises instead of calling ``sys.exit``, so a
    typo inside the shell prints an error and keeps the session alive.
    """
    parser_class = _InteractiveParser if interactive else argparse.ArgumentParser
    parser = parser_class(
        prog="spoti-cl",
        description=(
            "Download and stream Spotify tracks, albums and playlists as high "
            "quality audio. No Spotify client id, no OAuth, no ads."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  spoti-cl                                    open the interactive shell\n"
            "  spoti-cl get https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT\n"
            "  spoti-cl get https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M -o music\n"
            "  spoti-cl info https://open.spotify.com/album/5Z9iiGl2FcIfa3BMiv6OIw\n"
            "  spoti-cl stream <link> | ffmpeg -i pipe:0 -f s16le -ar 48000 pipe:1\n"
            "  spoti-cl serve --port 8765\n"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="chatty output")
    sub = parser.add_subparsers(dest="command", required=True)

    shell = sub.add_parser("shell", help="open the interactive shell")
    shell.set_defaults(func=cmd_shell)

    info = sub.add_parser("info", help="show metadata for a link")
    info.add_argument("link", help="Spotify track, album, playlist or artist link")
    info.add_argument("--json", action="store_true", help="machine readable output")
    info.set_defaults(func=cmd_info)

    get = sub.add_parser("get", help="download a track, album or playlist")
    get.add_argument("link", help="Spotify link")
    get.add_argument(
        "-o", "--output", default=None, help="output directory (default: downloads)"
    )
    get.add_argument(
        "-f",
        "--format",
        choices=["best", "mp3", "flac", "opus", "m4a", "aac", "wav"],
        help="output format (default: best - no re-encode)",
    )
    get.add_argument("-q", "--quality", type=int, help="bitrate for lossy formats")
    get.add_argument("-t", "--threads", type=int, help="parallel downloads")
    get.add_argument("-n", "--limit", type=int, help="only take the first N tracks")
    get.add_argument("--overwrite", action="store_true", help="replace existing files")
    get.add_argument("--no-cover", action="store_true", help="do not embed cover art")
    get.add_argument("--no-tags", action="store_true", help="do not write tags")
    get.add_argument(
        "--isrc",
        action="store_true",
        help="cross reference MusicBrainz for the ISRC of every track (slow, cached)",
    )
    get.set_defaults(func=cmd_get)

    stream = sub.add_parser("stream", help="stream audio to stdout")
    stream.add_argument("link", help="Spotify link")
    stream.set_defaults(func=cmd_stream)

    serve = sub.add_parser("serve", help="run the HTTP service for bots")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    search = sub.add_parser("search", help="search the Spotify catalogue")
    search.add_argument("query")
    search.add_argument("-n", "--limit", type=int, default=10)
    search.add_argument(
        "--type", choices=["track", "playlist"], default="track", help="what to search for"
    )
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    doctor = sub.add_parser("doctor", help="check the environment")
    doctor.add_argument(
        "link",
        nargs="?",
        default="https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
    )
    doctor.set_defaults(func=cmd_doctor)

    config = sub.add_parser("config", help="show or change the configuration")
    config.add_argument(
        "--set", nargs="*", metavar="KEY=VALUE", help="values to store"
    )
    config.set_defaults(func=cmd_config)

    return parser


def cmd_shell(args: argparse.Namespace, printer: Printer) -> int:
    """Open the interactive shell."""
    from .shell import InteractiveShell

    return InteractiveShell(config=Config.load()).run()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    # No arguments at all means "open the shell".
    if not arguments:
        from .shell import InteractiveShell

        return InteractiveShell(config=Config.load()).run()

    parser = build_parser()
    args = parser.parse_args(arguments)
    printer = Printer(verbose=args.verbose)
    try:
        return int(args.func(args, printer) or 0)
    except SpotifyLinkError as exc:
        printer.error(str(exc))
        return 2
    except KeyboardInterrupt:
        printer.warn("interrupted")
        return 130
    except Exception as exc:
        printer.error(str(exc))
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

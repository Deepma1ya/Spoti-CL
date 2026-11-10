"""The interactive shell.

Run ``spoti-cl`` with no arguments (or ``spoti-cl shell``) and you land in a
prompt that keeps one warm session alive: the anonymous token, the metadata
cache and the match cache all stay hot between commands, so the second
command in a session is as fast as the first.

Paste a bare Spotify link and it downloads. Everything else works exactly
like the one-shot command line.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from .api import SpotiCL
from .config import Config

BANNER_ART = r"""
 ____          _    _  _   _      _
/ ___|___  ___| | _(_) || |_(_)  / __|
\___ \ _ \/ __| |/ / | ||  _| \ \/ /
 ___) |  __/ (__|   <| || |___ \  /
|____/ \___|\___|_|\_|_||_|_/ /_/
"""

BUILTINS = (
    "help", "exit", "quit", "clear", "cd", "pwd", "ls", "history", "version",
    "verbose", "play",
)

COMMANDS = (
    "get", "info", "stream", "serve", "search", "doctor", "config", "shell",
)

OPTIONS = (
    "--json", "--overwrite", "--no-cover", "--no-tags", "--isrc",
    "-o", "-f", "-q", "-t", "-n", "-v",
)


def split_command(line: str) -> list[str]:
    """Split a command line into arguments, keeping Windows paths intact."""
    try:
        parts = shlex.split(line, posix=False)
    except ValueError:
        parts = line.split()
    cleaned: list[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        cleaned.append(part)
    return cleaned


def terminal_width(default: int = 100) -> int:
    try:
        return max(60, min(140, os.get_terminal_size().columns))
    except OSError:
        return default


def looks_like_link(token: str) -> bool:
    """True when a token is a bare Spotify URL."""
    lowered = token.lower()
    return lowered.startswith(("http://", "https://", "spotify:")) and (
        "spotify.com" in lowered or lowered.startswith("spotify:")
    )


class InteractiveShell:
    """A REPL around the same commands the one-shot CLI exposes."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.load()
        self.app = SpotiCL(config=self.config)
        # The shell starts where the terminal starts, like every other shell.
        self.cwd = Path.cwd()
        self.history_file = self._history_path()
        self.verbose = False

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _history_path() -> Path:
        from .cache import cache_root

        root = cache_root()
        return root.parent / "history" if root.name == "cache" else root / "history"

    def _setup_readline(self) -> bool:
        try:
            import readline  # noqa: F401  (Windows: provided by pyreadline3)
        except ImportError:
            return False

        import readline as rl

        try:
            rl.read_history_file(str(self.history_file))
        except (OSError, ValueError):
            pass

        def completer(text: str, state: int) -> str | None:
            try:
                matches = self._complete(text)
            except Exception:
                matches = []
            return matches[state] if state < len(matches) else None

        rl.set_completer(completer)
        rl.set_completer_delims(" \t\n")
        rl.parse_and_bind("tab: complete")
        return True

    def _complete(self, text: str) -> list[str]:
        if " " in text:
            head, _, tail = text.rpartition(" ")
            if tail.startswith("-"):
                return [opt for opt in OPTIONS if opt.startswith(tail)]
            base = Path(tail).expanduser()
            directory = base if base.is_dir() else base.parent
            try:
                entries = sorted(
                    p.name + ("/" if p.is_dir() else "") for p in directory.iterdir()
                )
            except OSError:
                entries = []
            return [head + " " + e for e in entries if e.startswith(base.name)]
        return [c for c in COMMANDS + BUILTINS if c.startswith(text)]

    def _save_history(self) -> None:
        try:
            import readline as rl

            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            rl.write_history_file(str(self.history_file))
        except Exception:
            pass

    # ----------------------------------------------------------------- output
    def _c(self, text: str, code: str) -> str:
        if os.environ.get("NO_COLOR"):
            return text
        return f"\033[{code}m{text}\033[0m"

    def say(self, message: str = "") -> None:
        print(message)

    def ok(self, message: str) -> None:
        print(f"{self._c('ok', '32')} {message}")

    def warn(self, message: str) -> None:
        print(f"{self._c('!!', '33')} {message}")

    def err(self, message: str) -> None:
        print(f"{self._c('xx', '31')} {message}")

    def hint(self, message: str) -> None:
        print(f"{self._c('->', '36')} {message}")

    # ------------------------------------------------------------------ shell
    def banner(self) -> None:
        from . import __version__

        if not os.environ.get("NO_COLOR"):
            print(self._c(BANNER_ART, "36"))
        print(self._c(f"  Spoti-CL {__version__}", "1;36"))
        print(self._c("  Spotify links to high quality audio. No client id, no account.", "90"))
        print()
        print(f"  {self._c('downloads go to', '90')} {self.cwd}")
        print(f"  {self._c('paste a Spotify link to download it', '90')}")
        print(f"  {self._c('type', '90')} help{self._c(' for commands, exit to quit', '90')}")
        print()

    def prompt(self) -> str:
        where = self._short_cwd()
        return (
            self._c("spoti-cl", "1;36")
            + (self._c(f" {where}", "90") if where else "")
            + self._c(" > ", "90")
        )

    def _short_cwd(self) -> str:
        """A compact form of the current directory for the prompt."""
        try:
            relative = self.cwd.relative_to(Path.cwd())
            text = str(relative) if str(relative) != "." else ""
        except ValueError:
            text = str(self.cwd)
        return f"[{text}]" if text and text != "." else ""

    def run(self) -> int:
        self.banner()
        if not self._setup_readline():
            self.hint("history and tab completion are unavailable on this platform")
        try:
            while True:
                try:
                    line = input(self.prompt())
                except EOFError:
                    print()
                    break
                except KeyboardInterrupt:
                    print()
                    continue

                # Pasted text often carries a byte order mark.
                line = line.lstrip("\ufeff").strip()
                if not line:
                    continue
                if self.dispatch(line):
                    break
        finally:
            self._save_history()
            self.app.close()
        return 0

    # --------------------------------------------------------------- dispatch
    def dispatch(self, line: str) -> bool:
        """Handle one line. Returns True when the shell should exit."""
        parts = split_command(line)
        if not parts:
            return False

        # Spotify ids are case sensitive, so the original token is kept.
        first = parts[0]
        command = first.lower()
        args = parts[1:]

        # A bare link is a download request.
        if looks_like_link(first):
            return self.run_command(["get", first])

        if command in ("exit", "quit", ":q"):
            return True
        if command in ("help", "?"):
            self.show_help()
            return False
        if command == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            self.banner()
            return False
        if command == "pwd":
            self.say(str(self.cwd))
            return False
        if command == "cd":
            self.change_dir(args)
            return False
        if command in ("ls", "dir"):
            self.list_dir()
            return False
        if command == "history":
            self.show_history()
            return False
        if command == "version":
            from . import __version__

            self.say(f"Spoti-CL {__version__}")
            return False
        if command == "verbose":
            self.toggle_verbose(args)
            return False
        if command == "play":
            self.play(args)
            return False

        return self.run_command(parts)

    # ------------------------------------------------------------- playback
    def play(self, args: list[str]) -> None:
        """Stream the track straight into ffplay."""
        import shutil
        import subprocess

        if not args:
            self.err("play needs a Spotify link")
            return
        player = shutil.which("ffplay")
        if not player:
            self.err("ffplay was not found - it ships with ffmpeg")
            self.hint("ffmpeg download: https://ffmpeg.org/download.html")
            return

        try:
            tracks = self.app.tracks(args[0])
        except Exception as exc:
            self.err(str(exc))
            return
        if not tracks:
            self.err("nothing to play")
            return

        track = tracks[0]
        try:
            match = self.app.matcher.find(track)
        except Exception as exc:
            self.err(str(exc))
            return

        from .audio.stream import extract_media_url

        info = extract_media_url(match, self.app.config)
        self.hint(f"playing {track.artist_label} - {track.name}")
        self.hint("ctrl-c to stop")
        try:
            subprocess.Popen(
                [player, "-nodisp", "-autoexit", "-loglevel", "error", info.media_url]
            ).wait()
        except KeyboardInterrupt:
            self.warn("stopped")

    # ------------------------------------------------------------- built-ins
    def show_help(self) -> None:
        self.say(self._c("  commands", "1"))
        rows = [
            ("get <link>", "download a track, album, playlist or artist"),
            ("info <link>", "show metadata for a link"),
            ("stream <link>", "resolve the stream and print the media URL"),
            ("search <query>", "search Spotify (-n, --type playlist)"),
            ("serve", "run the HTTP service for bots (--host, --port)"),
            ("doctor", "check yt-dlp, ffmpeg, mutagen and the API"),
            ("config", "show or change the defaults (--set k=v)"),
            ("shell", "restart this shell"),
        ]
        for name, description in rows:
            self.say(f"    {self._c(name.ljust(22), '36')}{description}")
        self.say()
        self.say(self._c("  shell built-ins", "1"))
        rows = [
            ("cd <dir>", "change where downloads land"),
            ("pwd", "print the download directory"),
            ("ls", "list the download directory"),
            ("play <link>", "stream the track through ffplay"),
            ("history", "show the command history"),
            ("verbose [on|off]", "toggle the chatty output"),
            ("clear", "clear the screen"),
            ("exit", "leave the shell"),
        ]
        for name, description in rows:
            self.say(f"    {self._c(name.ljust(22), '36')}{description}")
        self.say()
        self.say(self._c("  flags", "1"))
        self.say("    get -f mp3|flac|opus|best   -q bitrate   -t parallel   -n first N")
        self.say("    get --overwrite --no-cover --no-tags --isrc")
        self.say("    a bare Spotify link is a download")
        self.say()

    def change_dir(self, args: list[str]) -> None:
        if not args:
            self.say(str(self.cwd))
            return
        target = Path(args[0]).expanduser()
        if not target.is_absolute():
            target = self.cwd / target
        if not target.exists():
            self.err(f"no such directory: {target}")
            return
        self.cwd = target.resolve()
        self.hint(f"downloads now go to {self.cwd}")
    def list_dir(self) -> None:
        if not self.cwd.exists():
            self.warn(f"{self.cwd} does not exist yet - it will be created on download")
            return
        try:
            entries = sorted(
                self.cwd.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError as exc:
            self.err(str(exc))
            return
        if not entries:
            self.say("  (empty)")
            return
        width = terminal_width()
        for entry in entries:
            if entry.is_dir():
                self.say(f"  {self._c(entry.name + '/', '1;34')}")
            else:
                size = entry.stat().st_size
                name = entry.name[: width - 14]
                print(f"  {name:<{width - 14}} {size / 1_048_576:>8.2f} MB")

    def show_history(self) -> None:
        try:
            import readline as rl
        except ImportError:
            self.warn("no history available on this platform")
            return
        total = rl.get_current_history_length()
        for index in range(1, total + 1):
            self.say(f"{index:>4}  {rl.get_history_item(index)}")

    def toggle_verbose(self, args: list[str]) -> None:
        if args and args[0].lower() in ("on", "true", "1"):
            self.verbose = True
        elif args and args[0].lower() in ("off", "false", "0"):
            self.verbose = False
        else:
            self.verbose = not self.verbose
        self.say(f"verbose is {'on' if self.verbose else 'off'}")

    # --------------------------------------------------------------- commands
    def run_command(self, parts: list[str]) -> bool:
        from .cli import ShellExit, ShellUsageError, build_parser

        argv = list(parts)
        if argv and argv[0] in ("-v", "--verbose"):
            self.verbose = True
            argv = argv[1:]
        elif argv and argv[0] in ("-q", "--quiet"):
            self.verbose = False
            argv = argv[1:]

        parser = build_parser(interactive=True)
        try:
            args = parser.parse_args(argv)
        except ShellUsageError as exc:
            message = str(exc)
            if "invalid choice" in message:
                self.err(f"unknown command: {argv[0]}")
                self.hint("type help for the list of commands")
            else:
                self.err(message)
            return False
        except (ShellExit, SystemExit):
            return False

        # The shell owns the download directory and the session.
        if getattr(args, "command", "") == "get" and not getattr(args, "output", None):
            args.output = str(self.cwd)
        args._app = self.app  # type: ignore[attr-defined]
        args._interactive = True  # type: ignore[attr-defined]

        if not hasattr(args, "func"):
            return False

        try:
            args.func(args, _ShellPrinter(self))
        except KeyboardInterrupt:
            print()
            self.warn("interrupted")
        except Exception as exc:
            self.err(str(exc))
            if self.verbose:
                import traceback

                traceback.print_exc()
        return False


class _ShellPrinter:
    """Adapts the CLI printer interface onto the interactive shell."""

    def __init__(self, shell: InteractiveShell) -> None:
        self.shell = shell

    def info(self, message: str) -> None:
        self.shell.say(message)

    def good(self, message: str) -> None:
        self.shell.ok(message)

    def warn(self, message: str) -> None:
        self.shell.warn(message)

    def error(self, message: str) -> None:
        self.shell.err(message)

    def debug(self, message: str) -> None:
        if self.shell.verbose:
            self.shell.say(self.shell._c(message, "90"))

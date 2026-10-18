#!/usr/bin/env python3
"""TaskBridge installer UI — a rich-powered terminal dashboard.

`./install.sh` only bootstraps a python 3.12 venv; everything after that lives
here:

    runtime → dependencies → ngrok → bearer token → tunnel → credentials → serve

Two renderers, same event API:

* LiveUi  — full dashboard: gradient wordmark, live checklist with per-step
            spinners, streaming activity line, bordered summary panels.
* PlainUi — line-oriented fallback (no rich, stdout not a terminal, or
            TASKBRIDGE_PLAIN=1): same information, no cursor tricks.

The installer logic never knows which one is drawing.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

try:  # POSIX-only, and only needed for the hidden Authtoken prompt.
    import termios
except ImportError:  # pragma: no cover
    termios = None  # type: ignore[assignment]

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
PY = VENV / "bin" / "python"
PIP = VENV / "bin" / "pip"
SERVER = HERE / "opencode_bridge_mcp.py"
TOKEN_FILE = HERE / ".bridge-token"
NGROK_LOG = HERE / "ngrok.log"
NGROK_DOMAIN_FILE = HERE / ".ngrok-domain"
NGROK_API = "http://127.0.0.1:4040/api/tunnels"
SERVE_MARK = "opencode_bridge_mcp.py --transport"

# Brand palette — mirrors the landing-page tokens in app/globals.css.
PALETTE = {
    "dark": {
        "paper": "#efe4cc",
        "faint": "#9c8c72",
        "rule": "#6b5a43",
        "ember": "#e2603a",
        "signal": "#f2a007",
        "seal": "#8fc39a",
        "wait": "#b9a3e3",
    },
    "light": {
        "paper": "#241c12",
        "faint": "#6f6250",
        "rule": "#c3b291",
        "ember": "#c24d28",
        "signal": "#9a6206",
        "seal": "#2f7446",
        "wait": "#5f45b3",
    },
}
RAMP = ("ember", "signal", "seal")  # planning heat → dispatch → sealed

ART_WIDE = r"""
████████╗ █████╗ ███████╗██╗  ██╗██████╗ ██████╗ ██╗██████╗  ██████╗ ███████╗
╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝██╔══██╗██╔══██╗██║██╔══██╗██╔════╝ ██╔════╝
   ██║   ███████║███████╗█████╔╝ ██████╔╝██████╔╝██║██║  ██║██║  ███╗█████╗
   ██║   ██╔══██║╚════██║██╔═██╗ ██╔══██╗██╔══██╗██║██║  ██║██║   ██║██╔══╝
   ██║   ██║  ██║███████║██║  ██╗██████╔╝██║  ██║██║██████╔╝╚██████╔╝███████╗
   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝ ╚══════╝
"""
ART_MID = r"""
  _____         _    ____       _     _
 |_   _|_ _ ___| | _| __ ) _ __(_) __| | __ _  ___
   | |/ _` / __| |/ /  _ \| '__| |/ _` |/ _` |/ _ \
   | | (_| \__ \   <| |_) | |  | | (_| | (_| |  __/
   |_|\__,_|___/_|\_\____/|_|  |_|\__,_|\__, |\___|
                                        |___/
"""
ART_SMALL = r"""
  _____        _   ___     _    _
 |_   _|_ _ __| |_| _ )_ _(_)__| |__ _ ___
   | |/ _` (_-< / / _ \ '_| / _` / _` / -_)
   |_|\__,_/__/_\_\___/_| |_\__,_\__, \___|
                                 |___/
"""


class SetupError(RuntimeError):
    """A step failed in a way the user can act on."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(stops: Sequence[str], t: float) -> str:
    """Colour at position 0..1 along a multi-stop ramp, as '#rrggbb'."""
    t = min(0.9999, max(0.0, t)) * (len(stops) - 1)
    index = int(t)
    low = hex_to_rgb(stops[index])
    high = hex_to_rgb(stops[min(index + 1, len(stops) - 1)])
    frac = t - index
    return "#%02x%02x%02x" % tuple(round(low[k] + (high[k] - low[k]) * frac) for k in range(3))


def theme_name() -> str:
    explicit = os.environ.get("TASKBRIDGE_THEME", "").strip().lower()
    if explicit in PALETTE:
        return explicit
    try:  # xterm-style COLORFGBG="fg;bg" — a bright background means a light terminal
        background = int(os.environ.get("COLORFGBG", "").split(";")[-1])
    except ValueError:
        return "dark"
    return "light" if background >= 7 else "dark"


def pick_art(width: int) -> tuple[list[str], int]:
    """Widest wordmark that fits, as (lines, columns)."""
    for art in (ART_WIDE, ART_MID, ART_SMALL):
        lines = [line.rstrip() for line in art.strip("\n").splitlines()]
        cols = max(len(line) for line in lines)
        if width >= cols + 8:
            return lines, cols
    return [], 0


def paint(text: str, colour: str, bold: bool = False, enabled: bool = True) -> str:
    if not enabled:
        return text
    r, g, b = hex_to_rgb(colour)
    return f"\033[{'1;' if bold else ''}38;2;{r};{g};{b}m{text}\033[0m"


def human(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{int(seconds) // 60}m{int(seconds) % 60:02d}s"


def port_is_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def http_json(url: str, timeout: float = 2.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 — loopback
            return json.loads(response.read().decode("utf-8", "replace") or "{}")
    except (urllib.error.URLError, OSError, ValueError):
        return {}


def last_lines(path: Path, count: int = 5) -> list[str]:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines[-count:] if line.strip()]


def stream(cmd: Sequence[str], on_line: Callable[[str], None] | None = None, env: dict | None = None) -> int:
    """Run a command, feeding every output line to `on_line`. Returns exit code."""
    proc = subprocess.Popen(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    assert proc.stdout is not None
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            if on_line:
                on_line(line.rstrip())
    finally:
        proc.wait()
    return proc.returncode or 0


def ask_secret(hint: str) -> str | None:
    """Read one hidden line from /dev/tty. None when there is no terminal.

    Reads the tty directly so `curl … | bash` still prompts, exactly like the
    shell version did.
    """
    if termios is None:
        return None
    try:
        tty = open("/dev/tty", "r+")  # noqa: SIM115
    except OSError:
        return None
    try:
        fd = tty.fileno()
        try:
            attrs = termios.tcgetattr(fd)
        except termios.error:
            return None
        quiet = list(attrs)
        quiet[3] = attrs[3] & ~termios.ECHO
        tty.write(f"{hint}\n\033[1m❯\033[0m ")
        tty.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, quiet)
        try:
            line = tty.readline()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
            tty.write("\n")
            tty.flush()
        return line.strip()
    finally:
        tty.close()


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
@dataclass
class Step:
    key: str
    label: str
    detail: str = ""
    state: str = "pending"  # pending | running | ok | warn | fail
    seconds: float = 0.0
    started: float = 0.0


@dataclass
class Facts:
    port: int
    theme: dict = field(default_factory=lambda: PALETTE[theme_name()])
    python: str = ""
    platform: str = ""
    venv_ready: bool = False
    ngrok_version: str = ""
    auth_state: str = ""
    token: str = ""
    token_state: str = "reused"
    deps_state: str = ""
    public_url: str = ""
    tunnel_state: str = ""
    opencode_cli: bool = True
    started: float = field(default_factory=time.monotonic)


# --------------------------------------------------------------------------- #
# renderers
# --------------------------------------------------------------------------- #
class BaseUi:
    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self.steps: list[Step] = []
        self.activity = ""
        self._closed = False

    # lifecycle -------------------------------------------------------------
    def open(self) -> None: ...

    def close(self) -> None:
        self._closed = True

    # events ----------------------------------------------------------------
    def add(self, key: str, label: str) -> Step:
        step = Step(key=key, label=label)
        self.steps.append(step)
        return step

    def start(self, step: Step, detail: str = "") -> None:
        step.started = time.monotonic()
        step.state = "running"
        step.detail = detail
        self.refresh()

    def finish(self, step: Step, state: str, detail: str = "", seconds: float | None = None) -> None:
        step.seconds = seconds if seconds is not None else max(0.0, time.monotonic() - step.started)
        step.state = state
        if detail:
            step.detail = detail
        self.refresh()

    def say(self, text: str) -> None:
        self.activity = text
        self.refresh()

    def ask(self, question: str, hint: str = "") -> str | None: ...

    def note(self, text: str) -> None: ...

    def panel(self, title: str, rows: Iterable[tuple[str, str]], subtitle: str = "") -> None: ...

    def alert(self, title: str, lines: Sequence[str], hint: str = "") -> None: ...

    def refresh(self) -> None: ...


class PlainUi(BaseUi):
    """Line-oriented output — safe for pipes, logs, and hosts without rich."""

    GLYPH = {"running": "▸", "ok": "✓", "warn": "!", "fail": "✗", "pending": "·"}

    def __init__(self, facts: Facts) -> None:
        super().__init__(facts)
        self.colour = sys.stdout.isatty() and os.environ.get("TERM", "") not in ("", "dumb")
        self._last_activity = ""

    def _c(self, text: str, colour: str, bold: bool = False) -> str:
        return paint(text, colour, bold, enabled=self.colour)

    def open(self) -> None:
        theme = self.facts.theme
        lines, cols = pick_art(shutil.get_terminal_size((80, 24)).columns)
        stops = [theme[name] for name in RAMP]
        print()
        if lines:
            for line in lines:
                print("  " + "".join(self._c(ch, mix(stops, col / max(1, cols - 1)), True) for col, ch in enumerate(line)))
        else:
            print("  " + self._c("TASKBRIDGE", stops[0], True))
        print(f"  {self._c('MCP bridge between your assistant and the opencode worker', theme['faint'])}")
        print()

    def _row(self, step: Step) -> str:
        colour = {
            "running": self.facts.theme["signal"],
            "ok": self.facts.theme["seal"],
            "warn": self.facts.theme["signal"],
            "fail": self.facts.theme["ember"],
            "pending": self.facts.theme["faint"],
        }[step.state]
        head = f"  {self._c(self.GLYPH[step.state], colour, True)} {step.label.ljust(15)}"
        tail = self._c(step.detail, self.facts.theme["faint"]) if step.detail else ""
        return f"{head} {tail}".rstrip()

    def start(self, step: Step, detail: str = "") -> None:
        super().start(step, detail)
        print(self._row(step))

    def finish(self, step: Step, state: str, detail: str = "", seconds: float | None = None) -> None:
        super().finish(step, state, detail, seconds)
        print(f"{self._row(step)}  {self._c(human(step.seconds), self.facts.theme['faint'])}")

    def say(self, text: str) -> None:
        super().say(text)
        if text and text != self._last_activity:
            self._last_activity = text
            print(f"     {self._c('│ ' + text, self.facts.theme['faint'])}")

    def ask(self, question: str, hint: str = "") -> str | None:
        print()
        print(f"  {self._c(question, self.facts.theme['paper'], True)}")
        if hint:
            print(f"  {self._c(hint, self.facts.theme['faint'])}")
        return ask_secret("  Authtoken (input hidden, Enter to skip)")

    def note(self, text: str) -> None:
        print(f"  {self._c(text, self.facts.theme['faint'])}")

    def panel(self, title: str, rows: Iterable[tuple[str, str]], subtitle: str = "") -> None:
        theme = self.facts.theme
        flat: list[tuple[str, str]] = []
        for key, value in rows:
            for index, part in enumerate(value.split("\n")):
                flat.append((key if index == 0 else "", part))
        key_width = max(len(key) for key, _ in flat)
        body = [f"  {key.ljust(key_width)}  {value}" for key, value in flat]
        # Natural width — long values (URLs, tokens) must stay copy-pasteable.
        width = max([len(title) + 6] + [len(line) + 4 for line in body])
        print()
        head = f"─ {title} "
        print(self._c("╭" + head + "─" * max(0, width - len(head) - 1) + "╮", theme["rule"]))
        for line in body:
            print(f"{self._c('│', theme['rule'])} {line}{' ' * max(0, width - len(line) - 3)}{self._c('│', theme['rule'])}")
        if subtitle:
            text = f"  {subtitle}"
            print(f"{self._c('│', theme['rule'])} {text}{' ' * max(0, width - len(text) - 3)}{self._c('│', theme['rule'])}")
        print(self._c("╰" + "─" * (width - 2) + "╯", theme["rule"]))

    def alert(self, title: str, lines: Sequence[str], hint: str = "") -> None:
        theme = self.facts.theme
        print()
        print(f"  {self._c('✗ ' + title, theme['ember'], True)}")
        for line in lines:
            print(f"    {line}")
        if hint:
            print(f"\n  {self._c('hint · ' + hint, theme['faint'])}")


def build_live_ui(facts: Facts):
    """Build a rich-powered UI, or return None when rich is not importable."""
    try:
        from rich import box
        from rich.console import Console, Group
        from rich.live import Live
        from rich.panel import Panel
        from rich.spinner import Spinner
        from rich.table import Table
        from rich.text import Text
        from rich.theme import Theme
    except Exception:
        return None

    theme = facts.theme
    styles = Theme(
        {
            "tb.paper": theme["paper"],
            "tb.faint": theme["faint"],
            "tb.rule": theme["rule"],
            "tb.ember": theme["ember"],
            "tb.signal": theme["signal"],
            "tb.seal": theme["seal"],
            "tb.wait": theme["wait"],
            "tb.label": f"bold {theme['paper']}",
        }
    )

    class LiveUi(BaseUi):
        def __init__(self, facts: Facts) -> None:
            super().__init__(facts)
            self.console = Console(theme=styles, highlight=False, emoji=False)
            self.art, self.art_cols = pick_art(self.console.width)
            self.spinners: dict[str, Spinner] = {}
            self.live: Live | None = None

        # -- chrome ---------------------------------------------------------
        def _wordmark(self) -> Text:
            stops = [theme[name] for name in RAMP]
            out = Text()
            if not self.art:
                for col, ch in enumerate("TASKBRIDGE"):
                    out.append(ch, style=f"bold {mix(stops, col / 9)}")
                return out
            for index, line in enumerate(self.art):
                for col, ch in enumerate(line):
                    out.append(ch, style=f"bold {mix(stops, col / max(1, self.art_cols - 1))}")
                if index != len(self.art) - 1:
                    out.append("\n")
            return out

        def _banner(self) -> Panel:
            body = Group(
                self._wordmark(),
                Text(),
                Text("MCP bridge between your assistant and the opencode worker", style="tb.paper"),
                Text(
                    f"python {self.facts.python}  ·  {self.facts.platform}  ·  port {self.facts.port}"
                    "  ·  bearer auth over streamable HTTP",
                    style="tb.faint",
                ),
            )
            return Panel(
                body,
                box=box.ROUNDED,
                border_style="tb.rule",
                padding=(1, 2),
                title="[tb.faint]TaskBridge installer[/]",
                title_align="left",
            )

        def _checklist_panel(self, live_view: bool = False) -> Panel:
            table = Table.grid(padding=(0, 2))
            table.add_column(justify="left")             # glyph / spinner
            table.add_column(justify="left")             # step name
            table.add_column(justify="left", ratio=1)    # detail
            table.add_column(justify="right")            # timing
            glyphs = {
                "ok": ("✓", "tb.seal"),
                "warn": ("!", "tb.signal"),
                "fail": ("✗", "tb.ember"),
                "pending": ("○", "tb.faint"),
                "running": ("✓", "tb.seal"),
            }
            for step in self.steps:
                if step.state == "running" and live_view:
                    glyph = self.spinners.setdefault(step.key, Spinner("dots", style="tb.signal"))
                    label = Text(step.label, style="tb.label")
                    detail = Text(step.detail, style="tb.paper")
                    timing = Text("")
                else:
                    char, colour = glyphs[step.state]
                    glyph = Text(char, style=colour)
                    label = Text(step.label, style="tb.faint" if step.state == "pending" else "tb.label")
                    detail = Text(step.detail, style="tb.faint")
                    timing = Text(human(step.seconds) if step.seconds else "", style="tb.faint")
                table.add_row(glyph, label, detail, timing)
            done = sum(1 for step in self.steps if step.state in ("ok", "warn", "fail"))
            return Panel(
                table,
                box=box.ROUNDED,
                border_style="tb.rule",
                padding=(0, 1),
                title=f"[tb.faint]install[/] [tb.faint]{done}/{len(self.steps)}[/]",
                title_align="left",
            )

        def _render(self):
            blocks: list = [self._checklist_panel(live_view=True)]
            if self.activity:
                blocks.append(Text(f"  {self.activity}", style="tb.faint", no_wrap=True, overflow="ellipsis"))
            return Panel(
                Group(*blocks),
                box=box.ROUNDED,
                border_style="tb.rule",
                padding=(0, 1),
            )

        # -- lifecycle ------------------------------------------------------
        def open(self) -> None:
            self.console.print()
            self.console.print(self._banner())
            self.console.print()
            self.live = Live(self._render(), console=self.console, refresh_per_second=12, transient=True, vertical_overflow="visible")
            self.live.start()

        def close(self) -> None:
            if self._closed:
                return
            self._stop_live()
            # Leave the completed checklist on screen as the run's receipt.
            self.console.print(self._checklist_panel(live_view=False))
            super().close()

        def refresh(self) -> None:
            if self.live is not None:
                self.live.update(self._render())

        # -- events ---------------------------------------------------------
        def ask(self, question: str, hint: str = "") -> str | None:
            self._stop_live()
            self.console.print()
            self.console.print(
                Panel(
                    Group(*(Text(line, style="tb.paper") for line in [question, *([hint] if hint else [])])),
                    box=box.ROUNDED,
                    border_style="tb.rule",
                    padding=(0, 2),
                    title="[tb.signal]ngrok[/]",
                    title_align="left",
                )
            )
            return ask_secret("Authtoken (input hidden · Enter to skip)")

        def note(self, text: str) -> None:
            self._with_live_paused(lambda: self.console.print(Text(text, style="tb.faint")))

        def panel(self, title: str, rows: Iterable[tuple[str, str]], subtitle: str = "") -> None:
            def emit() -> None:
                table = Table.grid(padding=(0, 2))
                table.add_column(justify="left", no_wrap=True)
                table.add_column(justify="left", ratio=1, overflow="fold")
                for key, value in rows:
                    table.add_row(Text(key, style="tb.faint"), Text(value, style="tb.paper"))
                self.console.print(
                    Panel(
                        table,
                        box=box.ROUNDED,
                        border_style="tb.rule",
                        padding=(1, 2),
                        title=f"[tb.seal]{title}[/]",
                        title_align="left",
                        subtitle=f"[tb.faint]{subtitle}[/]" if subtitle else None,
                        subtitle_align="right",
                    )
                )

            self._with_live_paused(emit)

        def alert(self, title: str, lines: Sequence[str], hint: str = "") -> None:
            def emit() -> None:
                body = Group(
                    *(Text(line, style="tb.paper") for line in lines),
                    *([Text(), Text(f"hint · {hint}", style="tb.faint")] if hint else []),
                )
                self.console.print()
                self.console.print(
                    Panel(
                        body,
                        box=box.ROUNDED,
                        border_style="tb.ember",
                        padding=(1, 2),
                        title=f"[bold {theme['ember']}]✗ {title}[/]",
                        title_align="left",
                    )
                )

            self._with_live_paused(emit)

        # -- internals ------------------------------------------------------
        def _stop_live(self) -> None:
            if self.live is not None:
                self.live.stop()
                self.live = None

        def _with_live_paused(self, emit: Callable[[], None]) -> None:
            was_live = self.live is not None
            self._stop_live()
            try:
                emit()
            finally:
                if was_live and not self._closed:
                    self.live = Live(self._render(), console=self.console, refresh_per_second=12, transient=True, vertical_overflow="visible")
                    self.live.start()

    return LiveUi(facts)


# --------------------------------------------------------------------------- #
# install steps
# --------------------------------------------------------------------------- #
@dataclass
class Tracker:
    ui: BaseUi

    @contextlib.contextmanager
    def step(self, key: str, label: str, detail: str = ""):
        step = self.ui.add(key, label)
        self.ui.start(step, detail)
        try:
            yield step
        except SetupError as exc:
            self.ui.finish(step, "fail", str(exc))
            raise
        except Exception as exc:  # unexpected: report it instead of a bare traceback
            self.ui.finish(step, "fail", f"{type(exc).__name__}: {exc}")
            raise SetupError(f"{label} failed") from exc
        else:
            self.ui.finish(step, "warn" if step.state == "warn" else "ok", step.detail)


def install_requirements(ui: BaseUi) -> str:
    if not PIP.exists():
        raise SetupError("pip is missing from .venv", hint="delete the .venv directory and re-run ./install.sh")
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    collecting: set[str] = set()
    installed: list[str] = []

    def on_line(line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        if stripped.startswith(("Collecting ", "Downloading ")):
            collecting.add(stripped.split(" ", 1)[1].split(" ", 1)[0].strip("()"))
            ui.say(f"pip · {stripped[:110]}")
        elif stripped.startswith("Successfully installed"):
            installed.extend(stripped.split("Successfully installed", 1)[1].split())
        elif stripped.startswith(("Building ", "Installing ", "Using cached ")):
            ui.say(f"pip · {stripped[:110]}")

    code = stream(
        [str(PIP), "install", "-q", "--progress-bar", "off", "-r", str(HERE / "requirements.txt")],
        on_line=on_line,
        env=env,
    )
    ui.say("")
    if code != 0:
        raise SetupError(
            "could not install requirements.txt",
            hint="check the network, then retry: .venv/bin/pip install -r requirements.txt",
        )
    if installed:
        return f"installed {len(installed)} packages"
    if collecting:
        return f"{len(collecting)} packages already satisfied"
    return "requirements satisfied"


def ensure_ngrok(ui: BaseUi, step: Step) -> str:
    found = shutil.which("ngrok")
    if found is None:
        brew = shutil.which("brew")
        if brew is None:
            raise SetupError("ngrok is not installed", hint="download it from https://ngrok.com/download and re-run ./install.sh")
        step.detail = "installing via Homebrew…"
        ui.say("brew · installing ngrok/ngrok/ngrok")
        code = subprocess.run([brew, "install", "-q", "ngrok/ngrok/ngrok"], capture_output=True, text=True, check=False).returncode
        ui.say("")
        found = shutil.which("ngrok")
        if code != 0 or found is None:
            raise SetupError("could not install ngrok with Homebrew", hint="brew install ngrok/ngrok/ngrok")
        step.detail = "installed via Homebrew"
    version = subprocess.run([found, "version"], capture_output=True, text=True, check=False).stdout.strip()
    match = re.search(r"\d+\.\d+\.\d+", version)
    label = match.group(0) if match else "installed"
    return f"{step.detail} · {label}" if step.detail.startswith("installed") else f"already installed · {label}"


def ngrok_configured() -> bool:
    return subprocess.run(["ngrok", "config", "check"], capture_output=True, text=True, check=False).returncode == 0


def save_authtoken(token: str) -> None:
    result = subprocess.run(["ngrok", "config", "add-authtoken", token], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SetupError("ngrok rejected that Authtoken", hint="copy it again from https://dashboard.ngrok.com/get-started/your-authtoken")


def preflight_auth(ui: BaseUi, args: argparse.Namespace, port: int) -> str:
    """Sort the ngrok Authtoken out before the live checklist starts.

    Only prompts when a tunnel is actually needed and none is running yet.
    """
    provided = (args.ngrok_token or os.environ.get("NGROK_AUTHTOKEN", "")).strip()
    if provided:
        save_authtoken(provided)
        return "saved from --ngrok-token"
    if ngrok_configured():
        return "authtoken already configured"
    if tunnel_for_port(port):
        return "not needed — a tunnel is already running"
    entered = ui.ask(
        "Paste your ngrok Authtoken to open the public tunnel.",
        "It is stored in ngrok.yml, never in this repo. Get one free at dashboard.ngrok.com.",
    )
    if entered is None:
        return "missing — no terminal to prompt on"
    if not entered:
        raise SetupError(
            "ngrok needs an Authtoken to open the public tunnel",
            hint="get one at https://dashboard.ngrok.com/get-started/your-authtoken, then re-run ./install.sh",
        )
    save_authtoken(entered)
    return "authtoken saved to ngrok.yml"


def ensure_token(rotate: bool) -> tuple[str, str]:
    if rotate or not TOKEN_FILE.is_file() or TOKEN_FILE.stat().st_size == 0:
        state = "rotated" if rotate else "generated"
        TOKEN_FILE.write_text(secrets.token_hex(32) + "\n")
        os.chmod(TOKEN_FILE, 0o600)
        return TOKEN_FILE.read_text().strip(), state
    return TOKEN_FILE.read_text().strip(), "reused"


def tunnel_for_port(port: int) -> str:
    for tunnel in http_json(NGROK_API, timeout=2).get("tunnels", []):
        address = tunnel.get("config", {}).get("addr", "")
        url = tunnel.get("public_url", "")
        if address.endswith(f":{port}") and url.startswith("https://"):
            return url
    return ""


def ensure_tunnel(ui: BaseUi, step: Step, port: int) -> tuple[str, str]:
    url = tunnel_for_port(port)
    if url:
        step.detail = f"reusing the live tunnel for port {port}"
        return url, "reused"

    domain = NGROK_DOMAIN_FILE.read_text().strip() if NGROK_DOMAIN_FILE.is_file() else ""
    if domain:
        command = ["ngrok", "http", f"--url={domain}", str(port)]
        step.detail = f"opening the reserved domain {domain}…"
    else:
        command = ["ngrok", "http", str(port), "--log=stdout"]
        step.detail = f"opening a tunnel to 127.0.0.1:{port}…"
    with NGROK_LOG.open("w") as log:
        subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=str(HERE))
    for attempt in range(1, 16):
        time.sleep(1)
        ui.say(f"ngrok · waiting for the public URL… {attempt}/15")
        url = tunnel_for_port(port)
        if url:
            ui.say("")
            step.detail = f"started in {human(attempt)}"
            return url, "started"
    ui.say("")
    raise SetupError(
        "ngrok did not publish a public URL within 15s",
        hint=(f"last ngrok.log lines: {' / '.join(last_lines(NGROK_LOG, 3))}" if last_lines(NGROK_LOG, 3) else "re-run and paste a fresh Authtoken"),
    )


def run_setup(ui: BaseUi, facts: Facts, args: argparse.Namespace) -> None:
    track = Tracker(ui)

    with track.step("runtime", "python runtime", "checking .venv…") as step:
        if not PY.exists():
            raise SetupError(".venv is missing or incomplete", hint="delete the .venv directory and re-run ./install.sh")
        version = subprocess.run(
            [str(PY), "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
            capture_output=True, text=True, check=False, timeout=30,
        ).stdout.strip()
        facts.python = version or "3.12"
        facts.venv_ready = True
        step.detail = f"{facts.python} · {VENV.name}/ ready"

    with track.step("deps", "dependencies", "resolving requirements.txt…") as step:
        facts.deps_state = install_requirements(ui)
        step.detail = facts.deps_state

    with track.step("ngrok", "ngrok transport", "looking for ngrok…") as step:
        facts.ngrok_version = ensure_ngrok(ui, step)
        step.detail = facts.ngrok_version

    with track.step("auth", "ngrok account", "checking the Authtoken…") as step:
        step.detail = facts.auth_state

    with track.step("token", "bearer token", "reading .bridge-token…") as step:
        facts.token, facts.token_state = ensure_token(args.rotate)
        step.detail = {
            "reused": "reused .bridge-token",
            "generated": "generated · .bridge-token (mode 600)",
            "rotated": "rotated · .bridge-token (mode 600)",
        }[facts.token_state]

    with track.step("tunnel", "public tunnel", "asking ngrok for the current tunnels…") as step:
        facts.public_url, facts.tunnel_state = ensure_tunnel(ui, step, facts.port)

    with track.step("worker", "opencode CLI", "checking PATH…") as step:
        facts.opencode_cli = shutil.which("opencode") is not None
        if facts.opencode_cli:
            step.detail = "on PATH · the worker can run jobs"
        else:
            step.state = "warn"
            step.detail = "not on PATH — the worker needs it, the server does not"


# --------------------------------------------------------------------------- #
# summary + serve
# --------------------------------------------------------------------------- #
def stop_previous_server() -> bool:
    return subprocess.run(["pkill", "-f", SERVE_MARK], capture_output=True, text=True, check=False).returncode == 0


def wait_for_port(ui: BaseUi, port: int, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    announced = False
    while time.monotonic() < deadline:
        if port_is_free(port):
            return True
        if not announced and time.monotonic() - (deadline - timeout) > 1.5:
            ui.note(f"waiting for the previous instance to release port {port}…")
            announced = True
        time.sleep(0.3)
    return port_is_free(port)


def promote(ui: BaseUi, facts: Facts) -> None:
    mcp_url = f"{facts.public_url}/mcp"
    ui.panel(
        "ready",
        [
            ("MCP URL", mcp_url),
            ("Bearer token", facts.token),
            ("Token file", str(TOKEN_FILE)),
            ("Dashboard", f"{facts.public_url}/  (asks for the token)"),
        ],
        subtitle=f"{human(time.monotonic() - facts.started)} total",
    )
    ui.panel(
        "connect a client",
        [
            ("Claude / ChatGPT", f"URL     {mcp_url}\nHeader  Authorization: Bearer {facts.token}"),
            ("Claude Desktop", "stdio mode — no URL or token needed"),
            ("Health check", f"curl {facts.public_url}/health"),
            ("Rotate token", "./install.sh --rotate"),
            ("Stop server", "Ctrl+C — the ngrok tunnel stays up"),
        ],
    )
    if not facts.opencode_cli:
        ui.note("! opencode CLI is missing — install it so the worker can execute jobs.")


def serve(ui: BaseUi, facts: Facts) -> int:
    replaced = stop_previous_server()
    ui.panel(
        "server",
        [
            ("Listening", f"http://127.0.0.1:{facts.port}" + ("  ·  replaced the previous instance" if replaced else "")),
            ("Tunnel", f"{facts.public_url} → 127.0.0.1:{facts.port}"),
            ("Stop", "Ctrl+C stops the server; the ngrok tunnel stays up"),
        ],
    )
    if not wait_for_port(ui, facts.port):
        ui.note(f"! port {facts.port} is still busy — the server may fail to bind.")

    env = dict(os.environ)
    env["MCP_ALLOWED_HOSTS"] = facts.public_url.removeprefix("https://")
    env["BRIDGE_AUTH_TOKEN"] = facts.token
    os.chdir(HERE)
    os.execve(str(PY), [str(PY), str(SERVER), "--transport", "streamable-http", "--port", str(facts.port)], env)
    return 0  # unreachable


# --------------------------------------------------------------------------- #
# entrypoint
# --------------------------------------------------------------------------- #
def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install.sh",
        description="Install and launch TaskBridge — the MCP bridge between Claude/ChatGPT and the local opencode worker.",
    )
    parser.add_argument("--rotate", action="store_true", help="regenerate the bearer token before serving")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")), help="MCP server port (default 8000)")
    parser.add_argument("--ngrok-token", default="", help="ngrok Authtoken to save before opening the tunnel")
    parser.add_argument("--no-serve", action="store_true", help="set everything up and print credentials, but do not start the server")
    parser.add_argument("--plain", action="store_true", help="line output only — no live dashboard")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    os.chdir(HERE)
    facts = Facts(port=args.port, platform=sys.platform)
    ui: BaseUi = PlainUi(facts)
    if not args.plain and sys.stdout.isatty():
        ui = build_live_ui(facts) or ui

    ui.open()
    try:
        facts.auth_state = preflight_auth(ui, args, args.port)
        run_setup(ui, facts, args)
    except SetupError as exc:
        ui.close()
        ui.alert(str(exc) or "setup failed", [], hint=exc.hint)
        ui.note("nothing was started — fix the problem above and re-run ./install.sh")
        return 1
    except KeyboardInterrupt:
        ui.close()
        ui.note("aborted — nothing else was started")
        return 130
    ui.close()
    promote(ui, facts)
    if args.no_serve:
        ui.note("--no-serve: stopping before the server starts.")
        return 0
    return serve(ui, facts)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\naborted")
        raise SystemExit(130)

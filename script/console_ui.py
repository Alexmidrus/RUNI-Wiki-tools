"""Shared console UI helpers: colours, spinner, status output."""

from __future__ import annotations

import sys
import threading
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Console UI
# ---------------------------------------------------------------------------

_IS_TTY = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

# ANSI codes
_RESET   = "\033[0m"   if _IS_TTY else ""
_BOLD    = "\033[1m"    if _IS_TTY else ""
_DIM     = "\033[2m"    if _IS_TTY else ""
_CYAN    = "\033[36m"   if _IS_TTY else ""
_GREEN   = "\033[32m"   if _IS_TTY else ""
_YELLOW  = "\033[33m"   if _IS_TTY else ""
_MAGENTA = "\033[35m"   if _IS_TTY else ""
_WHITE   = "\033[97m"   if _IS_TTY else ""
_ERASE   = "\033[2K\r"  if _IS_TTY else ""

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"] if _IS_TTY else ["-"]
_CHECK  = f"{_GREEN}✓{_RESET}" if _IS_TTY else "[ok]"
_ARROW  = f"{_CYAN}▸{_RESET}" if _IS_TTY else ">"
_BULLET = f"{_DIM}│{_RESET}"  if _IS_TTY else "|"


class Spinner:
    """Animated spinner shown on stderr while a long operation runs."""

    def __init__(self, message: str) -> None:
        self._message = message
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._detail = ""
        self._lock = threading.Lock()

    def update(self, detail: str) -> None:
        with self._lock:
            self._detail = detail

    def _run(self) -> None:
        idx = 0
        while not self._stop.is_set():
            frame = _SPINNER_FRAMES[idx % len(_SPINNER_FRAMES)]
            with self._lock:
                detail = self._detail
            line = f"  {_CYAN}{frame}{_RESET} {self._message}"
            if detail:
                line += f"  {_DIM}{detail}{_RESET}"
            sys.stderr.write(f"{_ERASE}{line}")
            sys.stderr.flush()
            idx += 1
            self._stop.wait(0.08)
        sys.stderr.write(_ERASE)
        sys.stderr.flush()

    def __enter__(self) -> "Spinner":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()


def _header(text: str) -> None:
    sys.stderr.write(f"\n  {_BOLD}{_WHITE}{text}{_RESET}\n")
    sys.stderr.flush()


def _step_done(text: str, detail: str = "") -> None:
    suffix = f"  {_DIM}{detail}{_RESET}" if detail else ""
    sys.stderr.write(f"  {_CHECK} {text}{suffix}\n")
    sys.stderr.flush()


def _info(text: str) -> None:
    sys.stderr.write(f"  {_BULLET} {text}\n")
    sys.stderr.flush()


def _summary_box(rows: List[Tuple[str, str, str, str, str]]) -> None:
    """Print a neat summary table. Each row: (label, detected, exported, filtered, file)."""
    sys.stderr.write(f"\n  {_BOLD}{_WHITE}Результаты{_RESET}\n")
    sys.stderr.write(f"  {_DIM}{'─' * 60}{_RESET}\n")
    for label, detected, exported, filtered, filepath in rows:
        sys.stderr.write(
            f"  {_ARROW} {_BOLD}{label:<12}{_RESET}"
            f"  найдено {_CYAN}{detected:>5}{_RESET}"
            f"  экспорт {_GREEN}{exported:>5}{_RESET}"
        )
        if filtered != "0":
            sys.stderr.write(f"  {_DIM}(−{filtered} отфильтровано){_RESET}")
        sys.stderr.write(f"\n    {_DIM}{filepath}{_RESET}\n")
    sys.stderr.write(f"  {_DIM}{'─' * 60}{_RESET}\n\n")
    sys.stderr.flush()

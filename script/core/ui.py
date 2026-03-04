"""Shared console UI helpers: colours, spinner, status output (OOP approach)."""

from __future__ import annotations

import sys
import threading
from typing import List, Optional, Tuple


class ConsoleUI:
    """Encapsulates console output configuration, colors, and formatting methods."""

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stderr
        self._is_tty = hasattr(self._stream, "isatty") and self._stream.isatty()

        # ANSI codes
        self.reset   = "\033[0m"   if self._is_tty else ""
        self.bold    = "\033[1m"   if self._is_tty else ""
        self.dim     = "\033[2m"   if self._is_tty else ""
        self.cyan    = "\033[36m"  if self._is_tty else ""
        self.green   = "\033[32m"  if self._is_tty else ""
        self.yellow  = "\033[33m"  if self._is_tty else ""
        self.magenta = "\033[35m"  if self._is_tty else ""
        self.white   = "\033[97m"  if self._is_tty else ""
        self.erase   = "\033[2K\r" if self._is_tty else ""

        self.check  = f"{self.green}✓{self.reset}" if self._is_tty else "[ok]"
        self.arrow  = f"{self.cyan}▸{self.reset}" if self._is_tty else ">"
        self.bullet = f"{self.dim}│{self.reset}"  if self._is_tty else "|"
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"] if self._is_tty else ["-"]

    def header(self, text: str) -> None:
        self._stream.write(f"\n  {self.bold}{self.white}{text}{self.reset}\n")
        self._stream.flush()

    def step_done(self, text: str, detail: str = "") -> None:
        suffix = f"  {self.dim}{detail}{self.reset}" if detail else ""
        self._stream.write(f"  {self.check} {text}{suffix}\n")
        self._stream.flush()

    def info(self, text: str) -> None:
        self._stream.write(f"  {self.bullet} {text}\n")
        self._stream.flush()
        
    def error(self, text: str) -> None:
        self._stream.write(f"\n  {self.yellow}Ошибка:{self.reset} {text}\n")
        self._stream.flush()

    def summary_box(self, rows: List[Tuple[str, str, str, str, str]]) -> None:
        """Print a neat summary table. Each row: (label, detected, exported, filtered, file)."""
        self._stream.write(f"\n  {self.bold}{self.white}Результаты{self.reset}\n")
        self._stream.write(f"  {self.dim}{'─' * 60}{self.reset}\n")
        for label, detected, exported, filtered, filepath in rows:
            self._stream.write(
                f"  {self.arrow} {self.bold}{label:<12}{self.reset}"
                f"  найдено {self.cyan}{detected:>5}{self.reset}"
                f"  экспорт {self.green}{exported:>5}{self.reset}"
            )
            if filtered != "0":
                self._stream.write(f"  {self.dim}(−{filtered} отфильтровано){self.reset}")
            self._stream.write(f"\n    {self.dim}{filepath}{self.reset}\n")
        self._stream.write(f"  {self.dim}{'─' * 60}{self.reset}\n\n")
        self._stream.flush()

    def spinner(self, message: str) -> 'Spinner':
        return Spinner(message, self)

    def print_stdout(self, text: str) -> None:
        print(text)


class Spinner:
    """Animated spinner shown on stderr while a long operation runs."""

    def __init__(self, message: str, ui: ConsoleUI) -> None:
        self._message = message
        self._ui = ui
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
            frame = self._ui.spinner_frames[idx % len(self._ui.spinner_frames)]
            with self._lock:
                detail = self._detail
            line = f"  {self._ui.cyan}{frame}{self._ui.reset} {self._message}"
            if detail:
                line += f"  {self._ui.dim}{detail}{self._ui.reset}"
            self._ui._stream.write(f"{self._ui.erase}{line}")
            self._ui._stream.flush()
            idx += 1
            self._stop.wait(0.08)
        self._ui._stream.write(self._ui.erase)
        self._ui._stream.flush()

    def __enter__(self) -> "Spinner":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()

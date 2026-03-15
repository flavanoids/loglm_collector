"""Real-time log scout — monitors /var/log and journalctl for errors over a set duration."""

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rich.console import Console

console = Console(stderr=True)

# Severity keywords used to flag a line as noteworthy.
_ERROR_RE = re.compile(
    r"\b(emerg|alert|crit(?:ical)?|err(?:or)?|fail(?:ed|ure)?|panic|oops|oom|segfault|timeout|refused|denied)\b",
    re.IGNORECASE,
)

# Files/directories to skip (binary, rotated archives, etc.)
_SKIP_SUFFIXES = {".gz", ".xz", ".bz2", ".zst", ".1", ".2", ".3", ".4"}
_SKIP_NAMES = {"btmp", "wtmp", "lastlog", "faillog"}


@dataclass
class ScoutHit:
    """A single noteworthy line captured during scouting."""

    source: str
    line: str
    keyword: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ScoutResult:
    """Aggregated results from a scouting session."""

    duration_seconds: int
    hits: list[ScoutHit] = field(default_factory=list)

    @property
    def sources(self) -> dict[str, list[ScoutHit]]:
        """Group hits by source."""
        grouped: dict[str, list[ScoutHit]] = {}
        for hit in self.hits:
            grouped.setdefault(hit.source, []).append(hit)
        return grouped

    @property
    def total(self) -> int:
        return len(self.hits)


class LogScout:
    """Monitors log files and journalctl in real-time, collecting error-level lines."""

    def __init__(self, duration_seconds: int, log_dir: str = "/var/log") -> None:
        self.duration = duration_seconds
        self.log_dir = log_dir
        self._hits: list[ScoutHit] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ── public API ────────────────────────────────────────────────────────

    def run(self, on_hit=None) -> ScoutResult:
        """Run the scout for the configured duration.

        *on_hit* is an optional callback ``(ScoutHit) -> None`` invoked for
        each new hit so callers can show live progress.
        """
        self._hits.clear()
        self._stop.clear()
        self._on_hit = on_hit

        threads: list[threading.Thread] = []

        # Thread 1: journalctl -f
        t_journal = threading.Thread(target=self._watch_journal, daemon=True)
        threads.append(t_journal)

        # Thread 2+: tail each readable log file
        for path in self._discover_log_files():
            t = threading.Thread(target=self._tail_file, args=(path,), daemon=True)
            threads.append(t)

        for t in threads:
            t.start()

        # Wait for the scouting duration.
        self._stop.wait(timeout=self.duration)
        self._stop.set()

        # Give threads a moment to wind down.
        for t in threads:
            t.join(timeout=2)

        return ScoutResult(duration_seconds=self.duration, hits=list(self._hits))

    def stop(self) -> None:
        """Signal all watchers to stop early."""
        self._stop.set()

    # ── internal ──────────────────────────────────────────────────────────

    def _record(self, source: str, line: str, keyword: str) -> None:
        hit = ScoutHit(source=source, line=line.strip(), keyword=keyword)
        with self._lock:
            self._hits.append(hit)
        if self._on_hit:
            try:
                self._on_hit(hit)
            except Exception:  # pylint: disable=broad-except
                pass

    def _matches(self, line: str) -> str | None:
        """Return the first error keyword found in *line*, or None."""
        m = _ERROR_RE.search(line)
        return m.group(1).lower() if m else None

    def _discover_log_files(self) -> list[str]:
        """Return readable text files under /var/log (non-recursive for safety)."""
        results: list[str] = []
        try:
            for entry in os.scandir(self.log_dir):
                if not entry.is_file():
                    continue
                if entry.name in _SKIP_NAMES:
                    continue
                if any(entry.name.endswith(s) for s in _SKIP_SUFFIXES):
                    continue
                if os.access(entry.path, os.R_OK):
                    # Quick binary check: try reading a small chunk.
                    try:
                        with open(entry.path, "r", encoding="utf-8") as fh:
                            fh.read(256)
                        results.append(entry.path)
                    except (UnicodeDecodeError, OSError):
                        continue
        except OSError:
            pass
        return results

    def _tail_file(self, path: str) -> None:
        """Tail a single file, checking for new lines until stopped."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                # Seek to end so we only see new content.
                fh.seek(0, os.SEEK_END)
                while not self._stop.is_set():
                    line = fh.readline()
                    if line:
                        kw = self._matches(line)
                        if kw:
                            self._record(path, line, kw)
                    else:
                        # No new data — short sleep to avoid busy-loop.
                        time.sleep(0.25)
        except OSError:
            pass

    def _watch_journal(self) -> None:
        """Stream ``journalctl -f`` and capture error-level lines."""
        try:
            proc = subprocess.Popen(
                ["journalctl", "-f", "-o", "short-iso", "--no-pager"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError:
            return

        try:
            assert proc.stdout is not None
            while not self._stop.is_set():
                line = proc.stdout.readline()
                if not line:
                    break
                kw = self._matches(line)
                if kw:
                    self._record("journalctl", line, kw)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

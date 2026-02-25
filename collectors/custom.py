"""Collector for user-defined custom log sources from templates."""

import glob as globmod
import re

from collectors.base import BaseCollector, LogEntry


class CustomSourceCollector(BaseCollector):
    """Collects log lines from user-defined file paths and globs."""

    def __init__(self, sources: list) -> None:
        # sources: list[CustomSource] — typed loosely to avoid circular import
        self._sources = sources

    def get_name(self) -> str:
        return "Custom Sources"

    def get_description(self) -> str:
        return f"{len(self._sources)} user-defined log source(s)"

    def get_log_sources(self) -> list[str]:
        return [s.describe() for s in self._sources]

    def collect(self, hours: int) -> list[LogEntry]:
        entries: list[LogEntry] = []
        line_count = max(500, hours * 100)
        for src in self._sources:
            entries.extend(self._collect_source(src, line_count))
        return entries

    def _collect_source(self, src, line_count: int) -> list[LogEntry]:
        pattern = None
        if src.filter_pattern:
            try:
                pattern = re.compile(src.filter_pattern, re.IGNORECASE)
            except re.error:
                pattern = None

        paths = globmod.glob(src.path_glob)
        entries = []
        for path in sorted(paths):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()[-line_count:]
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if pattern and not pattern.search(line):
                        continue
                    entries.append(
                        LogEntry(
                            source=f"custom:{src.name}",
                            message=line,
                            raw=line,
                            level=src.default_level,
                        )
                    )
            except OSError:
                continue
        return entries

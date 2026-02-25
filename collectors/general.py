"""General Linux/systemd log collector."""

import re

from collectors.base import BaseCollector, LogEntry, run_command

_LEVEL_RE = re.compile(r"\b(emerg|alert|crit|err|warning|notice|info|debug)\b", re.IGNORECASE)
_OOM_RE = re.compile(r"oom|killed process|panic|oops", re.IGNORECASE)


def _parse_level(line: str) -> str:
    match = _LEVEL_RE.search(line)
    return match.group(1).lower() if match else "info"


class GeneralCollector(BaseCollector):
    """Collects general Linux system errors, OOM events, auth failures, and failed units."""

    def get_name(self) -> str:
        return "General Linux"

    def get_description(self) -> str:
        return "Kernel panics, OOM events, auth failures, systemd failed units"

    def get_log_sources(self) -> list[str]:
        return [
            "journalctl -p err..emerg",
            "journalctl OOM/panic/oops filter",
            "/var/log/auth.log or /var/log/secure",
            "systemctl --failed",
            "/var/log/kern.log",
        ]

    def collect(self, hours: int) -> list[LogEntry]:
        entries: list[LogEntry] = []
        since = f"{hours} hours ago"

        entries.extend(self._collect_errors(since))
        entries.extend(self._collect_oom(since))
        entries.extend(self._collect_auth(hours))
        entries.extend(self._collect_failed_units())
        entries.extend(self._collect_kern_log(hours))

        return entries

    def _collect_errors(self, since: str) -> list[LogEntry]:
        output = run_command(
            ["journalctl", "-p", "err..emerg", "--since", since, "--no-pager", "-o", "short-iso"],
            timeout=30,
        )
        entries = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            entries.append(
                LogEntry(
                    source="journalctl:errors",
                    message=line,
                    raw=line,
                    level=_parse_level(line),
                )
            )
        return entries

    def _collect_oom(self, since: str) -> list[LogEntry]:
        output = run_command(
            ["journalctl", "-k", "--since", since, "--no-pager", "-o", "short-iso"],
            timeout=30,
        )
        entries = []
        for line in output.splitlines():
            if _OOM_RE.search(line):
                entries.append(
                    LogEntry(
                        source="journalctl:oom",
                        message=line.strip(),
                        raw=line.strip(),
                        level="crit",
                    )
                )
        return entries

    def _collect_auth(self, hours: int) -> list[LogEntry]:
        line_count = max(200, hours * 50)
        for auth_path in ["/var/log/auth.log", "/var/log/secure"]:
            try:
                with open(auth_path, encoding="utf-8") as fh:
                    lines = fh.readlines()
                entries = []
                for line in lines[-line_count:]:
                    lower = line.lower()
                    if any(kw in lower for kw in ("failed", "failure", "invalid", "error", "refused")):
                        entries.append(
                            LogEntry(
                                source=auth_path,
                                message=line.strip(),
                                raw=line.strip(),
                                level="warning",
                            )
                        )
                return entries
            except OSError:
                continue
        return []

    def _collect_failed_units(self) -> list[LogEntry]:
        output = run_command(
            ["systemctl", "--failed", "--no-pager", "--plain"],
            timeout=10,
        )
        entries = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("●") or "0 loaded" in line:
                continue
            if ".service" in line or ".mount" in line or ".socket" in line:
                entries.append(
                    LogEntry(
                        source="systemctl:failed",
                        message=f"Failed unit: {line}",
                        raw=line,
                        level="err",
                    )
                )
        return entries

    def _collect_kern_log(self, hours: int) -> list[LogEntry]:
        line_count = max(500, hours * 100)
        try:
            with open("/var/log/kern.log", encoding="utf-8") as fh:
                lines = fh.readlines()
            entries = []
            for line in lines[-line_count:]:
                lower = line.lower()
                if any(kw in lower for kw in ("critical", "error", "err]", "crit")):
                    entries.append(
                        LogEntry(
                            source="/var/log/kern.log",
                            message=line.strip(),
                            raw=line.strip(),
                            level=_parse_level(line),
                        )
                    )
            return entries
        except OSError:
            return []

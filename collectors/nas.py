"""NAS/storage log collector."""

import re

from collectors.base import BaseCollector, LogEntry, run_command

_STORAGE_RE = re.compile(
    r"ata|scsi|sd[a-z]|nvme|I/O error|ext4.error|xfs|zfs|btrfs|mdadm|raid",
    re.IGNORECASE,
)
_LEVEL_RE = re.compile(r"\b(emerg|alert|crit|err|warning|notice|info|debug)\b", re.IGNORECASE)
_DEV_RE = re.compile(r"^(/dev/(sd[a-z]|nvme\d+n\d+))$")


def _parse_level(line: str) -> str:
    match = _LEVEL_RE.search(line)
    return match.group(1).lower() if match else "info"


class NasCollector(BaseCollector):
    """Collects NAS/storage-related log events: disks, ZFS, mdadm, SMART."""

    def get_name(self) -> str:
        return "NAS / Storage"

    def get_description(self) -> str:
        return "Disk I/O errors, ZFS pool status, mdadm RAID events, SMART errors"

    def get_log_sources(self) -> list[str]:
        return [
            "journalctl -k (storage/disk filter)",
            "/var/log/syslog or /var/log/messages",
            "zpool status",
            "mdadm --detail --scan",
            "smartctl -a <devices>",
        ]

    def collect(self, hours: int) -> list[LogEntry]:
        entries: list[LogEntry] = []
        since = f"{hours} hours ago"

        entries.extend(self._collect_journalctl(since))
        entries.extend(self._collect_syslog(hours))
        entries.extend(self._collect_zpool())
        entries.extend(self._collect_mdadm())
        entries.extend(self._collect_smart())

        return entries

    def _collect_journalctl(self, since: str) -> list[LogEntry]:
        output = run_command(
            ["journalctl", "-k", "--since", since, "--no-pager", "-o", "short-iso"],
            timeout=30,
        )
        entries = []
        for line in output.splitlines():
            if _STORAGE_RE.search(line):
                entries.append(
                    LogEntry(
                        source="journalctl:kernel",
                        message=line.strip(),
                        raw=line.strip(),
                        level=_parse_level(line),
                    )
                )
        return entries

    def _collect_syslog(self, hours: int) -> list[LogEntry]:
        line_count = max(1000, hours * 200)
        for syslog_path in ["/var/log/syslog", "/var/log/messages"]:
            try:
                with open(syslog_path, encoding="utf-8") as fh:
                    lines = fh.readlines()
                entries = []
                for line in lines[-line_count:]:
                    if _STORAGE_RE.search(line):
                        entries.append(
                            LogEntry(
                                source=syslog_path,
                                message=line.strip(),
                                raw=line.strip(),
                                level=_parse_level(line),
                            )
                        )
                return entries
            except OSError:
                continue
        return []

    def _collect_zpool(self) -> list[LogEntry]:
        output = run_command(["zpool", "status"], timeout=15)
        if not output:
            return []
        entries = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            level = "info"
            if any(kw in lower for kw in ("degraded", "faulted", "offline", "unavail", "error")):
                level = "err"
            elif "warning" in lower:
                level = "warning"
            entries.append(
                LogEntry(
                    source="zpool:status",
                    message=line,
                    raw=line,
                    level=level,
                )
            )
        return entries

    def _collect_mdadm(self) -> list[LogEntry]:
        output = run_command(["mdadm", "--detail", "--scan"], timeout=15)
        if not output:
            return []
        entries = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            entries.append(
                LogEntry(
                    source="mdadm:scan",
                    message=line,
                    raw=line,
                    level="info",
                )
            )
        return entries

    def _collect_smart(self) -> list[LogEntry]:
        import glob as globmod

        devices = globmod.glob("/dev/sd?") + globmod.glob("/dev/nvme?n?")
        entries = []
        for dev in devices:
            output = run_command(["smartctl", "-a", dev], timeout=20)
            if not output:
                continue
            for line in output.splitlines():
                lower = line.lower()
                if any(kw in lower for kw in ("error", "fail", "reallocated", "uncorrectable", "bad")):
                    entries.append(
                        LogEntry(
                            source=f"smartctl:{dev}",
                            message=line.strip(),
                            raw=line.strip(),
                            level="err",
                        )
                    )
        return entries

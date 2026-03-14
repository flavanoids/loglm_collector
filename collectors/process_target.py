"""Process/service/container target collector for loglm_collector.

Collects logs for a user-chosen target: PID, systemd unit, or container.
Discovery is generic (systemd, container runtimes) with no product names
in user-facing strings.
"""

import shutil
from dataclasses import dataclass
from typing import Literal

from collectors.base import BaseCollector, LogEntry, run_command

# Container runtimes: (binary name, args to list containers).
# List command must output lines like "ID\tNAME" for matching.
_CONTAINER_LIST = [
    ("docker", ["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}"]),
    ("podman", ["podman", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}"]),
]

TOP_PROCESSES_LIMIT = 5


@dataclass
class ProcessTarget:
    """Resolved target for process/service log collection."""

    kind: Literal["pid", "unit", "container", "containers_all", "containers_selected"]
    value: str  # pid, unit name, container id, or comma-separated ids for containers_selected
    runtime_bin: str | None = None  # for container(s): path to runtime binary
    display_name: str = ""  # human-readable label for logs


def get_top_processes(limit: int = TOP_PROCESSES_LIMIT) -> list[tuple[int, str]]:
    """Return up to `limit` processes, sorted by CPU usage (highest first)."""
    # ps -e -o pid,pcpu,comm --no-headers; sort by pcpu; take first `limit`
    out = run_command(
        ["ps", "-e", "-o", "pid,pcpu,comm", "--no-headers"],
        timeout=5,
    )
    rows: list[tuple[float, int, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            pcpu_str = parts[1].replace(",", ".")
            pcpu = float(pcpu_str) if pcpu_str and pcpu_str != "-" else 0.0
            comm = parts[2].strip() or f"pid:{pid}"
        except (ValueError, IndexError):
            continue
        rows.append((pcpu, pid, comm))
    rows.sort(key=lambda x: (-x[0], x[1]))
    seen_pid: set[int] = set()
    result: list[tuple[int, str]] = []
    for _pcpu, pid, comm in rows:
        if pid in seen_pid:
            continue
        seen_pid.add(pid)
        result.append((pid, comm))
        if len(result) >= limit:
            break
    return result


def _resolve_systemd_unit(name: str) -> str | None:
    """Return the unit name to use for journalctl if name is a loaded unit, else None."""
    for unit in (name, f"{name}.service"):
        out = run_command(
            ["systemctl", "show", unit, "-p", "LoadState", "--value"],
            timeout=5,
        )
        if out.strip() in ("loaded", "active"):
            return unit
    return None


def _find_container_runtime() -> tuple[str | None, list[str] | None]:
    """Return (path_to_binary, list_cmd) for first available container runtime."""
    for binary, list_cmd in _CONTAINER_LIST:
        path = shutil.which(binary)
        if path:
            return (path, list_cmd)
    return (None, None)


def _list_containers(runtime_path: str, list_cmd: list[str]) -> list[tuple[str, str]]:
    """Return list of (id, name) for containers. Uses runtime_path for first element."""
    cmd = [runtime_path] + list_cmd[1:]
    out = run_command(cmd, timeout=10)
    result: list[tuple[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        id_part, name_part = line.split("\t", 1)
        cid = id_part.strip()
        cname = name_part.strip() or cid[:12]
        if cid:
            result.append((cid, cname))
    return result


def _collect_single_container_logs(
    runtime_bin: str, cid: str, display_name: str, since: str
) -> list[LogEntry]:
    """Fetch logs for one container; return list of LogEntry."""
    out = run_command(
        [runtime_bin, "logs", "--since", since, cid],
        timeout=60,
    )
    source = f"container:{display_name}"
    entries: list[LogEntry] = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            entries.append(
                LogEntry(source=source, message=line, raw=line, level="info")
            )
    return entries


def _collect_multi_container_logs(
    runtime_bin: str,
    containers: list[tuple[str, str]],
    since: str,
) -> list[LogEntry]:
    """Fetch logs for multiple containers; return combined list of LogEntry."""
    entries: list[LogEntry] = []
    for cid, cname in containers:
        entries.extend(
            _collect_single_container_logs(
                runtime_bin, cid, cname or cid[:12], since
            )
        )
    return entries


def get_container_runtime_info() -> tuple[str, list[tuple[str, str]]] | None:
    """If a container runtime is available, return (runtime_path, [(id, name), ...]). Else None."""
    runtime_path, list_cmd = _find_container_runtime()
    if not runtime_path or not list_cmd:
        return None
    containers = _list_containers(runtime_path, list_cmd)
    if not containers:
        return None
    return (runtime_path, containers)


def resolve_target(user_input: str) -> ProcessTarget | None:
    """Resolve user input to a ProcessTarget (PID, unit, or container). Returns None if unresolved."""
    raw = user_input.strip()
    if not raw:
        return None

    # 1) All digits → PID
    if raw.isdigit():
        return ProcessTarget(
            kind="pid",
            value=raw,
            display_name=f"PID {raw}",
        )

    # 2) Systemd unit (service name, with or without .service)
    resolved_unit = _resolve_systemd_unit(raw)
    if resolved_unit:
        return ProcessTarget(
            kind="unit",
            value=resolved_unit,
            display_name=raw,
        )

    # 3) Container: match id or name from first available runtime
    runtime_path, list_cmd = _find_container_runtime()
    if runtime_path and list_cmd:
        for cid, cname in _list_containers(runtime_path, list_cmd):
            if raw == cid or raw == cname or cid.startswith(raw) or raw.lower() in cname.lower():
                return ProcessTarget(
                    kind="container",
                    value=cid,
                    runtime_bin=runtime_path,
                    display_name=cname or cid[:12],
                )

    return None


class ProcessTargetCollector(BaseCollector):
    """Collects logs for a single process target (PID, systemd unit, or container)."""

    def __init__(self, target: ProcessTarget, hours: int) -> None:
        self._target = target
        self._hours = hours

    def get_name(self) -> str:
        return f"Process / service: {self._target.display_name or self._target.value}"

    def get_description(self) -> str:
        return f"Logs for {self._target.display_name or self._target.value}"

    def get_log_sources(self) -> list[str]:
        if self._target.kind == "pid":
            return [f"journalctl _PID={self._target.value}"]
        if self._target.kind == "unit":
            return [f"journalctl -u {self._target.value}"]
        if self._target.kind == "containers_all":
            return ["Container logs: all containers"]
        if self._target.kind == "containers_selected":
            return [f"Container logs: {self._target.display_name}"]
        return [f"Container logs: {self._target.value} ({self._target.display_name})"]

    def collect(self, hours: int) -> list[LogEntry]:
        since = f"{hours}h"
        entries: list[LogEntry] = []

        if self._target.kind == "pid":
            out = run_command(
                [
                    "journalctl",
                    f"_PID={self._target.value}",
                    "--since", since,
                    "--no-pager", "-o", "short-iso",
                ],
                timeout=30,
            )
            source = f"journalctl:pid{self._target.value}"
            for line in out.splitlines():
                line = line.strip()
                if line and not line.startswith("--"):
                    entries.append(
                        LogEntry(source=source, message=line, raw=line, level="info")
                    )

        elif self._target.kind == "unit":
            out = run_command(
                [
                    "journalctl", "-u", self._target.value,
                    "--since", since,
                    "--no-pager", "-o", "short-iso",
                ],
                timeout=30,
            )
            source = f"journalctl:{self._target.value}"
            for line in out.splitlines():
                line = line.strip()
                if line and not line.startswith("--"):
                    entries.append(
                        LogEntry(source=source, message=line, raw=line, level="info")
                    )

        elif self._target.kind == "container" and self._target.runtime_bin:
            entries.extend(
                _collect_single_container_logs(
                    self._target.runtime_bin,
                    self._target.value,
                    self._target.display_name or self._target.value,
                    since,
                )
            )
        elif self._target.kind == "containers_all" and self._target.runtime_bin:
            _, list_cmd = _find_container_runtime()
            if list_cmd:
                containers = _list_containers(
                    self._target.runtime_bin, list_cmd
                )
                entries.extend(
                    _collect_multi_container_logs(
                        self._target.runtime_bin, containers, since
                    )
                )
        elif self._target.kind == "containers_selected" and self._target.runtime_bin:
            ids = [s.strip() for s in self._target.value.split(",") if s.strip()]
            _, list_cmd = _find_container_runtime()
            id_to_name: dict[str, str] = {}
            if list_cmd:
                for cid, cname in _list_containers(
                    self._target.runtime_bin, list_cmd
                ):
                    id_to_name[cid] = cname or cid[:12]
            containers = [(cid, id_to_name.get(cid, cid[:12])) for cid in ids]
            entries.extend(
                _collect_multi_container_logs(
                    self._target.runtime_bin, containers, since
                )
            )

        return entries

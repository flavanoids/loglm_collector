"""Base classes and shared utilities for log collectors."""

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from rich.console import Console

console = Console(stderr=True)


@dataclass
class LogEntry:
    """Represents a single parsed log entry."""

    source: str
    message: str
    raw: str
    timestamp: Optional[datetime] = None
    level: str = "info"
    extra: dict = field(default_factory=dict)


def run_command(cmd: list[str], timeout: int = 30) -> str:
    """Run a subprocess command, return stdout; log stderr to console."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
        )
        if result.stderr:
            console.log(f"[dim]stderr from {cmd[0]}: {result.stderr[:200]}[/dim]")
        return result.stdout
    except FileNotFoundError:
        console.log(f"[yellow]Command not found: {cmd[0]}[/yellow]")
        return ""
    except subprocess.TimeoutExpired:
        console.log(f"[yellow]Command timed out: {' '.join(cmd)}[/yellow]")
        return ""
    except Exception as e:  # pylint: disable=broad-except
        console.log(f"[red]Error running {cmd[0]}: {e}[/red]")
        return ""


class BaseCollector(ABC):
    """Abstract base class for all log collectors."""

    @abstractmethod
    def collect(self, hours: int) -> list[LogEntry]:
        """Collect log entries from the past N hours."""

    @abstractmethod
    def get_name(self) -> str:
        """Return human-readable collector name."""

    @abstractmethod
    def get_description(self) -> str:
        """Return a brief description of what this collector gathers."""

    @abstractmethod
    def get_log_sources(self) -> list[str]:
        """Return list of log source descriptions."""

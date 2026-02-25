"""Interactive rich-based menu for loglm_collector."""

from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from collectors.base import BaseCollector
from collectors import COLLECTOR_REGISTRY
from detector import DetectionResult

console = Console()

HOURS_OPTIONS = {
    "1": 1,
    "2": 6,
    "3": 24,
    "4": 168,
}

HOURS_LABELS = {
    "1": "Last 1 hour",
    "2": "Last 6 hours",
    "3": "Last 24 hours",
    "4": "Last 7 days",
}


@dataclass
class ProfileConfig:
    """User-selected configuration for a single collector profile."""

    profile: str
    collector: BaseCollector
    hours: int
    sources: list[str] = field(default_factory=list)


@dataclass
class CollectionConfig:
    """Full user-selected collection configuration."""

    profiles: list[ProfileConfig] = field(default_factory=list)
    use_api: bool = False
    api_url: str = "http://localhost:8000"
    output_dir: str = "."


class InteractiveMenu:
    """Drives the interactive menu flow using rich."""

    def __init__(self, api_running: bool = False, api_url: str = "http://localhost:8000") -> None:
        self.api_running = api_running
        self.api_url = api_url

    def run(self, detection: DetectionResult) -> CollectionConfig:
        """Run the full menu flow and return a CollectionConfig."""
        self._show_welcome(detection)
        active_profiles = self._confirm_profiles(detection)
        profile_configs = self._configure_profiles(active_profiles)
        use_api = self._choose_output_mode()
        return CollectionConfig(
            profiles=profile_configs,
            use_api=use_api,
            api_url=self.api_url,
        )

    def _show_welcome(self, detection: DetectionResult) -> None:
        console.print()
        console.print(
            Panel.fit(
                "[bold cyan]LogLM Collector[/bold cyan]\n"
                "[dim]Auto-detects logs and formats them for LogLM analysis[/dim]",
                border_style="cyan",
            )
        )
        console.print()

        table = Table(title="Detected System Profiles", border_style="blue")
        table.add_column("Profile", style="bold")
        table.add_column("Confidence", justify="center")
        table.add_column("Evidence")

        for p in detection.profiles:
            conf_str = f"{p.confidence:.0%}"
            color = "green" if p.confidence >= 0.7 else ("yellow" if p.confidence >= 0.3 else "red")
            evidence = "; ".join(p.evidence[:2]) if p.evidence else "N/A"
            table.add_row(p.profile.upper(), f"[{color}]{conf_str}[/{color}]", evidence)

        console.print(table)
        console.print()

    def _confirm_profiles(self, detection: DetectionResult) -> list[str]:
        """Let the user confirm or deselect detected profiles."""
        console.print("[bold]Step 1: Confirm profiles to collect[/bold]")
        console.print()

        available = []
        for idx, p in enumerate(detection.profiles, 1):
            collector_cls = COLLECTOR_REGISTRY.get(p.profile)
            desc = collector_cls().get_description() if collector_cls else ""
            default_on = p.confidence > 0.0
            marker = "[green]✓[/green]" if default_on else "[dim]○[/dim]"
            console.print(f"  {idx}. {marker} [bold]{p.profile.upper()}[/bold] — {desc}")
            available.append((p.profile, default_on))

        console.print()
        selected = []
        for profile, default in available:
            answer = Confirm.ask(f"  Include [bold]{profile.upper()}[/bold]?", default=default)
            if answer:
                selected.append(profile)

        console.print()
        return selected

    def _configure_profiles(self, active_profiles: list[str]) -> list[ProfileConfig]:
        """Configure time range for each active profile."""
        console.print("[bold]Step 2: Configure collection parameters[/bold]")
        console.print()

        configs = []
        for profile in active_profiles:
            collector_cls = COLLECTOR_REGISTRY.get(profile)
            if not collector_cls:
                continue
            collector = collector_cls()

            console.print(f"  [bold cyan]{collector.get_name()}[/bold cyan] — {collector.get_description()}")
            console.print("  Sources:")
            for src in collector.get_log_sources():
                console.print(f"    • {src}")
            console.print()

            console.print("  Time range:")
            for key, label in HOURS_LABELS.items():
                console.print(f"    {key}. {label}")

            choice = Prompt.ask("  Select time range", choices=list(HOURS_LABELS.keys()), default="3")
            hours = HOURS_OPTIONS[choice]
            console.print()

            configs.append(
                ProfileConfig(
                    profile=profile,
                    collector=collector,
                    hours=hours,
                    sources=collector.get_log_sources(),
                )
            )

        return configs

    def _choose_output_mode(self) -> bool:
        """Let user choose API vs file output; return True to use API."""
        console.print("[bold]Step 3: Output mode[/bold]")
        console.print()

        if self.api_running:
            console.print(f"  [green]✓ LogLM API detected at {self.api_url}[/green]")
            use_api = Confirm.ask("  Send entries to LogLM API?", default=True)
        else:
            console.print(f"  [yellow]✗ LogLM API not running at {self.api_url}[/yellow]")
            console.print("  Entries will be saved to a local JSON file.")
            use_api = False

        console.print()
        return use_api

    def show_collection_progress(
        self,
        profile_name: str,
        source: str,
        count: int,
    ) -> None:
        """Print a single collection result line."""
        console.print(f"  [dim]{profile_name}[/dim] [{source}] → [bold]{count}[/bold] entries")

    def show_summary(
        self,
        results: list[tuple[str, int]],
        output_path: str | None,
        api_used: bool,
    ) -> None:
        """Show final collection summary table."""
        console.print()

        table = Table(title="Collection Summary", border_style="green")
        table.add_column("Profile / Source", style="bold")
        table.add_column("Entries", justify="right")

        total = 0
        for name, count in results:
            table.add_row(name, str(count))
            total += count
        table.add_row("[bold]TOTAL[/bold]", f"[bold]{total}[/bold]")

        console.print(table)
        console.print()

        if api_used:
            console.print("[green]✓ Entries sent to LogLM API.[/green]")
        elif output_path:
            console.print(f"[green]✓ Output saved to:[/green] [bold]{output_path}[/bold]")

        console.print()

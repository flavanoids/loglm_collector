"""Interactive rich-based menu for loglm_collector."""

from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from collectors.base import BaseCollector
from collectors import COLLECTOR_REGISTRY
from collectors.process_target import (
    ProcessTarget,
    ProcessTargetCollector,
    get_container_runtime_info,
    get_top_processes,
    resolve_target,
)
from detector import DetectionResult
from templates.store import ISSUE_TYPE_CONFIG

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

# Order for issue-centric menu (all is always last)
ISSUE_TYPE_ORDER: list[str] = [
    "kernel_panic",
    "gpu",
    "memory",
    "process",
    "storage",
    "auth",
    "all",
]


def _issue_type_available(detection: DetectionResult, issue_key: str) -> bool:
    """Return True if this issue type is available given detected profiles."""
    if issue_key not in ISSUE_TYPE_CONFIG:
        return False
    profiles = ISSUE_TYPE_CONFIG[issue_key].get("profiles")
    if profiles is None:
        return True
    for profile in profiles:
        det = detection.get_profile(profile)
        if det is None or det.confidence <= 0.0:
            return False
    return True


def get_available_issue_choices(detection: DetectionResult) -> list[tuple[str, str]]:
    """Return (key, label) pairs for issue types that are available."""
    return [
        (key, ISSUE_TYPE_CONFIG[key]["label"])
        for key in ISSUE_TYPE_ORDER
        if key in ISSUE_TYPE_CONFIG and _issue_type_available(detection, key)
    ]


def choose_issue_type(detection: DetectionResult) -> str:
    """Show 'What do you want to collect?' menu; return issue type key."""
    choices = get_available_issue_choices(detection)
    if not choices:
        return "all"
    console.print()
    console.print("[bold]What do you want to collect?[/bold]")
    console.print()
    for idx, (_, label) in enumerate(choices, 1):
        console.print(f"  [bold]{idx}.[/bold] {label}")
    console.print()
    choice_list = [str(i) for i in range(1, len(choices) + 1)]
    choice = Prompt.ask("  Select", choices=choice_list, default="1")
    return choices[int(choice) - 1][0]


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

    def run_issue_centric(
        self, detection: DetectionResult, issue_type: str
    ) -> CollectionConfig:
        """Run simplified flow for a single issue type: one time range, no template."""
        self._show_welcome(detection)
        config = ISSUE_TYPE_CONFIG.get(issue_type, ISSUE_TYPE_CONFIG["all"])
        profiles = config.get("profiles")
        if not profiles:
            return self.run(detection)

        process_target: ProcessTarget | None = None
        step_time = "Step 1: Time range"
        step_output = "Step 2: Output mode"
        if issue_type == "process":
            process_target = self._choose_process_target()
            console.print()
            step_time = "Step 2: Time range"
            step_output = "Step 3: Output mode"

        console.print(f"[bold]{step_time}[/bold]")
        console.print()
        for key, label in HOURS_LABELS.items():
            console.print(f"  {key}. {label}")
        choice = Prompt.ask(
            "  Select time range", choices=list(HOURS_LABELS.keys()), default="3"
        )
        hours = HOURS_OPTIONS[choice]
        console.print()

        profile_configs = self._build_issue_centric_profiles(
            detection, profiles, hours, process_target
        )
        use_api = self._choose_output_mode(step_output)

        return CollectionConfig(
            profiles=profile_configs,
            use_api=use_api,
            api_url=self.api_url,
        )

    def _build_issue_centric_profiles(
        self,
        detection: DetectionResult,
        profiles: list[str],
        hours: int,
        process_target: ProcessTarget | None,
    ) -> list[ProfileConfig]:
        """Build profile configs for issue-centric flow, optionally including process target."""
        configs: list[ProfileConfig] = []
        for profile in profiles:
            det = detection.get_profile(profile)
            if det is None or det.confidence <= 0.0:
                continue
            collector_cls = COLLECTOR_REGISTRY.get(profile)
            if collector_cls is None:
                continue
            collector = collector_cls()
            configs.append(
                ProfileConfig(
                    profile=profile,
                    collector=collector,
                    hours=hours,
                    sources=collector.get_log_sources(),
                )
            )
        if process_target is not None:
            proc_collector = ProcessTargetCollector(process_target, hours)
            configs.append(
                ProfileConfig(
                    profile="process",
                    collector=proc_collector,
                    hours=hours,
                    sources=proc_collector.get_log_sources(),
                )
            )
        return configs

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

        table = Table(
            title="Detected system types",
            caption="[dim]Match = how sure we are this applies to your system; details explain why.[/dim]",
            border_style="blue",
        )
        table.add_column("Type", style="bold")
        table.add_column("Match", justify="center")
        table.add_column("Details")

        for p in detection.profiles:
            conf_str = f"{p.confidence:.0%}"
            color = "green" if p.confidence >= 0.7 else ("yellow" if p.confidence >= 0.3 else "red")
            evidence = "; ".join(p.evidence[:2]) if p.evidence else "N/A"
            table.add_row(p.profile.upper(), f"[{color}]{conf_str}[/{color}]", evidence)

        console.print(table)
        console.print()

    def _choose_process_target(self) -> ProcessTarget | None:
        """Let user pick one of top 5 processes, custom input, or (if available) all/select containers."""
        console.print("[bold]Choose process or service to collect logs for[/bold]")
        console.print()
        top = get_top_processes(5)
        for idx, (pid, name) in enumerate(top, 1):
            console.print(f"  [bold]{idx}.[/bold] {name} (PID {pid})")
        console.print(
            "  [bold]6.[/bold] Enter a custom process, [dim]service name[/dim], or [dim]PID[/dim]"
        )
        container_info = get_container_runtime_info()
        if container_info is not None:
            console.print("  [bold]7.[/bold] All containers")
            console.print("  [bold]8.[/bold] Select containers")
        console.print()
        choices = [str(i) for i in range(1, len(top) + 1)] + ["6"]
        if container_info is not None:
            choices.extend(["7", "8"])
        choice = Prompt.ask("  Select", choices=choices, default="1")

        choice_num = int(choice)
        if choice_num <= len(top):
            pid, name = top[choice_num - 1]
            return ProcessTarget(
                kind="pid",
                value=str(pid),
                display_name=f"{name} ({pid})",
            )
        if choice == "6":
            return self._choose_process_target_custom()
        if choice == "7" and container_info:
            return self._choose_process_target_all_containers(container_info)
        if choice == "8" and container_info:
            return self._choose_process_target_select_containers(container_info)
        return None

    def _choose_process_target_custom(self) -> ProcessTarget | None:
        """Prompt for custom service/PID/container; return target or None."""
        custom = Prompt.ask(
            "  Enter service name, container name/ID, or PID",
            default="",
        ).strip()
        if not custom:
            return None
        target = resolve_target(custom)
        if target is None:
            console.print(
                "[yellow]Could not resolve as PID, systemd unit, or container. "
                "Skipping process-specific logs; general logs only.[/yellow]"
            )
            console.print()
        return target

    def _choose_process_target_all_containers(
        self,
        container_info: tuple[str, list[tuple[str, str]]],
    ) -> ProcessTarget:
        """Return target for all containers."""
        runtime_path, _ = container_info
        return ProcessTarget(
            kind="containers_all",
            value="",
            runtime_bin=runtime_path,
            display_name="All containers",
        )

    def _choose_process_target_select_containers(
        self,
        container_info: tuple[str, list[tuple[str, str]]],
    ) -> ProcessTarget | None:
        """Let user pick container numbers; return target or None."""
        runtime_path, containers = container_info
        for idx, (cid, cname) in enumerate(containers, 1):
            console.print(
                f"  [bold]{idx}.[/bold] {cname} [dim]({cid[:12]})[/dim]"
            )
        console.print()
        sel = Prompt.ask(
            "  Enter numbers to collect (e.g. 1,3,5 or 1-3)",
            default="",
        ).strip()
        if not sel:
            return None
        ids = self._parse_container_selection(sel, len(containers))
        if not ids:
            console.print("[yellow]No valid selection. Skipping.[/yellow]")
            console.print()
            return None
        selected_ids = [containers[i - 1][0] for i in sorted(ids)]
        return ProcessTarget(
            kind="containers_selected",
            value=",".join(selected_ids),
            runtime_bin=runtime_path,
            display_name=f"{len(selected_ids)} container(s)",
        )

    @staticmethod
    def _parse_container_selection(text: str, max_num: int) -> set[int]:
        """Parse '1,3,5' or '1-3' or '1 2 3' into set of 1-based indices in range [1, max_num]."""
        result: set[int] = set()
        for part in text.replace(",", " ").split():
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a_str, _, b_str = part.partition("-")
                try:
                    a, b = int(a_str.strip()), int(b_str.strip())
                    for i in range(max(1, a), min(max_num, b) + 1):
                        result.add(i)
                except ValueError:
                    continue
            else:
                try:
                    n = int(part)
                    if 1 <= n <= max_num:
                        result.add(n)
                except ValueError:
                    continue
        return result

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

    def _choose_output_mode(self, step_label: str = "Step 3: Output mode") -> bool:
        """Let user choose API vs file output; return True to use API."""
        console.print(f"[bold]{step_label}[/bold]")
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

    def show_next_steps(
        self,
        api_running: bool,
        api_url: str,
        _already_sent_to_local: bool = False,
    ) -> tuple[str, str | None]:
        """Show 'What would you like to do next?' menu; return (action, remote_url_or_none).

        action is 'local' | 'remote' | 'exit'.
        For 'remote', the second value is the user-entered base URL.
        """
        console.print("[bold]What would you like to do next?[/bold]")
        console.print()
        console.print("  [bold]1.[/bold] Send to local LogLM")
        if api_running:
            console.print(f"      [dim]Use LogLM at {api_url}[/dim]")
        else:
            console.print("      [dim]Start LogLM locally first, then run this again[/dim]")
        console.print("  [bold]2.[/bold] Send to remote LogLM")
        console.print("      [dim]Enter the base URL of a LogLM API (e.g. https://loglm.example.com)[/dim]")
        console.print("  [bold]3.[/bold] Exit (keep log local)")
        console.print()
        choice = Prompt.ask("  Select", choices=["1", "2", "3"], default="3")

        if choice == "2":
            default_url = "https://localhost:8000"
            url = Prompt.ask(
                "  Remote LogLM API base URL",
                default=default_url,
            ).strip()
            if not url:
                url = default_url
            return ("remote", url.rstrip("/"))
        if choice == "1":
            return ("local", None)
        return ("exit", None)

"""Entry point for loglm_collector."""

import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from collectors.base import LogEntry
from collectors.custom import CustomSourceCollector
from collectors.scout import LogScout, ScoutResult
from detector import SystemDetector
from log_formatter import format_entries, generate_output_paths, save_json, save_text_bundle
from loglm_client import check_api_running, save_to_file, send_entries
from templates.store import ISSUE_TYPE_CONFIG, Template, TemplateStore
from ui.menu import (
    CollectionConfig,
    InteractiveMenu,
    choose_issue_type,
)
from ui.template_builder import ResponseLabeler, TemplateManager, select_template

console = Console()

_API_URL = "http://localhost:8000"


def _spinner() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    )


def _collect_all(config: CollectionConfig, template: Template | None) -> tuple[list[LogEntry], list[tuple[str, int]]]:
    """Run all configured collectors (+ custom sources from template); return entries + summary."""
    all_entries: list[LogEntry] = []
    summary: list[tuple[str, int]] = []

    console.print("[bold]Collecting logs\u2026[/bold]")
    console.print()

    collectors = list(config.profiles)

    # Inject custom sources from active template
    if template and template.custom_sources:
        from ui.menu import ProfileConfig  # pylint: disable=import-outside-toplevel
        csc = CustomSourceCollector(template.custom_sources)
        # reuse the first profile's hours, or default 24
        hours = config.profiles[0].hours if config.profiles else 24
        collectors.append(ProfileConfig(profile="custom", collector=csc, hours=hours))

    for profile_cfg in collectors:
        collector = profile_cfg.collector
        name = collector.get_name()

        with _spinner() as progress:
            task = progress.add_task(f"Collecting {name}\u2026", total=None)
            entries = collector.collect(profile_cfg.hours)
            progress.update(task, completed=True)

        all_entries.extend(entries)
        summary.append((name, len(entries)))
        console.print(f"  [cyan]{name}[/cyan]: {len(entries)} entries collected")

    console.print()
    return all_entries, summary


def _output(config: CollectionConfig, loglm_entries: list[dict], all_entries: list[LogEntry], api_running: bool) -> str:
    """Send to API or save file; return output path string."""
    json_path, txt_path = generate_output_paths(Path(config.output_dir))

    if config.use_api and api_running:
        console.print("[bold]Sending to LogLM API\u2026[/bold]")
        with _spinner() as progress:
            task = progress.add_task(f"Sending {len(loglm_entries)} entries\u2026", total=None)
            responses = send_entries(loglm_entries, config.api_url)
            progress.update(task, completed=True)
        save_json(responses, json_path)
    else:
        save_to_file(loglm_entries, json_path)
        save_text_bundle(all_entries, txt_path)

    return str(json_path)


def _handle_next_steps(
    choice: tuple[str, str | None],
    loglm_entries: list[dict],
    output_path: str,
    api_running: bool,
    api_url: str,
) -> None:
    """Send to local/remote LogLM per user choice, or no-op for exit."""
    next_action, remote_url = choice
    json_path = Path(output_path)
    if next_action == "local" and api_running:
        console.print("[bold]Sending to local LogLM\u2026[/bold]")
        with _spinner() as progress:
            task = progress.add_task(
                f"Sending {len(loglm_entries)} entries\u2026", total=None
            )
            responses = send_entries(loglm_entries, api_url)
            progress.update(task, completed=True)
        save_json(responses, json_path)
        console.print("[green]✓ Entries sent to local LogLM and saved.[/green]")
    elif next_action == "remote" and remote_url:
        console.print(f"[bold]Sending to remote LogLM at {remote_url}\u2026[/bold]")
        with _spinner() as progress:
            task = progress.add_task(
                f"Sending {len(loglm_entries)} entries\u2026", total=None
            )
            responses = send_entries(loglm_entries, remote_url)
            progress.update(task, completed=True)
        remote_path = json_path.parent / (json_path.stem + "_remote.json")
        save_json(responses, remote_path)
        console.print(
            f"[green]✓ Entries sent to remote LogLM. Responses saved to {remote_path}[/green]"
        )


def _top_menu(store: TemplateStore, api_running: bool) -> str:  # pylint: disable=unused-argument
    """Show top-level action menu; return chosen action key."""
    from rich.prompt import Prompt  # pylint: disable=import-outside-toplevel
    console.print()
    api_status = "[green]API online[/green]" if api_running else "[dim]API offline[/dim]"
    console.print(f"  LogLM API: {api_status}")
    console.print()
    console.print("  [bold]1.[/bold] Collect logs")
    console.print("  [bold]2.[/bold] Manage templates")
    console.print("  [bold]3.[/bold] Label responses (build training data)")
    console.print("  [bold]4.[/bold] Scout for errors (live monitor)")
    console.print("  [bold]q.[/bold] Quit")
    console.print()
    return Prompt.ask("  Select", choices=["1", "2", "3", "4", "q"], default="1")


def main() -> int:
    """Main entry point; returns exit code."""
    with _spinner() as progress:
        task = progress.add_task("Detecting system profiles\u2026", total=None)
        detection = SystemDetector().detect()
        progress.update(task, completed=True)

    with _spinner() as progress:
        task = progress.add_task("Checking LogLM API\u2026", total=None)
        api_running = check_api_running(_API_URL)
        progress.update(task, completed=True)

    store = TemplateStore()

    from rich.panel import Panel  # pylint: disable=import-outside-toplevel
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]LogLM Collector[/bold cyan]\n"
            "[dim]Log collection, formatting, and training-data tools for LogLM[/dim]",
            border_style="cyan",
        )
    )

    action = _top_menu(store, api_running)

    if action == "q":
        return 0

    if action == "2":
        TemplateManager(store).run()
        return 0

    if action == "3":
        ResponseLabeler().run()
        return 0

    if action == "4":
        _run_scout()
        return 0

    # action == "1": collect
    issue_type = choose_issue_type(detection)
    menu = InteractiveMenu(api_running=api_running, api_url=_API_URL)

    if issue_type == "all":
        template = select_template(store)
        config = menu.run(detection)
    else:
        template = ISSUE_TYPE_CONFIG[issue_type]["template"]
        config = menu.run_issue_centric(detection, issue_type)

    if not config.profiles:
        console.print("[yellow]No profiles selected. Exiting.[/yellow]")
        return 0

    all_entries, summary = _collect_all(config, template)
    loglm_entries = format_entries(all_entries, template)
    output_path = _output(config, loglm_entries, all_entries, api_running)

    if issue_type != "all" and issue_type in ISSUE_TYPE_CONFIG:
        summary.append(
            (f"[dim]Issue type: {ISSUE_TYPE_CONFIG[issue_type]['label']}[/dim]", 0)
        )
    elif template:
        summary.append((f"[dim]Template: {template.name}[/dim]", 0))
    menu.show_summary(summary, output_path, config.use_api and api_running)

    _handle_next_steps(
        menu.show_next_steps(
            api_running, config.api_url, config.use_api and api_running
        ),
        loglm_entries,
        output_path,
        api_running,
        config.api_url,
    )
    return 0


def _run_scout() -> None:
    """Run the live log scout."""
    menu = InteractiveMenu()
    duration = menu.choose_scout_duration()

    mins = duration / 60
    console.print()
    console.print(
        f"[bold]Scouting for errors across /var/log and journalctl "
        f"for {mins:.0f} minute{'s' if mins != 1 else ''}\u2026[/bold]"
    )
    console.print("[dim]Press Ctrl+C to stop early.[/dim]")
    console.print()

    scout = LogScout(duration_seconds=duration)
    hit_count = 0

    def _on_hit(hit) -> None:
        nonlocal hit_count
        hit_count += 1
        src = hit.source.replace("/var/log/", "")
        console.print(f"  [yellow]\u26a0[/yellow] [{src}] {hit.line[:100]}")

    try:
        result = scout.run(on_hit=_on_hit)
    except KeyboardInterrupt:
        scout.stop()
        console.print()
        console.print("[yellow]Scout stopped early by user.[/yellow]")
        result = ScoutResult(duration_seconds=duration, hits=list(scout._hits))

    menu.show_scout_results(result)


if __name__ == "__main__":
    sys.exit(main())

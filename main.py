"""Entry point for loglm_collector."""

import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from collectors.base import LogEntry
from collectors.custom import CustomSourceCollector
from detector import SystemDetector
from log_formatter import format_entries, generate_output_paths, save_json, save_text_bundle
from loglm_client import check_api_running, save_to_file, send_entries
from templates.store import Template, TemplateStore
from ui.menu import CollectionConfig, InteractiveMenu
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
    console.print("  [bold]q.[/bold] Quit")
    console.print()
    return Prompt.ask("  Select", choices=["1", "2", "3", "q"], default="1")


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

    # action == "1": collect
    template = select_template(store)

    menu = InteractiveMenu(api_running=api_running, api_url=_API_URL)
    config = menu.run(detection)

    if not config.profiles:
        console.print("[yellow]No profiles selected. Exiting.[/yellow]")
        return 0

    all_entries, summary = _collect_all(config, template)
    loglm_entries = format_entries(all_entries, template)
    output_path = _output(config, loglm_entries, all_entries, api_running)

    if template:
        summary.append((f"[dim]Template: {template.name}[/dim]", 0))
    menu.show_summary(summary, output_path, config.use_api and api_running)
    return 0


if __name__ == "__main__":
    sys.exit(main())

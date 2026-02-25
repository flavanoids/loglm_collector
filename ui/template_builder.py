"""TUI for creating, editing, and managing LogLM templates.

Three main modes:
  - Template Manager   — create / edit / delete named templates
  - Template Selector  — pick a template at collection time
  - Response Labeler   — annotate collected JSON output with Response text
"""

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from templates.store import (
    INSTRUCTION_SUGGESTIONS,
    CustomSource,
    InstructionRule,
    Template,
    TemplateStore,
)

console = Console()

_LEVELS = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]


# ── helpers ───────────────────────────────────────────────────────────────────


def _header(title: str) -> None:
    console.print()
    console.print(Panel.fit(f"[bold cyan]{title}[/bold cyan]", border_style="cyan"))
    console.print()


def _pick_from_list(items: list[str], prompt: str, allow_skip: bool = False) -> Optional[str]:
    """Display numbered list and return chosen item, or None if skipped."""
    for i, item in enumerate(items, 1):
        console.print(f"  [dim]{i:2}.[/dim] {item}")
    console.print()
    choices = [str(i) for i in range(1, len(items) + 1)]
    if allow_skip:
        choices.append("0")
        console.print("   [dim]0.[/dim] Skip / leave blank")
    choice = Prompt.ask(prompt, choices=choices, default="0" if allow_skip else "1")
    if choice == "0":
        return None
    return items[int(choice) - 1]


# ── instruction rule builder ──────────────────────────────────────────────────


def _build_instruction_rule() -> Optional[InstructionRule]:
    """Interactively build one InstructionRule; returns None if aborted."""
    console.print("[bold]Instruction text[/bold] — choose a suggestion or type your own:")
    console.print()
    instruction = _pick_from_list(INSTRUCTION_SUGGESTIONS, "Select suggestion (0 = type own)", allow_skip=True)
    if instruction is None:
        instruction = Prompt.ask("  Custom instruction text").strip()
    if not instruction:
        return None

    console.print()
    console.print("[bold]Match conditions[/bold] (all left blank = matches any log):")
    console.print()

    match_source = Prompt.ask(
        "  Source substring filter [dim](e.g. 'journalctl:kernel', blank=any)[/dim]",
        default="",
    ).strip()

    match_pattern = Prompt.ask(
        "  Keyword/regex pattern  [dim](e.g. 'amdgpu|gpu.hang', blank=any)[/dim]",
        default="",
    ).strip()

    console.print()
    console.print("  Log levels: " + "  ".join(f"[bold]{l}[/bold]" for l in _LEVELS))
    levels_raw = Prompt.ask(
        "  Match levels [dim](comma-separated, blank=any)[/dim]",
        default="",
    ).strip()
    match_levels = [l.strip() for l in levels_raw.split(",") if l.strip()] if levels_raw else []

    return InstructionRule(
        instruction=instruction,
        match_source=match_source,
        match_pattern=match_pattern,
        match_levels=match_levels,
    )


# ── custom source builder ─────────────────────────────────────────────────────


def _build_custom_source() -> Optional[CustomSource]:
    """Interactively build one CustomSource; returns None if aborted."""
    name = Prompt.ask("  Source name [dim](e.g. 'FWI Job Logs')[/dim]").strip()
    if not name:
        return None

    path_glob = Prompt.ask(
        "  File path or glob [dim](e.g. /scratch/jobs/fwi_*.log)[/dim]"
    ).strip()
    if not path_glob:
        return None

    filter_pattern = Prompt.ask(
        "  Filter regex       [dim](e.g. 'error|fail', blank=all lines)[/dim]",
        default="",
    ).strip()

    level = Prompt.ask(
        "  Default log level  [dim](err/warning/info)[/dim]",
        choices=["err", "warning", "info", "crit"],
        default="info",
    )

    return CustomSource(
        name=name,
        path_glob=path_glob,
        filter_pattern=filter_pattern,
        default_level=level,
    )


# ── template editor ───────────────────────────────────────────────────────────


def _edit_template(template: Template) -> Template:
    """Walk through editing all fields of a template; returns updated copy."""
    console.print(f"[bold]Name:[/bold] {template.name}")
    new_desc = Prompt.ask("Description", default=template.description).strip()
    template.description = new_desc

    # --- instruction rules ---
    console.print()
    while True:
        console.print(f"[bold]Instruction rules[/bold] ({len(template.instruction_rules)} defined):")
        for i, rule in enumerate(template.instruction_rules, 1):
            console.print(f"  {i}. {rule.describe()}")
        console.print()
        action = Prompt.ask(
            "  [a]dd rule  [d]elete rule  [c]ontinue",
            choices=["a", "d", "c"],
            default="c",
        )
        if action == "c":
            break
        if action == "a":
            console.print()
            rule = _build_instruction_rule()
            if rule:
                template.instruction_rules.append(rule)
                console.print("[green]Rule added.[/green]")
        elif action == "d" and template.instruction_rules:
            idx_str = Prompt.ask(
                "  Delete rule number",
                choices=[str(i) for i in range(1, len(template.instruction_rules) + 1)],
            )
            template.instruction_rules.pop(int(idx_str) - 1)
            console.print("[yellow]Rule removed.[/yellow]")
        console.print()

    # --- custom sources ---
    console.print()
    while True:
        console.print(f"[bold]Custom log sources[/bold] ({len(template.custom_sources)} defined):")
        for i, src in enumerate(template.custom_sources, 1):
            console.print(f"  {i}. {src.describe()}")
        console.print()
        action = Prompt.ask(
            "  [a]dd source  [d]elete source  [c]ontinue",
            choices=["a", "d", "c"],
            default="c",
        )
        if action == "c":
            break
        if action == "a":
            console.print()
            src = _build_custom_source()
            if src:
                template.custom_sources.append(src)
                console.print("[green]Source added.[/green]")
        elif action == "d" and template.custom_sources:
            idx_str = Prompt.ask(
                "  Delete source number",
                choices=[str(i) for i in range(1, len(template.custom_sources) + 1)],
            )
            template.custom_sources.pop(int(idx_str) - 1)
            console.print("[yellow]Source removed.[/yellow]")
        console.print()

    return template


# ── template manager (main TUI) ───────────────────────────────────────────────


class TemplateManager:  # pylint: disable=too-few-public-methods
    """Full TUI for creating, editing, and deleting templates."""

    def __init__(self, store: TemplateStore) -> None:
        self._store = store

    def run(self) -> None:
        """Enter the template management loop."""
        while True:
            _header("LogLM Template Manager")
            templates = self._store.all()

            if templates:
                table = Table(border_style="blue", show_header=True)
                table.add_column("#", justify="right", style="dim")
                table.add_column("Name", style="bold")
                table.add_column("Description")
                table.add_column("Rules", justify="right")
                table.add_column("Sources", justify="right")
                for i, t in enumerate(templates, 1):
                    table.add_row(
                        str(i), t.name, t.description[:50],
                        str(len(t.instruction_rules)),
                        str(len(t.custom_sources)),
                    )
                console.print(table)
            else:
                console.print("[dim]No templates saved yet.[/dim]")

            console.print()
            action = Prompt.ask(
                "  [n]ew  [e]dit  [d]elete  [b]ack",
                choices=["n", "e", "d", "b"],
                default="b",
            )

            if action == "b":
                break
            if action == "n":
                self._create()
            elif action == "e":
                self._edit(templates)
            elif action == "d":
                self._delete(templates)

    def _create(self) -> None:
        _header("Create Template")
        name = Prompt.ask("Template name").strip()
        if not name:
            return
        if self._store.get(name):
            console.print(f"[yellow]A template named '{name}' already exists. Editing it.[/yellow]")
        t = Template(name=name)
        t = _edit_template(t)
        self._store.save_template(t)
        console.print(f"[green]Template '{name}' saved.[/green]")
        console.print()

    def _edit(self, templates: list[Template]) -> None:
        if not templates:
            return
        _header("Edit Template")
        names = [t.name for t in templates]
        name = _pick_from_list(names, "Select template to edit", allow_skip=True)
        if not name:
            return
        t = self._store.get(name)
        if not t:
            return
        t = _edit_template(t)
        self._store.save_template(t)
        console.print(f"[green]Template '{name}' updated.[/green]")
        console.print()

    def _delete(self, templates: list[Template]) -> None:
        if not templates:
            return
        _header("Delete Template")
        names = [t.name for t in templates]
        name = _pick_from_list(names, "Select template to delete", allow_skip=True)
        if not name:
            return
        if Confirm.ask(f"  Delete '{name}'?", default=False):
            self._store.delete(name)
            console.print(f"[yellow]Template '{name}' deleted.[/yellow]")
        console.print()


# ── template selector (used in main collection flow) ──────────────────────────


def select_template(store: TemplateStore) -> Optional[Template]:
    """Prompt user to choose a template (or none) before collection."""
    templates = store.all()
    _header("Select Template")

    console.print("  Templates customize [italic]Instruction[/italic] text per log type and")
    console.print("  can add custom log sources to the collection.")
    console.print()

    if not templates:
        console.print("  [dim]No templates saved. Use 'Manage Templates' to create one.[/dim]")
        console.print()
        Prompt.ask("  Press Enter to continue with defaults", default="")
        return None

    options = ["(no template — use defaults)"] + [t.name for t in templates] + ["[Manage templates]"]
    for i, opt in enumerate(options, 1):
        console.print(f"  {i}. {opt}")
    console.print()
    choices = [str(i) for i in range(1, len(options) + 1)]
    choice = Prompt.ask("  Select", choices=choices, default="1")
    idx = int(choice) - 1

    if idx == 0:
        return None
    if idx == len(options) - 1:
        TemplateManager(store).run()
        return select_template(store)

    selected = templates[idx - 1]
    console.print(
        f"  [green]Using template:[/green] [bold]{selected.name}[/bold]"
        + (f" — {selected.description}" if selected.description else "")
    )
    console.print()
    return selected


# ── response labeler ──────────────────────────────────────────────────────────


class ResponseLabeler:  # pylint: disable=too-few-public-methods
    """TUI for annotating collected LogLM JSON entries with Response text."""

    def run(self) -> None:
        """Entry point: ask for a file, then label entries interactively."""
        _header("Response Labeler — Build Training Data")
        console.print(
            "  Load a collected [bold]loglm_output_*.json[/bold] file and annotate\n"
            "  each entry with a [italic]Response[/italic] to create fine-tuning data.\n"
        )

        input_path_str = Prompt.ask("  Path to input JSON file").strip()
        input_path = Path(input_path_str)
        if not input_path.exists():
            console.print(f"[red]File not found: {input_path}[/red]")
            return

        try:
            with open(input_path, encoding="utf-8") as fh:
                entries: list[dict] = json.load(fh)
        except Exception as e:  # pylint: disable=broad-except
            console.print(f"[red]Failed to load file: {e}[/red]")
            return

        output_path = input_path.parent / (input_path.stem + "_labeled.json")
        console.print(f"  Labeled output will be saved to: [bold]{output_path}[/bold]")
        console.print()
        console.print("  Commands during labeling:")
        console.print("    [bold]Enter[/bold]          skip this entry (keep blank Response)")
        console.print("    [bold]s[/bold]              skip remaining entries and save")
        console.print("    [bold]q[/bold]              quit without saving")
        console.print()

        if not Confirm.ask("  Begin labeling?", default=True):
            return

        labeled = list(entries)  # copy
        skip_rest = False

        for i, entry in enumerate(labeled):
            if skip_rest:
                break

            console.print()
            console.print(f"[dim]─── Entry {i + 1} / {len(labeled)} ───────────────────────────────[/dim]")
            console.print()
            console.print(
                Panel(
                    f"[bold]Instruction:[/bold] {entry.get('Instruction', '')}\n\n"
                    f"[bold]Input:[/bold] {entry.get('Input', '')[:500]}",
                    border_style="blue",
                    expand=False,
                )
            )
            console.print()

            existing = entry.get("Response", "")
            if existing:
                console.print(f"  [dim]Existing response:[/dim] {existing[:80]}")

            response = Prompt.ask(
                "  Response [dim](Enter=skip, s=stop, q=quit)[/dim]",
                default="",
            ).strip()

            if response == "q":
                console.print("[yellow]Quit — nothing saved.[/yellow]")
                return
            if response == "s":
                skip_rest = True
                continue
            if response:
                labeled[i] = {**entry, "Response": response}

        labeled_count = sum(1 for e in labeled if e.get("Response"))
        console.print()
        console.print(f"  [green]{labeled_count}[/green] of {len(labeled)} entries annotated.")

        if labeled_count == 0:
            if not Confirm.ask("  No responses written — save anyway?", default=False):
                return

        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(labeled, fh, indent=2, ensure_ascii=False)

        console.print(f"[green]Saved to {output_path}[/green]")
        console.print()

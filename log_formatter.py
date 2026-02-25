"""Formats LogEntry objects into LogLM-native JSON and human-readable text."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from collectors.base import LogEntry

INSTRUCTION_MAP: dict[str, str] = {
    "error": "Interpret the error message in the given log.",
    "err": "Interpret the error message in the given log.",
    "crit": "Interpret the error message in the given log.",
    "alert": "Interpret the error message in the given log.",
    "emerg": "Interpret the error message in the given log.",
    "warning": "Analyze the potential issue described in this log entry.",
    "warn": "Analyze the potential issue described in this log entry.",
}

_DEFAULT_INSTRUCTION = "Parse and summarize the information in this log entry."


def entry_to_loglm(entry: LogEntry, template=None) -> dict[str, str]:
    """Convert a single LogEntry to a LogLM JSON dict.

    If a Template is provided, its instruction rules are tried first.
    """
    instruction = ""
    if template is not None:
        instruction = template.resolve_instruction(entry.source, entry.raw, entry.level)
    if not instruction:
        instruction = INSTRUCTION_MAP.get(entry.level.lower(), _DEFAULT_INSTRUCTION)
    return {
        "Instruction": instruction,
        "Input": entry.raw,
        "Response": "",
    }


def format_entries(entries: list[LogEntry], template: Optional[object] = None) -> list[dict[str, str]]:
    """Convert a list of LogEntry objects to LogLM format.

    Pass a Template instance to apply custom instruction rules.
    """
    return [entry_to_loglm(e, template) for e in entries]


def save_json(loglm_entries: list[dict[str, str]], output_path: Path) -> None:
    """Write LogLM entries as a JSON file."""
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(loglm_entries, fh, indent=2, ensure_ascii=False)


def save_text_bundle(entries: list[LogEntry], output_path: Path) -> None:
    """Write a human-readable text summary of all log entries."""
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("LogLM Collector \u2014 Log Bundle\n")
        fh.write(f"Generated: {datetime.now().isoformat()}\n")
        fh.write(f"Total entries: {len(entries)}\n")
        fh.write("=" * 80 + "\n\n")

        current_source = None
        for entry in entries:
            if entry.source != current_source:
                current_source = entry.source
                fh.write(f"\n--- Source: {entry.source} ---\n")
            ts = entry.timestamp.isoformat() if entry.timestamp else "N/A"
            fh.write(f"[{ts}] [{entry.level.upper()}] {entry.message}\n")


def generate_output_paths(base_dir: Path | None = None) -> tuple[Path, Path]:
    """Return (json_path, txt_path) with timestamp-based names."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = base_dir or Path.cwd()
    return (
        base / f"loglm_output_{ts}.json",
        base / f"loglm_output_{ts}.txt",
    )

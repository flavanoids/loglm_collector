"""Template data models and JSON persistence for loglm_collector."""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_CONFIG_DIR = Path.home() / ".config" / "loglm_collector"
_TEMPLATES_FILE = _CONFIG_DIR / "templates.json"

# Suggested instruction texts shown as shortcuts in the builder
INSTRUCTION_SUGGESTIONS: list[str] = [
    "Interpret the error message in the given log.",
    "Analyze the potential issue described in this log entry.",
    "Parse and summarize the information in this log entry.",
    "Identify the GPU hardware event and assess its impact on running workloads.",
    "Diagnose this AMD GPU kernel event and suggest remediation steps.",
    "Diagnose this NVIDIA GPU kernel event and suggest remediation steps.",
    "Analyze this storage or I/O error and assess risk of data loss.",
    "Interpret this authentication failure and evaluate the security impact.",
    "Analyze this OOM kill event and identify likely root cause.",
    "Assess this systemd unit failure and suggest recovery steps.",
    "Interpret this LLM inference log entry and summarize GPU resource usage.",
    "Analyze this HPC/seismic job log entry and identify performance or failure issues.",
    "Interpret this kernel panic or oops and identify the faulting component.",
]


@dataclass
class InstructionRule:
    """Maps a log-matching condition to a custom instruction string."""

    instruction: str
    match_source: str = ""       # substring match on LogEntry.source
    match_pattern: str = ""      # regex match on LogEntry.raw
    match_levels: list[str] = field(default_factory=list)  # e.g. ["err", "crit"]

    def matches(self, source: str, raw: str, level: str) -> bool:
        """Return True if this rule matches the given log entry fields."""
        if self.match_source and self.match_source.lower() not in source.lower():
            return False
        if self.match_levels and level.lower() not in [l.lower() for l in self.match_levels]:
            return False
        if self.match_pattern:
            try:
                if not re.search(self.match_pattern, raw, re.IGNORECASE):
                    return False
            except re.error:
                return False
        return True

    def describe(self) -> str:
        """Short human-readable summary of this rule's conditions."""
        parts = []
        if self.match_source:
            parts.append(f"source contains '{self.match_source}'")
        if self.match_levels:
            parts.append(f"level in {self.match_levels}")
        if self.match_pattern:
            parts.append(f"pattern /{self.match_pattern}/")
        cond = " AND ".join(parts) if parts else "any log"
        return f"[{cond}] → {self.instruction[:60]}"


@dataclass
class CustomSource:
    """A user-defined log source to collect from."""

    name: str
    path_glob: str
    filter_pattern: str = ""   # optional regex to filter lines
    default_level: str = "info"

    def describe(self) -> str:
        parts = [f"glob: {self.path_glob}"]
        if self.filter_pattern:
            parts.append(f"filter: /{self.filter_pattern}/")
        parts.append(f"level: {self.default_level}")
        return f"{self.name} ({', '.join(parts)})"


@dataclass
class Template:
    """A named collection of instruction rules and optional custom sources."""

    name: str
    description: str = ""
    instruction_rules: list[InstructionRule] = field(default_factory=list)
    custom_sources: list[CustomSource] = field(default_factory=list)

    def resolve_instruction(self, source: str, raw: str, level: str) -> str:
        """Return the first matching rule's instruction, or None if no match."""
        for rule in self.instruction_rules:
            if rule.matches(source, raw, level):
                return rule.instruction
        return ""


class TemplateStore:
    """Loads and saves templates to ~/.config/loglm_collector/templates.json."""

    def __init__(self, path: Path = _TEMPLATES_FILE) -> None:
        self._path = path
        self._templates: list[Template] = []
        self._load()

    def all(self) -> list[Template]:
        return list(self._templates)

    def get(self, name: str) -> Optional[Template]:
        for t in self._templates:
            if t.name == name:
                return t
        return None

    def save_template(self, template: Template) -> None:
        """Add or replace a template by name, then persist."""
        self._templates = [t for t in self._templates if t.name != template.name]
        self._templates.append(template)
        self._persist()

    def delete(self, name: str) -> bool:
        before = len(self._templates)
        self._templates = [t for t in self._templates if t.name != name]
        if len(self._templates) < before:
            self._persist()
            return True
        return False

    # ── persistence ───────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            self._templates = []
            return
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            self._templates = [self._from_dict(t) for t in data]
        except Exception:  # pylint: disable=broad-except
            self._templates = []

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump([asdict(t) for t in self._templates], fh, indent=2, ensure_ascii=False)

    @staticmethod
    def _from_dict(data: dict) -> Template:
        rules = [InstructionRule(**r) for r in data.get("instruction_rules", [])]
        sources = [CustomSource(**s) for s in data.get("custom_sources", [])]
        return Template(
            name=data["name"],
            description=data.get("description", ""),
            instruction_rules=rules,
            custom_sources=sources,
        )

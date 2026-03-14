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


BUILTIN_TEMPLATES: list[Template] = [
    Template(
        name="nvidia-training-cluster",
        description="NVIDIA GPU training: CUDA OOM, Xid errors, NCCL faults, thermal throttling",
        instruction_rules=[
            InstructionRule(
                instruction=(
                    "Diagnose this NCCL collective communication error and assess "
                    "its impact on the distributed training job."
                ),
                match_source="journalctl",
                match_pattern=r"NCCL|nccl",
                match_levels=["err", "crit", "alert", "emerg"],
            ),
            InstructionRule(
                instruction=(
                    "Interpret this NVIDIA Xid error code and identify the underlying "
                    "GPU hardware or driver fault."
                ),
                match_source="journalctl",
                match_pattern=r"Xid|xid",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Interpret this CUDA error and identify whether it indicates a "
                    "hardware fault, driver issue, or application bug."
                ),
                match_source="journalctl",
                match_pattern=r"CUDA|cuda",
                match_levels=["err", "crit", "alert", "emerg"],
            ),
            InstructionRule(
                instruction=(
                    "Assess this GPU thermal throttling event and recommend steps "
                    "to prevent training degradation."
                ),
                match_source="",
                match_pattern=r"thermal|throttl",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Analyze this NVIDIA GPU diagnostic event and assess its impact "
                    "on training workloads."
                ),
                match_source="nvidia-smi",
                match_pattern="",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Diagnose this NVIDIA training cluster error and suggest "
                    "remediation steps."
                ),
                match_source="",
                match_pattern="",
                match_levels=["err", "crit", "alert", "emerg"],
            ),
        ],
        custom_sources=[],
    ),
    Template(
        name="amd-rocm-workstation",
        description="AMD GPU / ROCm workloads: HIP errors, amdgpu kernel events, thermal alerts",
        instruction_rules=[
            InstructionRule(
                instruction=(
                    "Diagnose this AMD GPU kernel event and suggest remediation steps."
                ),
                match_source="journalctl",
                match_pattern=r"amdgpu|gpu.hang|ring.*timeout|fence.*timeout",
                match_levels=["err", "crit", "alert", "emerg"],
            ),
            InstructionRule(
                instruction=(
                    "Interpret this HIP/ROCm runtime error and identify the root cause."
                ),
                match_source="",
                match_pattern=r"HIP|ROCm|hipError|rocm",
                match_levels=["err", "crit", "alert", "emerg"],
            ),
            InstructionRule(
                instruction=(
                    "Assess this AMD GPU thermal event and recommend cooling or "
                    "power configuration changes."
                ),
                match_source="",
                match_pattern=r"thermal|throttl|temperature",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Analyze this AMD GPU diagnostic event and assess hardware "
                    "health and workload impact."
                ),
                match_source="rocm-smi",
                match_pattern="",
                match_levels=[],
            ),
        ],
        custom_sources=[],
    ),
    Template(
        name="llm-inference-server",
        description="LLM serving: ollama, vllm, llama.cpp, TensorRT — GPU errors and OOM events",
        instruction_rules=[
            InstructionRule(
                instruction=(
                    "Diagnose this GPU out-of-memory event during LLM inference and "
                    "recommend batch size or quantization adjustments."
                ),
                match_source="",
                match_pattern=r"out.of.memory|OOM|CUDA out of memory|memory.*exhausted",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Interpret this LLM inference service event and summarize the "
                    "failure mode or resource constraint."
                ),
                match_source="",
                match_pattern=r"ollama|vllm|llama\.cpp|text.generation.inference|tgi",
                match_levels=["err", "crit", "warning", "alert", "emerg"],
            ),
            InstructionRule(
                instruction=(
                    "Interpret this TensorRT or Triton inference engine event and "
                    "identify optimization or compatibility issues."
                ),
                match_source="",
                match_pattern=r"TensorRT|tensorrt|triton",
                match_levels=["err", "crit", "warning"],
            ),
            InstructionRule(
                instruction=(
                    "Analyze this NVIDIA GPU event during LLM inference and assess "
                    "impact on serving throughput."
                ),
                match_source="nvidia-smi",
                match_pattern="",
                match_levels=[],
            ),
        ],
        custom_sources=[],
    ),
    Template(
        name="zfs-nas-server",
        description="ZFS / mdadm NAS: pool health, checksum errors, SMART diagnostics, RAID events",
        instruction_rules=[
            InstructionRule(
                instruction=(
                    "Diagnose this ZFS data integrity error and recommend scrub "
                    "or resilver actions."
                ),
                match_source="",
                match_pattern=r"checksum|cksum|data error|read error|write error|resilver|scrub",
                match_levels=["err", "crit", "alert", "emerg"],
            ),
            InstructionRule(
                instruction=(
                    "Analyze this ZFS pool status event and assess risk of data "
                    "loss or pool degradation."
                ),
                match_source="zpool",
                match_pattern="",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Interpret this SMART diagnostic result and evaluate disk "
                    "health and failure risk."
                ),
                match_source="smartctl",
                match_pattern="",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Analyze this software RAID event and assess array health "
                    "and required recovery steps."
                ),
                match_source="",
                match_pattern=r"mdadm|RAID|raid|degraded|failed.drive|array.*degraded",
                match_levels=[],
            ),
            InstructionRule(
                instruction=(
                    "Interpret this storage I/O error and assess risk of data "
                    "corruption or device failure."
                ),
                match_source="",
                match_pattern=r"ata[0-9]|scsi|nvme|I/O error|i/o error|sector",
                match_levels=["err", "crit", "alert", "emerg"],
            ),
        ],
        custom_sources=[],
    ),
]

BUILTIN_NAMES: set[str] = {t.name for t in BUILTIN_TEMPLATES}

# Issue-centric collection: profile list + template with default instructions.
# "all" means use full flow (confirm profiles, template selector).
ISSUE_TYPE_CONFIG: dict[str, dict] = {
    "kernel_panic": {
        "label": "Kernel panics & oops",
        "profiles": ["general"],
        "template": Template(
            name="issue:kernel_panic",
            description="Kernel panic and oops default instructions",
            instruction_rules=[
                InstructionRule(
                    instruction="Interpret this kernel panic or oops and identify the faulting component.",
                    match_pattern=r"panic|oops|kernel.*fault|BUG:",
                    match_levels=[],
                ),
            ],
            custom_sources=[],
        ),
    },
    "gpu": {
        "label": "GPU activity (errors / diagnostics)",
        "profiles": ["gpu"],
        "template": Template(
            name="issue:gpu",
            description="GPU errors and diagnostics default instructions",
            instruction_rules=[
                InstructionRule(
                    instruction="Identify the GPU hardware event and assess its impact on running workloads.",
                    match_source="",
                    match_pattern=r"nvidia|amdgpu|nvlink|rocm|gpu\.hang|Xid|CUDA|HIP",
                    match_levels=[],
                ),
                InstructionRule(
                    instruction="Analyze this GPU diagnostic event and assess hardware health.",
                    match_source="nvidia-smi",
                    match_pattern="",
                    match_levels=[],
                ),
                InstructionRule(
                    instruction="Analyze this AMD GPU diagnostic event and assess hardware health.",
                    match_source="rocm-smi",
                    match_pattern="",
                    match_levels=[],
                ),
            ],
            custom_sources=[],
        ),
    },
    "memory": {
        "label": "Memory (OOM, high usage)",
        "profiles": ["general"],
        "template": Template(
            name="issue:memory",
            description="OOM and memory events default instructions",
            instruction_rules=[
                InstructionRule(
                    instruction="Analyze this OOM kill event and identify likely root cause.",
                    match_pattern=r"oom|out of memory|killed process|OOM",
                    match_levels=[],
                ),
            ],
            custom_sources=[],
        ),
    },
    "process": {
        "label": "Process / application activity",
        "profiles": ["general"],
        "template": Template(
            name="issue:process",
            description="Process and application log default instructions",
            instruction_rules=[
                InstructionRule(
                    instruction="Analyze this process or system log entry.",
                    match_source="",
                    match_pattern="",
                    match_levels=[],
                ),
            ],
            custom_sources=[],
        ),
    },
    "storage": {
        "label": "Storage / NAS",
        "profiles": ["nas"],
        "template": Template(
            name="issue:storage",
            description="Storage and NAS default instructions",
            instruction_rules=[
                InstructionRule(
                    instruction="Analyze this storage or I/O error and assess risk of data loss.",
                    match_pattern=r"ata|scsi|nvme|I/O error|zfs|checksum|mdadm|raid|smartctl",
                    match_levels=[],
                ),
                InstructionRule(
                    instruction="Analyze this ZFS pool or RAID event and assess health.",
                    match_source="",
                    match_pattern=r"zpool|mdadm|degraded|resilver",
                    match_levels=[],
                ),
            ],
            custom_sources=[],
        ),
    },
    "auth": {
        "label": "Auth failures",
        "profiles": ["general"],
        "template": Template(
            name="issue:auth",
            description="Authentication failure default instructions",
            instruction_rules=[
                InstructionRule(
                    instruction="Interpret this authentication failure and evaluate the security impact.",
                    match_source="",
                    match_pattern=r"auth|authentication|failed password|invalid user|Accepted|refused",
                    match_levels=[],
                ),
            ],
            custom_sources=[],
        ),
    },
    "all": {
        "label": "All (confirm profiles & template)",
        "profiles": None,
        "template": None,
    },
}


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

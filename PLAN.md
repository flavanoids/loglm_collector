# PLAN.md — LogLM Collector

Current implementation state. This document reflects what is built and deployed,
not what could be added. Scope is intentionally closed.

---

## What is built

### Core pipeline

```
Detect → Select Template → Confirm Profiles → Configure → Collect → Format → Output
```

1. **System detection** (`detector.py`) — reads lsmod, sysfs, /dev, vendor tools to assign confidence scores to `general`, `gpu`, `nas` profiles
2. **Template selection** (`ui/template_builder.py` + `templates/store.py`) — user picks a saved template or skips; templates carry instruction rules and custom sources
3. **Profile menu** (`ui/menu.py`) — user confirms which profiles to collect, sets time range (1h / 6h / 24h / 7d)
4. **Collection** (`collectors/`) — each active collector runs, returns `list[LogEntry]`
5. **Formatting** (`log_formatter.py`) — entries converted to `{Instruction, Input, Response}` using template rules first, then level-based fallback
6. **Output** (`loglm_client.py`) — POST to LogLM API if running, otherwise write JSON + text bundle to disk

### Three top-level actions

| Action | Module | What it does |
|---|---|---|
| Collect logs | Full pipeline | Detect → collect → format → save/send |
| Manage templates | `ui/template_builder.py` → `TemplateManager` | Create/edit/delete templates with instruction rules and custom sources |
| Label responses | `ui/template_builder.py` → `ResponseLabeler` | Load collected JSON, annotate `Response` fields for fine-tuning |

### Collectors

| Collector | Auto-detects when |
|---|---|
| `GeneralCollector` | Always |
| `GpuCollector` | NVIDIA or AMD hardware present |
| `NasCollector` | ZFS/btrfs/mdadm modules, RAID active, or multiple block devices |
| `CustomSourceCollector` | Active template has `custom_sources` defined |

### Template system

- **`InstructionRule`** — maps (source substring, keyword regex, level list) → custom instruction text; first-match wins
- **`CustomSource`** — user-defined file glob + filter regex + default level; collected alongside profile results
- **`TemplateStore`** — persists to `~/.config/loglm_collector/templates.json`
- 13 built-in instruction suggestion strings covering: GPU errors, OOM kills, auth failures, storage errors, LLM inference, HPC jobs, kernel panics

### Output formats

- `loglm_output_<timestamp>.json` — list of `{Instruction, Input, Response}` dicts
- `loglm_output_<timestamp>.txt` — human-readable bundle grouped by source
- `loglm_output_<timestamp>_labeled.json` — labeled copy from ResponseLabeler

---

## Scope

**In scope:**
- Linux systems with systemd and journalctl
- NVIDIA GPUs (nvidia-smi, /dev/nvidia*, /proc/driver/nvidia)
- AMD GPUs (amdgpu/amdkfd/radeon, /dev/kfd, rocm-smi)
- ZFS, btrfs, mdadm, ext4, xfs storage stacks
- Standard `/var/log` paths
- LogLM API at `http://localhost:8000` (the single supported endpoint)
- User-defined log sources via templates (any readable file, any glob)

**Out of scope:**
- Windows, macOS, non-systemd Linux
- Remote log collection (SSH, syslog-ng, Loki, ELK)
- Real-time / tail-follow mode
- Log parsing beyond line extraction — no field parsing, no structured log decoding
- Automatic `Response` generation — only the LogLM API or human labeling fills that field
- Authentication to the LogLM API
- Multiple LogLM API endpoints

---

## Decisions made and why

**`log_formatter.py` not `formatter.py`** — `formatter` conflicts with a deprecated stdlib module name; pylint raises W4901.

**`--grep` in `_collect_workload_journal`** — journalctl `--grep` filters server-side, avoiding a full journal pull into Python memory. Five targeted pattern groups cover the workload surface area without an unbounded scan.

**ANSI stripping in `_collect_rocm_smi`** — `rocm-smi` emits ANSI escape codes in its concise output; stripped before storing as LogLM `Input`.

**`rocm-smi --showpids` over `/proc` scanning** — where rocm-smi is available (AMD systems with ROCm), it gives authoritative GPU process list. `/proc/*/cmdline` scan is a fallback only.

**Template rules: first-match wins** — simpler and more predictable than priority scoring. The user controls order by editing rules list in the template builder.

**Single top-level menu** — three actions (collect / manage templates / label) are mutually exclusive per session. No persistent daemon, no background collection.

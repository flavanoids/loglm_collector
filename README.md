# loglm_collector

A companion tool for [LogLM](https://github.com/lunyiliu/LogLM) that collects Linux system logs and formats them as LogLM-native `{Instruction, Input, Response}` JSON — ready for fine-tuning or API submission.

**Status:** This software is **in active development and testing**. It has **not yet been verified to work** in all environments; use with caution until further testing is complete.

---

## Who it's for

- **Sysadmins and SREs** — turn real system logs (kernel, auth, GPU, storage) into structured training or analysis data without writing parsers.
- **ML practitioners using LogLM** — get instruction-tuned log data from your own machines for fine-tuning or evaluation.
- **DevOps / platform teams** — automate log collection for GPU nodes, NAS boxes, or general-purpose servers with one tool; tailor instructions and sources via templates.

The tool is **interactive only** (menus, no CLI flags). Use it when you want to collect logs from the current machine, manage templates, or label responses for training.

---

## What it does

`loglm_collector` detects your system's hardware profile, collects relevant log data from the appropriate sources, and outputs structured entries that LogLM can consume directly.

**Three actions from a single menu:**

| Action | Description |
|--------|-------------|
| **1 — Collect logs** | Detect → select template → confirm profiles → choose time range → format → save to file or POST to LogLM API |
| **2 — Manage templates** | Create, edit, or delete templates (instruction rules, custom log sources) |
| **3 — Label responses** | Load a collected JSON file and annotate `Response` fields for fine-tuning |
| **Scout for errors** | Monitor `/var/log` and journalctl in real-time for a set duration, then report which sources raised attention |

---

## System requirements

- **Linux** with **systemd** and **journalctl**
- **Python 3.8+**

Optional (auto-detected):

| Profile | When detected |
|---------|----------------|
| **GPU** | NVIDIA (`nvidia-smi`, `/dev/nvidia*`) or AMD (`rocm-smi`, `/dev/kfd`, amdgpu/amdkfd modules) |
| **NAS** | ZFS, btrfs, or mdadm modules; active RAID; or multiple block devices |

The **General** profile (kernel errors, OOM, auth failures, failed units) is always enabled.

---

## Installation

*Note: This project is in active development and not yet verified; expect changes and possible issues.*

```bash
git clone https://github.com/<your-username>/loglm_collector.git
cd loglm_collector
pip install -r requirements.txt
```

**Dependencies:** `rich>=13.0.0`, `requests>=2.28.0`. `requests` is optional — the tool saves to file if it is unavailable.

---

## Usage

### Running the tool

```bash
python3 main.py
```

No CLI flags. The program will:

1. Detect system profiles (General, GPU, NAS) and show confidence.
2. Show the top menu: **Collect logs**, **Manage templates**, or **Label responses**.

### Collect logs (typical workflow)

1. **What do you want to collect?** — Pick an issue type or “All”:
   - **Kernel panics & oops**, **GPU activity**, **Memory (OOM)**, **Process/application**, **Storage/NAS**, **Auth failures** — single time range and default instructions (no template).
   - **All (confirm profiles & template)** — full flow: choose template, confirm profiles, set time range per profile.
2. **Time range** — Last 1 hour, 6 hours, 24 hours, or 7 days (one prompt for issue-centric; per-profile for “All”).
3. **Output mode** — If a LogLM API is at `http://localhost:8000`, optionally send there; otherwise output is saved to the current directory.

**Output files** (when saving to file):

- `loglm_output_<timestamp>.json` — LogLM-formatted entries
- `loglm_output_<timestamp>.txt` — Plain-text bundle of raw log lines

---

## Verifying the build

From the project root, ensure syntax, lint, and import hygiene pass:

```bash
# Syntax
python3 -m py_compile main.py detector.py log_formatter.py loglm_client.py \
  collectors/*.py templates/store.py ui/menu.py ui/template_builder.py

# Lint (target: 10.00/10)
python3 -m pylint main.py detector.py log_formatter.py loglm_client.py \
  collectors/ templates/ ui/ --disable=C,R0801

# Import hygiene
python3 -m pyflakes main.py detector.py log_formatter.py loglm_client.py \
  collectors/*.py templates/store.py ui/menu.py ui/template_builder.py
```

---

## Testing

**Interactive:** Run the tool and walk through the menus:

```bash
python3 main.py
```

- **1** → Collect: choose an issue type (e.g. **1** Kernel panics) or **7** for All, then time range and output.
- **2** → Manage templates.
- **3** → Label responses: path to a `loglm_output_*.json` file, then annotate.

**Non-interactive (piped):** Use a fixed sequence of answers for scripts or CI. Example — issue-centric collect (Kernel panics, 24h, save to file):

```bash
printf "1\n1\n3\nn\n" | python3 main.py 2>&1
```

(1=Collect, 1=first issue type, 3=24h, n=don’t send to API. Adjust numbers if your menu order differs.)

---

## Output format

Every entry follows the LogLM schema:

```json
{
  "Instruction": "Analyze this GPU error log entry and identify the fault.",
  "Input": "amdgpu 0000:0c:00.0: amdgpu: GPU reset begin!",
  "Response": ""
}
```

`Response` is empty at collection time. Fill it via **Label responses** (action 3) or via the LogLM API.

---

## Collectors

| Collector | Auto-detected when |
|-----------|--------------------|
| **General** | Always — kernel errors, OOM kills, auth failures, failed systemd units |
| **GPU** | NVIDIA or AMD hardware present (journal + vendor tools: nvidia-smi, rocm-smi) |
| **NAS** | ZFS/btrfs/mdadm, active RAID, or multiple block devices |
| **Custom** | Active template defines `custom_sources` (file globs, optional regex filter) |

---

## Templates

Templates customize collection without editing code:

- **Instruction rules** — Map log source, keyword pattern, or severity to a custom `Instruction` string.
- **Custom sources** — Add any readable file or glob path; optionally filter lines with a regex.

Templates are stored in `~/.config/loglm_collector/templates.json`. The tool ships with built-in instruction suggestions for GPU errors, OOM, auth failures, storage faults, LLM inference, HPC jobs, and kernel panics.

---

## Related

- [LogLM](https://github.com/lunyiliu/LogLM) — the log language model this tool feeds into

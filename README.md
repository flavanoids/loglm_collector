# loglm_collector

A companion tool for [LogLM](https://github.com/lunyiliu/LogLM) that collects Linux system logs and formats them as LogLM-native `{Instruction, Input, Response}` JSON — ready for fine-tuning or API submission.

---

## What it does

`loglm_collector` detects your system's hardware profile, collects relevant log data from the appropriate sources, and outputs structured entries that LogLM can consume directly.

Three actions from a single interactive menu:

| Action | Description |
|---|---|
| **Collect logs** | Detect → collect → format → save to file or POST to LogLM API |
| **Manage templates** | Create/edit/delete templates with custom instruction rules and log sources |
| **Label responses** | Load a collected JSON file and annotate `Response` fields for fine-tuning |

---

## System requirements

- Linux with **systemd** and **journalctl**
- Python 3.8+

Optional hardware support (auto-detected):
- NVIDIA GPU (`nvidia-smi`, `/dev/nvidia*`)
- AMD GPU (`rocm-smi`, `/dev/kfd`, amdgpu/amdkfd modules)
- Storage arrays: ZFS, btrfs, mdadm, SMART-capable drives

---

## Installation

```bash
git clone https://github.com/<your-username>/loglm_collector.git
cd loglm_collector
pip install -r requirements.txt
```

---

## Usage

```bash
python3 main.py
```

Interactive menus only — no CLI flags.

On first run you will be prompted to select or create a template, confirm which log profiles apply, and choose a time range (1h / 6h / 24h / 7d). Output is written to `loglm_output_<timestamp>.json` and `.txt` in the current directory, or POSTed to a running LogLM API at `http://localhost:8000`.

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

`Response` is always empty at collection time. It is populated by the **Label responses** action or by the LogLM API.

---

## Collectors

| Collector | Auto-detected when |
|---|---|
| **General** | Always — kernel errors, OOM kills, auth failures, failed units |
| **GPU** | NVIDIA or AMD hardware present |
| **NAS** | ZFS/btrfs/mdadm modules, active RAID, or multiple block devices |
| **Custom** | Active template has user-defined log sources |

---

## Templates

Templates let you tailor collection without editing code:

- **Instruction rules** — map a log source, keyword pattern, or severity level to a custom `Instruction` string
- **Custom sources** — point at any readable file or glob path and filter with a regex
- Saved to `~/.config/loglm_collector/templates.json`

13 built-in instruction suggestions are included covering GPU errors, OOM kills, auth failures, storage faults, LLM inference, HPC jobs, and kernel panics.

---

## Dependencies

```
rich>=13.0.0
requests>=2.28.0
```

`requests` is optional — the tool falls back to file output if it is unavailable.

---

## Related

- [LogLM](https://github.com/lunyiliu/LogLM) — the log language model this tool feeds into

# AGENTS.md — Collector Agents

Each collector is a self-contained agent responsible for one domain of log data.
This document defines each agent's exact scope, detection signals, and boundaries.

---

## BaseCollector contract (`collectors/base.py`)

Every collector must implement:

| Method | Returns | Contract |
|---|---|---|
| `collect(hours: int)` | `list[LogEntry]` | All log events from the past N hours |
| `get_name()` | `str` | Short display name shown in menus |
| `get_description()` | `str` | One-line summary of what is collected |
| `get_log_sources()` | `list[str]` | Human-readable list of sources queried |

`LogEntry` fields:

```python
source: str          # e.g. "journalctl:kernel", "/var/log/syslog"
message: str         # cleaned display string
raw: str             # verbatim line fed to LogLM as Input
timestamp: datetime  # optional; None if unparseable
level: str           # emerg|alert|crit|err|warning|notice|info|debug
```

Collectors **must not** parse or interpret log content — they collect raw lines.
Interpretation is LogLM's job.

---

## GeneralCollector (`collectors/general.py`)

**Profile key:** `general`
**Auto-detected:** always (confidence 1.0)

**Collects:**
- `journalctl -p err..emerg` — error-and-above across all units
- `journalctl -k` filtered for OOM kills, kernel panics, oops
- `/var/log/auth.log` or `/var/log/secure` — auth failure lines
- `systemctl --failed` — failed unit names
- `/var/log/kern.log` — critical/error-tagged kernel lines

**Does not collect:**
- Info/debug level journalctl output
- Application-specific service logs (those belong to GPU or custom collectors)
- Network logs, firewall logs, package manager logs

---

## GpuCollector (`collectors/gpu.py`)

**Profile key:** `gpu`
**Auto-detected:** NVIDIA or AMD hardware present

**Collects — kernel/hardware layer:**
- `journalctl -k` filtered for: `nvidia`, `nvlink`, `nvrm`, `amdgpu`, `amdkfd`, `radeon`, `kfd`, GPU hang/reset/fault, DRM errors, PCIe AER errors, DMA faults, thermal throttling, ring timeouts
- `/var/log/syslog` or `/var/log/messages` — same filter
- `/var/log/Xorg.0.log` — `(EE)` and `(WW)` lines

**Collects — vendor query tools:**
- `rocm-smi` concise status (AMD) — ANSI-stripped, data rows only
- `rocm-smi --showrasinfo all` — RAS error counters with non-zero counts only
- `rocm-smi --showpids` — KFD processes using the GPU
- `nvidia-smi -q -d ERROR` — NVIDIA error query (skipped if not present)

**Collects — application/workload layer:**
- `journalctl --grep` across five pattern clusters (CUDA/HIP/ROCm, LLM inference, HPC/seismic, GPU hang/OOM, graphics/gaming) — targeted, never full-journal pull
- `systemd` service journals for: `ollama`, `vllm`, `stable-diffusion`
- `/proc/*/cmdline` scan for GPU-compute process signatures (fallback when rocm-smi shows no PIDs)

**Workload patterns detected in `/proc` scan:**
`torch`, `tensorflow`, `jax`, `ollama`, `llama.cpp`, `vllm`, `comfyui`, `stable-diffusion`, `blender --background`, `gromacs`, `namd`, `amber`, `lammps`, `openmm`, `fwi`, `devito`, `triton`, `tensorrt`, `--device cuda/rocm/gpu`

**Does not collect:**
- General system errors (handled by GeneralCollector)
- Disk/storage events (handled by NasCollector)
- Full journalctl dumps — always uses `--grep` or `-k` filter

---

## NasCollector (`collectors/nas.py`)

**Profile key:** `nas`
**Auto-detected:** ZFS/btrfs/md modules loaded, active RAID, or >2 block devices

**Collects:**
- `journalctl -k` filtered for: `ata`, `scsi`, `sd[a-z]`, `nvme`, I/O error, ext4/xfs/zfs/btrfs/mdadm/raid keywords
- `/var/log/syslog` or `/var/log/messages` — same filter
- `zpool status` — full output, with error-level assignment for degraded/faulted states
- `mdadm --detail --scan` — array scan output
- `smartctl -a <dev>` for each `/dev/sd?` and `/dev/nvme?n?` — error/fail lines only

**Does not collect:**
- Filesystem mount events without errors
- Normal disk I/O metrics (IOPS, throughput)
- Network storage protocols (NFS, SMB) — those are application-layer, not kernel storage

---

## CustomSourceCollector (`collectors/custom.py`)

**Profile key:** `custom` (injected at runtime; not in `COLLECTOR_REGISTRY`)
**Source:** activated when the active Template has `custom_sources` defined

**Collects:**
- Each `CustomSource` in the template: resolves `path_glob`, reads last N lines, optionally filters with `filter_pattern` regex
- `default_level` is assigned to all entries from that source

**Does not collect:**
- Anything beyond what the user explicitly configured in the template
- Binary files (skips on decode error, not an error condition)

This collector has no detection logic — it is always passive. It runs after the profile collectors and adds its entries to the same pool.

---

## Detection — `SystemDetector` (`detector.py`)

Detects which profiles apply to the current system.

| Signal | Profile | Confidence |
|---|---|---|
| `/proc/driver/nvidia` exists | gpu | 0.90 |
| `/dev/nvidia*` device node | gpu | 0.90 |
| `nvidia` in lsmod | gpu | 0.80 |
| `nvidia-smi` returns GPU names | gpu | 0.95 |
| `amdgpu`/`amdkfd`/`radeon` in lsmod | gpu | 0.85 |
| `/dev/kfd` exists | gpu | 0.90 |
| `/sys/class/drm/card0/device/vendor` = `0x1002` | gpu | 0.90 |
| `rocm-smi --showproductname` returns data | gpu | 0.95 |
| `zfs`/`btrfs`/`md_mod` in lsmod | nas | 0.80 |
| `/proc/mdstat` shows active array | nas | 0.90 |
| `zpool list` returns pools | nas | 0.90 |
| >2 block devices in `/dev` | nas | 0.60 |
| 1–2 block devices | nas | 0.30 |
| (always) | general | 1.00 |

Confidence is the maximum of all matching signals for that profile.
The `general` profile is never suppressed regardless of confidence.

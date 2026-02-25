"""GPU/ML workload log collector — NVIDIA and AMD."""

import glob as globmod
import os
import re

from collectors.base import BaseCollector, LogEntry, run_command

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")

# Kernel/hardware layer — NVIDIA + AMD (amdgpu, amdkfd, radeon) + generic DRM/PCIe faults
_KERNEL_GPU_RE = re.compile(
    r"nvidia|nvlink|nvrm|"
    r"amdgpu|amdkfd|radeon|"
    r"gpu.hang|gpu.reset|gpu.fault|gpu.recover|"
    r"drm[:\s].*(error|fault|reset|hang|timeout)|"
    r"kfd[:\s]|"
    r"pcie.*(error|aer|correctable|uncorrectable)|"
    r"dma.*(error|fault|mapping)|"
    r"iommu.*(error|fault)|"
    r"throttl|thermal.event|"
    r"ring.*timeout|ring.*hang|"
    r"cp.protect.fault|vm.fault",
    re.IGNORECASE,
)

# Application/workload layer — runtime errors and known GPU-intensive processes
_WORKLOAD_RE = re.compile(
    # Compute runtime errors
    r"cuda.out.of.memory|hip.out.of.memory|"
    r"device.side.assert|illegal.memory.access|"
    r"hip.error|rocm.error|rocm.warn|"
    r"nccl.error|nccl.warn|"
    r"hsa.status.*error|"
    # ML inference/training services
    r"ollama|vllm|llama\.cpp|llama_server|text.generation.inference|"
    r"triton.server|tensorrt|tvm|"
    r"stable.diffusion|comfyui|automatic1111|"
    # ML frameworks (errors bubbling to journal)
    r"pytorch|tensorflow|jax[:\s]|"
    # HPC / scientific compute
    r"fwi|full.waveform|reverse.time.migration|seismic|"
    r"devito|opesci|madagascar|segyio|"
    r"gromacs|namd[:\s]|amber[:\s]|lammps|openmm|"
    # Gaming / graphics
    r"steam[:\s]|proton[:\s]|wine.*d3d|vulkan.*(error|warning)|"
    r"dxvk|vkd3d|"
    # SLURM GPU jobs
    r"slurmstepd.*gpu|gres.*gpu",
    re.IGNORECASE,
)

# OOM kills of GPU-intensive processes
_OOM_GPU_RE = re.compile(
    r"(?:killed process|oom.kill).*"
    r"(?:python|torch|tensorflow|jax|ollama|llama|vllm|"
    r"blender|steam|proton|wine|gromacs|namd|amber|fwi|devito|triton)",
    re.IGNORECASE,
)

# Cmdline patterns that indicate a process is doing GPU compute
_GPU_PROC_RE = re.compile(
    r"torch|tensorflow|jax|mxnet|paddle|"
    r"ollama|llama\.cpp|llama_server|vllm|text.generation.inference|comfyui|"
    r"stable.diffusion|diffusers|"
    r"blender.*(--background|cycles|gpu)|"
    r"gromacs|namd|amber|lammps|openmm|"
    r"fwi|devito|rtm|seiswave|"
    r"triton|tensorrt|tvm|"
    r"--device[= ].*(cuda|rocm|gpu)|"
    r"CUDA_VISIBLE_DEVICES|HIP_VISIBLE_DEVICES|ROCR_VISIBLE_DEVICES",
    re.IGNORECASE,
)

_LEVEL_RE = re.compile(r"\b(emerg|alert|crit|err|warning|notice|info|debug)\b", re.IGNORECASE)


def _parse_level(line: str) -> str:
    match = _LEVEL_RE.search(line)
    return match.group(1).lower() if match else "info"


def _filter_lines(output: str, pattern: re.Pattern) -> list[str]:
    return [l.strip() for l in output.splitlines() if l.strip() and pattern.search(l)]


class GpuCollector(BaseCollector):
    """Collects GPU events and GPU-intensive workload logs for NVIDIA and AMD."""

    def get_name(self) -> str:
        return "GPU / ML Workloads"

    def get_description(self) -> str:
        return "NVIDIA/AMD kernel events, ROCm/CUDA errors, LLM/HPC/gaming workload logs"

    def get_log_sources(self) -> list[str]:
        return [
            "journalctl -k (amdgpu|nvidia|drm|kfd|pcie fault filter)",
            "journalctl (ollama|vllm|rocm|cuda|workload filter)",
            "/var/log/syslog or /var/log/messages",
            "rocm-smi (AMD GPU status + active processes)",
            "nvidia-smi -q -d ERROR",
            "Running GPU processes (/proc scan)",
            "systemd GPU service journals (ollama, etc.)",
            "/var/log/Xorg.0.log",
        ]

    def collect(self, hours: int) -> list[LogEntry]:
        since = f"{hours} hours ago"
        entries: list[LogEntry] = []
        entries.extend(self._collect_kernel(since))
        entries.extend(self._collect_workload_journal(since))
        entries.extend(self._collect_syslog(hours))
        entries.extend(self._collect_rocm_smi())
        entries.extend(self._collect_nvidia_smi())
        entries.extend(self._collect_gpu_processes())
        entries.extend(self._collect_gpu_services(since))
        entries.extend(self._collect_xorg())
        return entries

    # ── kernel hardware layer ──────────────────────────────────────────────

    def _collect_kernel(self, since: str) -> list[LogEntry]:
        output = run_command(
            ["journalctl", "-k", "--since", since, "--no-pager", "-o", "short-iso"],
            timeout=30,
        )
        return [
            LogEntry(source="journalctl:kernel", message=l, raw=l, level=_parse_level(l))
            for l in _filter_lines(output, _KERNEL_GPU_RE)
        ]

    def _collect_syslog(self, hours: int) -> list[LogEntry]:
        line_count = max(1000, hours * 200)
        for path in ["/var/log/syslog", "/var/log/messages"]:
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.readlines()[-line_count:]
                return [
                    LogEntry(source=path, message=l.strip(), raw=l.strip(), level=_parse_level(l))
                    for l in lines
                    if _KERNEL_GPU_RE.search(l) or _WORKLOAD_RE.search(l)
                ]
            except OSError:
                continue
        return []

    # ── application / workload layer ──────────────────────────────────────

    def _collect_workload_journal(self, since: str) -> list[LogEntry]:
        """Journalctl user-space entries matching GPU-intensive workloads.

        Uses --grep for each keyword cluster so we never pull the full journal.
        """
        grep_patterns = [
            "cuda|hip|rocm|nccl",
            "ollama|vllm|llama|triton|tensorrt",
            "fwi|devito|seismic|gromacs|namd|openmm",
            "gpu.hang|gpu.reset|throttl|oom.kill",
            "stable.diffusion|comfyui|steam.*error|dxvk|vkd3d",
        ]
        entries: list[LogEntry] = []
        seen: set[str] = set()
        for pattern in grep_patterns:
            output = run_command(
                [
                    "journalctl", "--since", since, "--no-pager",
                    "-o", "short-iso", "--grep", pattern,
                    "--case-sensitive=false",
                ],
                timeout=20,
            )
            for line in output.splitlines():
                line = line.strip()
                if not line or line.startswith("--"):
                    continue
                if line not in seen:
                    seen.add(line)
                    entries.append(
                        LogEntry(
                            source="journalctl:workload",
                            message=line,
                            raw=line,
                            level=_parse_level(line),
                        )
                    )
        return entries

    def _collect_gpu_services(self, since: str) -> list[LogEntry]:
        """Pull full journal for known GPU service units."""
        services = ["ollama.service", "ollama", "vllm.service", "stable-diffusion.service"]
        entries = []
        for svc in services:
            output = run_command(
                ["journalctl", "-u", svc, "--since", since, "--no-pager", "-o", "short-iso"],
                timeout=15,
            )
            for line in output.splitlines():
                line = line.strip()
                if line and not line.startswith("--"):
                    entries.append(
                        LogEntry(
                            source=f"journalctl:{svc}",
                            message=line,
                            raw=line,
                            level=_parse_level(line),
                        )
                    )
        return entries

    def _collect_gpu_processes(self) -> list[LogEntry]:
        """Snapshot of running processes actively using GPU compute."""
        entries = []

        # AMD: rocm-smi lists PIDs using the GPU
        rocm_out = run_command(["rocm-smi", "--showpids"], timeout=10)
        if rocm_out:
            for line in rocm_out.splitlines():
                line = line.strip()
                if not line or line.startswith(("=", "K", "P", "-", "W")):
                    continue
                # lines look like: "1505   ollama   0   0   0   UNKNOWN"
                parts = line.split()
                if len(parts) >= 2 and parts[0].isdigit():
                    pid, name = parts[0], parts[1]
                    vram = parts[3] if len(parts) > 3 else "?"
                    msg = f"AMD GPU process: pid={pid} name={name} vram={vram}"
                    entries.append(
                        LogEntry(source="rocm-smi:pids", message=msg, raw=line, level="info")
                    )

        # Fallback: scan /proc cmdlines for GPU-compute patterns
        if not entries:
            entries.extend(self._proc_cmdline_scan())

        return entries

    def _proc_cmdline_scan(self) -> list[LogEntry]:
        """Scan /proc/*/cmdline for known GPU-intensive process signatures."""
        found = []
        for cmdline_path in globmod.glob("/proc/*/cmdline"):
            try:
                with open(cmdline_path, "rb") as fh:
                    raw_bytes = fh.read(512)
                cmdline = raw_bytes.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
                if _GPU_PROC_RE.search(cmdline):
                    pid = os.path.basename(os.path.dirname(cmdline_path))
                    msg = f"GPU-intensive process running: pid={pid} cmd={cmdline[:120]}"
                    found.append(
                        LogEntry(source="proc:cmdline", message=msg, raw=cmdline, level="info")
                    )
            except OSError:
                continue
        return found

    # ── vendor query tools ────────────────────────────────────────────────

    def _collect_rocm_smi(self) -> list[LogEntry]:
        """AMD GPU status snapshot — full concise view plus RAS error counters."""
        output = run_command(["rocm-smi"], timeout=15)
        entries = []
        if output:
            for raw_line in output.splitlines():
                line = _ANSI_RE.sub("", raw_line).strip()
                if not line or line.startswith(("=", "W", "[", "D", "R")):
                    continue
                # Skip pure header/label rows (no digits = no actual data)
                if not any(ch.isdigit() for ch in line):
                    continue
                lower = line.lower()
                level = "info"
                if any(kw in lower for kw in ("error", "fault", "hang", "reset", "throttl")):
                    level = "err"
                elif any(kw in lower for kw in ("warn", "degraded", "critical")):
                    level = "warning"
                entries.append(LogEntry(source="rocm-smi", message=line, raw=line, level=level))

        # RAS correctable/uncorrectable hardware error counters
        ras_out = run_command(["rocm-smi", "--showrasinfo", "all"], timeout=15)
        for raw_line in ras_out.splitlines():
            line = _ANSI_RE.sub("", raw_line).strip()
            if not line or line.startswith(("=", "W", "R", "G", "B", "_")):
                continue
            lower = line.lower()
            # Only emit if there are non-zero error counts
            if any(kw in lower for kw in ("correctable", "uncorrectable")):
                parts = line.split()
                counts = [p for p in parts if p.isdigit() and int(p) > 0]
                if counts:
                    entries.append(
                        LogEntry(source="rocm-smi:ras", message=line, raw=line, level="err")
                    )

        return entries

    def _collect_nvidia_smi(self) -> list[LogEntry]:
        """NVIDIA GPU error query (skipped gracefully if not present)."""
        output = run_command(["nvidia-smi", "-q", "-d", "ERROR"], timeout=15)
        if not output:
            return []
        return [
            LogEntry(source="nvidia-smi", message=l, raw=l, level="err")
            for l in output.splitlines()
            if l.strip()
        ]

    # ── display / Xorg ────────────────────────────────────────────────────

    def _collect_xorg(self) -> list[LogEntry]:
        try:
            with open("/var/log/Xorg.0.log", encoding="utf-8") as fh:
                lines = fh.readlines()
            entries = []
            for line in lines:
                lower = line.lower()
                if "(ee)" in lower or "(ww)" in lower:
                    level = "err" if "(ee)" in lower else "warning"
                    entries.append(
                        LogEntry(
                            source="/var/log/Xorg.0.log",
                            message=line.strip(),
                            raw=line.strip(),
                            level=level,
                        )
                    )
            return entries
        except OSError:
            return []

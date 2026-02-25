"""System profile auto-detection for loglm_collector."""

import os
from dataclasses import dataclass, field

from collectors.base import run_command


@dataclass  # pylint: disable=too-few-public-methods
class ProfileDetection:
    """Detection result for a single system profile."""

    profile: str
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass  # pylint: disable=too-few-public-methods
class DetectionResult:
    """Aggregated detection results for all profiles."""

    profiles: list[ProfileDetection] = field(default_factory=list)

    def get_profile(self, name: str) -> ProfileDetection | None:
        for p in self.profiles:
            if p.profile == name:
                return p
        return None


class SystemDetector:  # pylint: disable=too-few-public-methods
    """Detects what kind of Linux system is running and which profiles apply."""

    def detect(self) -> DetectionResult:
        result = DetectionResult()
        result.profiles.append(self._detect_general())
        result.profiles.append(self._detect_gpu())
        result.profiles.append(self._detect_nas())
        return result

    def _detect_general(self) -> ProfileDetection:
        return ProfileDetection(
            profile="general",
            confidence=1.0,
            evidence=["Always included as base Linux profile"],
        )

    def _detect_gpu(self) -> ProfileDetection:  # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        evidence: list[str] = []
        confidence = 0.0

        # ── NVIDIA ────────────────────────────────────────────────────────
        if os.path.exists("/proc/driver/nvidia"):
            evidence.append("/proc/driver/nvidia exists")
            confidence = max(confidence, 0.9)

        nvidia_devs = [f for f in os.listdir("/dev") if f.startswith("nvidia")] if os.path.exists("/dev") else []
        if nvidia_devs:
            evidence.append(f"/dev/{nvidia_devs[0]} device present")
            confidence = max(confidence, 0.9)

        lsmod_out = run_command(["lsmod"], timeout=5)
        lsmod_lower = lsmod_out.lower()
        if "nvidia" in lsmod_lower:
            evidence.append("nvidia module loaded (lsmod)")
            confidence = max(confidence, 0.8)

        smi_out = run_command(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=10)
        if smi_out.strip():
            evidence.append(f"nvidia-smi: {smi_out.strip()[:60]}")
            confidence = max(confidence, 0.95)

        # ── AMD ───────────────────────────────────────────────────────────
        for mod in ("amdgpu", "amdkfd", "radeon"):
            if mod in lsmod_lower:
                evidence.append(f"{mod} module loaded (lsmod)")
                confidence = max(confidence, 0.85)
                break

        if os.path.exists("/dev/kfd"):
            evidence.append("/dev/kfd (AMD KFD compute device) present")
            confidence = max(confidence, 0.9)

        vendor_path = "/sys/class/drm/card0/device/vendor"
        if os.path.exists(vendor_path):
            try:
                with open(vendor_path, encoding="utf-8") as fh:
                    vendor = fh.read().strip()
                if vendor == "0x1002":
                    dev_path = "/sys/class/drm/card0/device/device"
                    dev_id = ""
                    try:
                        with open(dev_path, encoding="utf-8") as fh:
                            dev_id = fh.read().strip()
                    except OSError:
                        pass
                    evidence.append(f"AMD GPU detected via sysfs (DID={dev_id or '?'})")
                    confidence = max(confidence, 0.9)
                elif vendor == "0x10de":
                    evidence.append("NVIDIA GPU detected via sysfs")
                    confidence = max(confidence, 0.9)
            except OSError:
                pass

        rocm_out = run_command(["rocm-smi", "--showproductname"], timeout=10)
        if rocm_out.strip() and "not supported" not in rocm_out.lower():
            for line in rocm_out.splitlines():
                line = line.strip()
                if "GPU" in line and (":" in line or "[" in line):
                    evidence.append(f"rocm-smi: {line[:70]}")
                    confidence = max(confidence, 0.95)
                    break

        # ── Workload hints ────────────────────────────────────────────────
        rocm_pids = run_command(["rocm-smi", "--showpids"], timeout=10)
        for line in rocm_pids.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0].isdigit():
                evidence.append(f"Active GPU process: {parts[1]} (pid {parts[0]})")
                break

        return ProfileDetection(profile="gpu", confidence=confidence, evidence=evidence)

    def _detect_nas(self) -> ProfileDetection:
        evidence: list[str] = []
        confidence = 0.0

        lsmod_out = run_command(["lsmod"], timeout=5)
        lsmod_lower = lsmod_out.lower()
        for mod in ("zfs", "btrfs", "md_mod"):
            if mod in lsmod_lower:
                evidence.append(f"{mod} kernel module loaded")
                confidence = max(confidence, 0.8)

        if os.path.exists("/proc/mdstat"):
            try:
                with open("/proc/mdstat", encoding="utf-8") as fh:
                    content = fh.read()
                if "md" in content and "active" in content.lower():
                    evidence.append("/proc/mdstat shows active RAID array")
                    confidence = max(confidence, 0.9)
                elif len(content.strip()) > 20:
                    evidence.append("/proc/mdstat present")
                    confidence = max(confidence, 0.5)
            except OSError:
                pass

        zpool_out = run_command(["zpool", "list", "-H"], timeout=10)
        if zpool_out.strip():
            evidence.append(f"zpool detected: {zpool_out.splitlines()[0][:60]}")
            confidence = max(confidence, 0.9)

        try:
            import glob as globmod
            block_devs = globmod.glob("/dev/sd?") + globmod.glob("/dev/nvme?n?")
            if len(block_devs) > 2:
                evidence.append(f"{len(block_devs)} block devices found (/dev/sd*, /dev/nvme*)")
                confidence = max(confidence, 0.6)
            elif block_devs:
                evidence.append(f"{len(block_devs)} block device(s) found")
                confidence = max(confidence, 0.3)
        except Exception:  # pylint: disable=broad-except
            pass

        return ProfileDetection(profile="nas", confidence=confidence, evidence=evidence)

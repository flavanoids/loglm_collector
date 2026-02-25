"""Collector registry for loglm_collector."""

from collectors.base import BaseCollector, LogEntry
from collectors.custom import CustomSourceCollector
from collectors.general import GeneralCollector
from collectors.gpu import GpuCollector
from collectors.nas import NasCollector

COLLECTOR_REGISTRY: dict[str, type[BaseCollector]] = {
    "general": GeneralCollector,
    "gpu": GpuCollector,
    "nas": NasCollector,
}

__all__ = [
    "BaseCollector",
    "CustomSourceCollector",
    "LogEntry",
    "GeneralCollector",
    "GpuCollector",
    "NasCollector",
    "COLLECTOR_REGISTRY",
]

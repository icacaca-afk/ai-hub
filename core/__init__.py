"""AI Hub — Core package

核心数据结构和基类。

API Stability:
  - Provider API: Stable
  - Task API: Stable
  - Result API: Stable
  - CapabilityRegistry API: Stable
  - Capability API: Stable
  - Bridge API: Experimental
"""

from core.provider import Provider, ProviderMetadata
from core.task import Task
from core.result import Result
from core.registry import CapabilityRegistry
from core.bridge import Bridge, CLIBridge, APIBridge, FakeBridge, GUIBridge, BrowserBridge, BridgeResult
from core.capabilities import classify, CAPABILITIES

__all__ = [
    "Provider",
    "ProviderMetadata",
    "Task",
    "Result",
    "CapabilityRegistry",
    "Bridge",
    "CLIBridge",
    "APIBridge",
    "FakeBridge",
    "GUIBridge",
    "BrowserBridge",
    "BridgeResult",
    "classify",
    "CAPABILITIES",
]

"""AI Hub — Core package

核心数据结构和基类。

API Stability:
  - Provider API: Stable
  - Result API: Stable
  - Registry API: Stable
  - Capability API: Stable
  - Bridge API: Experimental
"""

from core.provider import Provider, ProviderMetadata
from core.result import Result
from core.registry import ProviderRegistry
from core.bridge import Bridge, CLIBridge, APIBridge, FakeBridge, BridgeResult
from core.capabilities import classify, CAPABILITIES

__all__ = [
    "Provider",
    "ProviderMetadata",
    "Result",
    "ProviderRegistry",
    "Bridge",
    "CLIBridge",
    "APIBridge",
    "FakeBridge",
    "BridgeResult",
    "classify",
    "CAPABILITIES",
]

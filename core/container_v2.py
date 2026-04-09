"""Compatibility import for the v2 AI chain.

The primary container now wires PromptBuilderV2 and AIServiceV2 directly.
This module remains only to avoid breaking older imports while the rollout
finishes across scripts and local tooling.
"""

from core.container import Container


__all__ = ["Container"]

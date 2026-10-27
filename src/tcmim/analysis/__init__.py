"""
src/tcmim/analysis/__init__.py
==============================
TCMIM analysis package.

Exposes the Stage 2 propagation pipeline orchestrator and result types.
"""

from tcmim.analysis.orchestrator import PipelineResult, Stage2Pipeline

__all__ = [
    "PipelineResult",
    "Stage2Pipeline",
]

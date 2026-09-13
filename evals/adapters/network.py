"""Compatibility import for immutable archived validation scripts.

Active runtime code uses :mod:`evals.runtime.network`. The 2026-09-13
full-dataset evidence includes an archived script importing this function.
"""

from evals.runtime.network import trace_endpoint

__all__ = ["trace_endpoint"]

"""BurnGuard: stop AI agents from burning tokens.

Python API:

    from burnguard import Budget, BudgetExceeded, LoopDetector, scan, redact
"""

from burnguard.budget import Budget, BudgetExceeded, BudgetStatus
from burnguard.loops import LoopDetector
from burnguard.scanner import Finding, find_injection, find_pii, find_secrets, redact, scan

__version__ = "0.2.0"

__all__ = [
    "Budget",
    "BudgetExceeded",
    "BudgetStatus",
    "Finding",
    "LoopDetector",
    "find_injection",
    "find_pii",
    "find_secrets",
    "redact",
    "scan",
    "__version__",
]

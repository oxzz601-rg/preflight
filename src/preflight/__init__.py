"""preflight: does this project actually run on this machine?"""

from .core import Check, format_report, run_checks, summary

__version__ = "0.1.0"

__all__ = ["Check", "format_report", "run_checks", "summary"]

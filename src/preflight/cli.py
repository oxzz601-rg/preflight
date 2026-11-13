"""The ``preflight`` command line."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import __version__
from .core import format_report, run_checks, summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="preflight",
        description="Check that a project is ready to run on this machine.",
    )
    parser.add_argument("path", nargs="?", default=".", help="project root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--version", action="version", version="preflight {}".format(__version__))
    args = parser.parse_args(argv)

    root = pathlib.Path(args.path)
    if not root.is_dir():
        print("preflight: {} is not a directory".format(root), file=sys.stderr)
        return 2

    checks = run_checks(root)
    totals = summary(checks)
    if args.json:
        print(json.dumps({"root": str(root), "summary": totals, "checks": [check.to_dict() for check in checks]}, indent=2))
    else:
        print(format_report(checks))

    if totals["fail"]:
        return 1
    if args.strict and totals["warn"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

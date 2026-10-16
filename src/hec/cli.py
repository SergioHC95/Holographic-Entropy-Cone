"""One supported entry point for HEC proof construction and verification."""

from __future__ import annotations

import argparse
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("construct", "check", "plan", "storage", "native"))
    if not argv or argv[0] in ("-h", "--help"):
        parser.print_help()
        return
    args = parser.parse_args(argv[:1])
    if args.command == "construct":
        from .authoring import main as run
    elif args.command == "storage":
        from .storage import main as run
    elif args.command == "native":
        from .native import main as run
    elif args.command == "plan":
        from .reconstruction_checks import main as run

        argv.insert(1, "plan")
    else:
        from .reconstruction_checks import main as run

    run(argv[1:])

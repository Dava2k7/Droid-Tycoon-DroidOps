"""Application and frozen-process entry point."""

import argparse
import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="DroidOps", description="Danksy DroidOps")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--self-check", nargs="?", const="", metavar="REPORT")
    parser.add_argument("--no-desktop-check", action="store_true")
    args = parser.parse_args()
    if args.version:
        from . import __version__

        print(__version__)
        return 0
    if sys.platform != "win32":
        parser.error("DroidOps requires 64-bit Windows 10 or Windows 11.")
    if args.self_check is not None:
        from .runtime_check import run_self_check

        return run_self_check(args.self_check or None, desktop=not args.no_desktop_check)
    from .app import main as run

    run()
    return 0

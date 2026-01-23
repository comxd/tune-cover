#!/usr/bin/env python3
"""
TuneCover - Unified entry point.

A tool for fetching and embedding album artwork.
Supports both GUI and CLI modes.

Usage:
    python -m src.main              # Launch GUI (default)
    python -m src.main gui          # Launch GUI explicitly
    python -m src.main scan <path>  # Scan library (CLI)
    python -m src.main fetch <file> # Fetch covers (CLI)
"""

import sys


def check_core_dependencies():
    """Check if core dependencies are installed."""
    missing = []

    try:
        import mutagen
    except ImportError:
        missing.append("mutagen")

    try:
        import requests
    except ImportError:
        missing.append("requests")

    if missing:
        print("Missing dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nInstall with:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)


def main():
    """Main entry point."""
    # Check core dependencies first
    check_core_dependencies()

    # Import CLI module
    from src.cli.commands import create_parser, run_cli
    from src.utils.logging import setup_logging

    # Parse arguments
    parser = create_parser()
    args = parser.parse_args()

    # Configure logging
    setup_logging(verbose=getattr(args, "verbose", False), log_file=getattr(args, "log_file", None))

    # Run the appropriate command
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main() or 0)

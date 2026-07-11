"""Atlas entry point.

Usage:
    uv run python run.py           # start Atlas and run until Ctrl-C
    uv run python run.py --once    # bootstrap, health-check, report, exit
"""

from __future__ import annotations

import argparse
import sys

from atlas.kernel import build_application


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas")
    parser.add_argument(
        "--once",
        action="store_true",
        help="bootstrap, run health checks, print status, then exit",
    )
    args = parser.parse_args(argv)

    app = build_application()

    if args.once:
        app.start()
        report = app.health()
        for name, status in report.items():
            flag = "OK" if status.healthy else "FAIL"
            print(f"  [{flag}] {name}: {status.detail}")
        app.stop()
        return 0 if app.healthy() else 1

    app.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

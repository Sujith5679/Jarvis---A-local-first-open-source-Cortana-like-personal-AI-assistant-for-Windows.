"""Entry point: `python -m app.main` (invoked by start_jarvis.bat)."""

from __future__ import annotations

import sys

from app.bootstrap import bootstrap
from app.lifecycle import run_health_checks, shutdown


def main() -> int:
    ctx = bootstrap()
    health_results = run_health_checks(ctx)

    from ui.chat_window import run as run_ui

    try:
        exit_code = run_ui(ctx, health_results=health_results)
    finally:
        shutdown(ctx)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

"""Minimal, safe entry point for Dev Container smoke tests.

The real Discord/CSV/stock-price implementation is not yet present.
"""

import os


def main() -> None:
    dry_run = os.getenv("DRY_RUN", "true").lower() in {"true", "1", "yes"}
    if not dry_run:
        raise RuntimeError(
            "Live mode is not implemented. Keep DRY_RUN=true until explicitly enabled."
        )
    print("stock-signal development environment is ready (DRY_RUN=true).")


if __name__ == "__main__":
    main()

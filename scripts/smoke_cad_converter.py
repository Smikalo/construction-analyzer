#!/usr/bin/env python3
"""Real-runtime smoke test for the CAD/export converter seam."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.services.engineering_converters import (  # noqa: E402
    format_engineering_converter_smoke_report,
    run_engineering_converter_smoke,
)


def main() -> int:
    result = run_engineering_converter_smoke(get_settings())
    print(format_engineering_converter_smoke_report(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

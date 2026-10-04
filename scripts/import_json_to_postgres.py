#!/usr/bin/env python3
"""CLI wrapper for the legacy JSON to PostgreSQL importer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.json_importer import main


if __name__ == "__main__":
    raise SystemExit(main())

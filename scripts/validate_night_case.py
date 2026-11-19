"""Read-only Night City draft validation; always incomplete until all gates exist."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.night_case_format import validate_case_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверить черновик дела «Ночного города»")
    parser.add_argument("case", help="Путь к JSON дела")
    args = parser.parse_args(argv)
    report = validate_case_file(args.case)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    json.dump(asdict(report), sys.stdout, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0 if report.publishable else 1


if __name__ == "__main__":
    raise SystemExit(main())

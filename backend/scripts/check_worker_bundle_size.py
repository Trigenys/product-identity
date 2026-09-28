from __future__ import annotations

import argparse
import re
from pathlib import Path

TOTAL_UPLOAD_RE = re.compile(r"Total Upload:\s*([0-9.]+)\s*(bytes|KiB|MiB)", re.IGNORECASE)


def to_mib(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit == "mib":
        return value
    if unit == "kib":
        return value / 1024
    return value / (1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce a Cloudflare Worker bundle-size budget.")
    parser.add_argument("log", type=Path)
    parser.add_argument("--warn-mib", type=float, default=50.0)
    parser.add_argument("--max-mib", type=float, default=60.0)
    args = parser.parse_args()

    text = args.log.read_text(encoding="utf-8", errors="replace")
    matches = list(TOTAL_UPLOAD_RE.finditer(text))
    if not matches:
        raise SystemExit("Could not find Wrangler 'Total Upload' in build output.")

    value = float(matches[-1].group(1))
    unit = matches[-1].group(2)
    size_mib = to_mib(value, unit)

    print(f"Worker bundle: {size_mib:.2f} MiB")
    print(f"Warning budget: {args.warn_mib:.2f} MiB")
    print(f"Hard budget: {args.max_mib:.2f} MiB")

    if size_mib > args.max_mib:
        print(f"::error::Worker bundle is {size_mib:.2f} MiB, above the {args.max_mib:.2f} MiB project budget.")
        return 1
    if size_mib > args.warn_mib:
        print(f"::warning::Worker bundle is {size_mib:.2f} MiB, above the {args.warn_mib:.2f} MiB warning budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

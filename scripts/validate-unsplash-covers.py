#!/usr/bin/env python3
"""Validate Unsplash cover photo IDs used by the AIHues article pipeline.

Default usage:
    python3 scripts/validate-unsplash-covers.py

Optional usage:
    python3 scripts/validate-unsplash-covers.py ../apps/aihues-web/content/resources/posts.json

The script scans text files for Unsplash photo IDs, calls curl with HEAD requests,
and fails if any URL does not return HTTP 200 with image/jpeg or image/png.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "src" / "core" / "article_generator.py"
PHOTO_ID_RE = re.compile(r"photo-[0-9a-f-]+")
VALID_CONTENT_TYPES = {"image/jpeg", "image/png"}


def find_photo_ids(paths: list[Path]) -> list[str]:
    photo_ids: set[str] = set()
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")
        text = path.read_text(encoding="utf-8")
        photo_ids.update(PHOTO_ID_RE.findall(text))
    return sorted(photo_ids)


def _last_header_block(raw_headers: str) -> list[str]:
    blocks = [block for block in raw_headers.replace("\r\n", "\n").split("\n\n") if block.strip()]
    if not blocks:
        return []
    return blocks[-1].splitlines()


def validate_photo_id(photo_id: str, timeout: int) -> tuple[bool, str, str, str]:
    url = f"https://images.unsplash.com/{photo_id}?w=1200&q=80"
    result = subprocess.run(
        ["curl", "-sI", "-L", "--max-time", str(timeout), url],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    lines = _last_header_block(result.stdout)
    status = lines[0] if lines else f"curl-error rc={result.returncode}"
    content_type = ""
    content_length = ""

    for line in lines[1:]:
        key, _, value = line.partition(":")
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key == "content-type":
            content_type = normalized_value.split(";")[0].strip().lower()
        elif normalized_key == "content-length":
            content_length = normalized_value

    ok = status.startswith("HTTP/") and " 200" in status and content_type in VALID_CONTENT_TYPES
    return ok, status, content_type, content_length


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Unsplash cover image IDs")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files to scan for photo-* IDs. Defaults to src/core/article_generator.py",
    )
    parser.add_argument("--timeout", type=int, default=20, help="curl timeout per URL in seconds")
    args = parser.parse_args()

    paths = [Path(p).resolve() for p in args.paths] if args.paths else [DEFAULT_SOURCE]

    try:
        photo_ids = find_photo_ids(paths)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not photo_ids:
        print("No Unsplash photo IDs found.")
        return 0

    failures: list[tuple[str, str, str, str]] = []
    for photo_id in photo_ids:
        ok, status, content_type, content_length = validate_photo_id(photo_id, args.timeout)
        label = "OK" if ok else "BAD"
        print(f"{label}\t{photo_id}\t{status}\t{content_type}\t{content_length}")
        if not ok:
            failures.append((photo_id, status, content_type, content_length))

    print(f"TOTAL {len(photo_ids)} IDs, failures {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

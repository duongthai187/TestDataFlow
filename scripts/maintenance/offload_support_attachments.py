#!/usr/bin/env python3
"""Utility to offload aged support attachments to an archive directory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from services.support_service.app.storage import LocalAttachmentStorage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offload aged support attachments to cold storage")
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path(os.getenv("SUPPORT_ATTACHMENT_DIR", "./data/support/attachments")),
        help="Root directory where active attachments are stored (default: %(default)s or SUPPORT_ATTACHMENT_DIR)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Destination directory for archived attachments (default: <storage-dir>/archive)",
    )
    parser.add_argument(
        "--age-days",
        type=int,
        default=int(os.getenv("SUPPORT_ATTACHMENT_MAX_AGE_DAYS", "30")),
        help="Move files older than this many days (default: %(default)s or SUPPORT_ATTACHMENT_MAX_AGE_DAYS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be offloaded without moving them",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SUPPORT_ATTACHMENT_BASE_URL"),
        help="Optional public base URL (used for logging only)",
    )
    return parser.parse_args()


def _scan_candidates(storage_dir: Path, cutoff: datetime) -> list[Path]:
    candidates: list[Path] = []
    for path in storage_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        last_modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if last_modified <= cutoff:
            candidates.append(path)
    return sorted(candidates)


async def _offload(
    storage: LocalAttachmentStorage,
    *,
    storage_dir: Path,
    age: timedelta,
    archive_dir: Path | None,
    dry_run: bool,
) -> dict[str, object]:
    cutoff = datetime.now(timezone.utc) - age
    if dry_run:
        candidates = _scan_candidates(storage_dir, cutoff)
        total_bytes = sum(path.stat().st_size for path in candidates)
        return {
            "dry_run": True,
            "candidates": len(candidates),
            "total_bytes": total_bytes,
            "cutoff": cutoff.isoformat(),
        }

    archive_root = archive_dir
    moved = await storage.offload_older_than(age=age, archive_path=archive_root)
    total_bytes = sum(path.stat().st_size for path in moved if path.exists())
    return {
        "dry_run": False,
        "moved": len(moved),
        "total_bytes": total_bytes,
        "archive_root": str((archive_root or (storage_dir / "archive")).resolve()),
    }


async def main_async() -> int:
    args = parse_args()
    age = timedelta(days=args.age_days)
    storage_dir = args.storage_dir.resolve()
    if not storage_dir.exists():
        storage_dir.mkdir(parents=True, exist_ok=True)
    archive = args.archive_dir.resolve() if args.archive_dir else None

    storage = LocalAttachmentStorage(storage_dir, args.base_url)
    try:
        report = await _offload(
            storage,
            storage_dir=storage_dir,
            age=age,
            archive_dir=archive,
            dry_run=args.dry_run,
        )
    finally:
        await storage.close()

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main() -> None:
    try:
        exit_code = asyncio.run(main_async())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

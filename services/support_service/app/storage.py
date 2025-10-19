"""Attachment storage helpers for the support service."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from fastapi import UploadFile

from .metrics import (
    SUPPORT_ATTACHMENT_BACKLOG_BYTES,
    SUPPORT_ATTACHMENT_BACKLOG_FILES,
    SUPPORT_ATTACHMENT_STORED_TOTAL,
    normalise_content_type,
    update_attachment_backlog_gauges,
)


@dataclass(slots=True)
class AttachmentStorageResult:
    """Result metadata returned after persisting an attachment."""

    uri: str
    size_bytes: int
    relative_path: str


class AttachmentStorageProtocol(Protocol):
    async def save(self, file: UploadFile, relative_path: str) -> AttachmentStorageResult:
        ...

    async def offload_older_than(
        self,
        *,
        age: timedelta,
        archive_path: Path | None = None,
    ) -> list[Path]:
        ...

    async def close(self) -> None:
        ...


class LocalAttachmentStorage:
    """Simple filesystem-backed storage useful for local development and tests."""

    def __init__(self, base_path: Path, base_url: str | None = None) -> None:
        self._base_path = base_path
        self._base_url = base_url.rstrip("/") if base_url else None
        self._base_path.mkdir(parents=True, exist_ok=True)
        update_attachment_backlog_gauges(self._base_path)

    async def save(self, file: UploadFile, relative_path: str) -> AttachmentStorageResult:
        safe_relative = relative_path.lstrip("/")
        target_path = self._base_path / safe_relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        data = await file.read()
        await asyncio.to_thread(target_path.write_bytes, data)
        SUPPORT_ATTACHMENT_STORED_TOTAL.labels(
            content_type=normalise_content_type(file.content_type)
        ).inc()
        SUPPORT_ATTACHMENT_BACKLOG_FILES.inc()
        SUPPORT_ATTACHMENT_BACKLOG_BYTES.inc(len(data))
        await asyncio.to_thread(update_attachment_backlog_gauges, self._base_path)
        return AttachmentStorageResult(
            uri=self._build_uri(safe_relative),
            size_bytes=len(data),
            relative_path=safe_relative,
        )

    async def offload_older_than(
        self,
        *,
        age: timedelta,
        archive_path: Path | None = None,
    ) -> list[Path]:
        """Move attachments older than ``age`` to an archive directory.

        The archive path defaults to ``<base_path>/archive`` and will be created
        automatically. The method returns the list of files moved so that callers
        can feed the output to further processing (e.g. uploading to cold
        storage).
        """

        if age <= timedelta(0):  # Defensive guard to prevent accidental wipes.
            raise ValueError("age must be a positive duration")

        cutoff = datetime.now(timezone.utc) - age
        source_root = self._base_path.resolve()
        destination_root = (archive_path or (self._base_path / "archive")).resolve()
        moved: list[Path] = []

        def _move_files() -> None:
            for candidate in source_root.rglob("*"):
                if not candidate.is_file():
                    continue
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                last_modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                if last_modified > cutoff:
                    continue
                relative = candidate.relative_to(source_root)
                destination = destination_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(candidate), destination)
                moved.append(destination)

        await asyncio.to_thread(_move_files)
        await asyncio.to_thread(update_attachment_backlog_gauges, self._base_path)
        return moved

    async def close(self) -> None:
        # Nothing to clean up for local filesystem storage.
        return None

    def _build_uri(self, relative_path: str) -> str:
        if self._base_url is not None:
            return f"{self._base_url}/{relative_path}"
        return relative_path

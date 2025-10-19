"""Prometheus metrics for the support service."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from prometheus_client import Counter, Gauge, Histogram


SUPPORT_TICKET_CREATED_TOTAL: Final = Counter(
    "support_ticket_created_total",
    "Number of support tickets created.",
    labelnames=("channel",),
)

SUPPORT_CONVERSATION_ADDED_TOTAL: Final = Counter(
    "support_conversation_added_total",
    "Number of support ticket conversations created.",
    labelnames=("author_type",),
)

SUPPORT_TICKET_STATUS_CHANGED_TOTAL: Final = Counter(
    "support_ticket_status_changed_total",
    "Number of support ticket status transitions.",
    labelnames=("status",),
)

SUPPORT_TIMELINE_COLLECT_SECONDS: Final = Histogram(
    "support_timeline_collect_seconds",
    "Latency to assemble ticket timelines.",
    labelnames=("source",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL: Final = Counter(
    "support_timeline_cache_events_total",
    "Count of timeline cache interactions.",
    labelnames=("event",),
)

SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL: Final = Counter(
    "support_timeline_collection_failures_total",
    "Number of timeline aggregation failures.",
    labelnames=("stage",),
)

SUPPORT_ATTACHMENT_STORED_TOTAL: Final = Counter(
    "support_attachment_stored_total",
    "Number of ticket attachments persisted.",
    labelnames=("content_type",),
)

SUPPORT_ATTACHMENT_BACKLOG_BYTES: Final = Gauge(
    "support_attachment_backlog_bytes",
    "Total bytes stored in the support attachment repository.",
)

SUPPORT_ATTACHMENT_BACKLOG_FILES: Final = Gauge(
    "support_attachment_backlog_files",
    "Total number of files stored in the support attachment repository.",
)


def normalise_channel(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.strip().lower() or "unknown"


def normalise_author(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.strip().lower() or "unknown"


def normalise_status(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.strip().lower() or "unknown"


def normalise_content_type(value: str | None) -> str:
    if not value:
        return "application/octet-stream"
    normalised = value.strip().lower()
    return normalised or "application/octet-stream"


def update_attachment_backlog_gauges(base_path: Path) -> None:
    total_bytes = 0
    total_files = 0
    if base_path.exists():
        for path in base_path.rglob("*"):
            if path.is_file():
                try:
                    stat = path.stat()
                except OSError:
                    continue
                total_bytes += stat.st_size
                total_files += 1
    SUPPORT_ATTACHMENT_BACKLOG_BYTES.set(total_bytes)
    SUPPORT_ATTACHMENT_BACKLOG_FILES.set(total_files)

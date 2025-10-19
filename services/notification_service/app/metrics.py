"""Prometheus metrics for the notification service."""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Histogram

_EVENT_OUTCOME_LABELS: Final = (
    "processed",
    "invalid_payload",
    "missing_customer",
    "no_recipient",
    "opted_out",
    "rate_limited",
    "unsupported_topic",
)

# Notification delivery lifecycle -----------------------------------------------------------
NOTIFICATION_SENT_TOTAL: Final = Counter(
    "notification_sent_total",
    "Total number of notifications successfully sent.",
    labelnames=("channel",),
)

NOTIFICATION_FAILURE_TOTAL: Final = Counter(
    "notification_failure_total",
    "Total number of notifications that failed to send.",
    labelnames=("channel",),
)

NOTIFICATION_RATE_LIMIT_TOTAL: Final = Counter(
    "notification_rate_limited_total",
    "Number of notification send attempts blocked by rate limiting.",
    labelnames=("channel",),
)

NOTIFICATION_RATE_LIMIT_ERRORS_TOTAL: Final = Counter(
    "notification_rate_limit_errors_total",
    "Number of rate limiter Redis errors handled by the service.",
    labelnames=("operation",),
)

NOTIFICATION_OPT_OUT_TOTAL: Final = Counter(
    "notification_opt_out_total",
    "Number of notification sends skipped because the customer opted out.",
    labelnames=("channel",),
)

NOTIFICATION_SEND_LATENCY_SECONDS: Final = Histogram(
    "notification_send_latency_seconds",
    "Time taken to hand notifications off to the provider.",
    labelnames=("channel",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

# Preference changes -----------------------------------------------------------------------
NOTIFICATION_PREFERENCE_UPDATES_TOTAL: Final = Counter(
    "notification_preference_updates_total",
    "Total notification preference updates processed per channel.",
    labelnames=("channel",),
)

# Event handling ---------------------------------------------------------------------------
NOTIFICATION_EVENTS_PROCESSED_TOTAL: Final = Counter(
    "notification_events_processed_total",
    "Domain events that resulted in a notification being enqueued/sent.",
    labelnames=("topic",),
)

NOTIFICATION_EVENTS_DROPPED_TOTAL: Final = Counter(
    "notification_events_dropped_total",
    "Domain events skipped during processing due to validation or opt-out.",
    labelnames=("topic", "reason"),
)


def normalise_event_reason(raw_reason: str) -> str:
    """Return a bounded label value for event outcome counters."""

    reason = (raw_reason or "unsupported_topic").strip().lower().replace(" ", "_")
    if reason not in _EVENT_OUTCOME_LABELS:
        return "unsupported_topic"
    return reason
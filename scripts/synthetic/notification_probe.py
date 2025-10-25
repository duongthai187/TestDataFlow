#!/usr/bin/env python3
"""Synthetic probe for the notification service.

This script exercises the create/send flow of the notification API, measures
latency, and (optionally) verifies that key Prometheus metrics increment as
expected. Intended for on-call automation and scheduled synthetic checks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import httpx

CHANNEL_LABEL = "channel"

_METRIC_LINE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)$"
)


@dataclass(slots=True)
class MetricSample:
    name: str
    labels: Mapping[str, str]
    value: float


@dataclass(slots=True)
class MetricDelta:
    name: str
    labels: Mapping[str, str]
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


class ProbeError(RuntimeError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context = dict(context or {})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthetic probe for notification service")
    parser.add_argument(
        "--base-url",
        default=os.getenv("NOTIFICATION_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL for the notification service (default: %(default)s or NOTIFICATION_BASE_URL)",
    )
    parser.add_argument(
        "--metrics-path",
        default=os.getenv("NOTIFICATION_METRICS_PATH", "/metrics"),
        help="Path to Prometheus metrics endpoint (default: %(default)s or NOTIFICATION_METRICS_PATH)",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip verification of Prometheus metric deltas",
    )
    parser.add_argument(
        "--channel",
        default=os.getenv("NOTIFICATION_PROBE_CHANNEL", "email"),
        help="Channel to send notification on (default: %(default)s or NOTIFICATION_PROBE_CHANNEL)",
    )
    parser.add_argument(
        "--recipient",
        default=os.getenv("NOTIFICATION_PROBE_RECIPIENT", "synthetic@example.com"),
        help="Recipient to target (default: %(default)s or NOTIFICATION_PROBE_RECIPIENT)",
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="Override subject. Default generates a unique synthetic subject",
    )
    parser.add_argument(
        "--body",
        default=None,
        help="Override body. Default generates a synthetic body",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Polling interval (seconds) when waiting for status (default: %(default)s)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=5.0,
        help="Maximum time (seconds) to wait for final status (default: %(default)s)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=5.0,
        help="HTTP client timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--max-send-ms",
        type=float,
        default=float(os.getenv("NOTIFICATION_PROBE_MAX_SEND_MS", "2000")),
        help="Maximum allowed send latency in milliseconds (default: %(default)s or NOTIFICATION_PROBE_MAX_SEND_MS)",
    )
    parser.add_argument(
        "--expect-status",
        default=os.getenv("NOTIFICATION_PROBE_EXPECT_STATUS", "sent"),
        help="Expected final notification status (default: %(default)s or NOTIFICATION_PROBE_EXPECT_STATUS)",
    )
    return parser.parse_args()


def _parse_labels(raw: str | None) -> Dict[str, str]:
    if not raw:
        return {}
    labels: Dict[str, str] = {}
    parts = []
    current = []
    escaped = False
    in_quotes = False
    for char in raw:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
            continue
        if char == "," and not in_quotes:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current))
    for part in parts:
        if not part:
            continue
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            inner = value[1:-1]
            try:
                value = bytes(inner, "utf-8").decode("unicode_escape")
            except Exception:
                value = inner.replace('\\\"', '"').replace('\\\\', '\\')
            labels[key] = value
    return labels


def parse_metrics(text: str) -> List[MetricSample]:
    samples: List[MetricSample] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _METRIC_LINE.match(stripped)
        if not match:
            continue
        name = match.group("name")
        labels = _parse_labels(match.group("labels"))
        value = float(match.group("value"))
        samples.append(MetricSample(name=name, labels=labels, value=value))
    return samples


def find_metric_value(
    samples: Sequence[MetricSample],
    name: str,
    *,
    labels: Mapping[str, str],
) -> float:
    for sample in samples:
        if sample.name != name:
            continue
        if all(sample.labels.get(key) == value for key, value in labels.items()):
            return sample.value
    return 0.0


async def fetch_metrics(client: httpx.AsyncClient, path: str) -> List[MetricSample]:
    response = await client.get(path)
    response.raise_for_status()
    return parse_metrics(response.text)


async def _create_notification(client: httpx.AsyncClient, payload: Mapping[str, Any]) -> Tuple[int, float]:
    start = time.monotonic()
    response = await client.post("/notifications", json=payload)
    duration = (time.monotonic() - start) * 1000.0
    if response.status_code != 201:
        raise ProbeError(
            "Failed to create notification",
            context={"status_code": response.status_code, "body": response.text},
        )
    data = response.json()
    return int(data["id"]), duration


async def _send_notification(client: httpx.AsyncClient, notification_id: int) -> tuple[str, float]:
    start = time.monotonic()
    response = await client.post(f"/notifications/{notification_id}/send")
    duration = (time.monotonic() - start) * 1000.0
    if response.status_code == 429:
        raise ProbeError("Notification send rejected due to rate limit", context={"notification_id": notification_id})
    if response.status_code != 200:
        raise ProbeError(
            "Failed to send notification",
            context={"status_code": response.status_code, "body": response.text, "notification_id": notification_id},
        )
    data = response.json()
    return str(data.get("status", "")), duration


async def _poll_status(
    client: httpx.AsyncClient,
    notification_id: int,
    *,
    interval: float,
    timeout: float,
) -> tuple[str, float]:
    start = time.monotonic()
    deadline = start + timeout
    attempt = 0
    while True:
        attempt += 1
        response = await client.get(f"/notifications/{notification_id}")
        if response.status_code != 200:
            raise ProbeError(
                "Failed to fetch notification status",
                context={"status_code": response.status_code, "body": response.text, "notification_id": notification_id},
            )
        data = response.json()
        status = str(data.get("status", ""))
        if status in {"sent", "failed"}:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            return status, elapsed_ms
        if time.monotonic() >= deadline:
            raise ProbeError(
                "Notification status did not settle before timeout",
                context={"notification_id": notification_id, "timeout": timeout, "attempts": attempt},
            )
        await asyncio.sleep(interval)


def build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    identifier = uuid.uuid4().hex[:8]
    subject = args.subject or f"Synthetic probe {identifier}"
    body = args.body or f"Synthetic notification body {identifier}"
    metadata = {"probe": "notification", "id": identifier}
    return {
        "recipient": args.recipient,
        "channel": args.channel,
        "subject": subject,
        "body": body,
        "metadata": metadata,
    }


def _calc_metric_deltas(
    before: Sequence[MetricSample],
    after: Sequence[MetricSample],
    *,
    name: str,
    labels: Mapping[str, str],
) -> MetricDelta:
    return MetricDelta(
        name=name,
        labels=dict(labels),
        before=find_metric_value(before, name, labels=labels),
        after=find_metric_value(after, name, labels=labels),
    )


async def run_probe(args: argparse.Namespace) -> Dict[str, Any]:
    timeout = httpx.Timeout(args.request_timeout)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        metrics_before: Sequence[MetricSample] = ()
        if not args.skip_metrics:
            metrics_before = await fetch_metrics(client, args.metrics_path)

        payload = build_payload(args)
        notification_id, create_ms = await _create_notification(client, payload)
        _, send_ms = await _send_notification(client, notification_id)
        status, poll_ms = await _poll_status(
            client,
            notification_id,
            interval=args.poll_interval,
            timeout=args.poll_timeout,
        )
        total_ms = create_ms + send_ms + poll_ms

        if send_ms > args.max_send_ms:
            raise ProbeError(
                "Notification send latency exceeded threshold",
                context={"send_ms": round(send_ms, 2), "threshold_ms": args.max_send_ms},
            )

        if status.lower() != args.expect_status.lower():
            raise ProbeError(
                "Final status did not match expectation",
                context={
                    "expected": args.expect_status,
                    "actual": status,
                    "notification_id": notification_id,
                },
            )

        metrics_after: Sequence[MetricSample] = ()
        metric_results: List[MetricDelta] = []
        if not args.skip_metrics:
            metrics_after = await fetch_metrics(client, args.metrics_path)
            label_filter = {CHANNEL_LABEL: args.channel}
            metric_results.append(
                _calc_metric_deltas(
                    metrics_before,
                    metrics_after,
                    name="notification_sent_total",
                    labels=label_filter,
                )
            )
            metric_results.append(
                _calc_metric_deltas(
                    metrics_before,
                    metrics_after,
                    name="notification_send_latency_seconds_count",
                    labels=label_filter,
                )
            )
            metric_results.append(
                _calc_metric_deltas(
                    metrics_before,
                    metrics_after,
                    name="notification_failure_total",
                    labels=label_filter,
                )
            )
            sent_delta = metric_results[0].delta
            latency_delta = metric_results[1].delta
            failure_delta = metric_results[2].delta
            if sent_delta < 1:
                raise ProbeError(
                    "notification_sent_total did not increment",
                    context={"delta": sent_delta, "channel": args.channel},
                )
            if latency_delta < 1:
                raise ProbeError(
                    "notification_send_latency_seconds_count did not increment",
                    context={"delta": latency_delta, "channel": args.channel},
                )
            if failure_delta > 0:
                raise ProbeError(
                    "notification_failure_total increased during probe",
                    context={"delta": failure_delta, "channel": args.channel},
                )
        else:
            metrics_after = ()

        result = {
            "status": "ok",
            "notificationId": notification_id,
            "finalStatus": status,
            "durationsMs": {
                "create": round(create_ms, 2),
                "send": round(send_ms, 2),
                "poll": round(poll_ms, 2),
                "total": round(total_ms, 2),
            },
            "metrics": [
                {
                    "name": delta.name,
                    "labels": delta.labels,
                    "before": delta.before,
                    "after": delta.after,
                    "delta": delta.delta,
                }
                for delta in metric_results
            ],
        }
        return result


async def main_async() -> int:
    args = parse_args()
    try:
        result = await run_probe(args)
    except ProbeError as exc:
        payload = {"status": "error", "message": str(exc), "context": exc.context}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    except Exception as exc:  # pragma: no cover - defensive guard for unexpected failures
        payload = {
            "status": "error",
            "message": str(exc),
            "context": {"exc_type": exc.__class__.__name__},
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> None:
    exit_code = asyncio.run(main_async())
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

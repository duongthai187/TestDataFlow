#!/usr/bin/env python3
"""Simulate notification provider failures to exercise alerts and dashboards.

The script creates synthetic notifications via the public API and immediately
marks them as failed using the `/notifications/{id}/fail` endpoint. This drives
`notification_failure_total` and failure events, matching the path triggered
when the provider raises during `send_notification`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence

import httpx

CHANNEL_LABEL = "channel"


@dataclass(slots=True)
class MetricSample:
    name: str
    labels: Mapping[str, str]
    value: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate notification provider failures")
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
        "--count",
        type=int,
        default=5,
        help="Number of notifications to mark as failed (default: %(default)s)",
    )
    parser.add_argument(
        "--channel",
        default=os.getenv("NOTIFICATION_CHAOS_CHANNEL", "email"),
        help="Channel value for created notifications (default: %(default)s or NOTIFICATION_CHAOS_CHANNEL)",
    )
    parser.add_argument(
        "--recipient",
        default=os.getenv("NOTIFICATION_CHAOS_RECIPIENT", "ops-chaos@example.com"),
        help="Recipient address used for synthetic notifications (default: %(default)s or NOTIFICATION_CHAOS_RECIPIENT)",
    )
    parser.add_argument(
        "--reason",
        default="provider_error: simulated_chaos",
        help="Failure reason recorded for each notification (default: %(default)s)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=5.0,
        help="HTTP client timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip metric delta verification (useful if metrics endpoint unavailable)",
    )
    return parser.parse_args()


def _parse_labels(raw: str | None) -> Dict[str, str]:
    if not raw:
        return {}
    labels: Dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\"', '"')
        labels[key] = value
    return labels


def parse_metrics(text: str) -> List[MetricSample]:
    samples: List[MetricSample] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            metric, value_str = stripped.split(None, 1)
        except ValueError:
            continue
        if "{" in metric and metric.endswith("}"):
            name, label_str = metric.split("{", 1)
            labels = _parse_labels(label_str[:-1])
        else:
            name = metric
            labels = {}
        try:
            value = float(value_str)
        except ValueError:
            continue
        samples.append(MetricSample(name=name, labels=labels, value=value))
    return samples


def find_metric_value(samples: Sequence[MetricSample], name: str, *, labels: Mapping[str, str]) -> float:
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


async def create_notification(client: httpx.AsyncClient, *, channel: str, recipient: str, index: int) -> int:
    payload = {
        "recipient": recipient,
        "channel": channel,
        "subject": f"Chaos notification {index}",
        "body": f"Synthetic chaos payload #{index}",
        "metadata": {"chaos": True, "index": index},
    }
    response = await client.post("/notifications", json=payload)
    if response.status_code != 201:
        raise RuntimeError(
            f"Failed to create notification {index}: status={response.status_code} body={response.text}"
        )
    data = response.json()
    return int(data["id"])


async def fail_notification(client: httpx.AsyncClient, notification_id: int, *, reason: str) -> None:
    response = await client.post(f"/notifications/{notification_id}/fail", json={"message": reason})
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to mark notification {notification_id} as failed: status={response.status_code} body={response.text}"
        )


async def run(args: argparse.Namespace) -> dict[str, object]:
    timeout = httpx.Timeout(args.request_timeout)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        metrics_before: Sequence[MetricSample] = ()
        if not args.skip_metrics:
            metrics_before = await fetch_metrics(client, args.metrics_path)

        start = time.monotonic()
        ids: List[int] = []
        for index in range(1, args.count + 1):
            notification_id = await create_notification(
                client,
                channel=args.channel,
                recipient=args.recipient,
                index=index,
            )
            await fail_notification(client, notification_id, reason=args.reason)
            ids.append(notification_id)
        duration = time.monotonic() - start

        metrics_after: Sequence[MetricSample] = ()
        failure_delta: float | None = None
        if not args.skip_metrics:
            metrics_after = await fetch_metrics(client, args.metrics_path)
            failure_delta = find_metric_value(
                metrics_after,
                "notification_failure_total",
                labels={CHANNEL_LABEL: args.channel},
            ) - find_metric_value(
                metrics_before,
                "notification_failure_total",
                labels={CHANNEL_LABEL: args.channel},
            )

    return {
        "count": args.count,
        "fail_reason": args.reason,
        "durationSeconds": round(duration, 2),
        "notificationIds": ids,
        "failureMetricDelta": failure_delta,
    }


async def main_async() -> int:
    args = parse_args()
    try:
        report = await run(args)
    except Exception as exc:  # pragma: no cover - defensive guard
        payload = {"status": "error", "message": str(exc)}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    payload = {"status": "ok", **report}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main() -> None:
    exit_code = asyncio.run(main_async())
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Chaos scenario to exercise notification rate limiter during Redis outages.

The script intentionally disrupts the Redis dependency used by the notification
service rate limiter, drives traffic through the create/send endpoints, and
verifies that `notification_rate_limit_errors_total` increases while Redis is
unavailable. It optionally manages the Docker Compose service lifecycle to stop
and restart Redis around the experiment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence, Tuple

import httpx

_METRIC_LINE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]??\d+)?)$"
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


@dataclass(slots=True)
class CommandResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class ChaosError(RuntimeError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: Dict[str, Any] = dict(context or {})


def _env_default(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chaos scenario for notification rate limiter when Redis is down")
    parser.add_argument(
        "--base-url",
        default=_env_default("NOTIFICATION_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL for the notification service (default: %(default)s or NOTIFICATION_BASE_URL)",
    )
    parser.add_argument(
        "--metrics-path",
        default=_env_default("NOTIFICATION_METRICS_PATH", "/metrics"),
        help="Path to Prometheus metrics endpoint (default: %(default)s or NOTIFICATION_METRICS_PATH)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=int(_env_default("NOTIFICATION_CHAOS_COUNT", "10")),
        help="Number of notifications to create/send while Redis is offline (default: %(default)s or NOTIFICATION_CHAOS_COUNT)",
    )
    parser.add_argument(
        "--channel",
        default=_env_default("NOTIFICATION_CHAOS_CHANNEL", "email"),
        help="Channel to use for synthetic notifications (default: %(default)s or NOTIFICATION_CHAOS_CHANNEL)",
    )
    parser.add_argument(
        "--recipient",
        default=_env_default("NOTIFICATION_CHAOS_RECIPIENT", "chaos@example.com"),
        help="Recipient for synthetic notifications (default: %(default)s or NOTIFICATION_CHAOS_RECIPIENT)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=float(_env_default("NOTIFICATION_CHAOS_REQUEST_TIMEOUT", "5")),
        help="HTTP client timeout in seconds (default: %(default)s or NOTIFICATION_CHAOS_REQUEST_TIMEOUT)",
    )
    parser.add_argument(
        "--downtime-seconds",
        type=float,
        default=float(_env_default("NOTIFICATION_CHAOS_DOWNTIME", "3")),
        help="Delay after stopping Redis before sending traffic (default: %(default)s or NOTIFICATION_CHAOS_DOWNTIME)",
    )
    parser.add_argument(
        "--metrics-wait",
        type=float,
        default=float(_env_default("NOTIFICATION_CHAOS_METRICS_WAIT", "1")),
        help="Delay (seconds) before fetching metrics after requests complete (default: %(default)s or NOTIFICATION_CHAOS_METRICS_WAIT)",
    )
    parser.add_argument(
        "--compose-cmd",
        default=_env_default("NOTIFICATION_CHAOS_COMPOSE_CMD", "docker compose"),
        help="Docker Compose command, space separated (default: %(default)s or NOTIFICATION_CHAOS_COMPOSE_CMD)",
    )
    parser.add_argument(
        "--compose-file",
        dest="compose_files",
        action="append",
        help="Additional docker-compose file(s) to include (can be specified multiple times)",
    )
    parser.add_argument(
        "--redis-service",
        default=_env_default("NOTIFICATION_CHAOS_REDIS_SERVICE", "redis"),
        help="Docker Compose service name for Redis (default: %(default)s or NOTIFICATION_CHAOS_REDIS_SERVICE)",
    )
    parser.add_argument(
        "--redis-wait-timeout",
        type=float,
        default=float(_env_default("NOTIFICATION_CHAOS_REDIS_WAIT_TIMEOUT", "30")),
        help="Maximum time (seconds) to wait for Redis to respond after restart (default: %(default)s or NOTIFICATION_CHAOS_REDIS_WAIT_TIMEOUT)",
    )
    parser.add_argument(
        "--redis-wait-interval",
        type=float,
        default=float(_env_default("NOTIFICATION_CHAOS_REDIS_WAIT_INTERVAL", "2")),
        help="Interval (seconds) between readiness checks (default: %(default)s or NOTIFICATION_CHAOS_REDIS_WAIT_INTERVAL)",
    )
    parser.add_argument(
        "--compose-stop-timeout",
        type=float,
        default=float(_env_default("NOTIFICATION_CHAOS_COMPOSE_STOP_TIMEOUT", "5")),
        help="Timeout passed to `docker compose stop` in seconds (default: %(default)s or NOTIFICATION_CHAOS_COMPOSE_STOP_TIMEOUT)",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip Prometheus metric collection",
    )
    parser.add_argument(
        "--no-manage-redis",
        dest="manage_redis",
        action="store_false",
        help="Do not stop/start Redis automatically (assumes external orchestration)",
    )
    parser.set_defaults(manage_redis=True)

    args = parser.parse_args()

    if args.count <= 0:
        parser.error("--count must be positive")

    compose_cmd = shlex.split(args.compose_cmd)
    if not compose_cmd:
        parser.error("--compose-cmd resolved to an empty command")

    compose_files_env = os.getenv("NOTIFICATION_CHAOS_COMPOSE_FILES", "")
    compose_files: List[str] = []
    if args.compose_files:
        compose_files.extend(args.compose_files)
    elif compose_files_env:
        compose_files.extend([value for value in compose_files_env.split(":") if value])
    else:
        compose_files.append("docker-compose.yml")

    args.compose_cmd = compose_cmd
    args.compose_files = compose_files
    return args


def _parse_labels(raw: str | None) -> Dict[str, str]:
    if not raw:
        return {}
    labels: Dict[str, str] = {}
    parts: List[str] = []
    current: List[str] = []
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
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            inner = value[1:-1]
            try:
                decoded = bytes(inner, "utf-8").decode("unicode_escape")
            except Exception:
                decoded = inner.replace('\\"', '"').replace('\\\\', '\\')
            labels[key] = decoded
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


async def fetch_metrics(client: httpx.AsyncClient, path: str) -> List[MetricSample]:
    response = await client.get(path)
    response.raise_for_status()
    return parse_metrics(response.text)


def _metric_map(samples: Sequence[MetricSample], name: str) -> Dict[Tuple[Tuple[str, str], ...], float]:
    values: Dict[Tuple[Tuple[str, str], ...], float] = {}
    for sample in samples:
        if sample.name != name:
            continue
        key = tuple(sorted(sample.labels.items()))
        values[key] = sample.value
    return values


def compute_metric_deltas(
    before: Sequence[MetricSample],
    after: Sequence[MetricSample],
    name: str,
) -> List[MetricDelta]:
    previous = _metric_map(before, name)
    current = _metric_map(after, name)
    deltas: List[MetricDelta] = []
    keys = set(previous) | set(current)
    for key in sorted(keys):
        labels = dict(key)
        before_value = previous.get(key, 0.0)
        after_value = current.get(key, 0.0)
        deltas.append(MetricDelta(name=name, labels=labels, before=before_value, after=after_value))
    return deltas


async def _compose_command(
    args: argparse.Namespace,
    extra_args: Sequence[str],
) -> CommandResult:
    def _run() -> CommandResult:
        command = list(args.compose_cmd)
        for compose_file in args.compose_files:
            command.extend(["-f", compose_file])
        command.extend(extra_args)
        start = time.monotonic()
        proc = subprocess.run(command, capture_output=True, text=True)
        duration = time.monotonic() - start
        return CommandResult(
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=duration,
        )

    return await asyncio.to_thread(_run)


async def compose_command(
    args: argparse.Namespace,
    extra_args: Sequence[str],
    *,
    check: bool = True,
) -> CommandResult:
    result = await _compose_command(args, extra_args)
    if check and result.returncode != 0:
        raise ChaosError(
            "Docker Compose command failed",
            context={
                "command": result.command,
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )
    return result


async def wait_for_redis(args: argparse.Namespace) -> MutableMapping[str, Any]:
    deadline = time.monotonic() + args.redis_wait_timeout
    attempts = 0
    last_result: CommandResult | None = None
    while time.monotonic() < deadline:
        attempts += 1
        last_result = await compose_command(
            args,
            ["exec", "-T", args.redis_service, "redis-cli", "PING"],
            check=False,
        )
        if last_result.returncode == 0 and "PONG" in last_result.stdout.upper():
            return {
                "attempts": attempts,
                "ready": True,
                "stdout": last_result.stdout.strip(),
                "stderr": last_result.stderr.strip(),
            }
        await asyncio.sleep(args.redis_wait_interval)
    context: Dict[str, Any] = {"attempts": attempts, "ready": False}
    if last_result is not None:
        context.update(
            {
                "lastCommand": last_result.command,
                "stdout": last_result.stdout.strip(),
                "stderr": last_result.stderr.strip(),
                "returncode": last_result.returncode,
            }
        )
    raise ChaosError("Redis did not become ready within timeout", context=context)


async def _create_notification(client: httpx.AsyncClient, payload: Mapping[str, Any]) -> int:
    response = await client.post("/notifications", json=payload)
    if response.status_code != 201:
        raise ChaosError(
            "Failed to create notification",
            context={"status_code": response.status_code, "body": response.text},
        )
    data = response.json()
    return int(data["id"])


async def _send_notification(client: httpx.AsyncClient, notification_id: int) -> str:
    response = await client.post(f"/notifications/{notification_id}/send")
    if response.status_code == 429:
        raise ChaosError(
            "Notification send hit real rate limit",
            context={"notification_id": notification_id},
        )
    if response.status_code != 200:
        raise ChaosError(
            "Failed to send notification",
            context={
                "notification_id": notification_id,
                "status_code": response.status_code,
                "body": response.text,
            },
        )
    data = response.json()
    return str(data.get("status", ""))


def _build_payload(args: argparse.Namespace) -> Mapping[str, Any]:
    identifier = uuid.uuid4().hex[:8]
    return {
        "recipient": args.recipient,
        "channel": args.channel,
        "subject": f"Chaos redis outage {identifier}",
        "body": f"Synthetic chaos notification {identifier}",
        "metadata": {"chaos": "redis_outage", "id": identifier},
    }


async def run_scenario(args: argparse.Namespace) -> Mapping[str, Any]:
    timeout = httpx.Timeout(args.request_timeout)
    metrics_before: Sequence[MetricSample] = ()
    metrics_after: Sequence[MetricSample] = ()
    if not args.skip_metrics:
        async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
            metrics_before = await fetch_metrics(client, args.metrics_path)

    commands: List[Mapping[str, Any]] = []
    warnings: List[str] = []
    notifications: List[Mapping[str, Any]] = []
    redis_info: Mapping[str, Any] | None = None

    try:
        if args.manage_redis:
            stop_args = ["stop", "--timeout", str(int(args.compose_stop_timeout)), args.redis_service]
            stop_result = await compose_command(args, stop_args)
            commands.append(_command_to_dict(stop_result))
            await asyncio.sleep(max(args.downtime_seconds, 0))
        else:
            warnings.append("Redis management disabled; ensure outage is orchestrated externally")

        async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
            for _ in range(args.count):
                payload = _build_payload(args)
                notification_id = await _create_notification(client, payload)
                status = await _send_notification(client, notification_id)
                notifications.append({"id": notification_id, "status": status})

        await asyncio.sleep(max(args.metrics_wait, 0))
    finally:
        if args.manage_redis:
            start_result = await compose_command(args, ["start", args.redis_service])
            commands.append(_command_to_dict(start_result))
            try:
                redis_info = await wait_for_redis(args)
            except ChaosError as err:
                warnings.append(str(err))
                if err.context:
                    warnings.append(json.dumps(err.context))

    metric_deltas: List[MetricDelta] = []
    if not args.skip_metrics:
        async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
            metrics_after = await fetch_metrics(client, args.metrics_path)
        metric_deltas = compute_metric_deltas(
            metrics_before,
            metrics_after,
            name="notification_rate_limit_errors_total",
        )

    total_delta = sum(delta.delta for delta in metric_deltas)
    return {
        "status": "ok",
        "notifications": notifications,
        "rateLimitErrorDeltas": [
            {
                "labels": delta.labels,
                "before": delta.before,
                "after": delta.after,
                "delta": delta.delta,
            }
            for delta in metric_deltas
        ],
        "totalRateLimitErrorDelta": total_delta,
        "redis": {
            "managed": args.manage_redis,
            "commands": commands,
            "readiness": redis_info,
        },
        "warnings": warnings,
    }


def _command_to_dict(result: CommandResult) -> Mapping[str, Any]:
    return {
        "command": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "durationSeconds": round(result.duration_seconds, 3),
    }


async def main_async() -> int:
    args = parse_args()
    try:
        result = await run_scenario(args)
    except ChaosError as exc:
        payload = {
            "status": "error",
            "message": str(exc),
            "context": exc.context,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2
    except httpx.HTTPError as exc:
        payload = {
            "status": "error",
            "message": f"HTTP error: {exc}",
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 3

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))

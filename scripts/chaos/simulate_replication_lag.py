#!/usr/bin/env python3
"""Chaos scenario to simulate CDC replication lag by pausing Debezium connectors.

The script temporarily pauses Kafka Connect connectors (Debezium) via the REST
API, generates write load against MySQL while replication is halted, waits for a
configurable duration, and then resumes the connectors. It reports connector
states and MySQL binlog position deltas so on-call engineers can validate
alerting/dashboards for replication lag scenarios.
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
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import httpx

_TABLE_NAME = "chaos_replication_events"
_METRIC_LINE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]??\d+)?)$"
)


@dataclass(slots=True)
class CommandResult:
    command: List[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


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


class ChaosError(RuntimeError):
    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: Dict[str, Any] = dict(context or {})


def _env_default(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pause Debezium connectors to simulate replication lag")
    parser.add_argument(
        "--connect-url",
        default=_env_default("REPLICATION_LAG_CONNECT_URL", "http://127.0.0.1:8083"),
        help="Base URL for Kafka Connect REST API (default: %(default)s or REPLICATION_LAG_CONNECT_URL)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=float(_env_default("REPLICATION_LAG_CONNECT_TIMEOUT", "5")),
        help="HTTP timeout in seconds for Kafka Connect requests (default: %(default)s or REPLICATION_LAG_CONNECT_TIMEOUT)",
    )
    parser.add_argument(
        "--connectors",
        nargs="*",
        help="Specific connector names to target. Defaults to all available connectors.",
    )
    parser.add_argument(
        "--compose-cmd",
        default=_env_default("REPLICATION_LAG_COMPOSE_CMD", "docker compose"),
        help="Base docker compose command (default: %(default)s or REPLICATION_LAG_COMPOSE_CMD)",
    )
    parser.add_argument(
        "--compose-file",
        dest="compose_files",
        action="append",
        help="Additional docker compose files to include (-f). Can be passed multiple times.",
    )
    parser.add_argument(
        "--mysql-service",
        default=_env_default("REPLICATION_LAG_MYSQL_SERVICE", "mysql"),
        help="Docker compose service name for MySQL (default: %(default)s or REPLICATION_LAG_MYSQL_SERVICE)",
    )
    parser.add_argument(
        "--mysql-user",
        default=_env_default("REPLICATION_LAG_MYSQL_USER", "root"),
        help="MySQL user for CLI commands (default: %(default)s or REPLICATION_LAG_MYSQL_USER)",
    )
    parser.add_argument(
        "--mysql-password",
        default=_env_default("REPLICATION_LAG_MYSQL_PASSWORD", "root"),
        help="MySQL password for CLI commands (default: %(default)s or REPLICATION_LAG_MYSQL_PASSWORD)",
    )
    parser.add_argument(
        "--mysql-database",
        default=_env_default("REPLICATION_LAG_MYSQL_DATABASE", "oltp"),
        help="Database to write chaos events into (default: %(default)s or REPLICATION_LAG_MYSQL_DATABASE)",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=int(_env_default("REPLICATION_LAG_ROWS", "50")),
        help="Number of rows to insert while connectors are paused (default: %(default)s or REPLICATION_LAG_ROWS)",
    )
    parser.add_argument(
        "--pause-duration",
        type=float,
        default=float(_env_default("REPLICATION_LAG_PAUSE_SECONDS", "10")),
        help="Wait time (seconds) after inserts before resuming connectors (default: %(default)s or REPLICATION_LAG_PAUSE_SECONDS)",
    )
    parser.add_argument(
        "--wait-after-resume",
        type=float,
        default=float(_env_default("REPLICATION_LAG_WAIT_AFTER_RESUME", "5")),
        help="Time to wait (seconds) after resuming connectors before collecting final status (default: %(default)s or REPLICATION_LAG_WAIT_AFTER_RESUME)",
    )
    parser.add_argument(
        "--skip-metrics",
        action="store_true",
        help="Skip interrogation of Kafka Connect Prometheus metrics",
    )
    parser.add_argument(
        "--connect-metrics-url",
        default=_env_default("REPLICATION_LAG_METRICS_URL", "http://127.0.0.1:9404/metrics"),
        help="Prometheus metrics endpoint for Kafka Connect exporter (default: %(default)s or REPLICATION_LAG_METRICS_URL)",
    )

    args = parser.parse_args()

    if args.rows <= 0:
        parser.error("--rows must be positive")

    compose_cmd = shlex.split(args.compose_cmd)
    if not compose_cmd:
        parser.error("--compose-cmd resolved to an empty command")

    compose_files_env = os.getenv("REPLICATION_LAG_COMPOSE_FILES", "")
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


async def fetch_metrics(url: str, timeout: float) -> List[MetricSample]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
        samples: List[MetricSample] = []
        for line in response.text.splitlines():
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


def compute_metric_delta(name: str, samples_before: Sequence[MetricSample], samples_after: Sequence[MetricSample]) -> List[MetricDelta]:
    before_map: Dict[Tuple[Tuple[str, str], ...], float] = {}
    after_map: Dict[Tuple[Tuple[str, str], ...], float] = {}
    for sample in samples_before:
        if sample.name == name:
            before_map[tuple(sorted(sample.labels.items()))] = sample.value
    for sample in samples_after:
        if sample.name == name:
            after_map[tuple(sorted(sample.labels.items()))] = sample.value
    deltas: List[MetricDelta] = []
    all_keys = set(before_map) | set(after_map)
    for key in sorted(all_keys):
        labels = dict(key)
        deltas.append(
            MetricDelta(
                name=name,
                labels=labels,
                before=before_map.get(key, 0.0),
                after=after_map.get(key, 0.0),
            )
        )
    return deltas


async def _compose_command(args: argparse.Namespace, extra_args: Sequence[str]) -> CommandResult:
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


async def compose_command(args: argparse.Namespace, extra_args: Sequence[str], *, check: bool = True) -> CommandResult:
    result = await _compose_command(args, extra_args)
    if check and result.returncode != 0:
        raise ChaosError(
            "Docker compose command failed",
            context={
                "command": result.command,
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )
    return result


async def mysql_command(
    args: argparse.Namespace,
    sql: str,
    *,
    database: str | None = None,
    check: bool = True,
) -> CommandResult:
    def _run() -> CommandResult:
        command = list(args.compose_cmd)
        for compose_file in args.compose_files:
            command.extend(["-f", compose_file])
        command.extend([
            "exec",
            "-T",
            args.mysql_service,
            "mysql",
            f"-u{args.mysql_user}",
            f"-p{args.mysql_password}",
            "--batch",
            "--raw",
        ])
        if database:
            command.extend(["-D", database])
        command.extend(["-e", sql])
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

    result = await asyncio.to_thread(_run)
    if check and result.returncode != 0:
        raise ChaosError(
            "MySQL command failed",
            context={
                "command": result.command,
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )
    return result


def parse_mysql_table(output: str) -> List[Mapping[str, str]]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    headers = lines[0].split("\t")
    rows: List[Mapping[str, str]] = []
    for line in lines[1:]:
        cells = line.split("\t")
        row = {headers[index]: cells[index] if index < len(cells) else "" for index in range(len(headers))}
        rows.append(row)
    return rows


async def ensure_table(args: argparse.Namespace) -> None:
    sql = (
        "CREATE TABLE IF NOT EXISTS `"
        + _TABLE_NAME
        + "` ("
        "id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,"
        "payload VARCHAR(255) NOT NULL,"
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB"
    )
    await mysql_command(args, sql, database=args.mysql_database)


def _escape_mysql_value(value: str) -> str:
    return value.replace("'", "''")


async def insert_rows(args: argparse.Namespace, rows: int) -> List[str]:
    identifiers = [f"replication-lag-{uuid.uuid4().hex[:16]}" for _ in range(rows)]
    values = ",".join(f"('{_escape_mysql_value(identifier)}')" for identifier in identifiers)
    sql = f"INSERT INTO `{_TABLE_NAME}` (payload) VALUES {values}"
    await mysql_command(args, sql, database=args.mysql_database)
    return identifiers


async def fetch_row_count(args: argparse.Namespace) -> int:
    sql = f"SELECT COUNT(*) AS total FROM `{_TABLE_NAME}`"
    result = await mysql_command(args, sql, database=args.mysql_database)
    rows = parse_mysql_table(result.stdout)
    if not rows:
        return 0
    try:
        return int(rows[0].get("total", "0"))
    except ValueError:
        return 0


async def fetch_master_status(args: argparse.Namespace) -> Mapping[str, Any]:
    result = await mysql_command(args, "SHOW MASTER STATUS")
    rows = parse_mysql_table(result.stdout)
    if not rows:
        return {}
    row = rows[0]
    data: Dict[str, Any] = {**row}
    position = row.get("Position")
    if position:
        try:
            data["Position"] = int(position)
        except ValueError:
            pass
    return data


async def list_connectors(client: httpx.AsyncClient) -> List[str]:
    response = await client.get("/connectors")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ChaosError("Unexpected response listing connectors", context={"body": data})
    return sorted(str(name) for name in data)


async def connector_state(client: httpx.AsyncClient, name: str) -> str | None:
    response = await client.get(f"/connectors/{name}/status")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    state = data.get("connector", {}).get("state")
    return str(state) if state is not None else None


async def pause_connectors(client: httpx.AsyncClient, names: Iterable[str]) -> List[Tuple[str, httpx.Response]]:
    results: List[Tuple[str, httpx.Response]] = []
    for name in names:
        response = await client.post(f"/connectors/{name}/pause")
        results.append((name, response))
    return results


async def resume_connectors(client: httpx.AsyncClient, names: Iterable[str]) -> List[Tuple[str, httpx.Response]]:
    results: List[Tuple[str, httpx.Response]] = []
    for name in names:
        response = await client.post(f"/connectors/{name}/resume")
        results.append((name, response))
    return results


async def run_scenario(args: argparse.Namespace) -> Mapping[str, Any]:
    timeout = httpx.Timeout(args.connect_timeout)
    async with httpx.AsyncClient(base_url=args.connect_url, timeout=timeout) as client:
        connector_names = await list_connectors(client)
        if args.connectors:
            target = [name for name in args.connectors if name in connector_names]
            missing = sorted(name for name in args.connectors if name not in connector_names)
        else:
            target = connector_names
            missing = []
        if not target:
            raise ChaosError("No connectors available to pause", context={"connectors": connector_names, "missing": missing})

        if missing:
            raise ChaosError("Some requested connectors are not present", context={"missing": missing})

        before_states = {name: await connector_state(client, name) for name in target}

        pause_results = await pause_connectors(client, target)
        pause_errors = [name for name, response in pause_results if response.status_code >= 400]
        if pause_errors:
            raise ChaosError(
                "Failed to pause connectors",
                context={name: response.text.strip() for name, response in pause_results if response.status_code >= 400},
            )

        # Generate load while connectors are paused
        await ensure_table(args)
        before_count = await fetch_row_count(args)
        before_master = await fetch_master_status(args)
        identifiers = await insert_rows(args, args.rows)
        await asyncio.sleep(max(args.pause_duration, 0))

        resume_results = await resume_connectors(client, target)
        resume_errors = [name for name, response in resume_results if response.status_code >= 400]
        if resume_errors:
            raise ChaosError(
                "Failed to resume connectors",
                context={name: response.text.strip() for name, response in resume_results if response.status_code >= 400},
            )

        await asyncio.sleep(max(args.wait_after_resume, 0))
        after_states = {name: await connector_state(client, name) for name in target}

    after_count = await fetch_row_count(args)
    after_master = await fetch_master_status(args)

    metrics_before: Sequence[MetricSample] = ()
    metrics_after: Sequence[MetricSample] = ()
    metric_deltas: List[MetricDelta] = []
    if not args.skip_metrics:
        try:
            metrics_before = await fetch_metrics(args.connect_metrics_url, args.connect_timeout)
            metrics_after = await fetch_metrics(args.connect_metrics_url, args.connect_timeout)
            metric_deltas = compute_metric_delta("kafka_connect_connector_paused_total", metrics_before, metrics_after)
        except Exception as exc:
            metric_deltas = []
            metrics_error = f"Failed to fetch metrics: {exc}"
        else:
            metrics_error = None
    else:
        metrics_error = "skipped"

    total_delta = after_count - before_count
    position_before = before_master.get("Position") if isinstance(before_master.get("Position"), int) else None
    position_after = after_master.get("Position") if isinstance(after_master.get("Position"), int) else None
    position_delta = (position_after - position_before) if position_before is not None and position_after is not None else None

    return {
        "status": "ok",
        "connectors": [
            {
                "name": name,
                "before": before_states.get(name),
                "after": after_states.get(name),
                "pauseStatus": next(response.status_code for n, response in pause_results if n == name),
                "resumeStatus": next(response.status_code for n, response in resume_results if n == name),
            }
            for name in target
        ],
        "mysql": {
            "rowsInserted": len(identifiers),
            "rowCountBefore": before_count,
            "rowCountAfter": after_count,
            "rowCountDelta": total_delta,
            "masterStatusBefore": before_master,
            "masterStatusAfter": after_master,
            "binlogPositionDelta": position_delta,
        },
        "metrics": {
            "deltas": [
                {
                    "labels": delta.labels,
                    "before": delta.before,
                    "after": delta.after,
                    "delta": delta.delta,
                }
                for delta in metric_deltas
            ],
            "error": metrics_error,
        },
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

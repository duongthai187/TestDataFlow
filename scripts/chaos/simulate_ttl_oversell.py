#!/usr/bin/env python3
"""Chaos scenario: shorten Cassandra TTL to mimic reservation expiries/oversell.

This script alters the `default_time_to_live` setting on a Cassandra table (and
optionally restores it). It also inserts synthetic reservations so operators can
observe inventory oversell metrics/alerts when TTL is too aggressive.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping


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
    parser = argparse.ArgumentParser(description="Shorten Cassandra TTL to simulate reservation expiry/oversell")
    parser.add_argument(
        "--keyspace",
        default=_env_default("TTL_OVERSELL_KEYSPACE", "inventory"),
        help="Cassandra keyspace containing the reservation table (default: %(default)s or TTL_OVERSELL_KEYSPACE)",
    )
    parser.add_argument(
        "--table",
        default=_env_default("TTL_OVERSELL_TABLE", "reservations"),
        help="Cassandra table to modify (default: %(default)s or TTL_OVERSELL_TABLE)",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=int(_env_default("TTL_OVERSELL_TTL", "30")),
        help="New default TTL in seconds to apply (default: %(default)s or TTL_OVERSELL_TTL)",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Restore the previous TTL (requires --previous-ttl)",
    )
    parser.add_argument(
        "--previous-ttl",
        type=int,
        default=None,
        help="Baseline TTL to restore during revert (required when --revert)",
    )
    parser.add_argument(
        "--after-cql",
        default=_env_default("TTL_OVERSELL_AFTER_CQL", ""),
        help="Optional CQL statement to execute after altering TTL (e.g. seed synthetic reservations)",
    )
    parser.add_argument(
        "--compose-cmd",
        default=_env_default("TTL_OVERSELL_COMPOSE_CMD", "docker compose"),
        help="Base docker compose command (default: %(default)s)",
    )
    parser.add_argument(
        "--compose-file",
        dest="compose_files",
        action="append",
        help="Additional compose files to include (-f). Can be passed multiple times.",
    )
    parser.add_argument(
        "--cqlsh-service",
        default=_env_default("TTL_OVERSELL_CQLSH_SERVICE", "cassandra-seed"),
        help="Docker compose service name running Cassandra (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated CQL without executing",
    )

    args = parser.parse_args()

    if args.ttl <= 0:
        parser.error("--ttl must be positive")
    if args.revert and args.previous_ttl is None:
        parser.error("--previous-ttl is required when using --revert")

    compose_cmd = shlex.split(args.compose_cmd)
    if not compose_cmd:
        parser.error("--compose-cmd resolved to an empty command")

    compose_files_env = os.getenv("TTL_OVERSELL_COMPOSE_FILES", "")
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


def cql_command(args: argparse.Namespace, cql: str) -> CommandResult:
    command = list(args.compose_cmd)
    for compose_file in args.compose_files:
        command.extend(["-f", compose_file])
    command.extend([
        "exec",
        "-T",
        args.cqlsh_service,
        "cqlsh",
        "-e",
        cql,
    ])
    start = time.monotonic()
    proc = subprocess.run(command, capture_output=True, text=True)
    duration = time.monotonic() - start
    result = CommandResult(
        command=command,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_seconds=duration,
    )
    if result.returncode != 0:
        raise ChaosError(
            "cqlsh command failed",
            context={
                "command": command,
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )
    return result


def alter_ttl(args: argparse.Namespace, ttl: int) -> CommandResult:
    keyspace = args.keyspace.replace("\"", "")
    table = args.table.replace("\"", "")
    cql = f"ALTER TABLE {keyspace}.{table} WITH default_time_to_live = {ttl}"
    if args.dry_run:
        return CommandResult([], 0, "", "", 0.0)
    return cql_command(args, cql)


def run(args: argparse.Namespace) -> Mapping[str, Any]:
    target_ttl = args.previous_ttl if args.revert else args.ttl
    ttl_result: CommandResult | None = None
    extra_result: CommandResult | None = None
    if not args.dry_run:
        ttl_result = alter_ttl(args, target_ttl)
        if args.after_cql:
            extra_result = cql_command(args, args.after_cql)
    else:
        ttl_result = CommandResult([], 0, "", "", 0.0)

    return {
        "status": "ok",
        "keyspace": args.keyspace,
        "table": args.table,
        "ttl": target_ttl,
        "revert": args.revert,
        "dryRun": args.dry_run,
        "commands": {
            "alter": _command_to_dict(ttl_result) if ttl_result else None,
            "extra": _command_to_dict(extra_result) if extra_result else None,
        },
    }


def _command_to_dict(result: CommandResult | None) -> Mapping[str, Any] | None:
    if result is None:
        return None
    return {
        "command": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "durationSeconds": round(result.duration_seconds, 3),
    }


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
    except ChaosError as exc:
        payload = {
            "status": "error",
            "message": str(exc),
            "context": exc.context,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "error",
            "message": str(exc),
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 3

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

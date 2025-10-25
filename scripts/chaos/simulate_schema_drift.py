#!/usr/bin/env python3
"""Chaos scenario to simulate schema drift by altering OLTP tables.

The script adds (or drops) a designated column on a MySQL table hosted inside the
local Docker Compose stack. This mimics unexpected producer-side schema changes
that break downstream CDC/ETL consumers. The operation is reversible via the
`--revert` flag. A JSON report is printed summarising the applied SQL and table
metadata before/after the change.
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
    parser = argparse.ArgumentParser(description="Alter MySQL table to simulate schema drift")
    parser.add_argument(
        "--table",
        default=_env_default("SCHEMA_DRIFT_TABLE", "oltp.orders"),
        help="Target table in the form <database>.<table> (default: %(default)s or SCHEMA_DRIFT_TABLE)",
    )
    parser.add_argument(
        "--column",
        default=_env_default("SCHEMA_DRIFT_COLUMN", "unexpected_field"),
        help="Column name to add/drop (default: %(default)s or SCHEMA_DRIFT_COLUMN)",
    )
    parser.add_argument(
        "--column-type",
        default=_env_default("SCHEMA_DRIFT_COLUMN_TYPE", "VARCHAR(255)"),
        help="Column type definition used when adding the column (default: %(default)s or SCHEMA_DRIFT_COLUMN_TYPE)",
    )
    parser.add_argument(
        "--after",
        default=_env_default("SCHEMA_DRIFT_AFTER", ""),
        help="Optional column to insert AFTER in the ALTER TABLE statement",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Drop the column instead of adding it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated SQL without executing",
    )
    parser.add_argument(
        "--compose-cmd",
        default=_env_default("SCHEMA_DRIFT_COMPOSE_CMD", "docker compose"),
        help="Base Docker Compose command (default: %(default)s or SCHEMA_DRIFT_COMPOSE_CMD)",
    )
    parser.add_argument(
        "--compose-file",
        dest="compose_files",
        action="append",
        help="Additional docker-compose file(s) to include (-f). Can be provided multiple times.",
    )
    parser.add_argument(
        "--mysql-service",
        default=_env_default("SCHEMA_DRIFT_MYSQL_SERVICE", "mysql"),
        help="Docker Compose service name for MySQL (default: %(default)s or SCHEMA_DRIFT_MYSQL_SERVICE)",
    )
    parser.add_argument(
        "--mysql-user",
        default=_env_default("SCHEMA_DRIFT_MYSQL_USER", "root"),
        help="MySQL user for CLI commands (default: %(default)s or SCHEMA_DRIFT_MYSQL_USER)",
    )
    parser.add_argument(
        "--mysql-password",
        default=_env_default("SCHEMA_DRIFT_MYSQL_PASSWORD", "root"),
        help="MySQL password (default: %(default)s or SCHEMA_DRIFT_MYSQL_PASSWORD)",
    )
    args = parser.parse_args()

    if "." not in args.table:
        parser.error("--table must be in the form <database>.<table>")

    compose_cmd = shlex.split(args.compose_cmd)
    if not compose_cmd:
        parser.error("--compose-cmd resolved to an empty command")

    compose_files_env = os.getenv("SCHEMA_DRIFT_COMPOSE_FILES", "")
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


def mysql_exec(
    args: argparse.Namespace,
    sql: str,
    *,
    database: str,
    check: bool = True,
) -> CommandResult:
    command = list(args.compose_cmd)
    for compose_file in args.compose_files:
        command.extend(["-f", compose_file])
    command.extend(
        [
            "exec",
            "-T",
            args.mysql_service,
            "mysql",
            f"-u{args.mysql_user}",
            f"-p{args.mysql_password}",
            "--batch",
            "--raw",
            "-D",
            database,
            "-e",
            sql,
        ]
    )
    start = time.monotonic()
    proc = subprocess.run(command, capture_output=True, text=True)
    duration = time.monotonic() - start
    result = CommandResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, duration_seconds=duration)
    if check and result.returncode != 0:
        raise ChaosError(
            "MySQL command failed",
            context={
                "command": command,
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            },
        )
    return result


def column_exists(args: argparse.Namespace, database: str, table: str, column: str) -> bool:
    sql = (
        "SELECT COUNT(*) AS total FROM information_schema.columns "
        "WHERE table_schema = '"
        + database.replace("'", "''")
        + "' AND table_name = '"
        + table.replace("'", "''")
        + "' AND column_name = '"
        + column.replace("'", "''")
        + "'"
    )
    result = mysql_exec(args, sql, database=database)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    try:
        return int(lines[1]) > 0
    except ValueError:
        return False


def fetch_columns(args: argparse.Namespace, database: str, table: str) -> List[Mapping[str, str]]:
    sql = "SHOW COLUMNS FROM `" + table + "`"
    result = mysql_exec(args, sql, database=database)
    lines = [line.rstrip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return []
    headers = lines[0].split("\t")
    columns: List[Mapping[str, str]] = []
    for entry in lines[1:]:
        cells = entry.split("\t")
        row = {headers[i]: cells[i] if i < len(cells) else "" for i in range(len(headers))}
        columns.append(row)
    return columns


def build_sql(args: argparse.Namespace, database: str, table: str) -> str:
    column = args.column
    if args.revert:
        return f"ALTER TABLE `{table}` DROP COLUMN `{column}`"
    clause = f"ADD COLUMN `{column}` {args.column_type}"
    if args.after:
        clause += f" AFTER `{args.after}`"
    return f"ALTER TABLE `{table}` {clause}"


def run(args: argparse.Namespace) -> Mapping[str, Any]:
    database, table = args.table.split(".", 1)
    table = table.strip("`")
    database = database.strip("`")

    exists_before = column_exists(args, database, table, args.column)
    action = "drop" if args.revert else "add"
    sql = build_sql(args, database, table)

    if args.revert and not exists_before:
        raise ChaosError(
            "Column not present; nothing to drop",
            context={"database": database, "table": table, "column": args.column},
        )
    if not args.revert and exists_before:
        raise ChaosError(
            "Column already exists; refusing to add duplicate",
            context={"database": database, "table": table, "column": args.column},
        )

    before_columns = fetch_columns(args, database, table)

    command_result: CommandResult | None = None
    if not args.dry_run:
        command_result = mysql_exec(args, sql, database=database)
    exists_after = column_exists(args, database, table, args.column)
    after_columns = fetch_columns(args, database, table)

    if not args.dry_run:
        if args.revert and exists_after:
            raise ChaosError("Column still present after DROP", context={"database": database, "table": table})
        if not args.revert and not exists_after:
            raise ChaosError("Column missing after ADD", context={"database": database, "table": table})

    return {
        "status": "ok",
        "action": action,
        "database": database,
        "table": table,
        "sql": sql,
        "dryRun": args.dry_run,
        "command": None
        if command_result is None
        else {
            "command": command_result.command,
            "returncode": command_result.returncode,
            "stderr": command_result.stderr.strip(),
            "stdout": command_result.stdout.strip(),
            "durationSeconds": round(command_result.duration_seconds, 3),
        },
        "columnExistsBefore": exists_before,
        "columnExistsAfter": exists_after,
        "columnsBefore": before_columns,
        "columnsAfter": after_columns,
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

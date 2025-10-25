#!/usr/bin/env python3
"""Generate synthetic support cases against the support-service API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import string
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence

import httpx

DEFAULT_SUBJECT_PREFIXES = [
    "Order",
    "Payment",
    "Shipment",
    "Refund",
    "Account",
    "Promotion",
]

DEFAULT_SUBJECT_SUFFIXES = [
    "issue",
    "question",
    "follow-up",
    "confirmation",
    "delay",
    "update request",
]

DEFAULT_CHANNELS = ["email", "chat", "phone", "portal"]
DEFAULT_PRIORITIES = ["low", "medium", "high"]
DEFAULT_AGENT_IDS = [
    "agent-alice",
    "agent-bob",
    "agent-charlie",
    "agent-delta",
]
DEFAULT_MESSAGES = [
    "Customer is asking about the latest shipment status and whether the parcel cleared customs.",
    "Payment captured twice; needs immediate manual review and refund.",
    "Promo code failed during checkout, requesting new voucher.",
    "App crashed when uploading proof of purchase, please advise next steps.",
    "Order arrived damaged, wants partial refund or replacement.",
]


def _env_default(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def _split_env(name: str, fallback: Sequence[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return list(fallback)
    return [token.strip() for token in value.split(",") if token.strip()]


@dataclass(slots=True)
class TicketResult:
    ticket_id: str | None
    duration: float
    messages_created: int
    status_code: int | None
    error: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic support tickets")
    parser.add_argument(
        "--base-url",
        default=_env_default("SUPPORT_SERVICE_BASE_URL", "http://127.0.0.1:8109"),
        help="Support service base URL (default: %(default)s or SUPPORT_SERVICE_BASE_URL)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=int(_env_default("SUPPORT_GENERATOR_COUNT", "5")),
        help="Number of tickets to create (default: %(default)s or SUPPORT_GENERATOR_COUNT)",
    )
    parser.add_argument(
        "--messages-per-ticket",
        type=int,
        default=int(_env_default("SUPPORT_GENERATOR_MESSAGES", "1")),
        help="Number of total messages per ticket including the initial message (default: %(default)s or SUPPORT_GENERATOR_MESSAGES)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(_env_default("SUPPORT_GENERATOR_CONCURRENCY", "4")),
        help="Maximum concurrent ticket creations (default: %(default)s or SUPPORT_GENERATOR_CONCURRENCY)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(_env_default("SUPPORT_GENERATOR_TIMEOUT", "5")),
        help="HTTP timeout in seconds (default: %(default)s or SUPPORT_GENERATOR_TIMEOUT)",
    )
    parser.add_argument(
        "--channels",
        nargs="*",
        default=_split_env("SUPPORT_GENERATOR_CHANNELS", DEFAULT_CHANNELS),
        help="List of possible channels (default: %(default)s)",
    )
    parser.add_argument(
        "--priorities",
        nargs="*",
        default=_split_env("SUPPORT_GENERATOR_PRIORITIES", DEFAULT_PRIORITIES),
        help="List of possible priorities (default: %(default)s)",
    )
    parser.add_argument(
        "--agent-ids",
        nargs="*",
        default=_split_env("SUPPORT_GENERATOR_AGENT_IDS", DEFAULT_AGENT_IDS),
        help="List of agent ids used for assignment (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated payloads without calling the API",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the final JSON result (default: False)",
    )

    args = parser.parse_args()

    if args.count <= 0:
        parser.error("--count must be positive")
    if args.messages_per_ticket <= 0:
        parser.error("--messages-per-ticket must be positive")
    if args.concurrency <= 0:
        parser.error("--concurrency must be positive")
    if not args.channels:
        parser.error("--channels must provide at least one option")
    if not args.priorities:
        parser.error("--priorities must provide at least one option")

    return args


def _random_text(options: Sequence[str]) -> str:
    return random.choice(options)


def _random_subject() -> str:
    return f"{_random_text(DEFAULT_SUBJECT_PREFIXES)} {_random_text(DEFAULT_SUBJECT_SUFFIXES)}".title()


def _random_sentence() -> str:
    return _random_text(DEFAULT_MESSAGES)


def _random_token(length: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def _build_ticket_payload(
    idx: int,
    *,
    channels: Sequence[str],
    priorities: Sequence[str],
    agent_ids: Sequence[str],
) -> Mapping[str, Any]:
    customer_id = f"cust-{_random_token(6)}"
    assigned_agent = random.choice(agent_ids)
    ticket_id_hint = f"scenario-{uuid.uuid4().hex[:8]}-{idx}"
    context: dict[str, Any] = {
        "order": {
            "id": random.randint(10_000, 99_999),
            "total": round(random.uniform(20.0, 500.0), 2),
            "currency": "USD",
        },
        "scenario": ticket_id_hint,
    }
    payload: Dict[str, Any] = {
        "subject": _random_subject(),
        "description": _random_sentence(),
        "customerId": customer_id,
        "channel": random.choice(channels),
        "priority": random.choice(priorities),
        "assignedAgentId": assigned_agent,
        "context": context,
        "initialMessage": {
            "authorType": "customer",
            "message": _random_sentence(),
            "metadata": {
                "channel": context["scenario"],
            },
        },
    }
    return payload


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
) -> tuple[int, MutableMapping[str, Any]]:
    response = await client.post(url, json=payload)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, MutableMapping):
        raise ValueError("Unexpected JSON response structure")
    return response.status_code, body


async def _create_ticket(
    client: httpx.AsyncClient,
    base_url: str,
    payload: Mapping[str, Any],
    *,
    messages_per_ticket: int,
) -> TicketResult:
    start = time.perf_counter()
    try:
        status, body = await _post_json(client, f"{base_url}/support/cases", payload)
        ticket_id = str(body.get("id"))
        messages_created = 1
        if messages_per_ticket > 1:
            followup_payload = {
                "authorType": "agent",
                "message": _random_sentence(),
            }
            for _ in range(messages_per_ticket - 1):
                await _post_json(
                    client,
                    f"{base_url}/support/cases/{ticket_id}/messages",
                    followup_payload,
                )
                messages_created += 1
        duration = time.perf_counter() - start
        return TicketResult(
            ticket_id=ticket_id,
            duration=duration,
            messages_created=messages_created,
            status_code=status,
            error=None,
        )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        duration = time.perf_counter() - start
        status = getattr(exc, "response", None)
        status_code = status.status_code if status is not None else None
        return TicketResult(
            ticket_id=None,
            duration=duration,
            messages_created=0,
            status_code=status_code,
            error=str(exc),
        )


async def _worker(
    client: httpx.AsyncClient,
    base_url: str,
    queue: "asyncio.Queue[Mapping[str, Any]]",
    *,
    messages_per_ticket: int,
    results: list[TicketResult],
) -> None:
    while True:
        payload = await queue.get()
        try:
            result = await _create_ticket(
                client,
                base_url,
                payload,
                messages_per_ticket=messages_per_ticket,
            )
            results.append(result)
        finally:
            queue.task_done()


async def generate_tickets(args: argparse.Namespace) -> Mapping[str, Any]:
    base_url = args.base_url.rstrip("/")
    payloads = [
        _build_ticket_payload(
            idx,
            channels=args.channels,
            priorities=args.priorities,
            agent_ids=args.agent_ids,
        )
        for idx in range(args.count)
    ]

    if args.dry_run:
        return {
            "status": "dry-run",
            "count": args.count,
            "sample": payloads[: min(3, len(payloads))],
        }

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        queue: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue()
        for payload in payloads:
            queue.put_nowait(payload)

        results: List[TicketResult] = []
        workers = [
            asyncio.create_task(
                _worker(
                    client,
                    base_url,
                    queue,
                    messages_per_ticket=args.messages_per_ticket,
                    results=results,
                )
            )
            for _ in range(min(args.concurrency, args.count))
        ]

        await queue.join()

        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    successes = [result for result in results if result.ticket_id]
    failures = [result for result in results if not result.ticket_id]
    average_duration = (
        sum(result.duration for result in successes) / len(successes)
        if successes
        else 0.0
    )

    return {
        "status": "ok" if not failures else "partial",
        "requested": args.count,
        "created": len(successes),
        "failed": len(failures),
        "averageDurationSeconds": round(average_duration, 3),
        "results": {
            "success": [
                {
                    "ticketId": result.ticket_id,
                    "durationSeconds": round(result.duration, 3),
                    "messagesCreated": result.messages_created,
                    "statusCode": result.status_code,
                }
                for result in successes
            ],
            "failure": [
                {
                    "durationSeconds": round(result.duration, 3),
                    "statusCode": result.status_code,
                    "error": result.error,
                }
                for result in failures
            ],
        },
    }


async def main_async() -> int:
    args = parse_args()
    report = await generate_tickets(args)
    output = json.dumps(report, indent=2 if args.pretty else None)
    print(output)
    return 0 if report.get("status") in {"ok", "dry-run"} else 2


def main() -> None:
    try:
        exit_code = asyncio.run(main_async())
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

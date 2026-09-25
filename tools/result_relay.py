#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

PREFIX = "ACP_RUNTIME_RELAY_V3|"
LEGACY_PREFIX_V2 = "ACP_RUNTIME_RELAY_V2|"
LEGACY_PREFIX_V1 = "ACP_RUNTIME_RELAY_V1|"
MAX_PROMPT_CHARS = 12000
HEX40 = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MSK = timedelta(hours=3)

TICKET_STATUSES = {
    "armed",
    "admitted",
    "ready",
    "transport-lost",
    "accepted",
    "persisted",
    "closed",
}
AUTHOR_KINDS = {"persistent-agent", "infrastructure"}
RELAY_STATUSES = {"complete", "blocked"}


class RelayError(ValueError):
    pass


def sha256_utf8(value: str) -> str:
    if not isinstance(value, str):
        raise RelayError("sha256 input must be a string")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def encode_relay(envelope: dict[str, Any]) -> str:
    if envelope.get("schema_version") != 3:
        raise RelayError("new relays must use schema_version=3")
    raw = PREFIX + json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(raw) > MAX_PROMPT_CHARS:
        raise RelayError("relay exceeds v3 prompt bound")
    return raw


def parse_relay(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise RelayError("relay must be a string")
    if len(raw) > MAX_PROMPT_CHARS:
        raise RelayError("relay exceeds prompt bound")
    if raw.startswith(PREFIX):
        encoded = raw[len(PREFIX):]
    elif raw.startswith(LEGACY_PREFIX_V2):
        encoded = raw[len(LEGACY_PREFIX_V2):]
    elif raw.startswith(LEGACY_PREFIX_V1):
        encoded = raw[len(LEGACY_PREFIX_V1):]
    else:
        raise RelayError("invalid relay prefix")
    try:
        envelope = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise RelayError("invalid relay JSON") from exc
    if not isinstance(envelope, dict):
        raise RelayError("relay envelope must be an object")
    return envelope


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RelayError(f"{label} must be a non-empty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RelayError(f"{label} must be a positive integer")
    return value


def _validate_timestamp(value: Any, label: str, *, require_msk: bool = False) -> datetime:
    stamp = _nonempty(value, label)
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RelayError(f"invalid {label}") from exc
    if dt.tzinfo is None:
        raise RelayError(f"{label} must be timezone-aware")
    if require_msk and dt.utcoffset() != MSK:
        raise RelayError(f"{label} must use UTC+03:00")
    return dt


def validate_ticket(ticket: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "task_id",
        "logical_attempt",
        "request_digest",
        "request_blob_sha",
        "transport_task_id",
        "transport_slot_id",
        "transport_generation",
        "delivery_try",
        "admission_nonce",
        "relay_id",
        "relay_nonce",
        "expected_author_id",
        "allowed_payload_kind",
        "scheduled_not_before",
        "relay_deadline_at",
        "slot_quiescence_until",
        "status",
    }
    missing = sorted(required - set(ticket))
    if missing:
        raise RelayError("ticket missing fields: " + ", ".join(missing))
    if ticket.get("schema_version") != 1:
        raise RelayError("unsupported transport ticket schema_version")
    _nonempty(ticket.get("task_id"), "task_id")
    _positive_int(ticket.get("logical_attempt"), "logical_attempt")
    request_digest = _nonempty(ticket.get("request_digest"), "request_digest")
    if not DIGEST.fullmatch(request_digest):
        raise RelayError("invalid request_digest")
    request_blob_sha = _nonempty(ticket.get("request_blob_sha"), "request_blob_sha")
    if not HEX40.fullmatch(request_blob_sha):
        raise RelayError("invalid request_blob_sha")
    _nonempty(ticket.get("transport_task_id"), "transport_task_id")
    _nonempty(ticket.get("transport_slot_id"), "transport_slot_id")
    _positive_int(ticket.get("transport_generation"), "transport_generation")
    _positive_int(ticket.get("delivery_try"), "delivery_try")
    _nonempty(ticket.get("admission_nonce"), "admission_nonce")
    _nonempty(ticket.get("relay_id"), "relay_id")
    _nonempty(ticket.get("relay_nonce"), "relay_nonce")
    _nonempty(ticket.get("expected_author_id"), "expected_author_id")
    _nonempty(ticket.get("allowed_payload_kind"), "allowed_payload_kind")
    not_before = _validate_timestamp(ticket.get("scheduled_not_before"), "scheduled_not_before")
    deadline = _validate_timestamp(ticket.get("relay_deadline_at"), "relay_deadline_at")
    quiescence = _validate_timestamp(ticket.get("slot_quiescence_until"), "slot_quiescence_until")
    if not (not_before < deadline < quiescence):
        raise RelayError("transport ticket time ordering must be scheduled_not_before < relay_deadline_at < slot_quiescence_until")
    if ticket.get("status") not in TICKET_STATUSES:
        raise RelayError("invalid transport ticket status")


def validate_publication_time(ticket: dict[str, Any], transport_updated_at: str) -> None:
    """Require the platform metadata mutation to have occurred within the ticket deadline."""
    validate_ticket(ticket)
    updated = _validate_timestamp(transport_updated_at, "transport_updated_at")
    deadline = _validate_timestamp(ticket["relay_deadline_at"], "relay_deadline_at")
    if updated > deadline:
        raise RelayError("relay publication occurred after relay_deadline_at")


def validate_envelope_against_ticket(
    envelope: dict[str, Any],
    ticket: dict[str, Any],
) -> None:
    validate_ticket(ticket)
    required = {
        "schema_version",
        "relay_id",
        "transport_task_id",
        "transport_slot_id",
        "transport_generation",
        "task_id",
        "logical_attempt",
        "delivery_try",
        "request_digest",
        "request_blob_sha",
        "admission_nonce",
        "relay_nonce",
        "author_id",
        "author_kind",
        "status",
        "terminal",
        "payload_kind",
        "payload_encoding",
        "payload_text",
        "payload_sha256",
        "authored_at_msk",
    }
    missing = sorted(required - set(envelope))
    if missing:
        raise RelayError("relay missing fields: " + ", ".join(missing))
    if envelope.get("schema_version") != 3:
        raise RelayError("unsupported relay schema_version for acceptance")

    expected = {
        "relay_id": ticket["relay_id"],
        "transport_task_id": ticket["transport_task_id"],
        "transport_slot_id": ticket["transport_slot_id"],
        "transport_generation": ticket["transport_generation"],
        "task_id": ticket["task_id"],
        "logical_attempt": ticket["logical_attempt"],
        "delivery_try": ticket["delivery_try"],
        "request_digest": ticket["request_digest"],
        "request_blob_sha": ticket["request_blob_sha"],
        "admission_nonce": ticket["admission_nonce"],
        "relay_nonce": ticket["relay_nonce"],
        "author_id": ticket["expected_author_id"],
        "payload_kind": ticket["allowed_payload_kind"],
    }
    for key, value in expected.items():
        if envelope.get(key) != value:
            raise RelayError(f"{key} binding mismatch")

    _positive_int(envelope.get("logical_attempt"), "logical_attempt")
    _positive_int(envelope.get("delivery_try"), "delivery_try")
    _positive_int(envelope.get("transport_generation"), "transport_generation")

    if envelope.get("author_kind") not in AUTHOR_KINDS:
        raise RelayError("invalid author_kind")
    if envelope.get("status") not in RELAY_STATUSES:
        raise RelayError("invalid relay status")
    if envelope.get("terminal") is not True:
        raise RelayError("relay must be terminal")
    if envelope.get("payload_encoding") != "utf-8":
        raise RelayError("payload_encoding must be utf-8")
    _validate_timestamp(envelope.get("authored_at_msk"), "authored_at_msk", require_msk=True)

    payload_text = envelope.get("payload_text")
    if not isinstance(payload_text, str):
        raise RelayError("payload_text must be a string")
    payload_sha256 = _nonempty(envelope.get("payload_sha256"), "payload_sha256")
    if not DIGEST.fullmatch(payload_sha256):
        raise RelayError("invalid payload_sha256")
    if payload_sha256 != sha256_utf8(payload_text):
        raise RelayError("payload_sha256 mismatch")
    if envelope.get("status") == "blocked" and not payload_text:
        raise RelayError("blocked relay requires non-empty payload_text")


def validate_raw_relay(raw: str, *, ticket: dict[str, Any]) -> dict[str, Any]:
    envelope = parse_relay(raw)
    validate_envelope_against_ticket(envelope, ticket)
    return envelope


def acceptance_candidate(
    raw: str,
    *,
    ticket: dict[str, Any],
    transport_updated_at: str,
) -> dict[str, Any]:
    envelope = validate_raw_relay(raw, ticket=ticket)
    validate_publication_time(ticket, transport_updated_at)
    return {
        "schema_version": 2,
        "task_id": envelope["task_id"],
        "logical_attempt": envelope["logical_attempt"],
        "delivery_try": envelope["delivery_try"],
        "relay_id": envelope["relay_id"],
        "relay_nonce": envelope["relay_nonce"],
        "admission_nonce": envelope["admission_nonce"],
        "transport_task_id": envelope["transport_task_id"],
        "transport_slot_id": envelope["transport_slot_id"],
        "transport_generation": envelope["transport_generation"],
        "request_digest": envelope["request_digest"],
        "request_blob_sha": envelope["request_blob_sha"],
        "author_id": envelope["author_id"],
        "status": envelope["status"],
        "payload_kind": envelope["payload_kind"],
        "raw_relay_sha256": sha256_utf8(raw),
        "payload_sha256": envelope["payload_sha256"],
        "transport_updated_at": transport_updated_at,
    }


def plan_acceptance(
    raw: str,
    *,
    ticket: dict[str, Any],
    transport_updated_at: str,
    existing_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = acceptance_candidate(
        raw,
        ticket=ticket,
        transport_updated_at=transport_updated_at,
    )
    if existing_receipt is None:
        return {"decision": "accept-new", "receipt": candidate}
    if not isinstance(existing_receipt, dict):
        raise RelayError("existing receipt must be an object")
    if existing_receipt.get("schema_version") != 2:
        raise RelayError("unsupported acceptance receipt schema_version")
    if existing_receipt.get("task_id") != candidate["task_id"]:
        raise RelayError("existing receipt task binding mismatch")
    if existing_receipt.get("logical_attempt") != candidate["logical_attempt"]:
        raise RelayError("canonical receipt already exists for a different logical attempt")
    same = all(existing_receipt.get(key) == value for key, value in candidate.items())
    if same:
        return {"decision": "already-accepted", "receipt": candidate}
    raise RelayError("canonical relay receipt already exists with different content")


def next_delivery_ticket(
    current_ticket: dict[str, Any],
    *,
    transport_task_id: str,
    transport_slot_id: str,
    transport_generation: int,
    admission_nonce: str,
    relay_id: str,
    relay_nonce: str,
    scheduled_not_before: str,
    relay_deadline_at: str,
    slot_quiescence_until: str,
) -> dict[str, Any]:
    """Create the next transport retry without advancing the semantic task attempt."""
    validate_ticket(current_ticket)
    return {
        "schema_version": 1,
        "task_id": current_ticket["task_id"],
        "logical_attempt": current_ticket["logical_attempt"],
        "request_digest": current_ticket["request_digest"],
        "request_blob_sha": current_ticket["request_blob_sha"],
        "transport_task_id": _nonempty(transport_task_id, "transport_task_id"),
        "transport_slot_id": _nonempty(transport_slot_id, "transport_slot_id"),
        "transport_generation": _positive_int(transport_generation, "transport_generation"),
        "delivery_try": current_ticket["delivery_try"] + 1,
        "admission_nonce": _nonempty(admission_nonce, "admission_nonce"),
        "relay_id": _nonempty(relay_id, "relay_id"),
        "relay_nonce": _nonempty(relay_nonce, "relay_nonce"),
        "expected_author_id": current_ticket["expected_author_id"],
        "allowed_payload_kind": current_ticket["allowed_payload_kind"],
        "scheduled_not_before": scheduled_not_before,
        "relay_deadline_at": relay_deadline_at,
        "slot_quiescence_until": slot_quiescence_until,
        "status": "armed",
    }

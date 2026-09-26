#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

PREFIX = "ACP_MAILBOX_RELAY_V1|"
MAX_PROMPT_CHARS = 12000
HEX40 = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MSK = timedelta(hours=3)


class MailboxRelayError(ValueError):
    pass


def sha256_utf8(value: str) -> str:
    if not isinstance(value, str):
        raise MailboxRelayError("sha256 input must be a string")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def encode_relay(envelope: dict[str, Any]) -> str:
    if envelope.get("schema_version") != 1:
        raise MailboxRelayError("mailbox relays must use schema_version=1")
    raw = PREFIX + json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(raw) > MAX_PROMPT_CHARS:
        raise MailboxRelayError("mailbox relay exceeds prompt bound")
    return raw


def parse_relay(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise MailboxRelayError("relay must be a string")
    if len(raw) > MAX_PROMPT_CHARS:
        raise MailboxRelayError("mailbox relay exceeds prompt bound")
    if not raw.startswith(PREFIX):
        raise MailboxRelayError("invalid mailbox relay prefix")
    try:
        envelope = json.loads(raw[len(PREFIX):])
    except json.JSONDecodeError as exc:
        raise MailboxRelayError("invalid mailbox relay JSON") from exc
    if not isinstance(envelope, dict):
        raise MailboxRelayError("mailbox relay envelope must be an object")
    return envelope


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MailboxRelayError(f"{label} must be a non-empty string")
    return value


def _msk_timestamp(value: Any) -> None:
    stamp = _nonempty(value, "authored_at_msk")
    try:
        dt = datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise MailboxRelayError("invalid authored_at_msk") from exc
    if dt.tzinfo is None or dt.utcoffset() != MSK:
        raise MailboxRelayError("authored_at_msk must use UTC+03:00")


def validate_envelope(
    envelope: dict[str, Any],
    *,
    relay_id: str,
    producer_task_id: str,
    mailbox_task_id: str,
    mailbox_id: str,
    mailbox_generation: int,
    admission_nonce: str,
    task_id: str,
    logical_attempt: int,
    request_digest: str,
    request_blob_sha: str,
    execution_id: str,
    execution_generation: int,
    relay_nonce: str,
    author_id: str,
    allowed_payload_kinds: set[str] | None = None,
) -> None:
    required = {
        "schema_version", "relay_id", "producer_task_id", "mailbox_task_id",
        "mailbox_id", "mailbox_generation", "admission_nonce", "task_id",
        "logical_attempt", "request_digest", "request_blob_sha", "execution_id",
        "execution_generation", "relay_nonce", "author_id", "author_kind",
        "status", "terminal", "payload_kind", "payload_encoding", "payload_text",
        "payload_sha256", "authored_at_msk",
    }
    missing = sorted(required - set(envelope))
    if missing:
        raise MailboxRelayError("mailbox relay missing fields: " + ", ".join(missing))
    if envelope.get("schema_version") != 1:
        raise MailboxRelayError("unsupported mailbox relay schema_version")

    expected = {
        "relay_id": relay_id,
        "producer_task_id": producer_task_id,
        "mailbox_task_id": mailbox_task_id,
        "mailbox_id": mailbox_id,
        "mailbox_generation": mailbox_generation,
        "admission_nonce": admission_nonce,
        "task_id": task_id,
        "logical_attempt": logical_attempt,
        "request_digest": request_digest,
        "request_blob_sha": request_blob_sha,
        "execution_id": execution_id,
        "execution_generation": execution_generation,
        "relay_nonce": relay_nonce,
        "author_id": author_id,
    }
    for key, value in expected.items():
        if envelope.get(key) != value:
            raise MailboxRelayError(f"{key} binding mismatch")

    if not isinstance(logical_attempt, int) or logical_attempt < 1:
        raise MailboxRelayError("logical_attempt must be a positive integer")
    if not isinstance(mailbox_generation, int) or mailbox_generation < 1:
        raise MailboxRelayError("mailbox_generation must be a positive integer")
    if not isinstance(execution_generation, int) or execution_generation < 1:
        raise MailboxRelayError("execution_generation must be a positive integer")
    if not DIGEST.fullmatch(_nonempty(envelope.get("request_digest"), "request_digest")):
        raise MailboxRelayError("invalid request_digest")
    if not HEX40.fullmatch(_nonempty(envelope.get("request_blob_sha"), "request_blob_sha")):
        raise MailboxRelayError("invalid request_blob_sha")
    if envelope.get("author_kind") != "infrastructure":
        raise MailboxRelayError("mailbox producer must be infrastructure")
    if envelope.get("status") not in {"complete", "blocked"}:
        raise MailboxRelayError("invalid relay status")
    if envelope.get("terminal") is not True:
        raise MailboxRelayError("relay must be terminal")
    if envelope.get("payload_encoding") != "utf-8":
        raise MailboxRelayError("payload_encoding must be utf-8")
    kind = _nonempty(envelope.get("payload_kind"), "payload_kind")
    if allowed_payload_kinds is not None and kind not in allowed_payload_kinds:
        raise MailboxRelayError("payload_kind is not allowed")
    payload = envelope.get("payload_text")
    if not isinstance(payload, str):
        raise MailboxRelayError("payload_text must be a string")
    if envelope.get("status") == "blocked" and not payload:
        raise MailboxRelayError("blocked relay requires non-empty payload_text")
    supplied = _nonempty(envelope.get("payload_sha256"), "payload_sha256")
    if not DIGEST.fullmatch(supplied):
        raise MailboxRelayError("invalid payload_sha256")
    if supplied != sha256_utf8(payload):
        raise MailboxRelayError("payload_sha256 mismatch")
    _msk_timestamp(envelope.get("authored_at_msk"))


def validate_raw_relay(raw: str, **expected: Any) -> dict[str, Any]:
    envelope = parse_relay(raw)
    validate_envelope(envelope, **expected)
    return envelope


def acceptance_candidate(raw: str, **expected: Any) -> dict[str, Any]:
    env = validate_raw_relay(raw, **expected)
    return {
        "schema_version": 1,
        "task_id": env["task_id"],
        "logical_attempt": env["logical_attempt"],
        "execution_id": env["execution_id"],
        "execution_generation": env["execution_generation"],
        "relay_id": env["relay_id"],
        "producer_task_id": env["producer_task_id"],
        "mailbox_task_id": env["mailbox_task_id"],
        "mailbox_id": env["mailbox_id"],
        "mailbox_generation": env["mailbox_generation"],
        "admission_nonce": env["admission_nonce"],
        "relay_nonce": env["relay_nonce"],
        "request_digest": env["request_digest"],
        "request_blob_sha": env["request_blob_sha"],
        "author_id": env["author_id"],
        "status": env["status"],
        "payload_kind": env["payload_kind"],
        "raw_relay_sha256": sha256_utf8(raw),
        "payload_sha256": env["payload_sha256"],
    }

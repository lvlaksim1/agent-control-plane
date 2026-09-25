#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

PREFIX = "ACP_RUNTIME_RELAY_V2|"
LEGACY_PREFIX = "ACP_RUNTIME_RELAY_V1|"
MAX_PROMPT_CHARS = 12000
HEX40 = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MSK = timedelta(hours=3)


class RelayError(ValueError):
    pass


def sha256_utf8(value: str) -> str:
    if not isinstance(value, str):
        raise RelayError("sha256 input must be a string")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def encode_relay(envelope: dict[str, Any]) -> str:
    if envelope.get("schema_version") != 2:
        raise RelayError("new relays must use schema_version=2")
    raw = PREFIX + json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(raw) > MAX_PROMPT_CHARS:
        raise RelayError("relay exceeds v2 prompt bound")
    return raw


def parse_relay(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise RelayError("relay must be a string")
    if len(raw) > MAX_PROMPT_CHARS:
        raise RelayError("relay exceeds prompt bound")
    if raw.startswith(PREFIX):
        encoded = raw[len(PREFIX):]
    elif raw.startswith(LEGACY_PREFIX):
        encoded = raw[len(LEGACY_PREFIX):]
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


def _validate_timestamp(value: Any) -> None:
    stamp = _nonempty(value, "authored_at_msk")
    try:
        dt = datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise RelayError("invalid authored_at_msk") from exc
    if dt.tzinfo is None or dt.utcoffset() != MSK:
        raise RelayError("authored_at_msk must use UTC+03:00")


def _validate_common_bindings(
    envelope: dict[str, Any],
    *,
    relay_id: str,
    transport_task_id: str,
    task_id: str,
    request_digest: str,
    request_blob_sha: str,
    relay_nonce: str,
    author_id: str,
    allowed_payload_kinds: set[str] | None,
) -> None:
    expected = {
        "relay_id": relay_id,
        "transport_task_id": transport_task_id,
        "task_id": task_id,
        "request_digest": request_digest,
        "request_blob_sha": request_blob_sha,
        "relay_nonce": relay_nonce,
        "author_id": author_id,
    }
    for key, value in expected.items():
        if envelope.get(key) != value:
            raise RelayError(f"{key} binding mismatch")
    if not DIGEST.fullmatch(_nonempty(envelope.get("request_digest"), "request_digest")):
        raise RelayError("invalid request_digest")
    if not HEX40.fullmatch(_nonempty(envelope.get("request_blob_sha"), "request_blob_sha")):
        raise RelayError("invalid request_blob_sha")
    if envelope.get("author_kind") not in {"persistent-agent", "infrastructure"}:
        raise RelayError("invalid author_kind")
    if envelope.get("status") not in {"complete", "blocked"}:
        raise RelayError("invalid relay status")
    kind = _nonempty(envelope.get("payload_kind"), "payload_kind")
    if allowed_payload_kinds is not None and kind not in allowed_payload_kinds:
        raise RelayError("payload_kind is not allowed")
    _validate_timestamp(envelope.get("authored_at_msk"))


def validate_envelope(
    envelope: dict[str, Any],
    *,
    relay_id: str,
    transport_task_id: str,
    task_id: str,
    attempt: int,
    request_digest: str,
    request_blob_sha: str,
    relay_nonce: str,
    author_id: str,
    allowed_payload_kinds: set[str] | None = None,
) -> None:
    required = {
        "schema_version",
        "relay_id",
        "transport_task_id",
        "task_id",
        "attempt",
        "request_digest",
        "request_blob_sha",
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
    if envelope.get("schema_version") != 2:
        raise RelayError("unsupported relay schema_version for acceptance")
    if not isinstance(attempt, int) or attempt < 1:
        raise RelayError("expected attempt must be a positive integer")
    if envelope.get("attempt") != attempt:
        raise RelayError("attempt binding mismatch")
    _validate_common_bindings(
        envelope,
        relay_id=relay_id,
        transport_task_id=transport_task_id,
        task_id=task_id,
        request_digest=request_digest,
        request_blob_sha=request_blob_sha,
        relay_nonce=relay_nonce,
        author_id=author_id,
        allowed_payload_kinds=allowed_payload_kinds,
    )
    if envelope.get("terminal") is not True:
        raise RelayError("relay must be terminal")
    if envelope.get("payload_encoding") != "utf-8":
        raise RelayError("payload_encoding must be utf-8")
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


def validate_raw_relay(raw: str, **expected: Any) -> dict[str, Any]:
    envelope = parse_relay(raw)
    validate_envelope(envelope, **expected)
    return envelope


def acceptance_candidate(raw: str, **expected: Any) -> dict[str, Any]:
    envelope = validate_raw_relay(raw, **expected)
    return {
        "schema_version": 1,
        "task_id": envelope["task_id"],
        "attempt": envelope["attempt"],
        "relay_id": envelope["relay_id"],
        "relay_nonce": envelope["relay_nonce"],
        "transport_task_id": envelope["transport_task_id"],
        "request_digest": envelope["request_digest"],
        "request_blob_sha": envelope["request_blob_sha"],
        "author_id": envelope["author_id"],
        "status": envelope["status"],
        "payload_kind": envelope["payload_kind"],
        "raw_relay_sha256": sha256_utf8(raw),
        "payload_sha256": envelope["payload_sha256"],
    }


def plan_acceptance(
    raw: str,
    *,
    existing_receipt: dict[str, Any] | None = None,
    **expected: Any,
) -> dict[str, Any]:
    candidate = acceptance_candidate(raw, **expected)
    if existing_receipt is None:
        return {"decision": "accept-new", "receipt": candidate}
    if not isinstance(existing_receipt, dict):
        raise RelayError("existing receipt must be an object")
    if existing_receipt.get("schema_version") != 1:
        raise RelayError("unsupported acceptance receipt schema_version")
    if existing_receipt.get("task_id") != candidate["task_id"]:
        raise RelayError("existing receipt task binding mismatch")
    same = all(existing_receipt.get(key) == value for key, value in candidate.items())
    if same:
        return {"decision": "already-accepted", "receipt": candidate}
    raise RelayError("canonical relay receipt already exists with different content")

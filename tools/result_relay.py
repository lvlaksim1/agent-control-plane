#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

PREFIX="ACP_RUNTIME_RELAY_V1|"
MAX_PROMPT_CHARS=12000
HEX40=re.compile(r"^[0-9a-f]{40}$")
DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$")
MSK=timedelta(hours=3)

class RelayError(ValueError):
    pass

def encode_relay(envelope:dict[str,Any])->str:
    raw=PREFIX+json.dumps(envelope,ensure_ascii=False,separators=(",",":"),sort_keys=True)
    if len(raw)>MAX_PROMPT_CHARS:
        raise RelayError("relay exceeds v1 prompt bound")
    return raw

def parse_relay(raw:str)->dict[str,Any]:
    if not isinstance(raw,str) or not raw.startswith(PREFIX):
        raise RelayError("invalid relay prefix")
    if len(raw)>MAX_PROMPT_CHARS:
        raise RelayError("relay exceeds v1 prompt bound")
    try:
        envelope=json.loads(raw[len(PREFIX):])
    except json.JSONDecodeError as exc:
        raise RelayError("invalid relay JSON") from exc
    if not isinstance(envelope,dict):
        raise RelayError("relay envelope must be an object")
    return envelope

def _nonempty(value:Any,label:str)->str:
    if not isinstance(value,str) or not value:
        raise RelayError(f"{label} must be a non-empty string")
    return value

def validate_envelope(
    envelope:dict[str,Any],
    *,
    relay_id:str,
    transport_task_id:str,
    task_id:str,
    request_digest:str,
    request_blob_sha:str,
    relay_nonce:str,
    author_id:str,
    allowed_payload_kinds:set[str]|None=None,
)->None:
    required={
      "schema_version","relay_id","transport_task_id","task_id","request_digest",
      "request_blob_sha","relay_nonce","author_id","author_kind","status",
      "payload_kind","payload","authored_at_msk"
    }
    missing=sorted(required-set(envelope))
    if missing:
        raise RelayError("relay missing fields: "+", ".join(missing))
    if envelope["schema_version"]!=1:
        raise RelayError("unsupported relay schema_version")
    expected={
      "relay_id":relay_id,
      "transport_task_id":transport_task_id,
      "task_id":task_id,
      "request_digest":request_digest,
      "request_blob_sha":request_blob_sha,
      "relay_nonce":relay_nonce,
      "author_id":author_id,
    }
    for key,value in expected.items():
        if envelope.get(key)!=value:
            raise RelayError(f"{key} binding mismatch")
    if not DIGEST.fullmatch(_nonempty(envelope["request_digest"],"request_digest")):
        raise RelayError("invalid request_digest")
    if not HEX40.fullmatch(_nonempty(envelope["request_blob_sha"],"request_blob_sha")):
        raise RelayError("invalid request_blob_sha")
    if envelope["author_kind"] not in {"persistent-agent","infrastructure"}:
        raise RelayError("invalid author_kind")
    if envelope["status"] not in {"complete","blocked"}:
        raise RelayError("invalid relay status")
    kind=_nonempty(envelope["payload_kind"],"payload_kind")
    if allowed_payload_kinds is not None and kind not in allowed_payload_kinds:
        raise RelayError("payload_kind is not allowed")
    if not isinstance(envelope["payload"],dict):
        raise RelayError("payload must be an object")
    stamp=_nonempty(envelope["authored_at_msk"],"authored_at_msk")
    try:
        dt=datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise RelayError("invalid authored_at_msk") from exc
    if dt.tzinfo is None or dt.utcoffset()!=MSK:
        raise RelayError("authored_at_msk must use UTC+03:00")
    if envelope["status"]=="blocked" and not envelope["payload"].get("reason"):
        raise RelayError("blocked relay requires payload.reason")

def validate_raw_relay(raw:str,**expected:Any)->dict[str,Any]:
    envelope=parse_relay(raw)
    validate_envelope(envelope,**expected)
    return envelope

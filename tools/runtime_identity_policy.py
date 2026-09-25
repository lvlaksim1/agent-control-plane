#!/usr/bin/env python3
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

MOSCOW = ZoneInfo("Europe/Moscow")
HEADER_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{4}) · (\d{2}:\d{2}) MSK · ([A-Za-z0-9._:-]+)$")

class RuntimeIdentityPolicyError(ValueError):
    pass

def validate_inter_agent_request(request: dict[str, Any], *, terminal: bool = False) -> None:
    """Validate the runtime-boundary additions for new inter-agent work."""
    issuer = request.get("issuer_agent_id")
    if issuer == "owner" or terminal:
        return
    responsibility = request.get("responsibility")
    if not isinstance(responsibility, dict):
        raise RuntimeIdentityPolicyError("new inter-agent work requires responsibility")
    if responsibility.get("semantics_version") != 3:
        raise RuntimeIdentityPolicyError("new nonterminal inter-agent work requires responsibility semantics_version 3")
    mode = responsibility.get("mode")
    caller = responsibility.get("caller_agent_id")
    target = request.get("target_agent_id")
    if caller != issuer:
        raise RuntimeIdentityPolicyError("caller_agent_id must equal issuer_agent_id")
    if target == caller:
        raise RuntimeIdentityPolicyError("inter-agent request must target a different persistent agent_id")
    policy = responsibility.get("continuation_policy")
    if mode == "bounded_delegation":
        if responsibility.get("commitment_owner_agent_id") != issuer:
            raise RuntimeIdentityPolicyError("bounded delegation keeps commitment with caller")
        if responsibility.get("return_to_agent_id") != issuer:
            raise RuntimeIdentityPolicyError("bounded delegation retains caller as return provenance")
        if policy not in {"manual_pull", "automatic_new_runtime"}:
            raise RuntimeIdentityPolicyError("bounded delegation requires manual_pull or automatic_new_runtime")
    elif mode == "explicit_handoff":
        if policy != "none":
            raise RuntimeIdentityPolicyError("explicit handoff continuation_policy must be none")
    else:
        raise RuntimeIdentityPolicyError("unsupported responsibility mode")

def assert_runtime_affinity(*, runtime_agent_id: str, requested_agent_id: str) -> None:
    if not runtime_agent_id or not requested_agent_id:
        raise RuntimeIdentityPolicyError("agent ids must be non-empty")
    if runtime_agent_id != requested_agent_id:
        raise RuntimeIdentityPolicyError("persistent agent_id switch inside one runtime is forbidden")

def format_user_header(source_id: str, now: datetime) -> str:
    if not source_id:
        raise RuntimeIdentityPolicyError("source_id must be non-empty")
    local = now.astimezone(MOSCOW)
    return f"{local:%d.%m.%Y} · {local:%H:%M} MSK · {source_id}"

def validate_user_header(header: str, expected_source_id: str) -> None:
    match = HEADER_RE.fullmatch(header)
    if match is None:
        raise RuntimeIdentityPolicyError("invalid user-visible source header")
    if match.group(3) != expected_source_id:
        raise RuntimeIdentityPolicyError("user-visible source id mismatch")

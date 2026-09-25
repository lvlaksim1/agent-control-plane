#!/usr/bin/env python3
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

MOSCOW = ZoneInfo("Europe/Moscow")
HEADER_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{4}) · (\d{2}:\d{2}) MSK · ([A-Za-z0-9._:-]+)$")

SEPARATE_TARGET = "runtime:separate-target"
MANUAL_PULL = "continuation:manual-pull"
AUTO_RETURN = "continuation:automatic-new-runtime"

class RuntimeIdentityPolicyError(ValueError):
    pass

def continuation_mode(request: dict[str, Any]) -> str:
    constraints = request.get("constraints")
    if not isinstance(constraints, list):
        raise RuntimeIdentityPolicyError("task constraints must be a list")
    modes = [x for x in (MANUAL_PULL, AUTO_RETURN) if x in constraints]
    if len(modes) != 1:
        raise RuntimeIdentityPolicyError("inter-agent task requires exactly one continuation execution policy")
    return "manual_pull" if modes[0] == MANUAL_PULL else "automatic_new_runtime"

def validate_inter_agent_request(request: dict[str, Any], *, terminal: bool = False) -> None:
    """Validate fixed-runtime additions without changing proven responsibility v2."""
    issuer = request.get("issuer_agent_id")
    if issuer == "owner" or terminal:
        return
    responsibility = request.get("responsibility")
    if not isinstance(responsibility, dict):
        raise RuntimeIdentityPolicyError("new inter-agent work requires responsibility")
    if responsibility.get("semantics_version") != 2:
        raise RuntimeIdentityPolicyError("inter-agent authority/responsibility remains semantics_version 2")
    if responsibility.get("caller_agent_id") != issuer:
        raise RuntimeIdentityPolicyError("caller_agent_id must equal issuer_agent_id")
    if request.get("target_agent_id") == issuer:
        raise RuntimeIdentityPolicyError("delegated target must be a different persistent agent_id")
    constraints = request.get("constraints")
    if not isinstance(constraints, list) or SEPARATE_TARGET not in constraints:
        raise RuntimeIdentityPolicyError("inter-agent task requires runtime:separate-target")
    if responsibility.get("mode") == "bounded_delegation":
        continuation_mode(request)
    elif responsibility.get("mode") == "explicit_handoff":
        if MANUAL_PULL in constraints or AUTO_RETURN in constraints:
            raise RuntimeIdentityPolicyError("explicit handoff cannot request caller continuation")
    else:
        raise RuntimeIdentityPolicyError("unsupported responsibility mode")

def validate_autonomous_return_pair(child: dict[str, Any], caller_task: dict[str, Any]) -> None:
    """The caller continuation is a precreated dependency, never a same-runtime return."""
    if continuation_mode(child) != "automatic_new_runtime":
        raise RuntimeIdentityPolicyError("child is not an automatic-new-runtime delegation")
    caller_id = child["issuer_agent_id"]
    if caller_task.get("target_agent_id") != caller_id:
        raise RuntimeIdentityPolicyError("return task must target the original caller")
    deps = caller_task.get("dependencies")
    if not isinstance(deps, list) or not any(
        isinstance(dep, dict)
        and dep.get("task_id") == child.get("task_id")
        and dep.get("relation") == "depends_on"
        for dep in deps
    ):
        raise RuntimeIdentityPolicyError("return task must depend on exact child task")
    constraints = caller_task.get("constraints")
    if not isinstance(constraints, list) or "runtime:caller-continuation" not in constraints:
        raise RuntimeIdentityPolicyError("return task must declare runtime:caller-continuation")

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

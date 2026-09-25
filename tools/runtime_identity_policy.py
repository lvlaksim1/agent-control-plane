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
CALLER_CONTINUATION = "runtime:caller-continuation"

class RuntimeIdentityPolicyError(ValueError):
    pass

def _constraints(request: dict[str, Any]) -> list[str]:
    constraints = request.get("constraints")
    if not isinstance(constraints, list) or any(not isinstance(x, str) or not x for x in constraints):
        raise RuntimeIdentityPolicyError("task constraints must be a list of non-empty strings")
    return constraints

def continuation_mode(request: dict[str, Any]) -> str:
    constraints = _constraints(request)
    modes = [x for x in (MANUAL_PULL, AUTO_RETURN) if x in constraints]
    if len(modes) != 1:
        raise RuntimeIdentityPolicyError("inter-agent task requires exactly one continuation execution policy")
    return "manual_pull" if modes[0] == MANUAL_PULL else "automatic_new_runtime"

def is_caller_continuation_request(request: dict[str, Any]) -> bool:
    issuer = request.get("issuer_agent_id")
    target = request.get("target_agent_id")
    if not isinstance(issuer, str) or not issuer or not isinstance(target, str) or not target:
        return False
    try:
        constraints = _constraints(request)
    except RuntimeIdentityPolicyError:
        return False
    return issuer != "owner" and target == issuer and CALLER_CONTINUATION in constraints

def validate_inter_agent_request(request: dict[str, Any], *, terminal: bool = False) -> None:
    """Validate fixed-runtime execution policy without changing responsibility semantics v2.

    Same-agent caller-continuation tasks are allowed only as dependency-bound work
    that will reinstate the caller in a new Worker runtime. All actual inter-agent
    work must cross a separate runtime boundary.
    """
    issuer = request.get("issuer_agent_id")
    if issuer == "owner" or terminal:
        return
    if not isinstance(issuer, str) or not issuer:
        raise RuntimeIdentityPolicyError("agent-issued task requires issuer_agent_id")
    target = request.get("target_agent_id")
    if not isinstance(target, str) or not target:
        raise RuntimeIdentityPolicyError("agent-issued task requires target_agent_id")
    constraints = _constraints(request)

    if target == issuer:
        if CALLER_CONTINUATION not in constraints:
            raise RuntimeIdentityPolicyError("same-agent scheduled work is allowed only as runtime:caller-continuation")
        if SEPARATE_TARGET in constraints or MANUAL_PULL in constraints or AUTO_RETURN in constraints:
            raise RuntimeIdentityPolicyError("caller-continuation task cannot carry delegated-target continuation constraints")
        if request.get("responsibility") is not None:
            raise RuntimeIdentityPolicyError("caller-continuation is same-agent work and must not create a responsibility transfer/delegation contract")
        deps = request.get("dependencies")
        if not isinstance(deps, list) or not deps:
            raise RuntimeIdentityPolicyError("caller-continuation must depend on at least one exact child task")
        return

    responsibility = request.get("responsibility")
    if not isinstance(responsibility, dict):
        raise RuntimeIdentityPolicyError("new inter-agent work requires responsibility")
    if responsibility.get("semantics_version") != 2:
        raise RuntimeIdentityPolicyError("inter-agent authority/responsibility remains semantics_version 2")
    if responsibility.get("caller_agent_id") != issuer:
        raise RuntimeIdentityPolicyError("caller_agent_id must equal issuer_agent_id")
    if SEPARATE_TARGET not in constraints:
        raise RuntimeIdentityPolicyError("inter-agent task requires runtime:separate-target")
    if CALLER_CONTINUATION in constraints:
        raise RuntimeIdentityPolicyError("delegated target task cannot masquerade as caller-continuation")
    if responsibility.get("mode") == "bounded_delegation":
        continuation_mode(request)
    elif responsibility.get("mode") == "explicit_handoff":
        if MANUAL_PULL in constraints or AUTO_RETURN in constraints:
            raise RuntimeIdentityPolicyError("explicit handoff cannot request caller continuation")
    else:
        raise RuntimeIdentityPolicyError("unsupported responsibility mode")

def validate_autonomous_return_pair(child: dict[str, Any], caller_task: dict[str, Any]) -> None:
    """The caller continuation is a precreated dependency, never a same-runtime return."""
    validate_inter_agent_request(child)
    if continuation_mode(child) != "automatic_new_runtime":
        raise RuntimeIdentityPolicyError("child is not an automatic-new-runtime delegation")
    caller_id = child["issuer_agent_id"]
    if caller_task.get("issuer_agent_id") != caller_id:
        raise RuntimeIdentityPolicyError("return task must be issued by the original caller")
    if caller_task.get("target_agent_id") != caller_id:
        raise RuntimeIdentityPolicyError("return task must target the original caller")
    validate_inter_agent_request(caller_task)
    deps = caller_task.get("dependencies")
    if not any(
        isinstance(dep, dict)
        and dep.get("task_id") == child.get("task_id")
        and dep.get("relation") == "depends_on"
        for dep in deps
    ):
        raise RuntimeIdentityPolicyError("return task must depend on exact child task")
    constraints = caller_task.get("constraints")
    if not isinstance(constraints, list) or CALLER_CONTINUATION not in constraints:
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

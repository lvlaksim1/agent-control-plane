#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PRIORITY_BASE = {"low": 100, "normal": 200, "high": 300, "critical": 400}
EXECUTABLE_AGENT_STATUSES = {"registered", "ready"}
TASK_STATUSES = {"queued","claimed","active","waiting","blocked","quarantined","completed","cancelled","superseded"}

class ControlPlaneError(ValueError):
    pass

def parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ControlPlaneError("timestamp must be a non-empty string")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ControlPlaneError(f"invalid timestamp: {value}") from exc
    if dt.tzinfo is None:
        raise ControlPlaneError("timestamp must include timezone")
    return dt.astimezone(timezone.utc)

def format_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def request_digest(request: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(request)).hexdigest()

def require_fields(obj: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [f for f in fields if f not in obj]
    if missing:
        raise ControlPlaneError(f"{label} missing fields: {', '.join(missing)}")

def validate_registry(registry: dict[str, Any]) -> None:
    require_fields(registry, ["schema_version", "agents"], "registry")
    if registry["schema_version"] != 1:
        raise ControlPlaneError("unsupported registry schema_version")
    if not isinstance(registry["agents"], list):
        raise ControlPlaneError("registry.agents must be a list")
    seen = set()
    for agent in registry["agents"]:
        require_fields(agent, ["agent_id","agent_type","role","home_repository","authority_ref","entrypoint","status","automatic_execution_allowed"], "agent")
        aid = agent["agent_id"]
        if not isinstance(aid, str) or not aid:
            raise ControlPlaneError("agent_id must be non-empty")
        if aid in seen:
            raise ControlPlaneError(f"duplicate agent_id: {aid}")
        seen.add(aid)
        if agent["agent_type"] not in {"project-manager", "service-agent"}:
            raise ControlPlaneError(f"unsupported agent_type for {aid}")
        if not isinstance(agent["automatic_execution_allowed"], bool):
            raise ControlPlaneError(f"automatic_execution_allowed must be boolean for {aid}")

def registry_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_registry(registry)
    return {a["agent_id"]: a for a in registry["agents"]}

def validate_request(request: dict[str, Any]) -> None:
    require_fields(request, ["schema_version","task_id","issuer_agent_id","target_agent_id","objective","authority_basis","scope","constraints","target","priority","dependencies","completion_contract","created_at"], "task request")
    if request["schema_version"] != 1:
        raise ControlPlaneError("unsupported task request schema_version")
    if request["priority"] not in PRIORITY_BASE:
        raise ControlPlaneError("invalid priority")
    if not isinstance(request["dependencies"], list):
        raise ControlPlaneError("dependencies must be a list")
    responsibility=request.get("responsibility")
    if responsibility is not None:
        if not isinstance(responsibility,dict):
            raise ControlPlaneError("responsibility must be an object or null")
        require_fields(responsibility,["mode","commitment_owner_agent_id","return_to_agent_id"],"responsibility")
        mode=responsibility["mode"]
        if mode not in {"bounded_delegation","explicit_handoff"}:
            raise ControlPlaneError("invalid responsibility mode")
        owner=responsibility["commitment_owner_agent_id"]
        return_to=responsibility["return_to_agent_id"]
        if not isinstance(owner,str) or not owner:
            raise ControlPlaneError("responsibility commitment owner must be non-empty")
        if mode=="bounded_delegation":
            if request["issuer_agent_id"]=="owner":
                raise ControlPlaneError("owner direct task does not use agent bounded_delegation")
            if owner!=request["issuer_agent_id"]:
                raise ControlPlaneError("bounded delegation keeps commitment with issuer")
            if return_to!=request["issuer_agent_id"]:
                raise ControlPlaneError("bounded delegation must return to caller")
        else:
            if owner!=request["target_agent_id"]:
                raise ControlPlaneError("explicit handoff transfers commitment to target")
            if return_to is not None:
                raise ControlPlaneError("explicit handoff cannot imply automatic return")
    parse_time(request["created_at"])
    ids = set()
    for dep in request["dependencies"]:
        require_fields(dep, ["task_id", "relation"], "dependency")
        if dep["relation"] != "depends_on":
            raise ControlPlaneError(f"unsupported dependency relation: {dep['relation']}")
        if dep["task_id"] == request["task_id"]:
            raise ControlPlaneError("task cannot depend on itself")
        if dep["task_id"] in ids:
            raise ControlPlaneError("duplicate dependency")
        ids.add(dep["task_id"])

def validate_state(state: dict[str, Any], request: dict[str, Any]) -> None:
    require_fields(state, ["schema_version","task_id","status","request_digest","attempt","runtime_loss_count","claim","latest_checkpoint"], "task state")
    if state["schema_version"] != 1:
        raise ControlPlaneError("unsupported task state schema_version")
    if state["task_id"] != request["task_id"]:
        raise ControlPlaneError("task state/request task_id mismatch")
    if state["status"] not in TASK_STATUSES:
        raise ControlPlaneError("invalid task status")
    if state["request_digest"] != request_digest(request):
        raise ControlPlaneError("immutable request digest mismatch")
    if not isinstance(state["attempt"], int) or state["attempt"] < 0:
        raise ControlPlaneError("attempt must be a non-negative integer")
    if not isinstance(state["runtime_loss_count"], int) or state["runtime_loss_count"] < 0:
        raise ControlPlaneError("runtime_loss_count must be a non-negative integer")
    if state["claim"] is not None:
        require_fields(state["claim"], ["execution_id","generation","slot_id","claimed_at"], "task claim")
        parse_time(state["claim"]["claimed_at"])

def validate_lease(lease: dict[str, Any]) -> None:
    require_fields(lease, ["schema_version","state","generation","execution_id","task_id","agent_id","slot_id","claimed_at","lease_until"], "lease")
    if lease["schema_version"] != 1:
        raise ControlPlaneError("unsupported lease schema_version")
    if lease["state"] not in {"idle", "active"}:
        raise ControlPlaneError("invalid lease state")
    if not isinstance(lease["generation"], int) or lease["generation"] < 0:
        raise ControlPlaneError("generation must be a non-negative integer")
    fields = ["execution_id","task_id","agent_id","slot_id","claimed_at","lease_until"]
    if lease["state"] == "idle":
        for f in fields:
            if lease[f] is not None:
                raise ControlPlaneError(f"idle lease must clear {f}")
    else:
        for f in fields:
            if lease[f] in (None, ""):
                raise ControlPlaneError(f"active lease requires {f}")
        parse_time(lease["claimed_at"])
        parse_time(lease["lease_until"])

def validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    require_fields(checkpoint, ["schema_version","checkpoint_id","task_id","execution_id","generation","sequence","created_at","completed_steps","verified_evidence","next_action"], "checkpoint")
    if checkpoint["schema_version"] != 1:
        raise ControlPlaneError("unsupported checkpoint schema_version")
    if not isinstance(checkpoint["sequence"], int) or checkpoint["sequence"] < 1:
        raise ControlPlaneError("checkpoint sequence must be >= 1")
    if not isinstance(checkpoint["generation"], int) or checkpoint["generation"] < 1:
        raise ControlPlaneError("checkpoint generation must be >= 1")
    parse_time(checkpoint["created_at"])
    if not isinstance(checkpoint["completed_steps"], list) or not isinstance(checkpoint["verified_evidence"], list):
        raise ControlPlaneError("checkpoint evidence fields must be lists")
    if not isinstance(checkpoint["next_action"], str) or not checkpoint["next_action"]:
        raise ControlPlaneError("next_action must be non-empty")

def detect_dependency_cycle(requests: list[dict[str, Any]]) -> None:
    by_id = {r["task_id"]: r for r in requests}
    visiting, visited = set(), set()
    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise ControlPlaneError(f"dependency cycle detected at {task_id}")
        visiting.add(task_id)
        for dep in by_id[task_id]["dependencies"]:
            if dep["task_id"] in by_id:
                visit(dep["task_id"])
        visiting.remove(task_id)
        visited.add(task_id)
    for task_id in by_id:
        visit(task_id)

def effective_priority(priority: str, created_at: str, now: datetime) -> int:
    created = parse_time(created_at)
    age_days = max(0, int((now - created).total_seconds() // 86400))
    aging_boost = min(300, (age_days // 7) * 100)
    return min(400, PRIORITY_BASE[priority] + aging_boost)

def ready_tasks(registry: dict[str, Any], bundles: list[tuple[dict[str, Any], dict[str, Any]]], now: datetime) -> list[dict[str, Any]]:
    agents = registry_index(registry)
    requests, states = [], {}
    for request, state in bundles:
        validate_request(request)
        validate_state(state, request)
        if request["task_id"] in states:
            raise ControlPlaneError(f"duplicate task_id: {request['task_id']}")
        requests.append(request)
        states[request["task_id"]] = state
    detect_dependency_cycle(requests)
    ids = {r["task_id"] for r in requests}
    ready = []
    for request in requests:
        state = states[request["task_id"]]
        if state["status"] != "queued":
            continue
        agent = agents.get(request["target_agent_id"])
        if not agent or agent["status"] not in EXECUTABLE_AGENT_STATUSES or not agent["automatic_execution_allowed"]:
            continue
        if any(dep["task_id"] not in ids or states[dep["task_id"]]["status"] != "completed" for dep in request["dependencies"]):
            continue
        ready.append({"task_id":request["task_id"],"target_agent_id":request["target_agent_id"],"effective_priority":effective_priority(request["priority"],request["created_at"],now),"created_at":request["created_at"]})
    ready.sort(key=lambda x: (-x["effective_priority"], parse_time(x["created_at"]), x["task_id"]))
    return ready

def claim_plan(lease: dict[str, Any], request: dict[str, Any], state: dict[str, Any], *, slot_id: str, execution_id: str, now: datetime, lease_minutes: int = 45):
    validate_lease(lease); validate_request(request); validate_state(state, request)
    if lease["state"] != "idle":
        raise ControlPlaneError("global lease is not idle")
    if state["status"] != "queued":
        raise ControlPlaneError("task is not queued")
    if not slot_id or not execution_id:
        raise ControlPlaneError("slot_id and execution_id are required")
    generation = lease["generation"] + 1
    claimed_at = format_time(now)
    new_lease={"schema_version":1,"state":"active","generation":generation,"execution_id":execution_id,"task_id":request["task_id"],"agent_id":request["target_agent_id"],"slot_id":slot_id,"claimed_at":claimed_at,"lease_until":format_time(now+timedelta(minutes=lease_minutes))}
    new_state=copy.deepcopy(state)
    new_state["status"]="claimed"; new_state["attempt"]+=1
    new_state["claim"]={"execution_id":execution_id,"generation":generation,"slot_id":slot_id,"claimed_at":claimed_at}
    return new_lease,new_state

def fence_valid(lease: dict[str, Any], *, task_id: str, agent_id: str, execution_id: str, generation: int) -> bool:
    validate_lease(lease)
    return lease["state"]=="active" and lease["task_id"]==task_id and lease["agent_id"]==agent_id and lease["execution_id"]==execution_id and lease["generation"]==generation

def activate_state(state: dict[str, Any], request: dict[str, Any], lease: dict[str, Any]) -> dict[str, Any]:
    validate_state(state, request)
    if state["status"] != "claimed":
        raise ControlPlaneError("task is not claimed")
    c=state["claim"]
    if not fence_valid(lease,task_id=request["task_id"],agent_id=request["target_agent_id"],execution_id=c["execution_id"],generation=c["generation"]):
        raise ControlPlaneError("claim does not own current fence")
    n=copy.deepcopy(state); n["status"]="active"; return n

def renew_lease(lease: dict[str, Any], *, execution_id: str, generation: int, now: datetime, lease_minutes: int = 45) -> dict[str, Any]:
    validate_lease(lease)
    if lease["state"]!="active":
        raise ControlPlaneError("cannot renew idle lease")
    if lease["execution_id"]!=execution_id or lease["generation"]!=generation:
        raise ControlPlaneError("stale execution cannot renew lease")
    n=copy.deepcopy(lease); n["lease_until"]=format_time(now+timedelta(minutes=lease_minutes)); return n

def recover_expired_plan(lease: dict[str, Any], state: dict[str, Any], request: dict[str, Any], *, now: datetime, quarantine_after: int = 3):
    validate_lease(lease); validate_state(state, request)
    if lease["state"]!="active":
        raise ControlPlaneError("no active lease to recover")
    if now <= parse_time(lease["lease_until"]):
        raise ControlPlaneError("lease has not expired")
    if lease["task_id"]!=request["task_id"]:
        raise ControlPlaneError("task does not match active lease")
    new_lease={"schema_version":1,"state":"idle","generation":lease["generation"]+1,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,"claimed_at":None,"lease_until":None}
    new_state=copy.deepcopy(state); new_state["runtime_loss_count"]+=1
    new_state["status"]="quarantined" if new_state["runtime_loss_count"]>=quarantine_after else "queued"
    new_state["claim"]=None
    return new_lease,new_state

def reconcile_state_from_lease(lease: dict[str, Any], request: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    validate_lease(lease); validate_state(state, request)
    n=copy.deepcopy(state)
    if lease["state"]=="active" and lease["task_id"]==request["task_id"]:
        if state["status"]=="queued":
            n["status"]="claimed"; n["attempt"]+=1
            n["claim"]={"execution_id":lease["execution_id"],"generation":lease["generation"],"slot_id":lease["slot_id"],"claimed_at":lease["claimed_at"]}
        return n
    if state["status"] in {"claimed","active"} and state["claim"] is not None:
        c=state["claim"]
        if not fence_valid(lease,task_id=request["task_id"],agent_id=request["target_agent_id"],execution_id=c["execution_id"],generation=c["generation"]):
            n["status"]="queued"; n["claim"]=None
    return n

def select_resume_checkpoint(task_id: str, checkpoints: list[dict[str, Any]]):
    valid=[]
    for c in checkpoints:
        validate_checkpoint(c)
        if c["task_id"]==task_id:
            valid.append(c)
    if not valid:
        return None
    valid.sort(key=lambda c:(c["sequence"],parse_time(c["created_at"]),c["checkpoint_id"]))
    return valid[-1]

def load_json(path: Path):
    with path.open("r",encoding="utf-8") as f:
        return json.load(f)

def discover_task_bundles(root: Path):
    bundles=[]; d=root/"tasks"
    if not d.exists(): return bundles
    for child in sorted(d.iterdir()):
        if child.is_dir() and (child/"request.json").exists() and (child/"state.json").exists():
            bundles.append((load_json(child/"request.json"),load_json(child/"state.json")))
    return bundles

def validate_repository(root: Path):
    errors=[]
    try: validate_registry(load_json(root/"registry"/"agents.json"))
    except Exception as exc: errors.append(f"registry: {exc}")
    try: validate_lease(load_json(root/"runtime"/"lease.json"))
    except Exception as exc: errors.append(f"lease: {exc}")
    try:
        bundles=discover_task_bundles(root); requests=[]; seen=set()
        for request,state in bundles:
            validate_request(request); validate_state(state,request)
            if request["task_id"] in seen: raise ControlPlaneError(f"duplicate task_id: {request['task_id']}")
            seen.add(request["task_id"]); requests.append(request)
        detect_dependency_cycle(requests)
    except Exception as exc: errors.append(f"tasks: {exc}")
    return errors

def main() -> int:
    p=argparse.ArgumentParser(description="Deterministic Agent Control Plane validator/planner")
    sub=p.add_subparsers(dest="command",required=True)
    v=sub.add_parser("validate"); v.add_argument("--root",default=".")
    r=sub.add_parser("ready"); r.add_argument("--root",default="."); r.add_argument("--now",required=True)
    a=p.parse_args(); root=Path(a.root)
    if a.command=="validate":
        errors=validate_repository(root)
        if errors:
            for error in errors: print(f"ERROR: {error}")
            return 1
        print("VALID"); return 0
    if a.command=="ready":
        for item in ready_tasks(load_json(root/"registry"/"agents.json"),discover_task_bundles(root),parse_time(a.now)):
            print(json.dumps(item,sort_keys=True))
        return 0
    return 2

if __name__=="__main__":
    raise SystemExit(main())

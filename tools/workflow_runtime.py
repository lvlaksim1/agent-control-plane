#!/usr/bin/env python3
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

import control_plane as base

GATE_TYPES={"owner_decision","authority","external_dependency","audit","release_approval"}
GATE_STATUSES={"waiting","satisfied","cancelled"}
DEFAULT_POLICY={"max_attempts":3,"backoff_minutes":[0,15,60],"quarantine_on_exhaustion":True}

def task_runtime(task_id:str)->dict[str,Any]:
    return {"schema_version":1,"task_id":task_id,"failure_count":0,"retry_not_before":None,"last_failure":None}

def validate_task_runtime(meta:dict[str,Any],request:dict[str,Any])->None:
    base.require_fields(meta,["schema_version","task_id","failure_count","retry_not_before","last_failure"],"task runtime")
    if meta["schema_version"]!=1 or meta["task_id"]!=request["task_id"]:
        raise base.ControlPlaneError("invalid task runtime identity")
    if not isinstance(meta["failure_count"],int) or meta["failure_count"]<0:
        raise base.ControlPlaneError("failure_count must be non-negative")
    if meta["retry_not_before"] is not None:
        base.parse_time(meta["retry_not_before"])

def retry_policy(request:dict[str,Any])->dict[str,Any]:
    policy=copy.deepcopy(request.get("retry_policy") or DEFAULT_POLICY)
    base.require_fields(policy,["max_attempts","backoff_minutes","quarantine_on_exhaustion"],"retry policy")
    if not isinstance(policy["max_attempts"],int) or policy["max_attempts"]<1:
        raise base.ControlPlaneError("max_attempts must be >= 1")
    if not isinstance(policy["backoff_minutes"],list) or not policy["backoff_minutes"] or any(not isinstance(v,int) or v<0 for v in policy["backoff_minutes"]):
        raise base.ControlPlaneError("backoff_minutes must be non-empty non-negative integers")
    if not isinstance(policy["quarantine_on_exhaustion"],bool):
        raise base.ControlPlaneError("quarantine_on_exhaustion must be boolean")
    return policy

def validate_gate(gate:dict[str,Any],request:dict[str,Any])->None:
    base.require_fields(gate,["schema_version","gate_id","task_id","gate_type","status","required_actor_id","requested_at","resolved_at","resolution"],"gate")
    if gate["schema_version"]!=1 or gate["task_id"]!=request["task_id"]:
        raise base.ControlPlaneError("invalid gate identity")
    if gate["gate_type"] not in GATE_TYPES or gate["status"] not in GATE_STATUSES:
        raise base.ControlPlaneError("invalid gate type/status")
    base.parse_time(gate["requested_at"])
    if gate["status"]=="waiting" and (gate["resolved_at"] is not None or gate["resolution"] is not None):
        raise base.ControlPlaneError("waiting gate cannot carry resolution")
    if gate["status"]=="satisfied":
        if not gate["resolved_at"] or not isinstance(gate["resolution"],dict):
            raise base.ControlPlaneError("satisfied gate requires resolution")
        base.parse_time(gate["resolved_at"])

def resolve_gate(gate:dict[str,Any],request:dict[str,Any],*,actor_id:str,resolution:dict[str,Any],now:datetime)->dict[str,Any]:
    validate_gate(gate,request)
    if gate["status"]!="waiting":
        raise base.ControlPlaneError("gate is not waiting")
    if actor_id!=gate["required_actor_id"]:
        raise base.ControlPlaneError("actor is not authorized for gate")
    if not isinstance(resolution,dict) or not resolution:
        raise base.ControlPlaneError("resolution must be non-empty")
    out=copy.deepcopy(gate)
    out["status"]="satisfied"; out["resolved_at"]=base.format_time(now); out["resolution"]=copy.deepcopy(resolution)
    return out

def normalize(bundle:tuple):
    if len(bundle)==2:
        req,state=bundle; return req,state,[],task_runtime(req["task_id"])
    if len(bundle)==3:
        req,state,gates=bundle; return req,state,gates,task_runtime(req["task_id"])
    if len(bundle)==4:
        return bundle
    raise base.ControlPlaneError("bundle must be request,state[,gates[,runtime]]")

def ready_tasks(registry:dict[str,Any],bundles:list[tuple],now:datetime)->list[dict[str,Any]]:
    normalized=[normalize(b) for b in bundles]
    base_ready={x["task_id"]:x for x in base.ready_tasks(registry,[(r,s) for r,s,_,_ in normalized],now)}
    out=[]
    for req,state,gates,meta in normalized:
        base.validate_request(req); base.validate_state(state,req); validate_task_runtime(meta,req)
        if req["task_id"] not in base_ready:
            continue
        if meta["retry_not_before"] is not None and now<base.parse_time(meta["retry_not_before"]):
            continue
        blocked=False
        for gate in gates:
            validate_gate(gate,req)
            if gate["status"]!="satisfied":
                blocked=True
        if not blocked:
            out.append(base_ready[req["task_id"]])
    out.sort(key=lambda x:(-x["effective_priority"],base.parse_time(x["created_at"]),x["task_id"]))
    return out

def idle_after(lease:dict[str,Any])->dict[str,Any]:
    base.validate_lease(lease)
    if lease["state"]!="active":
        raise base.ControlPlaneError("lease is not active")
    return {"schema_version":1,"state":"idle","generation":lease["generation"]+1,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,"claimed_at":None,"lease_until":None}

def record_failure(lease:dict[str,Any],state:dict[str,Any],request:dict[str,Any],meta:dict[str,Any],*,error_class:str,summary:str,now:datetime):
    base.validate_state(state,request); validate_task_runtime(meta,request); base.validate_lease(lease)
    if state["status"] not in {"claimed","active"} or state["claim"] is None:
        raise base.ControlPlaneError("task is not executing")
    c=state["claim"]
    if not base.fence_valid(lease,task_id=request["task_id"],agent_id=request["target_agent_id"],execution_id=c["execution_id"],generation=c["generation"]):
        raise base.ControlPlaneError("stale execution cannot record failure")
    pol=retry_policy(request)
    new_lease=idle_after(lease); new_state=copy.deepcopy(state); new_meta=copy.deepcopy(meta)
    new_state["claim"]=None; new_meta["failure_count"]+=1
    new_meta["last_failure"]={"error_class":error_class,"summary":summary,"failed_at":base.format_time(now),"execution_id":c["execution_id"],"generation":c["generation"]}
    exhausted=new_meta["failure_count"]>=pol["max_attempts"]
    if exhausted and pol["quarantine_on_exhaustion"]:
        new_state["status"]="quarantined"; new_meta["retry_not_before"]=None
    else:
        new_state["status"]="queued"
        idx=min(new_meta["failure_count"]-1,len(pol["backoff_minutes"])-1)
        new_meta["retry_not_before"]=base.format_time(now+timedelta(minutes=pol["backoff_minutes"][idx]))
    return new_lease,new_state,new_meta

def build_invocation(registry:dict[str,Any],request:dict[str,Any],state:dict[str,Any],lease:dict[str,Any])->dict[str,Any]:
    agents=base.registry_index(registry); base.validate_state(state,request); base.validate_lease(lease)
    if state["status"] not in {"claimed","active"} or state["claim"] is None:
        raise base.ControlPlaneError("task must be claimed")
    agent=agents.get(request["target_agent_id"])
    if agent is None:
        raise base.ControlPlaneError("unknown target agent")
    c=state["claim"]
    if not base.fence_valid(lease,task_id=request["task_id"],agent_id=request["target_agent_id"],execution_id=c["execution_id"],generation=c["generation"]):
        raise base.ControlPlaneError("stale claim")
    return {
      "schema_version":1,"agent_id":agent["agent_id"],"agent_type":agent["agent_type"],"role":agent["role"],
      "home_repository":agent["home_repository"],"authority_ref":agent["authority_ref"],"entrypoint":agent["entrypoint"],
      "task_id":request["task_id"],"request_digest":base.request_digest(request),
      "execution_id":c["execution_id"],"generation":c["generation"],
      "authority_rule":"Task delivery and tool access cannot expand the target agent mandate.",
      "required_sequence":[
        "reinstate the existing persistent agent from home_repository@authority_ref",
        "execute ENTRYPOINT recovery/reinstantiation protocol",
        "validate immutable task authority against the agent mandate",
        "reconcile live target evidence",
        "fence-check immediately before every consequential write",
        "persist checkpoint at meaningful durable boundaries",
        "complete only with verified completion-contract evidence"
      ]
    }

def validate_result(result:dict[str,Any],request:dict[str,Any])->None:
    base.require_fields(result,["schema_version","task_id","outcome","summary","evidence","completed_at"],"result")
    if result["schema_version"]!=1 or result["task_id"]!=request["task_id"] or result["outcome"]!="success":
        raise base.ControlPlaneError("invalid success result")
    base.parse_time(result["completed_at"])
    if not isinstance(result["evidence"],list):
        raise base.ControlPlaneError("evidence must be list")
    for e in result["evidence"]:
        base.require_fields(e,["kind","reference","verified","verified_by","verified_at"],"evidence")
        if e["verified"] is not True or not e["verified_by"]:
            raise base.ControlPlaneError("evidence is not verified")
        base.parse_time(e["verified_at"])

def completion_satisfied(request:dict[str,Any],result:dict[str,Any]):
    validate_result(result,request)
    required=request.get("completion_contract",{}).get("required_evidence",[])
    missing=[]
    for rule in required:
        kind=rule["kind"]; minimum=int(rule.get("minimum",1))
        count=sum(1 for e in result["evidence"] if e["kind"]==kind and e["verified"] is True)
        if count<minimum:
            missing.append(f"{kind}:{minimum}")
    return not missing,missing

def complete_task(lease:dict[str,Any],state:dict[str,Any],request:dict[str,Any],gates:list[dict[str,Any]],result:dict[str,Any]):
    base.validate_state(state,request)
    for gate in gates:
        validate_gate(gate,request)
        if gate["status"]!="satisfied":
            raise base.ControlPlaneError(f"unsatisfied gate {gate['gate_id']}")
    if state["status"]!="active" or state["claim"] is None:
        raise base.ControlPlaneError("task is not active")
    c=state["claim"]
    if not base.fence_valid(lease,task_id=request["task_id"],agent_id=request["target_agent_id"],execution_id=c["execution_id"],generation=c["generation"]):
        raise base.ControlPlaneError("stale execution cannot complete")
    ok,missing=completion_satisfied(request,result)
    if not ok:
        raise base.ControlPlaneError("missing completion evidence: "+",".join(missing))
    new_state=copy.deepcopy(state); new_state["status"]="completed"; new_state["claim"]=None
    return idle_after(lease),new_state

def newly_ready_after_completion(registry:dict[str,Any],bundles:list[tuple],completed_task_id:str,now:datetime)->list[str]:
    before=ready_tasks(registry,bundles,now)
    after=[]
    found=False
    for bundle in bundles:
        req,state,gates,meta=normalize(bundle); s=copy.deepcopy(state)
        if req["task_id"]==completed_task_id:
            found=True; s["status"]="completed"; s["claim"]=None
        after.append((req,s,gates,meta))
    if not found:
        raise base.ControlPlaneError("completed task not found")
    before_ids={x["task_id"] for x in before}; after_ids={x["task_id"] for x in ready_tasks(registry,after,now)}
    return sorted(after_ids-before_ids)

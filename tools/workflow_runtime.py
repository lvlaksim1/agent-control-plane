#!/usr/bin/env python3
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

import control_plane as base

GATE_TYPES={"owner_decision","authority","external_dependency","audit","release_approval"}
GATE_STATUSES={"waiting","satisfied","cancelled"}
DEFAULT_POLICY={"max_attempts":3,"backoff_minutes":[0,15,60],"quarantine_on_exhaustion":True}

TASK_CARRIER_MODES={"live","hold"}

def task_runtime(task_id:str)->dict[str,Any]:
    return {"schema_version":1,"task_id":task_id,"failure_count":0,"retry_not_before":None,"last_failure":None}

def validate_task_carrier(carrier:dict[str,Any]|None)->None:
    if carrier is None:
        return
    if not isinstance(carrier,dict):
        raise base.ControlPlaneError("task carrier must be an object or null")
    base.require_fields(carrier,["mode","carrier_id","set_by","reason","heartbeat_at","lease_until","fallback_after_expiry"],"task carrier")
    if carrier["mode"] not in TASK_CARRIER_MODES:
        raise base.ControlPlaneError("invalid task carrier mode")
    if not carrier["carrier_id"] or not carrier["set_by"] or not carrier["reason"]:
        raise base.ControlPlaneError("task carrier identity/provenance must be non-empty")
    if not isinstance(carrier["fallback_after_expiry"],bool):
        raise base.ControlPlaneError("task carrier fallback_after_expiry must be boolean")
    if carrier["mode"]=="live":
        if not carrier["heartbeat_at"] or not carrier["lease_until"]:
            raise base.ControlPlaneError("live task carrier requires heartbeat_at and lease_until")
        heartbeat=base.parse_time(carrier["heartbeat_at"])
        lease_until=base.parse_time(carrier["lease_until"])
        if lease_until<=heartbeat:
            raise base.ControlPlaneError("live task carrier lease must expire after heartbeat")
    else:
        if carrier["heartbeat_at"] is not None or carrier["lease_until"] is not None:
            raise base.ControlPlaneError("hold task carrier must not expire")
        if carrier["fallback_after_expiry"] is not False:
            raise base.ControlPlaneError("hold task carrier cannot allow expiry fallback")

def validate_task_runtime(meta:dict[str,Any],request:dict[str,Any])->None:
    base.require_fields(meta,["schema_version","task_id","failure_count","retry_not_before","last_failure"],"task runtime")
    if meta["schema_version"]!=1 or meta["task_id"]!=request["task_id"]:
        raise base.ControlPlaneError("invalid task runtime identity")
    if not isinstance(meta["failure_count"],int) or meta["failure_count"]<0:
        raise base.ControlPlaneError("failure_count must be non-negative")
    if meta["retry_not_before"] is not None:
        base.parse_time(meta["retry_not_before"])

def validate_state_carrier(state:dict[str,Any],request:dict[str,Any])->None:
    base.validate_state(state,request)
    validate_task_carrier(state.get("carrier"))

def task_carrier_blocks_scheduler(state:dict[str,Any],request:dict[str,Any],*,now:datetime)->bool:
    validate_state_carrier(state,request)
    carrier=state.get("carrier")
    if carrier is None:
        return False
    if carrier["mode"]=="hold":
        return True
    lease_until=base.parse_time(carrier["lease_until"])
    if now < lease_until:
        return True
    return carrier["fallback_after_expiry"] is not True

def set_live_task_carrier(state:dict[str,Any],request:dict[str,Any],*,carrier_id:str,set_by:str,reason:str,now:datetime,lease_minutes:int=45)->dict[str,Any]:
    """Prepare one CAS update on state.json. Claim-vs-carrier races resolve on the same Git object."""
    validate_state_carrier(state,request)
    if state["status"]!="queued" or state.get("claim") is not None:
        raise base.ControlPlaneError("live carrier can be acquired only from unclaimed queued state")
    if not carrier_id or not set_by or not reason or not isinstance(lease_minutes,int) or lease_minutes<1:
        raise base.ControlPlaneError("invalid live task carrier parameters")
    current=state.get("carrier")
    if current is not None:
        if current["mode"]=="hold":
            raise base.ControlPlaneError("explicit task hold must be cleared before live acquisition")
        if now < base.parse_time(current["lease_until"]) and current["carrier_id"]!=carrier_id:
            raise base.ControlPlaneError("task already has a fresh live carrier")
    out=copy.deepcopy(state)
    out["carrier"]={
      "mode":"live",
      "carrier_id":carrier_id,
      "set_by":set_by,
      "reason":reason,
      "heartbeat_at":base.format_time(now),
      "lease_until":base.format_time(now+timedelta(minutes=lease_minutes)),
      "fallback_after_expiry":True
    }
    validate_state_carrier(out,request)
    return out

def renew_live_task_carrier(state:dict[str,Any],request:dict[str,Any],*,carrier_id:str,now:datetime,lease_minutes:int=45)->dict[str,Any]:
    validate_state_carrier(state,request)
    if state["status"]!="queued" or state.get("claim") is not None:
        raise base.ControlPlaneError("only unclaimed queued live task can renew carrier")
    carrier=state.get("carrier")
    if not isinstance(carrier,dict) or carrier.get("mode")!="live":
        raise base.ControlPlaneError("task has no live carrier")
    if carrier.get("carrier_id")!=carrier_id:
        raise base.ControlPlaneError("task carrier mismatch")
    if now>=base.parse_time(carrier["lease_until"]):
        raise base.ControlPlaneError("expired live task carrier cannot be renewed without reconciliation")
    out=copy.deepcopy(state)
    out["carrier"]["heartbeat_at"]=base.format_time(now)
    out["carrier"]["lease_until"]=base.format_time(now+timedelta(minutes=lease_minutes))
    return out

def clear_task_carrier(state:dict[str,Any],request:dict[str,Any])->dict[str,Any]:
    validate_state_carrier(state,request)
    if state.get("claim") is not None:
        raise base.ControlPlaneError("cannot clear carrier from claimed task")
    out=copy.deepcopy(state)
    out["carrier"]=None
    return out

def live_carrier_fence_valid(state:dict[str,Any],request:dict[str,Any],gateway_lease:dict[str,Any],*,carrier_id:str,now:datetime)->bool:
    """Direct-live execution fence. Re-read state and gateway before consequential writes."""
    try:
        validate_state_carrier(state,request)
    except Exception:
        return False
    if state.get("status")!="queued" or state.get("claim") is not None:
        return False
    carrier=state.get("carrier")
    if not isinstance(carrier,dict) or carrier.get("mode")!="live" or carrier.get("carrier_id")!=carrier_id:
        return False
    if now>=base.parse_time(carrier["lease_until"]):
        return False
    if gateway_lease.get("task_id")==request["task_id"] and gateway_lease.get("state") in {"reserved","active"}:
        return False
    return True

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

def validate_task_routing(registry:dict[str,Any],request:dict[str,Any])->None:
    """Validate routing identity only; target-agent mandate validation remains runtime responsibility."""
    agents=base.registry_index(registry)
    issuer=request.get("issuer_agent_id")
    if issuer=="owner":
        return
    if issuer not in agents:
        raise base.ControlPlaneError(f"unknown task issuer: {issuer}")
    if agents[issuer]["status"] not in base.EXECUTABLE_AGENT_STATUSES:
        raise base.ControlPlaneError(f"task issuer is not active: {issuer}")
    authority=request.get("authority_basis")
    if not isinstance(authority,dict) or not authority.get("kind") or not authority.get("reference"):
        raise base.ControlPlaneError("agent-issued task requires explicit authority basis")
    if issuer=="ecosystem-supervisor":
        return
    # A Project Manager or Service Agent may route work directly. Supervisor is never required.
    # This structural acceptance does not prove the requested action is within issuer/target mandate;
    # the reinstantiated target agent must validate that before acting.
    return

def ready_tasks(registry:dict[str,Any],bundles:list[tuple],now:datetime)->list[dict[str,Any]]:
    normalized=[normalize(b) for b in bundles]
    base_ready={x["task_id"]:x for x in base.ready_tasks(registry,[(r,s) for r,s,_,_ in normalized],now)}
    out=[]
    for req,state,gates,meta in normalized:
        base.validate_request(req); validate_task_routing(registry,req); base.validate_state(state,req); validate_task_runtime(meta,req)
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
      "task_id":request["task_id"],"request_digest":base.request_digest(request),"request_blob_sha":state.get("request_blob_sha"),
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

def _validate_result_common(result:dict[str,Any],request:dict[str,Any])->None:
    base.require_fields(result,["schema_version","task_id","request_digest","request_blob_sha","outcome","summary","evidence","completed_at"],"result")
    if result["schema_version"]!=1 or result["task_id"]!=request["task_id"] or result["outcome"]!="success":
        raise base.ControlPlaneError("invalid success result")
    if result["request_digest"]!=base.request_digest(request):
        raise base.ControlPlaneError("result/request digest mismatch")
    if not isinstance(result["request_blob_sha"],str) or len(result["request_blob_sha"])!=40:
        raise base.ControlPlaneError("result must bind to request blob")
    base.parse_time(result["completed_at"])
    if not isinstance(result["evidence"],list):
        raise base.ControlPlaneError("evidence must be list")
    for e in result["evidence"]:
        base.require_fields(e,["kind","reference","verified","verified_by","verified_at"],"evidence")
        if e["verified"] is not True or not e["verified_by"]:
            raise base.ControlPlaneError("evidence is not verified")
        base.parse_time(e["verified_at"])

def validate_result(result:dict[str,Any],request:dict[str,Any])->None:
    _validate_result_common(result,request)
    mode=result.get("execution_mode","autonomous")
    if mode=="autonomous":
        base.require_fields(result,["execution_id","generation"],"autonomous result")
        if not isinstance(result["generation"],int) or result["generation"]<1 or not result["execution_id"]:
            raise base.ControlPlaneError("autonomous result must bind to execution fence")
    elif mode=="live":
        base.require_fields(result,["carrier_id"],"live result")
        if not isinstance(result["carrier_id"],str) or not result["carrier_id"]:
            raise base.ControlPlaneError("live result must bind to carrier")
    else:
        raise base.ControlPlaneError("invalid result execution_mode")

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
    if result.get("execution_mode","autonomous")!="autonomous":
        raise base.ControlPlaneError("gateway completion requires autonomous result")
    for gate in gates:
        validate_gate(gate,request)
        if gate["status"]!="satisfied":
            raise base.ControlPlaneError(f"unsatisfied gate {gate['gate_id']}")
    if state["status"]!="active" or state["claim"] is None:
        raise base.ControlPlaneError("task is not active")
    c=state["claim"]
    if not base.fence_valid(lease,task_id=request["task_id"],agent_id=request["target_agent_id"],execution_id=c["execution_id"],generation=c["generation"]):
        raise base.ControlPlaneError("stale execution cannot complete")
    if result["request_blob_sha"]!=state.get("request_blob_sha"):
        raise base.ControlPlaneError("result/request blob mismatch")
    if result["execution_id"]!=c["execution_id"] or result["generation"]!=c["generation"]:
        raise base.ControlPlaneError("result does not belong to current execution")
    ok,missing=completion_satisfied(request,result)
    if not ok:
        raise base.ControlPlaneError("missing completion evidence: "+",".join(missing))
    new_state=copy.deepcopy(state); new_state["status"]="completed"; new_state["claim"]=None; new_state["carrier"]=None
    return idle_after(lease),new_state

def complete_live_task(state:dict[str,Any],request:dict[str,Any],gates:list[dict[str,Any]],result:dict[str,Any],gateway_lease:dict[str,Any],*,carrier_id:str,now:datetime)->dict[str,Any]:
    """Terminalize direct-live work before its carrier can expire into autonomous fallback."""
    validate_state_carrier(state,request)
    if result.get("execution_mode")!="live":
        raise base.ControlPlaneError("live completion requires execution_mode=live")
    for gate in gates:
        validate_gate(gate,request)
        if gate["status"]!="satisfied":
            raise base.ControlPlaneError(f"unsatisfied gate {gate['gate_id']}")
    if not live_carrier_fence_valid(state,request,gateway_lease,carrier_id=carrier_id,now=now):
        raise base.ControlPlaneError("live carrier fence is not valid")
    if result["request_blob_sha"]!=state.get("request_blob_sha"):
        raise base.ControlPlaneError("result/request blob mismatch")
    if result.get("carrier_id")!=carrier_id:
        raise base.ControlPlaneError("result does not belong to current live carrier")
    ok,missing=completion_satisfied(request,result)
    if not ok:
        raise base.ControlPlaneError("missing completion evidence: "+",".join(missing))
    out=copy.deepcopy(state)
    out["status"]="completed"
    out["claim"]=None
    out["carrier"]=None
    return out

def repair_completed_projection(lease:dict[str,Any],state:dict[str,Any],request:dict[str,Any],gates:list[dict[str,Any]],result:dict[str,Any])->dict[str,Any]:
    base.validate_lease(lease); base.validate_state(state,request)
    if lease["state"]!="idle":
        raise base.ControlPlaneError("completion projection repair requires idle lease")
    for gate in gates:
        validate_gate(gate,request)
        if gate["status"]!="satisfied":
            raise base.ControlPlaneError("cannot repair completion with unsatisfied gate")
    if result["request_blob_sha"]!=state.get("request_blob_sha"):
        raise base.ControlPlaneError("cannot repair result/request blob mismatch")
    ok,missing=completion_satisfied(request,result)
    if not ok:
        raise base.ControlPlaneError("cannot repair completion evidence: "+",".join(missing))
    out=copy.deepcopy(state); out["status"]="completed"; out["claim"]=None
    return out

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


def gateway_execution_admitted(state:dict[str,Any],request:dict[str,Any],gateway_lease:dict[str,Any],*,require_active_state:bool=True)->bool:
    """Deterministic target-write admission against the public two-phase gateway receipt."""
    base.validate_state(state,request)
    claim=state.get("claim")
    if claim is None:
        return False
    if require_active_state and state.get("status")!="active":
        return False
    if not require_active_state and state.get("status") not in {"claimed","active"}:
        return False
    required_lease=["state","generation","execution_id","task_id","agent_id","slot_id","request_blob_sha","activation_projection_blob_sha"]
    if any(k not in gateway_lease for k in required_lease):
        return False
    if gateway_lease.get("state")!="active":
        return False
    receipt=claim.get("activation_projection_blob_sha")
    if not isinstance(receipt,str) or len(receipt)!=40:
        return False
    expected={
      "task_id":request["task_id"],
      "agent_id":request["target_agent_id"],
      "execution_id":claim.get("execution_id"),
      "generation":claim.get("generation"),
      "slot_id":claim.get("slot_id"),
      "request_blob_sha":state.get("request_blob_sha"),
      "activation_projection_blob_sha":receipt,
    }
    return all(gateway_lease.get(k)==v for k,v in expected.items())

def claimed_execution_ready(state:dict[str,Any],request:dict[str,Any],gateway_lease:dict[str,Any])->bool:
    """Allows a later dispatcher to begin target reinstantiation only after a durable activation receipt."""
    return state.get("status")=="claimed" and gateway_execution_admitted(state,request,gateway_lease,require_active_state=False)

def scheduler_ready_tasks(registry:dict[str,Any],bundles:list[tuple],now:datetime)->list[dict[str,Any]]:
    """Scheduler READY resolution: skip only tasks whose own state carrier is live/held."""
    eligible=[]
    for bundle in bundles:
        req,state,gates,meta=normalize(bundle)
        validate_task_runtime(meta,req)
        if task_carrier_blocks_scheduler(state,req,now=now):
            continue
        eligible.append((req,state,gates,meta))
    return ready_tasks(registry,eligible,now)

def scheduler_claimed_execution_ready(state:dict[str,Any],request:dict[str,Any],gateway_lease:dict[str,Any],*,now:datetime)->bool:
    """Scheduler Phase-B admission. A fresh carrier on this exact task blocks reinstantiation."""
    if task_carrier_blocks_scheduler(state,request,now=now):
        return False
    return claimed_execution_ready(state,request,gateway_lease)

WAKE_RECENT_KEY_LIMIT=32

def validate_wake_state(wake:dict[str,Any])->None:
    base.require_fields(wake,[
      "desired_generation","armed_generation","served_generation",
      "recent_request_keys","last_request","last_armed_at","last_served_at","last_worker_run_id"
    ],"wake state")
    for key in ("desired_generation","armed_generation","served_generation"):
        if not isinstance(wake[key],int) or wake[key]<0:
            raise base.ControlPlaneError(f"{key} must be a non-negative integer")
    if wake["armed_generation"]>wake["desired_generation"]:
        raise base.ControlPlaneError("armed generation cannot exceed desired generation")
    if wake["served_generation"]>wake["armed_generation"]:
        raise base.ControlPlaneError("served generation cannot exceed armed generation")
    keys=wake["recent_request_keys"]
    if not isinstance(keys,list) or len(keys)>WAKE_RECENT_KEY_LIMIT or any(not isinstance(x,str) or not x for x in keys):
        raise base.ControlPlaneError("invalid recent wake request keys")
    if len(keys)!=len(set(keys)):
        raise base.ControlPlaneError("recent wake request keys must be unique")
    for ts in ("last_armed_at","last_served_at"):
        if wake[ts] is not None:
            base.parse_time(wake[ts])
    req=wake["last_request"]
    if req is not None:
        base.require_fields(req,["generation","request_key","reason","requested_by","requested_at"],"wake request")
        if req["generation"]!=wake["desired_generation"]:
            raise base.ControlPlaneError("last wake request must match desired generation")
        if not req["request_key"] or not req["reason"] or not req["requested_by"]:
            raise base.ControlPlaneError("wake request fields must be non-empty")
        base.parse_time(req["requested_at"])

def wake_pending(wake:dict[str,Any])->bool:
    validate_wake_state(wake)
    return wake["desired_generation"]>wake["served_generation"]

def wake_needs_arming(wake:dict[str,Any])->bool:
    validate_wake_state(wake)
    return wake["desired_generation"]>wake["armed_generation"]

def request_wake(wake:dict[str,Any],*,request_key:str,reason:str,requested_by:str,now:datetime):
    validate_wake_state(wake)
    if not request_key or not reason or not requested_by:
        raise base.ControlPlaneError("wake request requires key, reason and requester")
    if request_key in wake["recent_request_keys"]:
        return copy.deepcopy(wake),False
    out=copy.deepcopy(wake)
    out["desired_generation"]+=1
    keys=list(out["recent_request_keys"])+[request_key]
    out["recent_request_keys"]=keys[-WAKE_RECENT_KEY_LIMIT:]
    out["last_request"]={
      "generation":out["desired_generation"],
      "request_key":request_key,
      "reason":reason,
      "requested_by":requested_by,
      "requested_at":base.format_time(now)
    }
    return out,True

def mark_wake_armed(wake:dict[str,Any],*,generation:int,now:datetime)->dict[str,Any]:
    validate_wake_state(wake)
    if generation<1 or generation>wake["desired_generation"]:
        raise base.ControlPlaneError("cannot arm unknown wake generation")
    out=copy.deepcopy(wake)
    out["armed_generation"]=max(out["armed_generation"],generation)
    out["last_armed_at"]=base.format_time(now)
    validate_wake_state(out)
    return out

def mark_wake_served(wake:dict[str,Any],*,generation:int,now:datetime,worker_run_id:str)->dict[str,Any]:
    validate_wake_state(wake)
    if generation<1 or generation>wake["armed_generation"]:
        raise base.ControlPlaneError("cannot serve unarmed wake generation")
    if not worker_run_id:
        raise base.ControlPlaneError("worker_run_id is required")
    out=copy.deepcopy(wake)
    out["served_generation"]=max(out["served_generation"],generation)
    out["last_served_at"]=base.format_time(now)
    out["last_worker_run_id"]=worker_run_id
    validate_wake_state(out)
    return out

def stale_armed_wake(wake:dict[str,Any],*,now:datetime,stale_after_minutes:int)->bool:
    validate_wake_state(wake)
    if stale_after_minutes<1:
        raise base.ControlPlaneError("stale_after_minutes must be positive")
    if wake["armed_generation"]<=wake["served_generation"]:
        return False
    if wake["last_armed_at"] is None:
        return True
    return now>=base.parse_time(wake["last_armed_at"])+timedelta(minutes=stale_after_minutes)

def broker_generation_to_arm(wake:dict[str,Any],*,now:datetime,stale_after_minutes:int)->int|None:
    """Return the next global wake generation to deliver. Per-task carrier admission occurs at task selection/execution."""
    validate_wake_state(wake)
    if wake["desired_generation"]>wake["armed_generation"]:
        return wake["desired_generation"]
    if stale_armed_wake(wake,now=now,stale_after_minutes=stale_after_minutes):
        return wake["armed_generation"]
    return None


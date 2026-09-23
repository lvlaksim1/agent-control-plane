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

def validate_result(result:dict[str,Any],request:dict[str,Any])->None:
    base.require_fields(result,["schema_version","task_id","request_digest","request_blob_sha","execution_id","generation","outcome","summary","evidence","completed_at"],"result")
    if result["schema_version"]!=1 or result["task_id"]!=request["task_id"] or result["outcome"]!="success":
        raise base.ControlPlaneError("invalid success result")
    if result["request_digest"]!=base.request_digest(request):
        raise base.ControlPlaneError("result/request digest mismatch")
    if not isinstance(result["request_blob_sha"],str) or len(result["request_blob_sha"])!=40:
        raise base.ControlPlaneError("result must bind to request blob")
    if not isinstance(result["generation"],int) or result["generation"]<1 or not result["execution_id"]:
        raise base.ControlPlaneError("result must bind to execution fence")
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
    if result["request_blob_sha"]!=state.get("request_blob_sha"):
        raise base.ControlPlaneError("result/request blob mismatch")
    if result["execution_id"]!=c["execution_id"] or result["generation"]!=c["generation"]:
        raise base.ControlPlaneError("result does not belong to current execution")
    ok,missing=completion_satisfied(request,result)
    if not ok:
        raise base.ControlPlaneError("missing completion evidence: "+",".join(missing))
    new_state=copy.deepcopy(state); new_state["status"]="completed"; new_state["claim"]=None
    return idle_after(lease),new_state

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

EXECUTION_MODES={"interactive","autonomous","hold"}

def validate_execution_mode(state:dict[str,Any])->None:
    base.require_fields(state,[
      "schema_version","mode","autonomous_scheduler_allowed",
      "fallback_after_presence_expiry","set_by","authority","reason","set_at",
      "presence","owner_hold"
    ],"execution mode")
    if state["schema_version"]!=2:
        raise base.ControlPlaneError("execution mode schema_version must be 2")
    if state["mode"] not in EXECUTION_MODES:
        raise base.ControlPlaneError("invalid execution mode")
    if not isinstance(state["autonomous_scheduler_allowed"],bool):
        raise base.ControlPlaneError("autonomous_scheduler_allowed must be boolean")
    if not isinstance(state["fallback_after_presence_expiry"],bool):
        raise base.ControlPlaneError("fallback_after_presence_expiry must be boolean")
    if not state["set_by"] or not state["authority"] or not state["reason"]:
        raise base.ControlPlaneError("execution mode provenance fields must be non-empty")
    base.parse_time(state["set_at"])

    hold=state["owner_hold"]
    if not isinstance(hold,dict):
        raise base.ControlPlaneError("owner_hold must be an object")
    base.require_fields(hold,["enabled","reason","set_by","set_at"],"owner hold")
    if not isinstance(hold["enabled"],bool):
        raise base.ControlPlaneError("owner_hold.enabled must be boolean")
    if hold["enabled"]:
        if state["mode"]!="hold":
            raise base.ControlPlaneError("enabled owner hold requires mode=hold")
        if not hold["reason"] or not hold["set_by"] or not hold["set_at"]:
            raise base.ControlPlaneError("enabled owner hold requires provenance")
        base.parse_time(hold["set_at"])
    elif state["mode"]=="hold":
        raise base.ControlPlaneError("mode=hold requires enabled owner hold")

    presence=state["presence"]
    if state["mode"]=="interactive":
        if state["autonomous_scheduler_allowed"] is not False:
            raise base.ControlPlaneError("interactive mode cannot explicitly allow scheduler")
        if hold["enabled"]:
            raise base.ControlPlaneError("interactive mode cannot also be owner hold")
        if not isinstance(presence,dict):
            raise base.ControlPlaneError("interactive mode requires presence lease")
        base.require_fields(presence,["carrier_id","heartbeat_at","lease_until"],"interactive presence")
        if not presence["carrier_id"]:
            raise base.ControlPlaneError("interactive presence carrier_id is required")
        heartbeat=base.parse_time(presence["heartbeat_at"])
        lease_until=base.parse_time(presence["lease_until"])
        if lease_until<=heartbeat:
            raise base.ControlPlaneError("interactive presence lease must expire after heartbeat")
    else:
        if presence is not None:
            raise base.ControlPlaneError("non-interactive mode must not carry presence lease")

    if state["mode"]=="autonomous":
        if state["autonomous_scheduler_allowed"] is not True:
            raise base.ControlPlaneError("autonomous mode must explicitly allow scheduler")
        if hold["enabled"]:
            raise base.ControlPlaneError("autonomous mode cannot carry owner hold")
    if state["mode"]=="hold" and state["autonomous_scheduler_allowed"] is not False:
        raise base.ControlPlaneError("owner hold must block scheduler")

def interactive_presence_fresh(state:dict[str,Any],*,now:datetime)->bool:
    validate_execution_mode(state)
    if state["mode"]!="interactive":
        return False
    return now < base.parse_time(state["presence"]["lease_until"])

def renew_interactive_presence(state:dict[str,Any],*,carrier_id:str,now:datetime,lease_minutes:int)->dict[str,Any]:
    """Renew only a still-fresh lease owned by the same carrier; expired carriers cannot silently reclaim."""
    validate_execution_mode(state)
    if state["mode"]!="interactive":
        raise base.ControlPlaneError("only interactive presence can be renewed")
    if not isinstance(lease_minutes,int) or lease_minutes<1:
        raise base.ControlPlaneError("lease_minutes must be a positive integer")
    presence=state["presence"]
    if presence["carrier_id"]!=carrier_id:
        raise base.ControlPlaneError("interactive presence carrier mismatch")
    if not interactive_presence_fresh(state,now=now):
        raise base.ControlPlaneError("expired interactive presence cannot be renewed without reconciliation")
    out=copy.deepcopy(state)
    out["presence"]["heartbeat_at"]=base.format_time(now)
    out["presence"]["lease_until"]=base.format_time(now+timedelta(minutes=lease_minutes))
    validate_execution_mode(out)
    return out

def scheduler_admission_allowed(state:dict[str,Any],*,now:datetime)->bool:
    validate_execution_mode(state)
    if state["mode"]=="hold":
        return False
    if state["mode"]=="autonomous":
        return True
    if interactive_presence_fresh(state,now=now):
        return False
    return state["fallback_after_presence_expiry"] is True

def scheduler_ready_tasks(execution_mode:dict[str,Any],registry:dict[str,Any],bundles:list[tuple],now:datetime)->list[dict[str,Any]]:
    """Scheduler-only READY resolution; interactive admission is checked before discovery."""
    if not scheduler_admission_allowed(execution_mode,now=now):
        return []
    return ready_tasks(registry,bundles,now)

def scheduler_claimed_execution_ready(execution_mode:dict[str,Any],state:dict[str,Any],request:dict[str,Any],gateway_lease:dict[str,Any],*,now:datetime)->bool:
    """Scheduler-only Phase-B admission; a fresh interactive carrier blocks target reinstantiation."""
    if not scheduler_admission_allowed(execution_mode,now=now):
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

def broker_generation_to_arm(wake:dict[str,Any],execution_mode:dict[str,Any],*,now:datetime,stale_after_minutes:int)->int|None:
    """Return the wake generation the Broker may schedule, after deterministic execution-mode admission."""
    validate_wake_state(wake)
    if not scheduler_admission_allowed(execution_mode,now=now):
        return None
    if wake["desired_generation"]>wake["armed_generation"]:
        return wake["desired_generation"]
    if stale_armed_wake(wake,now=now,stale_after_minutes=stale_after_minutes):
        return wake["armed_generation"]
    return None


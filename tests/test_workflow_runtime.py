import copy, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import control_plane as cp
import workflow_runtime as wr
NOW=datetime(2026,9,23,0,0,tzinfo=timezone.utc)

def harden_agent_task(r,issuer,target,mode="bounded_delegation",parent=None,depth=1,allowed=None,forbidden=None,subdelegation="bounded"):
 r["issuer_agent_id"]=issuer
 r["target_agent_id"]=target
 r["authority_basis"]={
  "kind":"owner-directive","reference":"OWNER-ROOT",
  "grant":{
   "allowed_effects":["read","write"],
   "forbidden_effects":["release"],
   "scope":["test"],
   "inherited_constraints":["no-release"],
   "subdelegation":"bounded"
  }
 }
 r["scope"]=["test"]
 r["parent_task_id"]=parent
 execution_constraints=["runtime:separate-target"]
 if mode=="bounded_delegation":
  execution_constraints.append("continuation:manual-pull")
 r["constraints"]=list(dict.fromkeys((r.get("constraints") or [])+["no-release"]+execution_constraints))
 r["responsibility"]={
  "semantics_version":2,
  "mode":mode,
  "caller_agent_id":issuer,
  "commitment_owner_agent_id":issuer,
  "proposed_commitment_owner_agent_id":target if mode=="explicit_handoff" else None,
  "return_to_agent_id":issuer if mode=="bounded_delegation" else None,
  "transfer_requires_target_acceptance":mode=="explicit_handoff",
  "authority_chain":{
   "root":{"kind":"owner-directive","reference":"OWNER-ROOT"},
   "immediate_grantor_agent_id":issuer,
   "grant_reference":"GRANT-"+r["task_id"],
   "delegation_depth":depth,
   "parent_task_id":parent,
   "allowed_effects":allowed or ["read","write"],
   "forbidden_effects":forbidden or ["release"],
   "subdelegation":subdelegation
  }
 }
 return r

def registry(auto=True,ids=("agent-a",)):
 return {"schema_version":1,"agents":[{"agent_id":x,"agent_type":"service-agent","role":"Tester","home_repository":f"o/{x}","authority_ref":"main","entrypoint":".context/ENTRYPOINT.md","status":"ready","automatic_execution_allowed":auto} for x in ids]}

def request(task_id,target="agent-a",deps=None,max_attempts=3):
 return {"schema_version":1,"task_id":task_id,"issuer_agent_id":"owner","target_agent_id":target,"objective":task_id,"authority_basis":{"kind":"owner-directive"},"scope":["test"],"constraints":[],"target":{"repository":"o/r","ref":"main"},"priority":"normal","dependencies":[{"task_id":d,"relation":"depends_on"} for d in (deps or [])],"completion_contract":{"required_evidence":[{"kind":"commit","minimum":1}]},"created_at":"2026-09-01T00:00:00Z","retry_policy":{"max_attempts":max_attempts,"backoff_minutes":[0,15,60],"quarantine_on_exhaustion":True}}

def state(r,status="queued"):
 return {"schema_version":1,"task_id":r["task_id"],"status":status,"request_digest":cp.request_digest(r),"request_blob_sha":"a"*40,"attempt":0,"runtime_loss_count":0,"claim":None,"latest_checkpoint":None}

def idle(g=0):
 return {"schema_version":1,"state":"idle","generation":g,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,"claimed_at":None,"lease_until":None}

def gate(r,status="waiting"):
 return {"schema_version":1,"gate_id":"G1","task_id":r["task_id"],"gate_type":"owner_decision","status":status,"required_actor_id":"owner","requested_at":"2026-09-22T00:00:00Z","resolved_at":"2026-09-22T01:00:00Z" if status=="satisfied" else None,"resolution":{"decision":"approved"} if status=="satisfied" else None}

def result(task_id,kind="commit",req=None,execution_id="e1",generation=1):
 r=req or request(task_id)
 return {"schema_version":1,"task_id":task_id,"request_digest":cp.request_digest(r),"request_blob_sha":"a"*40,"execution_id":execution_id,"generation":generation,"outcome":"success","summary":"done","evidence":[{"kind":kind,"reference":"o/r@abc","verified":True,"verified_by":"ecosystem-supervisor","verified_at":"2026-09-23T00:30:00Z"}],"completed_at":"2026-09-23T00:30:00Z"}

class WorkflowRuntimeTests(unittest.TestCase):
 def test_gate_blocks_then_owner_resolves(self):
  r=request("A"); s=state(r); g=gate(r)
  self.assertEqual(wr.ready_tasks(registry(),[(r,s,[g],wr.task_runtime("A"))],NOW),[])
  with self.assertRaises(cp.ControlPlaneError): wr.resolve_gate(g,r,actor_id="agent-a",resolution={"decision":"yes"},now=NOW)
  g=wr.resolve_gate(g,r,actor_id="owner",resolution={"decision":"yes"},now=NOW)
  self.assertEqual([x["task_id"] for x in wr.ready_tasks(registry(),[(r,s,[g],wr.task_runtime("A"))],NOW)],["A"])

 def test_failure_backoff_and_quarantine(self):
  r=request("A",max_attempts=2); s=state(r); m=wr.task_runtime("A")
  l,s=cp.claim_plan(idle(),r,s,slot_id="s",execution_id="e1",now=NOW); s=cp.activate_state(s,r,l)
  l,s,m=wr.record_failure(l,s,r,m,error_class="tool",summary="temporary",now=NOW)
  self.assertEqual((s["status"],m["failure_count"]),("queued",1))
  l,s=cp.claim_plan(l,r,s,slot_id="s",execution_id="e2",now=NOW); s=cp.activate_state(s,r,l)
  l,s,m=wr.record_failure(l,s,r,m,error_class="tool",summary="again",now=NOW)
  self.assertEqual((s["status"],m["failure_count"],l["state"]),("quarantined",2,"idle"))

 def test_retry_not_before_filters_ready(self):
  r=request("A"); s=state(r); m=wr.task_runtime("A"); m["retry_not_before"]="2026-09-23T01:00:00Z"
  self.assertEqual(wr.ready_tasks(registry(),[(r,s,[],m)],NOW),[])

 def test_invocation_points_to_same_persistent_agent(self):
  r=request("A"); l,s=cp.claim_plan(idle(),r,state(r),slot_id="s",execution_id="e1",now=NOW)
  inv=wr.build_invocation(registry(),r,s,l)
  self.assertEqual((inv["agent_id"],inv["home_repository"],inv["authority_ref"]),("agent-a","o/agent-a","main"))
  self.assertIn("can only narrow",inv["authority_rule"])
  self.assertIn("authority_basis",inv)
  self.assertIn("responsibility",inv)

 def test_completion_requires_verified_contract_evidence(self):
  r=request("A"); l,s=cp.claim_plan(idle(),r,state(r),slot_id="s",execution_id="e1",now=NOW); s=cp.activate_state(s,r,l)
  with self.assertRaises(cp.ControlPlaneError): wr.complete_task(l,s,r,[],result("A","report",req=r))
  l,s=wr.complete_task(l,s,r,[],result("A",req=r))
  self.assertEqual((l["state"],s["status"]),("idle","completed"))

 def test_unsatisfied_gate_blocks_completion(self):
  r=request("A"); l,s=cp.claim_plan(idle(),r,state(r),slot_id="s",execution_id="e1",now=NOW); s=cp.activate_state(s,r,l)
  with self.assertRaises(cp.ControlPlaneError): wr.complete_task(l,s,r,[gate(r)],result("A",req=r))

 def test_result_projection_repair_prevents_duplicate_execution(self):
  r=request("A"); s=state(r); res=result("A",req=r,execution_id="old-exec",generation=7)
  repaired=wr.repair_completed_projection(idle(8),s,r,[],res)
  self.assertEqual(repaired["status"],"completed")
  self.assertEqual(wr.ready_tasks(registry(),[(r,repaired,[],wr.task_runtime("A"))],NOW),[])

 def test_result_blob_mismatch_is_rejected(self):
  r=request("A"); s=state(r); res=result("A",req=r); res["request_blob_sha"]="b"*40
  with self.assertRaises(cp.ControlPlaneError): wr.repair_completed_projection(idle(2),s,r,[],res)

 def test_result_digest_mismatch_is_rejected(self):
  r=request("A"); res=result("A",req=r); res["request_digest"]="sha256:"+"0"*64
  with self.assertRaises(cp.ControlPlaneError): wr.completion_satisfied(r,res)

 def test_completion_unblocks_dependency(self):
  a=request("A"); b=request("B",deps=["A"])
  self.assertEqual(wr.newly_ready_after_completion(registry(),[(a,state(a,"active"),[],wr.task_runtime("A")),(b,state(b),[],wr.task_runtime("B"))],"A",NOW),["B"])

 def test_three_agent_sandbox_workflow(self):
  reg=registry(True,("pm","auditor","supervisor"))
  a=request("A","pm"); b=request("B","auditor",["A"]); c=request("C","supervisor",["B"])
  ga=wr.resolve_gate(gate(a),a,actor_id="owner",resolution={"decision":"approved"},now=NOW)
  sa,sb,sc=state(a),state(b),state(c); ma,mb,mc=wr.task_runtime("A"),wr.task_runtime("B"),wr.task_runtime("C")
  self.assertEqual([x["task_id"] for x in wr.ready_tasks(reg,[(a,sa,[ga],ma),(b,sb,[],mb),(c,sc,[],mc)],NOW)],["A"])
  l,sa=cp.claim_plan(idle(),a,sa,slot_id="1",execution_id="a1",now=NOW); sa=cp.activate_state(sa,a,l)
  l,sa=cp.recover_expired_plan(l,sa,a,now=datetime(2026,9,23,1,0,tzinfo=timezone.utc))
  self.assertFalse(cp.fence_valid(l,task_id="A",agent_id="pm",execution_id="a1",generation=1))
  l,sa=cp.claim_plan(l,a,sa,slot_id="2",execution_id="a2",now=datetime(2026,9,23,1,1,tzinfo=timezone.utc)); sa=cp.activate_state(sa,a,l); l,sa=wr.complete_task(l,sa,a,[ga],result("A",req=a,execution_id="a2",generation=3))
  self.assertEqual([x["task_id"] for x in wr.ready_tasks(reg,[(a,sa,[ga],ma),(b,sb,[],mb),(c,sc,[],mc)],NOW)],["B"])
  l,sb=cp.claim_plan(l,b,sb,slot_id="3",execution_id="b1",now=NOW); sb=cp.activate_state(sb,b,l); l,sb=wr.complete_task(l,sb,b,[],result("B",req=b,execution_id="b1",generation=5))
  l,sc=cp.claim_plan(l,c,sc,slot_id="4",execution_id="c1",now=NOW); sc=cp.activate_state(sc,c,l); l,sc=wr.complete_task(l,sc,c,[],result("C",req=c,execution_id="c1",generation=7))
  self.assertEqual((sa["status"],sb["status"],sc["status"],l["state"]),("completed","completed","completed","idle"))

 def test_owner_can_route_directly_to_project_manager_without_supervisor(self):
  reg={"schema_version":1,"agents":[
   {"agent_id":"pm","agent_type":"project-manager","role":"PM","home_repository":"o/p","authority_ref":"main","entrypoint":".context/ENTRYPOINT.md","status":"ready","automatic_execution_allowed":True},
   {"agent_id":"ecosystem-supervisor","agent_type":"service-agent","role":"Supervisor","home_repository":"o/s","authority_ref":"main","entrypoint":".context/ENTRYPOINT.md","status":"ready","automatic_execution_allowed":False}]}
  r=request("DIRECT","pm"); r["issuer_agent_id"]="owner"
  self.assertEqual([x["task_id"] for x in wr.ready_tasks(reg,[(r,state(r),[],wr.task_runtime("DIRECT"))],NOW)],["DIRECT"])

 def test_project_manager_can_route_directly_to_auditor(self):
  reg={"schema_version":1,"agents":[
   {"agent_id":"pm","agent_type":"project-manager","role":"PM","home_repository":"o/p","authority_ref":"main","entrypoint":".context/ENTRYPOINT.md","status":"ready","automatic_execution_allowed":True},
   {"agent_id":"auditor","agent_type":"service-agent","role":"Auditor","home_repository":"o/a","authority_ref":"main","entrypoint":".context/ENTRYPOINT.md","status":"ready","automatic_execution_allowed":True}]}
  r=harden_agent_task(request("AUD","auditor"),"pm","auditor")
  self.assertEqual([x["task_id"] for x in wr.ready_tasks(reg,[(r,state(r),[],wr.task_runtime("AUD"))],NOW)],["AUD"])

 def test_unknown_agent_issuer_is_rejected(self):
  r=request("BAD"); r["issuer_agent_id"]="unknown"; r["authority_basis"]={"kind":"engagement","reference":"ENG-X"}
  with self.assertRaises(cp.ControlPlaneError):
   wr.ready_tasks(registry(),[(r,state(r),[],wr.task_runtime("BAD"))],NOW)

 def test_reserved_gateway_never_admits_target_write(self):
  r=request("F"); s=state(r,"claimed")
  s["claim"]={"execution_id":"e1","generation":9,"slot_id":"dispatcher-00","claimed_at":"2026-09-23T00:00:00Z","activation_projection_blob_sha":"b"*40}
  lease={"state":"reserved","generation":9,"execution_id":"e1","task_id":"F","agent_id":"agent-a","slot_id":"dispatcher-00","request_blob_sha":"a"*40,"activation_projection_blob_sha":None}
  self.assertFalse(wr.claimed_execution_ready(s,r,lease))
  s["status"]="active"
  self.assertFalse(wr.gateway_execution_admitted(s,r,lease))

 def test_active_gateway_requires_matching_activation_receipt(self):
  r=request("F"); s=state(r,"claimed")
  s["claim"]={"execution_id":"e1","generation":9,"slot_id":"dispatcher-00","claimed_at":"2026-09-23T00:00:00Z","activation_projection_blob_sha":"b"*40}
  lease={"state":"active","generation":9,"execution_id":"e1","task_id":"F","agent_id":"agent-a","slot_id":"dispatcher-00","request_blob_sha":"a"*40,"activation_projection_blob_sha":"b"*40}
  self.assertTrue(wr.claimed_execution_ready(s,r,lease))
  s["status"]="active"
  self.assertTrue(wr.gateway_execution_admitted(s,r,lease))
  bad=dict(lease); bad["activation_projection_blob_sha"]="c"*40
  self.assertFalse(wr.gateway_execution_admitted(s,r,bad))

 def test_active_state_without_activation_receipt_is_never_admitted(self):
  r=request("F"); s=state(r,"active")
  s["claim"]={"execution_id":"e1","generation":9,"slot_id":"dispatcher-00","claimed_at":"2026-09-23T00:00:00Z"}
  lease={"state":"active","generation":9,"execution_id":"e1","task_id":"F","agent_id":"agent-a","slot_id":"dispatcher-00","request_blob_sha":"a"*40,"activation_projection_blob_sha":"b"*40}
  self.assertFalse(wr.gateway_execution_admitted(s,r,lease))


 def test_new_agent_task_requires_hardened_responsibility_but_completed_legacy_is_readable(self):
  reg=registry(True,("pm","auditor"))
  legacy=request("LEGACY-ROUTE","auditor")
  legacy["issuer_agent_id"]="pm"
  legacy["authority_basis"]={"kind":"engagement","reference":"OLD"}
  legacy["responsibility"]={
   "mode":"bounded_delegation",
   "commitment_owner_agent_id":"pm",
   "return_to_agent_id":"pm"
  }
  with self.assertRaises(cp.ControlPlaneError):
   wr.ready_tasks(reg,[(legacy,state(legacy),[],wr.task_runtime("LEGACY-ROUTE"))],NOW)
  claimed=state(legacy,"claimed"); claimed["claim"]={"execution_id":"e1","generation":1,"slot_id":"s","claimed_at":"2026-09-23T00:00:00Z"}
  with self.assertRaises(cp.ControlPlaneError):
   wr.validate_task_routing(reg,legacy,claimed)
  self.assertEqual(
   wr.ready_tasks(reg,[(legacy,state(legacy,"completed"),[],wr.task_runtime("LEGACY-ROUTE"))],NOW),
   []
  )

 def test_new_inter_agent_task_requires_fixed_runtime_constraints(self):
  reg=registry(True,("pm","auditor"))
  r=harden_agent_task(request("FIXED-RUNTIME","auditor"),"pm","auditor")
  r["constraints"].remove("runtime:separate-target")
  s=state(r)
  with self.assertRaises(cp.ControlPlaneError):
   wr.validate_task_routing(reg,r,s)

 def test_same_agent_scheduled_work_requires_caller_continuation(self):
  reg=registry(True,("supervisor",))
  r=request("CALLER-CONTINUE","supervisor",deps=["CHILD"])
  r["issuer_agent_id"]="supervisor"
  r["authority_basis"]={"kind":"owner-directive","reference":"OWNER-ROOT"}
  r["constraints"]=["runtime:caller-continuation"]
  wr.validate_task_routing(reg,r,state(r))
  bad=copy.deepcopy(r); bad["constraints"]=[]
  with self.assertRaises(cp.ControlPlaneError):
   wr.validate_task_routing(reg,bad,state(bad))

 def test_invocation_carries_hardened_authority_and_responsibility(self):
  reg=registry(True,("pm","auditor"))
  r=harden_agent_task(request("INV-V2","auditor"),"pm","auditor")
  s=state(r)
  l,s=cp.claim_plan(idle(),r,s,slot_id="s",execution_id="e1",now=NOW)
  inv=wr.build_invocation(reg,r,s,l)
  self.assertEqual(inv["responsibility"]["semantics_version"],2)
  self.assertEqual(inv["authority_basis"],r["authority_basis"])
  self.assertEqual(inv["constraints"],r["constraints"])
  self.assertIn("acceptance", " ".join(inv["required_sequence"]))

 def _acceptance_source(self,reg,r,*,repo=None,ref=None,commit=None,path=None,record_mutator=None):
  target=cp.registry_index(reg)[r["target_agent_id"]]
  record={
   "schema":"context-capsule-responsibility-acceptance","schema_version":1,
   "record_id":"ACC-"+r["task_id"],"task_id":r["task_id"],"request_digest":cp.request_digest(r),
   "accepted_by_agent_id":r["target_agent_id"],"commitment_owner_agent_id":r["target_agent_id"],
   "accepted_at":"2026-09-23T00:01:00Z"
  }
  if record_mutator: record_mutator(record)
  content=__import__("json").dumps(record,sort_keys=True,separators=(",",":"))+"\n"
  source={
   "repository":repo or target["home_repository"],"authority_ref":ref or target["authority_ref"],
   "commit_sha":commit or "c"*40,
   "path":path or f".context/responsibility/acceptances/{r['task_id']}.json",
   "blob_sha":wr._git_blob_sha(content),"record_id":record["record_id"]
  }
  def reader(repository,authority_ref,commit_sha,record_path):
   return {"commit_sha":source["commit_sha"],"blob_sha":source["blob_sha"],"content":content}
  return source,reader

 def _autonomous_handoff_fence(self,r,s):
  s["claim"]["activation_projection_blob_sha"]="b"*40
  gateway={
   "state":"active","generation":s["claim"]["generation"],"execution_id":s["claim"]["execution_id"],
   "task_id":r["task_id"],"agent_id":r["target_agent_id"],"slot_id":s["claim"]["slot_id"],
   "request_blob_sha":s["request_blob_sha"],"activation_projection_blob_sha":"b"*40
  }
  return gateway

 def test_explicit_handoff_requires_verified_target_home_acceptance_before_activation(self):
  reg=registry(True,("manager","specialist"))
  r=harden_agent_task(request("HANDOFF-A","specialist"),"manager","specialist",mode="explicit_handoff")
  s=state(r)
  l,s=cp.claim_plan(idle(),r,s,slot_id="s",execution_id="e1",now=NOW)
  with self.assertRaises(cp.ControlPlaneError):
   cp.activate_state(s,r,l,registry=reg)
  gateway=self._autonomous_handoff_fence(r,s)
  source,reader=self._acceptance_source(reg,r)
  accepted=wr.record_handoff_acceptance(
   reg,s,r,gateway,agent_id="specialist",source=source,authoritative_reader=reader,now=NOW
  )
  active=cp.activate_state(accepted,r,l,registry=reg)
  self.assertEqual(active["status"],"active")
  self.assertTrue(wr.handoff_acceptance_satisfied(active,r,reg))
  self.assertEqual(active["responsibility_acceptance"]["source"]["commit_sha"],"c"*40)

 def test_handoff_acceptance_rejects_wrong_agent_home_or_fabricated_source(self):
  reg=registry(True,("manager","specialist"))
  r=harden_agent_task(request("HANDOFF-B","specialist"),"manager","specialist",mode="explicit_handoff")
  s=state(r); l,s=cp.claim_plan(idle(),r,s,slot_id="s",execution_id="e1",now=NOW)
  gateway=self._autonomous_handoff_fence(r,s)
  source,reader=self._acceptance_source(reg,r)
  with self.assertRaises(cp.ControlPlaneError):
   wr.record_handoff_acceptance(reg,s,r,gateway,agent_id="manager",source=source,authoritative_reader=reader,now=NOW)
  wrong_repo,bad_reader=self._acceptance_source(reg,r,repo="o/not-specialist")
  with self.assertRaises(cp.ControlPlaneError):
   wr.record_handoff_acceptance(reg,s,r,gateway,agent_id="specialist",source=wrong_repo,authoritative_reader=bad_reader,now=NOW)
  bad_source,reader2=self._acceptance_source(reg,r,path=".context/other/fake.json")
  with self.assertRaises(cp.ControlPlaneError):
   wr.record_handoff_acceptance(reg,s,r,gateway,agent_id="specialist",source=bad_source,authoritative_reader=reader2,now=NOW)
  mismatch,reader3=self._acceptance_source(reg,r)
  mismatch["blob_sha"]="d"*40
  with self.assertRaises(cp.ControlPlaneError):
   wr.record_handoff_acceptance(reg,s,r,gateway,agent_id="specialist",source=mismatch,authoritative_reader=reader3,now=NOW)

 def test_handoff_acceptance_rejects_stale_autonomous_fence(self):
  reg=registry(True,("manager","specialist"))
  r=harden_agent_task(request("HANDOFF-STALE","specialist"),"manager","specialist",mode="explicit_handoff")
  s=state(r); l,s=cp.claim_plan(idle(),r,s,slot_id="s",execution_id="e1",now=NOW)
  gateway=self._autonomous_handoff_fence(r,s); gateway["generation"]+=1
  source,reader=self._acceptance_source(reg,r)
  with self.assertRaises(cp.ControlPlaneError):
   wr.record_handoff_acceptance(reg,s,r,gateway,agent_id="specialist",source=source,authoritative_reader=reader,now=NOW)

 def test_cross_agent_handoff_cannot_use_live_carrier(self):
  r=harden_agent_task(request("HANDOFF-LIVE","specialist"),"manager","specialist",mode="explicit_handoff")
  with self.assertRaises(cp.ControlPlaneError):
   wr.set_live_task_carrier(
    state(r),r,carrier_id="live-handoff",set_by="manager",reason="handoff",now=NOW,lease_minutes=45
   )

 def test_bounded_delegation_does_not_use_handoff_acceptance_receipt(self):
  reg=registry(True,("manager","auditor"))
  r=harden_agent_task(request("DELEG-NO-ACCEPT","auditor"),"manager","auditor")
  source,reader=self._acceptance_source(reg,r)
  with self.assertRaises(cp.ControlPlaneError):
   wr.record_handoff_acceptance(reg,state(r),r,{"state":"idle"},agent_id="auditor",source=source,authoritative_reader=reader,now=NOW)

class LiveReturnTests(unittest.TestCase):
 def live_result(self,r,carrier_id="live-caller"):
  return {
   "schema_version":1,"task_id":r["task_id"],"request_digest":cp.request_digest(r),
   "request_blob_sha":"a"*40,"execution_mode":"live","carrier_id":carrier_id,
   "outcome":"success","summary":"done",
   "evidence":[{"kind":"commit","reference":"o/r@abc","verified":True,"verified_by":"agent-a","verified_at":"2026-09-23T00:30:00Z"}],
   "completed_at":"2026-09-23T00:30:00Z"
  }

 def delegated(self,task_id,issuer,target,parent=None,workflow="WF-LIVE",fixed=True):
  r=harden_agent_task(request(task_id,target),issuer,target,parent=parent,depth=2 if parent else 1)
  r["workflow_id"]=workflow
  if not fixed:
   r["constraints"]=[x for x in r["constraints"] if x not in {"runtime:separate-target","continuation:manual-pull","continuation:automatic-new-runtime"}]
  return r

 def live_state(self,r,carrier_id="live-caller"):
  s=state(r)
  s["carrier"]={
   "mode":"live","carrier_id":carrier_id,"set_by":r["issuer_agent_id"],"reason":"historical delegation",
   "heartbeat_at":"2026-09-23T00:00:00Z","lease_until":"2026-09-23T01:00:00Z","fallback_after_expiry":True
  }
  return s

 def idle_gateway(self):
  return {"state":"idle","generation":46,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None}

 def repaired_historical(self,r):
  return wr.repair_expired_live_completion(
   self.live_state(r),r,[],self.live_result(r),
   result_committed_at=datetime(2026,9,23,0,30,tzinfo=timezone.utc),
   now=datetime(2026,9,23,1,1,tzinfo=timezone.utc)
  )

 def test_new_inter_agent_task_cannot_acquire_live_carrier(self):
  r=self.delegated("AUD-NEW","supervisor","auditor",fixed=True)
  with self.assertRaises(cp.ControlPlaneError):
   wr.set_live_task_carrier(
    state(r),r,carrier_id="live-caller",set_by="supervisor",reason="delegation",
    now=datetime(2026,9,23,0,0,tzinfo=timezone.utc)
   )

 def test_new_inter_agent_direct_live_completion_is_rejected(self):
  reg=registry(True,("supervisor","auditor"))
  r=self.delegated("AUD-COMPLETE","supervisor","auditor",fixed=True)
  with self.assertRaises(cp.ControlPlaneError):
   wr.complete_live_delegation(
    reg,self.live_state(r),r,[],self.live_result(r),self.idle_gateway(),
    carrier_id="live-caller",now=datetime(2026,9,23,0,30,tzinfo=timezone.utc)
   )

 def test_same_runtime_return_api_fails_closed(self):
  reg=registry(True,("supervisor","auditor"))
  r=self.delegated("AUD-OLD","supervisor","auditor",fixed=False)
  repaired=self.repaired_historical(r)
  self.assertIsNotNone(repaired)
  with self.assertRaises(cp.ControlPlaneError):
   wr.build_live_return_package(
    reg,r,repaired,self.live_result(r),now=datetime(2026,9,23,0,45,tzinfo=timezone.utc)
   )

 def test_historical_partial_live_completion_repairs_and_recovers_in_new_runtime(self):
  reg=registry(True,("supervisor","auditor"))
  r=self.delegated("AUD-PARTIAL","supervisor","auditor",fixed=False)
  repaired=self.repaired_historical(r)
  self.assertIsNotNone(repaired)
  self.assertEqual(repaired["status"],"completed")
  self.assertIsNone(repaired["carrier"])
  self.assertEqual(repaired["continuation"]["status"],"pending")
  packages=wr.recoverable_return_continuations(
   reg,[(r,repaired,[],wr.task_runtime(r["task_id"]))],{r["task_id"]:self.live_result(r)},
   datetime(2026,9,23,1,1,tzinfo=timezone.utc)
  )
  self.assertEqual(len(packages),1)
  self.assertEqual(packages[0]["agent_id"],"supervisor")
  self.assertEqual(packages[0]["delivery_mode"],"autonomous_recovery")
  self.assertIn("fresh Worker runtime",packages[0]["required_sequence"][0])

 def test_historical_pending_return_not_recovered_before_live_lease_expiry(self):
  reg=registry(True,("supervisor","auditor"))
  r=self.delegated("AUD-LIVE","supervisor","auditor",fixed=False)
  s=self.live_state(r)
  s["continuation"]=wr._pending_return_continuation(r,s,s["carrier"])
  s["status"]="completed"; s["carrier"]=None
  packages=wr.recoverable_return_continuations(
   reg,[(r,s,[],wr.task_runtime(r["task_id"]))],{r["task_id"]:self.live_result(r)},
   datetime(2026,9,23,0,45,tzinfo=timezone.utc)
  )
  self.assertEqual(packages,[])

 def test_consumed_historical_return_is_not_redelivered(self):
  reg=registry(True,("supervisor","auditor"))
  r=self.delegated("AUD-DONE","supervisor","auditor",fixed=False)
  repaired=self.repaired_historical(r)
  continuation_id=repaired["continuation"]["continuation_id"]
  consumed=wr.acknowledge_return_continuation(
   repaired,r,self.live_result(r),continuation_id=continuation_id,caller_agent_id="supervisor",
   now=datetime(2026,9,23,1,2,tzinfo=timezone.utc)
  )
  packages=wr.recoverable_return_continuations(
   reg,[(r,consumed,[],wr.task_runtime(r["task_id"]))],{r["task_id"]:self.live_result(r)},
   datetime(2026,9,23,1,3,tzinfo=timezone.utc)
  )
  self.assertEqual(packages,[])

 def test_historical_recovery_with_mismatched_result_fails_closed(self):
  reg=registry(True,("supervisor","auditor"))
  r=self.delegated("AUD-BAD","supervisor","auditor",fixed=False)
  repaired=self.repaired_historical(r)
  bad=self.live_result(r,carrier_id="other-carrier")
  with self.assertRaises(cp.ControlPlaneError):
   wr.recoverable_return_continuations(
    reg,[(r,repaired,[],wr.task_runtime(r["task_id"]))],{r["task_id"]:bad},
    datetime(2026,9,23,1,1,tzinfo=timezone.utc)
   )

 def test_explicit_handoff_has_no_return_continuation(self):
  reg=registry(True,("manager","specialist"))
  r=harden_agent_task(request("H","specialist"),"manager","specialist",mode="explicit_handoff")
  s=state(r,"completed"); s["continuation"]=None
  self.assertIsNone(wr.build_live_return_package(
   reg,r,s,self.live_result(r),now=datetime(2026,9,23,0,30,tzinfo=timezone.utc)
  ))


class TaskCarrierTests(unittest.TestCase):
 def live_state(self,task_id="A",lease_until="2026-09-23T00:30:00Z"):
  r=request(task_id); s=state(r)
  s["carrier"]={
   "mode":"live","carrier_id":"owner-live-runtime-test","set_by":"owner",
   "reason":"live owner chain","heartbeat_at":"2026-09-23T00:00:00Z",
   "lease_until":lease_until,"fallback_after_expiry":True
  }
  return r,s

 def idle_gateway(self):
  return {"state":"idle","generation":46,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None}

 def live_result(self,r,s,carrier_id="owner-live-runtime-test"):
  return {
   "schema_version":1,"task_id":r["task_id"],"request_digest":cp.request_digest(r),
   "request_blob_sha":s["request_blob_sha"],"execution_mode":"live","carrier_id":carrier_id,
   "outcome":"success","summary":"done",
   "evidence":[{"kind":"commit","reference":"live-result-commit","verified":True,"verified_by":"agent-a","verified_at":"2026-09-23T00:04:00Z"}],
   "completed_at":"2026-09-23T00:04:00Z"
  }

 def test_live_carrier_blocks_only_its_task(self):
  a,sa=self.live_state("A")
  b=request("B"); sb=state(b)
  ready=wr.scheduler_ready_tasks(registry(),[(a,sa,[],wr.task_runtime("A")),(b,sb,[],wr.task_runtime("B"))],NOW)
  self.assertEqual([x["task_id"] for x in ready],["B"])

 def test_expired_live_carrier_requires_result_aware_preflight(self):
  a,sa=self.live_state("A","2026-09-23T00:05:00Z")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  with self.assertRaises(cp.ControlPlaneError):
   wr.scheduler_ready_tasks(registry(),[(a,sa,[],wr.task_runtime("A"))],later)

 def test_expired_live_carrier_without_result_allows_autonomous_fallback(self):
  a,sa=self.live_state("A","2026-09-23T00:05:00Z")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  ready,repairs=wr.scheduler_preflight(
   registry(),[(a,sa,[],wr.task_runtime("A"))],{"A":None},later
  )
  self.assertEqual([x["task_id"] for x in ready],["A"])
  self.assertEqual(repairs,[])

 def test_durable_live_result_repairs_partial_completion_before_fallback(self):
  a,sa=self.live_state("A","2026-09-23T00:05:00Z")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  record={"result":self.live_result(a,sa),"committed_at":datetime(2026,9,23,0,4,tzinfo=timezone.utc)}
  ready,repairs=wr.scheduler_preflight(
   registry(),[(a,sa,[],wr.task_runtime("A"))],{"A":record},later
  )
  self.assertEqual(ready,[])
  self.assertEqual(len(repairs),1)
  task_id,repaired=repairs[0]
  self.assertEqual(task_id,"A")
  self.assertEqual(repaired["status"],"completed")
  self.assertIsNone(repaired["claim"])
  self.assertIsNone(repaired["carrier"])

 def test_mismatched_live_result_does_not_suppress_legitimate_fallback(self):
  a,sa=self.live_state("A","2026-09-23T00:05:00Z")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  bad=self.live_result(a,sa,carrier_id="other-live-runtime")
  ready,repairs=wr.scheduler_preflight(
   registry(),[(a,sa,[],wr.task_runtime("A"))],
   {"A":{"result":bad,"committed_at":datetime(2026,9,23,0,4,tzinfo=timezone.utc)}},later
  )
  self.assertEqual([x["task_id"] for x in ready],["A"])
  self.assertEqual(repairs,[])

 def test_late_live_result_does_not_suppress_legitimate_fallback(self):
  a,sa=self.live_state("A","2026-09-23T00:05:00Z")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  ready,repairs=wr.scheduler_preflight(
   registry(),[(a,sa,[],wr.task_runtime("A"))],
   {"A":{"result":self.live_result(a,sa),"committed_at":datetime(2026,9,23,0,6,tzinfo=timezone.utc)}},later
  )
  self.assertEqual([x["task_id"] for x in ready],["A"])
  self.assertEqual(repairs,[])

 def test_present_live_result_without_commit_time_fails_closed(self):
  a,sa=self.live_state("A","2026-09-23T00:05:00Z")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  with self.assertRaises(cp.ControlPlaneError):
   wr.scheduler_preflight(
    registry(),[(a,sa,[],wr.task_runtime("A"))],
    {"A":{"result":self.live_result(a,sa),"committed_at":None}},later
   )

 def test_hold_blocks_only_its_task_without_expiry(self):
  a=request("A"); sa=state(a)
  sa["carrier"]={
   "mode":"hold","carrier_id":"owner-hold-A","set_by":"owner","reason":"pause task A",
   "heartbeat_at":None,"lease_until":None,"fallback_after_expiry":False
  }
  b=request("B"); sb=state(b)
  ready=wr.scheduler_ready_tasks(registry(),[(a,sa,[],wr.task_runtime("A")),(b,sb,[],wr.task_runtime("B"))],datetime(2027,1,1,tzinfo=timezone.utc))
  self.assertEqual([x["task_id"] for x in ready],["B"])

 def test_live_carrier_acquisition_is_same_state_projection_as_scheduler_claim(self):
  r=request("A"); s=state(r)
  acquired=wr.set_live_task_carrier(s,r,carrier_id="owner-live-runtime-test",set_by="owner",reason="live handoff",now=NOW,lease_minutes=45)
  self.assertEqual(acquired["status"],"queued")
  self.assertIsNone(acquired["claim"])
  self.assertEqual(acquired["carrier"]["carrier_id"],"owner-live-runtime-test")
  claimed=state(r,"claimed"); claimed["claim"]={"execution_id":"e1","generation":2,"slot_id":"execution-worker","claimed_at":"2026-09-23T00:00:00Z"}
  with self.assertRaises(cp.ControlPlaneError):
   wr.set_live_task_carrier(claimed,r,carrier_id="owner-live-runtime-test",set_by="owner",reason="too late",now=NOW)

 def test_live_carrier_can_be_renewed_by_same_carrier(self):
  r,s=self.live_state("A")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  renewed=wr.renew_live_task_carrier(s,r,carrier_id="owner-live-runtime-test",now=later,lease_minutes=45)
  self.assertEqual(renewed["carrier"]["heartbeat_at"],"2026-09-23T00:10:00Z")
  self.assertEqual(renewed["carrier"]["lease_until"],"2026-09-23T00:55:00Z")

 def test_other_carrier_cannot_renew(self):
  r,s=self.live_state("A")
  with self.assertRaises(cp.ControlPlaneError):
   wr.renew_live_task_carrier(s,r,carrier_id="other-runtime",now=NOW,lease_minutes=45)

 def test_claimed_phase_b_blocked_only_for_live_carried_task(self):
  r,s=self.live_state("F")
  s["status"]="claimed"
  s["claim"]={"execution_id":"e1","generation":9,"slot_id":"execution-worker","claimed_at":"2026-09-23T00:00:00Z","activation_projection_blob_sha":"b"*40}
  lease={"state":"active","generation":9,"execution_id":"e1","task_id":"F","agent_id":"agent-a","slot_id":"execution-worker","request_blob_sha":"a"*40,"activation_projection_blob_sha":"b"*40}
  self.assertFalse(wr.scheduler_claimed_execution_ready(s,r,lease,now=NOW))
  later=datetime(2026,9,23,0,31,tzinfo=timezone.utc)
  self.assertTrue(wr.scheduler_claimed_execution_ready(s,r,lease,now=later))

 def test_live_fence_rejects_same_task_gateway_ownership(self):
  r,s=self.live_state("A")
  gateway={"state":"reserved","task_id":"A"}
  self.assertFalse(wr.live_carrier_fence_valid(s,r,gateway,carrier_id="owner-live-runtime-test",now=NOW))

 def test_live_completion_terminalizes_before_expiry(self):
  r,s=self.live_state("A")
  result=self.live_result(r,s)
  completed=wr.complete_live_task(s,r,[],result,self.idle_gateway(),carrier_id="owner-live-runtime-test",now=datetime(2026,9,23,0,10,tzinfo=timezone.utc))
  self.assertEqual(completed["status"],"completed")
  self.assertIsNone(completed["carrier"])
  ready=wr.scheduler_ready_tasks(registry(),[(r,completed,[],wr.task_runtime("A"))],datetime(2026,9,23,1,0,tzinfo=timezone.utc))
  self.assertEqual(ready,[])

 def test_expired_live_carrier_cannot_complete(self):
  r,s=self.live_state("A","2026-09-23T00:05:00Z")
  later=datetime(2026,9,23,0,10,tzinfo=timezone.utc)
  with self.assertRaises(cp.ControlPlaneError):
   wr.complete_live_task(s,r,[],self.live_result(r,s),self.idle_gateway(),carrier_id="owner-live-runtime-test",now=later)


class EventWakeTests(unittest.TestCase):
 def wake(self):
  return {
   "desired_generation":0,
   "armed_generation":0,
   "served_generation":0,
   "recent_request_keys":[],
   "last_request":None,
   "last_armed_at":None,
   "last_served_at":None,
   "last_worker_run_id":None
  }

 def test_wake_request_is_replay_safe(self):
  w=self.wake()
  w,created=wr.request_wake(w,request_key="task-ready:A",reason="task-ready",requested_by="owner",now=NOW)
  self.assertTrue(created)
  self.assertEqual(w["desired_generation"],1)
  again,created=wr.request_wake(w,request_key="task-ready:A",reason="task-ready",requested_by="owner",now=NOW)
  self.assertFalse(created)
  self.assertEqual(again["desired_generation"],1)

 def test_wake_arm_and_serve_generations(self):
  w,_=wr.request_wake(self.wake(),request_key="phase-b:A:e1:9",reason="phase-b",requested_by="execution-worker",now=NOW)
  self.assertTrue(wr.wake_needs_arming(w))
  w=wr.mark_wake_armed(w,generation=1,now=NOW)
  self.assertFalse(wr.wake_needs_arming(w))
  self.assertTrue(wr.wake_pending(w))
  w=wr.mark_wake_served(w,generation=1,now=NOW,worker_run_id="run-1")
  self.assertFalse(wr.wake_pending(w))
  self.assertEqual(w["served_generation"],1)

 def test_stale_armed_wake_is_detected_for_watchdog(self):
  w,_=wr.request_wake(self.wake(),request_key="ready:B",reason="task-ready",requested_by="pm",now=NOW)
  w=wr.mark_wake_armed(w,generation=1,now=NOW)
  later=datetime(2026,9,23,0,21,tzinfo=timezone.utc)
  self.assertTrue(wr.stale_armed_wake(w,now=later,stale_after_minutes=20))
  w=wr.mark_wake_served(w,generation=1,now=later,worker_run_id="run-2")
  self.assertFalse(wr.stale_armed_wake(w,now=later,stale_after_minutes=20))

 def test_invalid_generation_transitions_are_rejected(self):
  w=self.wake()
  with self.assertRaises(cp.ControlPlaneError):
   wr.mark_wake_armed(w,generation=1,now=NOW)
  w,_=wr.request_wake(w,request_key="x",reason="ready",requested_by="owner",now=NOW)
  with self.assertRaises(cp.ControlPlaneError):
   wr.mark_wake_served(w,generation=1,now=NOW,worker_run_id="run-unarmed")
  w=wr.mark_wake_armed(w,generation=1,now=NOW)
  w,_=wr.request_wake(w,request_key="y",reason="newer-ready",requested_by="owner",now=NOW)
  self.assertEqual((w["desired_generation"],w["armed_generation"]),(2,1))
  with self.assertRaises(cp.ControlPlaneError):
   wr.mark_wake_served(w,generation=2,now=NOW,worker_run_id="run-too-new")


class BrokerRelayTests(unittest.TestCase):
 def wake(self):
  return {
   "desired_generation":0,
   "armed_generation":0,
   "served_generation":0,
   "recent_request_keys":[],
   "last_request":None,
   "last_armed_at":None,
   "last_served_at":None,
   "last_worker_run_id":None
  }

 def test_broker_arms_newest_unarmed_desired_generation(self):
  w,_=wr.request_wake(self.wake(),request_key="relay:new",reason="ready",requested_by="issuer",now=NOW)
  self.assertEqual(wr.broker_generation_to_arm(w,now=NOW,stale_after_minutes=20),1)

 def test_broker_rearms_same_stale_generation_without_increment(self):
  w,_=wr.request_wake(self.wake(),request_key="relay:stale",reason="ready",requested_by="issuer",now=NOW)
  w=wr.mark_wake_armed(w,generation=1,now=NOW)
  later=datetime(2026,9,23,0,21,tzinfo=timezone.utc)
  self.assertEqual(wr.broker_generation_to_arm(w,now=later,stale_after_minutes=20),1)
  self.assertEqual(w["desired_generation"],1)

 def test_broker_noops_after_generation_is_served(self):
  w,_=wr.request_wake(self.wake(),request_key="relay:done",reason="ready",requested_by="issuer",now=NOW)
  w=wr.mark_wake_armed(w,generation=1,now=NOW)
  w=wr.mark_wake_served(w,generation=1,now=NOW,worker_run_id="run-1")
  later=datetime(2026,9,23,0,30,tzinfo=timezone.utc)
  self.assertIsNone(wr.broker_generation_to_arm(w,now=later,stale_after_minutes=20))


if __name__=="__main__": unittest.main()

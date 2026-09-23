import sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import control_plane as cp
import workflow_runtime as wr
NOW=datetime(2026,9,23,0,0,tzinfo=timezone.utc)

def registry(auto=True,ids=("agent-a",)):
 return {"schema_version":1,"agents":[{"agent_id":x,"agent_type":"service-agent","role":"Tester","home_repository":f"o/{x}","authority_ref":"main","entrypoint":".context/ENTRYPOINT.md","status":"ready","automatic_execution_allowed":auto} for x in ids]}

def request(task_id,target="agent-a",deps=None,max_attempts=3):
 return {"schema_version":1,"task_id":task_id,"issuer_agent_id":"owner","target_agent_id":target,"objective":task_id,"authority_basis":{"kind":"owner-directive"},"scope":["test"],"constraints":[],"target":{"repository":"o/r","ref":"main"},"priority":"normal","dependencies":[{"task_id":d,"relation":"depends_on"} for d in (deps or [])],"completion_contract":{"required_evidence":[{"kind":"commit","minimum":1}]},"created_at":"2026-09-01T00:00:00Z","retry_policy":{"max_attempts":max_attempts,"backoff_minutes":[0,15,60],"quarantine_on_exhaustion":True}}

def state(r,status="queued"):
 return {"schema_version":1,"task_id":r["task_id"],"status":status,"request_digest":cp.request_digest(r),"attempt":0,"runtime_loss_count":0,"claim":None,"latest_checkpoint":None}

def idle(g=0):
 return {"schema_version":1,"state":"idle","generation":g,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,"claimed_at":None,"lease_until":None}

def gate(r,status="waiting"):
 return {"schema_version":1,"gate_id":"G1","task_id":r["task_id"],"gate_type":"owner_decision","status":status,"required_actor_id":"owner","requested_at":"2026-09-22T00:00:00Z","resolved_at":"2026-09-22T01:00:00Z" if status=="satisfied" else None,"resolution":{"decision":"approved"} if status=="satisfied" else None}

def result(task_id,kind="commit"):
 return {"schema_version":1,"task_id":task_id,"outcome":"success","summary":"done","evidence":[{"kind":kind,"reference":"o/r@abc","verified":True,"verified_by":"ecosystem-supervisor","verified_at":"2026-09-23T00:30:00Z"}],"completed_at":"2026-09-23T00:30:00Z"}

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
  self.assertIn("cannot expand",inv["authority_rule"])

 def test_completion_requires_verified_contract_evidence(self):
  r=request("A"); l,s=cp.claim_plan(idle(),r,state(r),slot_id="s",execution_id="e1",now=NOW); s=cp.activate_state(s,r,l)
  with self.assertRaises(cp.ControlPlaneError): wr.complete_task(l,s,r,[],result("A","report"))
  l,s=wr.complete_task(l,s,r,[],result("A"))
  self.assertEqual((l["state"],s["status"]),("idle","completed"))

 def test_unsatisfied_gate_blocks_completion(self):
  r=request("A"); l,s=cp.claim_plan(idle(),r,state(r),slot_id="s",execution_id="e1",now=NOW); s=cp.activate_state(s,r,l)
  with self.assertRaises(cp.ControlPlaneError): wr.complete_task(l,s,r,[gate(r)],result("A"))

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
  l,sa=cp.claim_plan(l,a,sa,slot_id="2",execution_id="a2",now=datetime(2026,9,23,1,1,tzinfo=timezone.utc)); sa=cp.activate_state(sa,a,l); l,sa=wr.complete_task(l,sa,a,[ga],result("A"))
  self.assertEqual([x["task_id"] for x in wr.ready_tasks(reg,[(a,sa,[ga],ma),(b,sb,[],mb),(c,sc,[],mc)],NOW)],["B"])
  l,sb=cp.claim_plan(l,b,sb,slot_id="3",execution_id="b1",now=NOW); sb=cp.activate_state(sb,b,l); l,sb=wr.complete_task(l,sb,b,[],result("B"))
  l,sc=cp.claim_plan(l,c,sc,slot_id="4",execution_id="c1",now=NOW); sc=cp.activate_state(sc,c,l); l,sc=wr.complete_task(l,sc,c,[],result("C"))
  self.assertEqual((sa["status"],sb["status"],sc["status"],l["state"]),("completed","completed","completed","idle"))

if __name__=="__main__": unittest.main()

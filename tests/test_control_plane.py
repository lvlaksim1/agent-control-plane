import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import control_plane as cp

def registry(auto=True):
    return {"schema_version":1,"agents":[{"agent_id":"agent-a","agent_type":"service-agent","role":"Tester","home_repository":"o/a","authority_ref":"main","entrypoint":".context/ENTRYPOINT.md","status":"ready","automatic_execution_allowed":auto}]}

def request(task_id,priority="normal",created_at="2026-09-01T00:00:00Z",deps=None,target="agent-a"):
    return {"schema_version":1,"task_id":task_id,"issuer_agent_id":"owner","target_agent_id":target,"objective":f"Do {task_id}","authority_basis":{"kind":"owner-directive","reference":"test"},"scope":["test"],"constraints":[],"target":{"repository":"o/r","ref":"main"},"priority":priority,"dependencies":[{"task_id":d,"relation":"depends_on"} for d in (deps or [])],"workflow_id":None,"parent_task_id":None,"relation":None,"completion_contract":{"evidence_required":["commit"],"conditions":["verified"]},"created_at":created_at}

def state(req,status="queued"):
    return {"schema_version":1,"task_id":req["task_id"],"status":status,"request_digest":cp.request_digest(req),"attempt":0,"runtime_loss_count":0,"claim":None,"latest_checkpoint":None}

def idle(generation=0):
    return {"schema_version":1,"state":"idle","generation":generation,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,"claimed_at":None,"lease_until":None}

NOW=datetime(2026,9,23,0,0,tzinfo=timezone.utc)

class Tests(unittest.TestCase):
    def test_request_digest_detects_mutation(self):
        r=request("T1"); s=state(r); r["objective"]="mutated"
        with self.assertRaises(cp.ControlPlaneError): cp.validate_state(s,r)

    def test_ready_requires_completed_dependencies(self):
        a=request("A"); b=request("B",deps=["A"])
        self.assertEqual([x["task_id"] for x in cp.ready_tasks(registry(),[(a,state(a)),(b,state(b))],NOW)],["A"])
        self.assertEqual([x["task_id"] for x in cp.ready_tasks(registry(),[(a,state(a,"completed")),(b,state(b))],NOW)],["B"])

    def test_disabled_agent_is_not_ready(self):
        a=request("A"); self.assertEqual(cp.ready_tasks(registry(False),[(a,state(a))],NOW),[])

    def test_cycle_is_rejected(self):
        a=request("A",deps=["B"]); b=request("B",deps=["A"])
        with self.assertRaises(cp.ControlPlaneError): cp.ready_tasks(registry(),[(a,state(a)),(b,state(b))],NOW)

    def test_priority_aging_is_deterministic(self):
        h=request("H","high","2026-09-22T00:00:00Z"); n=request("N","normal","2026-09-01T00:00:00Z")
        self.assertEqual([x["task_id"] for x in cp.ready_tasks(registry(),[(h,state(h)),(n,state(n))],NOW)],["N","H"])

    def test_claim_increments_generation_and_attempt(self):
        r=request("A"); l,s=cp.claim_plan(idle(7),r,state(r),slot_id="slot-24",execution_id="exec-1",now=NOW)
        self.assertEqual(l["generation"],8); self.assertEqual(s["attempt"],1)
        self.assertTrue(cp.fence_valid(l,task_id="A",agent_id="agent-a",execution_id="exec-1",generation=8))

    def test_stale_execution_fails_fence(self):
        r=request("A"); l,s=cp.claim_plan(idle(),r,state(r),slot_id="slot",execution_id="old",now=NOW)
        nl,ns=cp.recover_expired_plan(l,s,r,now=datetime(2026,9,23,1,0,tzinfo=timezone.utc))
        self.assertFalse(cp.fence_valid(nl,task_id="A",agent_id="agent-a",execution_id="old",generation=1))
        self.assertEqual(nl["generation"],2); self.assertEqual(ns["status"],"queued")

    def test_recovery_quarantines_after_three_losses(self):
        r=request("A"); s=state(r); s["runtime_loss_count"]=2
        l,c=cp.claim_plan(idle(10),r,s,slot_id="slot",execution_id="exec-3",now=NOW)
        nl,ns=cp.recover_expired_plan(l,c,r,now=datetime(2026,9,23,1,0,tzinfo=timezone.utc))
        self.assertEqual(ns["runtime_loss_count"],3); self.assertEqual(ns["status"],"quarantined"); self.assertEqual(nl["generation"],12)

    def test_partial_claim_projection_reconciles_from_lease(self):
        r=request("A"); l,_=cp.claim_plan(idle(),r,state(r),slot_id="slot",execution_id="exec-1",now=NOW)
        fixed=cp.reconcile_state_from_lease(l,r,state(r))
        self.assertEqual(fixed["status"],"claimed"); self.assertEqual(fixed["claim"]["execution_id"],"exec-1"); self.assertEqual(fixed["attempt"],1)

    def test_checkpoint_survives_recovery_and_latest_selected(self):
        r=request("A"); s=state(r); s["latest_checkpoint"]="tasks/A/checkpoints/0002.json"
        l,c=cp.claim_plan(idle(),r,s,slot_id="slot",execution_id="exec-1",now=NOW)
        _,ns=cp.recover_expired_plan(l,c,r,now=datetime(2026,9,23,1,0,tzinfo=timezone.utc))
        self.assertEqual(ns["latest_checkpoint"],"tasks/A/checkpoints/0002.json")
        cs=[
          {"schema_version":1,"checkpoint_id":"c1","task_id":"A","execution_id":"exec-1","generation":1,"sequence":1,"created_at":"2026-09-23T00:10:00Z","completed_steps":["one"],"verified_evidence":["sha:a"],"next_action":"two"},
          {"schema_version":1,"checkpoint_id":"c2","task_id":"A","execution_id":"exec-1","generation":1,"sequence":2,"created_at":"2026-09-23T00:20:00Z","completed_steps":["one","two"],"verified_evidence":["sha:b"],"next_action":"three"}]
        self.assertEqual(cp.select_resume_checkpoint("A",cs)["checkpoint_id"],"c2")

    def test_renewal_rejects_old_execution(self):
        r=request("A"); l,_=cp.claim_plan(idle(),r,state(r),slot_id="slot",execution_id="exec-1",now=NOW)
        with self.assertRaises(cp.ControlPlaneError):
            cp.renew_lease(l,execution_id="old",generation=1,now=datetime(2026,9,23,0,20,tzinfo=timezone.utc))

if __name__=="__main__":
    unittest.main()

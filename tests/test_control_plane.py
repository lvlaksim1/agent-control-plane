import sys
import copy
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

    def test_bounded_delegation_keeps_commitment_and_returns_to_caller(self):
        r=request("D"); r["issuer_agent_id"]="agent-a"; r["responsibility"]={
            "mode":"bounded_delegation",
            "commitment_owner_agent_id":"agent-a",
            "return_to_agent_id":"agent-a"
        }
        cp.validate_request(r)

    def test_bounded_delegation_rejects_ownership_transfer(self):
        r=request("D"); r["issuer_agent_id"]="agent-a"; r["responsibility"]={
            "mode":"bounded_delegation",
            "commitment_owner_agent_id":"agent-b",
            "return_to_agent_id":"agent-a"
        }
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_request(r)

    def test_explicit_handoff_transfers_commitment_and_has_no_automatic_return(self):
        r=request("H",target="agent-a"); r["issuer_agent_id"]="agent-b"; r["responsibility"]={
            "mode":"explicit_handoff",
            "commitment_owner_agent_id":"agent-a",
            "return_to_agent_id":None
        }
        cp.validate_request(r)

    def test_explicit_handoff_rejects_implicit_return(self):
        r=request("H",target="agent-a"); r["issuer_agent_id"]="agent-b"; r["responsibility"]={
            "mode":"explicit_handoff",
            "commitment_owner_agent_id":"agent-a",
            "return_to_agent_id":"agent-b"
        }
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_request(r)

    def _v2(self, r, issuer, target, mode="bounded_delegation", parent=None, depth=1, allowed=None, forbidden=None, subdelegation="bounded"):
        r["issuer_agent_id"]=issuer
        r["target_agent_id"]=target
        r["parent_task_id"]=parent
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
        r["constraints"]=["no-release"]
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
                "grant_reference":f"GRANT-{r['task_id']}",
                "delegation_depth":depth,
                "parent_task_id":parent,
                "allowed_effects":allowed or ["read","write"],
                "forbidden_effects":forbidden or ["release"],
                "subdelegation":subdelegation
            }
        }
        return r

    def test_v2_bounded_delegation_separates_responsibility_and_authority(self):
        r=self._v2(request("V2-D"),"agent-a","agent-b")
        cp.validate_request(r)
        self.assertEqual(r["responsibility"]["commitment_owner_agent_id"],"agent-a")
        self.assertIsNone(r["responsibility"]["proposed_commitment_owner_agent_id"])
        self.assertFalse(r["responsibility"]["transfer_requires_target_acceptance"])

    def test_v2_explicit_handoff_is_proposed_until_target_acceptance(self):
        r=self._v2(request("V2-H"),"agent-a","agent-b",mode="explicit_handoff")
        cp.validate_request(r)
        self.assertEqual(r["responsibility"]["commitment_owner_agent_id"],"agent-a")
        self.assertEqual(r["responsibility"]["proposed_commitment_owner_agent_id"],"agent-b")
        self.assertTrue(r["responsibility"]["transfer_requires_target_acceptance"])
        broken=copy.deepcopy(r)
        broken["responsibility"]["commitment_owner_agent_id"]="agent-b"
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_request(broken)

    def test_v2_root_authority_must_match_task_authority_basis(self):
        r=self._v2(request("V2-ROOT"),"agent-a","agent-b")
        r["responsibility"]["authority_chain"]["root"]["reference"]="OTHER"
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_request(r)

    def test_nested_v2_delegation_can_only_attenuate_authority(self):
        parent=request("ROOT")
        parent["authority_basis"]={
            "kind":"owner-directive","reference":"OWNER-ROOT",
            "grant":{
                "allowed_effects":["read","write"],
                "forbidden_effects":["release"],
                "scope":["test"],
                "inherited_constraints":["no-release"],
                "subdelegation":"bounded"
            }
        }
        parent["scope"]=["test"]
        parent["constraints"]=["no-release"]

        child=self._v2(request("CHILD"),"agent-a","agent-b",parent="ROOT",depth=1,allowed=["read","write"],forbidden=["release"],subdelegation="bounded")
        grand=self._v2(request("GRAND"),"agent-b","agent-c",parent="CHILD",depth=2,allowed=["read"],forbidden=["release","delete"])
        grand["constraints"]=["no-release","read-only"]

        cp.validate_request(child); cp.validate_request(grand)
        cp.validate_authority_relations([parent,child,grand])

        widened=copy.deepcopy(grand)
        widened["responsibility"]["authority_chain"]["allowed_effects"].append("admin")
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_authority_relations([parent,child,widened])

        dropped_forbidden=copy.deepcopy(grand)
        dropped_forbidden["responsibility"]["authority_chain"]["forbidden_effects"]=[]
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_authority_relations([parent,child,dropped_forbidden])

        dropped_constraint=copy.deepcopy(grand)
        dropped_constraint["constraints"]=[]
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_authority_relations([parent,child,dropped_constraint])

        widened_scope=copy.deepcopy(grand)
        widened_scope["scope"]=["test","other"]
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_authority_relations([parent,child,widened_scope])

        no_sub=copy.deepcopy(child)
        no_sub["responsibility"]["authority_chain"]["subdelegation"]="forbidden"
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_authority_relations([parent,no_sub,grand])

    def test_acceptance_receipt_is_structured_request_target_and_fence_bound(self):
        r=self._v2(request("V2-ACCEPT",target="agent-b"),"agent-a","agent-b",mode="explicit_handoff")
        s=state(r,"claimed")
        s["claim"]={"execution_id":"e1","generation":1,"slot_id":"s","claimed_at":"2026-09-23T00:00:00Z","activation_projection_blob_sha":"b"*40}
        s["responsibility_acceptance"]={
            "request_digest":cp.request_digest(r),
            "accepted_by_agent_id":"agent-b",
            "accepted_at":"2026-09-23T00:01:00Z",
            "projected_at":"2026-09-23T00:02:00Z",
            "source":{
                "repository":"o/agent-b","authority_ref":"main","commit_sha":"c"*40,
                "path":".context/responsibility/acceptances/V2-ACCEPT.json",
                "blob_sha":"d"*40,"record_id":"ACC-V2-ACCEPT"
            },
            "execution_fence":{
                "mode":"autonomous","execution_id":"e1","generation":1,
                "activation_projection_blob_sha":"b"*40
            }
        }
        cp.validate_state(s,r)
        bad=copy.deepcopy(s); bad["responsibility_acceptance"]["accepted_by_agent_id"]="agent-a"
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_state(bad,r)

    def test_root_agent_delegation_requires_normalized_grant_and_attenuation(self):
        r=self._v2(request("ROOT-GRANT"),"agent-a","agent-b",allowed=["read"],forbidden=["release"])
        cp.validate_request(r)
        widened=copy.deepcopy(r)
        widened["responsibility"]["authority_chain"]["allowed_effects"]=["read","admin"]
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_request(widened)
        missing=copy.deepcopy(r)
        missing["authority_basis"].pop("grant")
        with self.assertRaises(cp.ControlPlaneError):
            cp.validate_request(missing)

    def test_first_owner_derived_hop_preserves_complete_root_grant(self):
        parent=request("OWNER-PARENT")
        parent["authority_basis"]={
            "kind":"owner-directive","reference":"OWNER-ROOT",
            "grant":{
                "allowed_effects":["read","write"],
                "forbidden_effects":["release"],
                "scope":["test"],
                "inherited_constraints":["no-release"],
                "subdelegation":"bounded"
            }
        }
        parent["scope"]=["test"]; parent["constraints"]=["no-release"]
        child=self._v2(request("OWNER-CHILD"),"agent-a","agent-b",parent="OWNER-PARENT",depth=1,allowed=["read"],forbidden=["release"])
        cp.validate_authority_relations([parent,child])

        widened=copy.deepcopy(child); widened["responsibility"]["authority_chain"]["allowed_effects"]=["read","admin"]
        with self.assertRaises(cp.ControlPlaneError): cp.validate_authority_relations([parent,widened])
        dropped=copy.deepcopy(child); dropped["constraints"]=[]
        with self.assertRaises(cp.ControlPlaneError): cp.validate_authority_relations([parent,dropped])
        scope_widen=copy.deepcopy(child); scope_widen["scope"]=["test","other"]
        with self.assertRaises(cp.ControlPlaneError): cp.validate_authority_relations([parent,scope_widen])
        forbidden_parent=copy.deepcopy(parent); forbidden_parent["authority_basis"]["grant"]["subdelegation"]="forbidden"
        with self.assertRaises(cp.ControlPlaneError): cp.validate_authority_relations([forbidden_parent,child])

if __name__=="__main__":
    unittest.main()

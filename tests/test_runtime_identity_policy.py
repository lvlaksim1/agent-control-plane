import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import runtime_identity_policy as p

class RuntimeIdentityPolicyTests(unittest.TestCase):
    def child(self,mode):
        return {
            "task_id":"CHILD",
            "issuer_agent_id":"ecosystem-supervisor",
            "target_agent_id":"project-manager-auditor",
            "constraints":["runtime:separate-target",mode],
            "dependencies":[],
            "responsibility":{
                "semantics_version":2,
                "mode":"bounded_delegation",
                "caller_agent_id":"ecosystem-supervisor",
            },
        }

    def caller_task(self):
        return {
            "task_id":"CALLER-CONTINUE",
            "issuer_agent_id":"ecosystem-supervisor",
            "target_agent_id":"ecosystem-supervisor",
            "constraints":["runtime:caller-continuation"],
            "dependencies":[{"task_id":"CHILD","relation":"depends_on"}],
            "responsibility":None,
        }

    def test_interactive_child_requires_separate_runtime(self):
        p.validate_inter_agent_request(self.child("continuation:manual-pull"))
        bad=self.child("continuation:manual-pull")
        bad["constraints"].remove("runtime:separate-target")
        with self.assertRaises(p.RuntimeIdentityPolicyError):
            p.validate_inter_agent_request(bad)

    def test_runtime_cannot_change_persistent_agent(self):
        p.assert_runtime_affinity(runtime_agent_id="ecosystem-supervisor",requested_agent_id="ecosystem-supervisor")
        with self.assertRaises(p.RuntimeIdentityPolicyError):
            p.assert_runtime_affinity(runtime_agent_id="ecosystem-supervisor",requested_agent_id="project-manager-auditor")

    def test_autonomous_return_is_dependency_bound_new_runtime(self):
        child=self.child("continuation:automatic-new-runtime")
        caller=self.caller_task()
        p.validate_autonomous_return_pair(child,caller)

    def test_same_agent_work_requires_caller_continuation_constraint(self):
        caller=self.caller_task()
        p.validate_inter_agent_request(caller)
        bad=dict(caller)
        bad["constraints"]=[]
        with self.assertRaises(p.RuntimeIdentityPolicyError):
            p.validate_inter_agent_request(bad)

    def test_caller_continuation_cannot_carry_delegation_contract(self):
        caller=self.caller_task()
        caller["responsibility"]={
            "semantics_version":2,
            "mode":"bounded_delegation",
            "caller_agent_id":"ecosystem-supervisor",
        }
        with self.assertRaises(p.RuntimeIdentityPolicyError):
            p.validate_inter_agent_request(caller)

    def test_delegated_target_cannot_masquerade_as_caller_continuation(self):
        child=self.child("continuation:manual-pull")
        child["constraints"].append("runtime:caller-continuation")
        with self.assertRaises(p.RuntimeIdentityPolicyError):
            p.validate_inter_agent_request(child)

if __name__=="__main__":
    unittest.main()

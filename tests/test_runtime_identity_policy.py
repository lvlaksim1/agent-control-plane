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
            "responsibility":{
                "semantics_version":2,
                "mode":"bounded_delegation",
                "caller_agent_id":"ecosystem-supervisor",
            },
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
        caller={
            "target_agent_id":"ecosystem-supervisor",
            "constraints":["runtime:caller-continuation"],
            "dependencies":[{"task_id":"CHILD","relation":"depends_on"}],
        }
        p.validate_autonomous_return_pair(child,caller)

if __name__=="__main__":
    unittest.main()

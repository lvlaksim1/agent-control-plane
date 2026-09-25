import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import control_plane as cp
import runtime_identity_policy as rp

class RuntimeIdentityPilotProjectionTests(unittest.TestCase):
    def test_runtime_identity_audit_task_is_valid_and_separate_runtime(self):
        task=ROOT/"tasks"/"TASK-RUNTIME-IDENTITY-AUDIT-002"
        request=json.loads((task/"request.json").read_text(encoding="utf-8"))
        state=json.loads((task/"state.json").read_text(encoding="utf-8"))
        cp.validate_request(request)
        cp.validate_state(state,request)
        rp.validate_inter_agent_request(request)
        self.assertEqual(state["status"],"queued")
        self.assertEqual(request["target_agent_id"],"project-manager-auditor")
        self.assertIn("continuation:manual-pull",request["constraints"])

if __name__=="__main__":
    unittest.main()

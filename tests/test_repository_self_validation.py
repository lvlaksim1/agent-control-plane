import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import control_plane as cp
import workflow_runtime as wr
import runtime_identity_policy as rp

class RuntimeIdentityPilotProjectionTests(unittest.TestCase):
    def bundle(self):
        task=ROOT/"tasks"/"TASK-RUNTIME-IDENTITY-AUDIT-002"
        request=json.loads((task/"request.json").read_text(encoding="utf-8"))
        state=json.loads((task/"state.json").read_text(encoding="utf-8"))
        runtime=json.loads((task/"runtime.json").read_text(encoding="utf-8"))
        return request,state,[],runtime

    def test_runtime_identity_audit_task_is_valid_and_separate_runtime(self):
        request,state,_,_=self.bundle()
        cp.validate_request(request)
        cp.validate_state(state,request)
        rp.validate_inter_agent_request(request)
        self.assertEqual(state["status"],"queued")
        self.assertEqual(request["target_agent_id"],"project-manager-auditor")
        self.assertIn("continuation:manual-pull",request["constraints"])

    def test_runtime_identity_audit_task_is_scheduler_ready(self):
        registry=json.loads((ROOT/"registry"/"agents.json").read_text(encoding="utf-8"))
        ready=wr.scheduler_ready_tasks(
            registry,
            [self.bundle()],
            datetime(2026,9,25,10,0,tzinfo=timezone.utc),
        )
        self.assertEqual([x["task_id"] for x in ready],["TASK-RUNTIME-IDENTITY-AUDIT-002"])

if __name__=="__main__":
    unittest.main()

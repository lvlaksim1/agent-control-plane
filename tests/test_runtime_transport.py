import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import result_relay as rr
import runtime_transport as rt


def ticket(**overrides):
    base = {
        "schema_version": 1,
        "task_id": "TASK-1",
        "logical_attempt": 1,
        "request_digest": "sha256:" + "a" * 64,
        "request_blob_sha": "b" * 40,
        "transport_task_id": "jawbone-1",
        "transport_slot_id": "runtime-slot-1",
        "transport_generation": 1,
        "delivery_try": 1,
        "admission_nonce": "adm-1",
        "relay_id": "relay-1",
        "relay_nonce": "nonce-1",
        "expected_author_id": "execution-worker",
        "allowed_payload_kind": "probe",
        "scheduled_not_before": "2026-09-25T21:00:00+00:00",
        "relay_deadline_at": "2026-09-25T21:10:00+00:00",
        "slot_quiescence_until": "2026-09-25T21:25:00+00:00",
        "status": "armed",
    }
    base.update(overrides)
    return base


def relay(t=None, **overrides):
    t = t or ticket()
    payload = overrides.pop("payload_text", "RESULT=PASS")
    env = {
        "schema_version": 3,
        "relay_id": t["relay_id"],
        "transport_task_id": t["transport_task_id"],
        "transport_slot_id": t["transport_slot_id"],
        "transport_generation": t["transport_generation"],
        "task_id": t["task_id"],
        "logical_attempt": t["logical_attempt"],
        "delivery_try": t["delivery_try"],
        "request_digest": t["request_digest"],
        "request_blob_sha": t["request_blob_sha"],
        "admission_nonce": t["admission_nonce"],
        "relay_nonce": t["relay_nonce"],
        "author_id": t["expected_author_id"],
        "author_kind": "infrastructure",
        "status": "complete",
        "terminal": True,
        "payload_kind": t["allowed_payload_kind"],
        "payload_encoding": "utf-8",
        "payload_text": payload,
        "payload_sha256": rr.sha256_utf8(payload),
        "authored_at_msk": "2026-09-26T00:05:00+03:00",
    }
    env.update(overrides)
    return rr.encode_relay(env)


def pool():
    return {
        "schema_version": 1,
        "pool_generation": 7,
        "slots": [
            {
                "slot_id": "runtime-slot-1",
                "automation_id": "auto-1",
                "state": "idle",
                "last_transport_generation": 5,
                "current_ticket": None,
                "quiescent_until": None,
            },
            {
                "slot_id": "runtime-slot-2",
                "automation_id": "auto-2",
                "state": "idle",
                "last_transport_generation": 7,
                "current_ticket": None,
                "quiescent_until": None,
            },
        ],
    }


class ObservationTests(unittest.TestCase):
    def test_before_not_before_awaits_launch(self):
        out = rt.classify_observation(
            ticket=ticket(),
            observation={"prompt": "instruction", "last_run_time": None, "updated_at": "2026-09-25T20:59:00+00:00"},
            now="2026-09-25T20:59:30+00:00",
        )
        self.assertEqual(out["state"], "awaiting-launch")

    def test_current_run_before_deadline_awaits_relay(self):
        out = rt.classify_observation(
            ticket=ticket(),
            observation={
                "prompt": "instruction",
                "last_run_time": "2026-09-25T21:02:00+00:00",
                "updated_at": "2026-09-25T21:00:00+00:00",
            },
            now="2026-09-25T21:03:00+00:00",
        )
        self.assertEqual(out["state"], "awaiting-relay")

    def test_old_last_run_does_not_count_for_current_delivery(self):
        out = rt.classify_observation(
            ticket=ticket(),
            observation={
                "prompt": "instruction",
                "last_run_time": "2026-09-25T20:55:00+00:00",
                "updated_at": "2026-09-25T21:00:00+00:00",
            },
            now="2026-09-25T21:05:00+00:00",
        )
        self.assertEqual(out["state"], "awaiting-launch")

    def test_no_current_run_after_deadline_is_launch_miss(self):
        out = rt.classify_observation(
            ticket=ticket(),
            observation={
                "prompt": "instruction",
                "last_run_time": "2026-09-25T20:55:00+00:00",
                "updated_at": "2026-09-25T21:00:00+00:00",
            },
            now="2026-09-25T21:11:00+00:00",
        )
        self.assertEqual(out["state"], "launch-miss")

    def test_run_without_relay_after_deadline_is_egress_miss(self):
        out = rt.classify_observation(
            ticket=ticket(),
            observation={
                "prompt": "instruction",
                "last_run_time": "2026-09-25T21:02:00+00:00",
                "updated_at": "2026-09-25T21:00:00+00:00",
            },
            now="2026-09-25T21:11:00+00:00",
        )
        self.assertEqual(out["state"], "egress-miss")

    def test_valid_relay_is_ready(self):
        t = ticket()
        raw = relay(t)
        out = rt.classify_observation(
            ticket=t,
            observation={
                "prompt": raw,
                "last_run_time": "2026-09-25T21:02:00+00:00",
                "updated_at": "2026-09-25T21:04:00+00:00",
            },
            now="2026-09-25T21:05:00+00:00",
        )
        self.assertEqual(out["state"], "ready")
        self.assertEqual(out["transport_updated_at"], "2026-09-25T21:04:00+00:00")

    def test_late_valid_relay_is_not_ready(self):
        t = ticket()
        raw = relay(t)
        out = rt.classify_observation(
            ticket=t,
            observation={
                "prompt": raw,
                "last_run_time": "2026-09-25T21:02:00+00:00",
                "updated_at": "2026-09-25T21:10:01+00:00",
            },
            now="2026-09-25T21:11:00+00:00",
        )
        self.assertEqual(out["state"], "late-relay")

    def test_stale_generation_is_relay_stale(self):
        t = ticket()
        raw = relay(t, transport_generation=0)
        out = rt.classify_observation(
            ticket=t,
            observation={
                "prompt": raw,
                "last_run_time": "2026-09-25T21:02:00+00:00",
                "updated_at": "2026-09-25T21:04:00+00:00",
            },
            now="2026-09-25T21:05:00+00:00",
        )
        self.assertEqual(out["state"], "relay-stale")

    def test_bad_payload_hash_is_invalid(self):
        t = ticket()
        raw = relay(t, payload_sha256="sha256:" + "0" * 64)
        out = rt.classify_observation(
            ticket=t,
            observation={
                "prompt": raw,
                "last_run_time": "2026-09-25T21:02:00+00:00",
                "updated_at": "2026-09-25T21:04:00+00:00",
            },
            now="2026-09-25T21:05:00+00:00",
        )
        self.assertEqual(out["state"], "relay-invalid")


class SlotPoolTests(unittest.TestCase):
    def test_prefer_other_idle_slot_for_retry(self):
        chosen = rt.select_idle_slot(
            pool(),
            now="2026-09-25T21:00:00+00:00",
            avoid_slot_id="runtime-slot-1",
        )
        self.assertEqual(chosen["slot_id"], "runtime-slot-2")

    def test_allocate_increments_global_generation(self):
        new_pool, allocation = rt.allocate_slot(
            pool(),
            now="2026-09-25T21:00:00+00:00",
            ticket_path="tasks/TASK-1/relay/1/8/ticket.json",
            quiescent_until="2026-09-25T21:25:00+00:00",
            avoid_slot_id="runtime-slot-1",
        )
        self.assertEqual(new_pool["pool_generation"], 8)
        self.assertEqual(allocation["transport_generation"], 8)
        self.assertEqual(allocation["slot_id"], "runtime-slot-2")
        slot = next(s for s in new_pool["slots"] if s["slot_id"] == "runtime-slot-2")
        self.assertEqual(slot["state"], "armed")
        self.assertEqual(slot["last_transport_generation"], 8)

    def test_quiescent_slot_not_reused_too_early(self):
        p = pool()
        p["slots"][0]["state"] = "quiescent"
        p["slots"][0]["quiescent_until"] = "2026-09-25T21:30:00+00:00"
        p["slots"][1]["state"] = "armed"
        with self.assertRaisesRegex(rt.TransportError, "no idle"):
            rt.select_idle_slot(p, now="2026-09-25T21:20:00+00:00")

    def test_quiescent_slot_recycles_after_deadline(self):
        p = pool()
        p["slots"][0]["state"] = "quiescent"
        p["slots"][0]["current_ticket"] = "old"
        p["slots"][0]["quiescent_until"] = "2026-09-25T21:30:00+00:00"
        p["slots"][1]["state"] = "armed"
        chosen = rt.select_idle_slot(p, now="2026-09-25T21:31:00+00:00")
        self.assertEqual(chosen["slot_id"], "runtime-slot-1")

    def test_generation_fence_required_to_quiesce(self):
        p = pool()
        p["slots"][0]["state"] = "armed"
        p["slots"][0]["last_transport_generation"] = 8
        with self.assertRaisesRegex(rt.TransportError, "generation fence"):
            rt.mark_slot_quiescent(
                p,
                slot_id="runtime-slot-1",
                transport_generation=7,
                quiescent_until="2026-09-25T21:30:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()

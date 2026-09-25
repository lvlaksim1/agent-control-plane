import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import result_relay as rr


def ticket(**overrides):
    base = {
        "schema_version": 1,
        "task_id": "TASK-1",
        "logical_attempt": 3,
        "request_digest": "sha256:" + "a" * 64,
        "request_blob_sha": "b" * 40,
        "transport_task_id": "jawbone-1",
        "transport_slot_id": "runtime-slot-1",
        "transport_generation": 17,
        "delivery_try": 2,
        "admission_nonce": "adm-123456789",
        "relay_id": "RELAY-TEST-001",
        "relay_nonce": "relay-123456789",
        "expected_author_id": "execution-worker",
        "allowed_payload_kind": "probe",
        "scheduled_not_before": "2026-09-25T18:00:00+00:00",
        "relay_deadline_at": "2026-09-25T18:10:00+00:00",
        "slot_quiescence_until": "2026-09-25T18:25:00+00:00",
        "status": "armed",
    }
    base.update(overrides)
    return base


def envelope(t=None, **overrides):
    t = t or ticket()
    payload = overrides.pop("payload_text", "Привет GitHub 12345\nline2")
    base = {
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
        "authored_at_msk": "2026-09-25T21:05:00+03:00",
    }
    base.update(overrides)
    return base


class RelayV3Tests(unittest.TestCase):
    def test_valid_round_trip_preserves_utf8_payload(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t))
        out = rr.validate_raw_relay(raw, ticket=t)
        self.assertEqual(out["payload_text"], "Привет GitHub 12345\nline2")
        self.assertEqual(out["payload_sha256"], rr.sha256_utf8(out["payload_text"]))

    def test_transport_retry_does_not_advance_logical_attempt(self):
        first = ticket()
        nxt = rr.next_delivery_ticket(
            first,
            transport_task_id="jawbone-2",
            transport_slot_id="runtime-slot-2",
            transport_generation=18,
            admission_nonce="adm-new",
            relay_id="RELAY-TEST-002",
            relay_nonce="relay-new",
            scheduled_not_before="2026-09-25T19:00:00+00:00",
            relay_deadline_at="2026-09-25T19:10:00+00:00",
            slot_quiescence_until="2026-09-25T19:25:00+00:00",
        )
        self.assertEqual(nxt["logical_attempt"], first["logical_attempt"])
        self.assertEqual(nxt["delivery_try"], first["delivery_try"] + 1)
        self.assertEqual(nxt["transport_generation"], 18)

    def test_stale_generation_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, transport_generation=16))
        with self.assertRaisesRegex(rr.RelayError, "transport_generation binding mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_old_delivery_after_retry_rejected(self):
        first = ticket()
        old_raw = rr.encode_relay(envelope(first))
        current = rr.next_delivery_ticket(
            first,
            transport_task_id="jawbone-2",
            transport_slot_id="runtime-slot-2",
            transport_generation=18,
            admission_nonce="adm-new",
            relay_id="RELAY-TEST-002",
            relay_nonce="relay-new",
            scheduled_not_before="2026-09-25T19:00:00+00:00",
            relay_deadline_at="2026-09-25T19:10:00+00:00",
            slot_quiescence_until="2026-09-25T19:25:00+00:00",
        )
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(old_raw, ticket=current)

    def test_wrong_admission_nonce_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, admission_nonce="wrong"))
        with self.assertRaisesRegex(rr.RelayError, "admission_nonce binding mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_wrong_final_relay_nonce_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, relay_nonce="wrong"))
        with self.assertRaisesRegex(rr.RelayError, "relay_nonce binding mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_wrong_transport_task_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, transport_task_id="other"))
        with self.assertRaisesRegex(rr.RelayError, "transport_task_id binding mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_wrong_transport_slot_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, transport_slot_id="other"))
        with self.assertRaisesRegex(rr.RelayError, "transport_slot_id binding mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_wrong_logical_attempt_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, logical_attempt=2))
        with self.assertRaisesRegex(rr.RelayError, "logical_attempt binding mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_wrong_request_binding_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, request_blob_sha="c" * 40))
        with self.assertRaisesRegex(rr.RelayError, "request_blob_sha binding mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_payload_hash_mismatch_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, payload_sha256="sha256:" + "0" * 64))
        with self.assertRaisesRegex(rr.RelayError, "payload_sha256 mismatch"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_non_terminal_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, terminal=False))
        with self.assertRaisesRegex(rr.RelayError, "must be terminal"):
            rr.validate_raw_relay(raw, ticket=t)

    def test_non_moscow_timestamp_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, authored_at_msk="2026-09-25T18:05:00+00:00"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, ticket=t)

    def test_blocked_requires_reason_text(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t, status="blocked", payload_text=""))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, ticket=t)
        blocked = envelope(t, status="blocked", payload_text="base drift")
        blocked["payload_sha256"] = rr.sha256_utf8(blocked["payload_text"])
        rr.validate_raw_relay(rr.encode_relay(blocked), ticket=t)

    def test_oversize_rejected(self):
        t = ticket()
        huge = envelope(t, payload_text="x" * 13000)
        huge["payload_sha256"] = rr.sha256_utf8(huge["payload_text"])
        with self.assertRaises(rr.RelayError):
            rr.encode_relay(huge)

    def test_exact_duplicate_is_idempotent(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t))
        first = rr.plan_acceptance(raw, ticket=t)
        second = rr.plan_acceptance(raw, ticket=t, existing_receipt=first["receipt"])
        self.assertEqual(first["decision"], "accept-new")
        self.assertEqual(second["decision"], "already-accepted")

    def test_conflicting_relay_after_receipt_rejected(self):
        t = ticket()
        raw = rr.encode_relay(envelope(t))
        first = rr.plan_acceptance(raw, ticket=t)
        changed = envelope(t, payload_text="different")
        changed["payload_sha256"] = rr.sha256_utf8(changed["payload_text"])
        with self.assertRaisesRegex(rr.RelayError, "already exists"):
            rr.plan_acceptance(
                rr.encode_relay(changed),
                ticket=t,
                existing_receipt=first["receipt"],
            )

    def test_v2_is_parseable_but_not_accepted_as_v3(self):
        legacy = 'ACP_RUNTIME_RELAY_V2|{"schema_version":2}'
        self.assertEqual(rr.parse_relay(legacy)["schema_version"], 2)
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(legacy, ticket=ticket())

    def test_ticket_time_ordering_is_fail_closed(self):
        bad = ticket(slot_quiescence_until="2026-09-25T18:05:00+00:00")
        with self.assertRaisesRegex(rr.RelayError, "time ordering"):
            rr.validate_ticket(bad)


if __name__ == "__main__":
    unittest.main()

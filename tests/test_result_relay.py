import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import result_relay as rr


def envelope(**overrides):
    payload = overrides.pop("payload_text", "Привет GitHub 12345\nline2")
    base = {
        "schema_version": 2,
        "relay_id": "RELAY-TEST-001",
        "transport_task_id": "jawbone-1",
        "task_id": "TASK-1",
        "attempt": 3,
        "request_digest": "sha256:" + "a" * 64,
        "request_blob_sha": "b" * 40,
        "relay_nonce": "nonce-123456789",
        "author_id": "execution-worker",
        "author_kind": "infrastructure",
        "status": "complete",
        "terminal": True,
        "payload_kind": "probe",
        "payload_encoding": "utf-8",
        "payload_text": payload,
        "payload_sha256": rr.sha256_utf8(payload),
        "authored_at_msk": "2026-09-25T18:52:32+03:00",
    }
    base.update(overrides)
    return base


EXPECTED = {
    "relay_id": "RELAY-TEST-001",
    "transport_task_id": "jawbone-1",
    "task_id": "TASK-1",
    "attempt": 3,
    "request_digest": "sha256:" + "a" * 64,
    "request_blob_sha": "b" * 40,
    "relay_nonce": "nonce-123456789",
    "author_id": "execution-worker",
    "allowed_payload_kinds": {"probe"},
}


class RelayTests(unittest.TestCase):
    def test_valid_round_trip_preserves_utf8_payload(self):
        raw = rr.encode_relay(envelope())
        out = rr.validate_raw_relay(raw, **EXPECTED)
        self.assertEqual(out["payload_text"], "Привет GitHub 12345\nline2")
        self.assertEqual(out["payload_sha256"], rr.sha256_utf8(out["payload_text"]))

    def test_wrong_transport_task_rejected(self):
        raw = rr.encode_relay(envelope(transport_task_id="other"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_wrong_nonce_rejected(self):
        raw = rr.encode_relay(envelope(relay_nonce="old"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_wrong_author_rejected(self):
        raw = rr.encode_relay(envelope(author_id="other"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_wrong_request_binding_rejected(self):
        raw = rr.encode_relay(envelope(request_blob_sha="c" * 40))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_stale_attempt_rejected(self):
        raw = rr.encode_relay(envelope(attempt=2))
        with self.assertRaisesRegex(rr.RelayError, "attempt binding mismatch"):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_non_terminal_rejected(self):
        raw = rr.encode_relay(envelope(terminal=False))
        with self.assertRaisesRegex(rr.RelayError, "must be terminal"):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_payload_hash_mismatch_rejected(self):
        raw = rr.encode_relay(envelope(payload_sha256="sha256:" + "0" * 64))
        with self.assertRaisesRegex(rr.RelayError, "payload_sha256 mismatch"):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_non_moscow_timestamp_rejected(self):
        raw = rr.encode_relay(envelope(authored_at_msk="2026-09-25T15:52:32+00:00"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, **EXPECTED)

    def test_blocked_requires_reason_text(self):
        raw = rr.encode_relay(envelope(status="blocked", payload_text=""))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw, **EXPECTED)
        raw = rr.encode_relay(envelope(status="blocked", payload_text="base drift"))
        rr.validate_raw_relay(raw, **EXPECTED)

    def test_oversize_rejected(self):
        huge = envelope(payload_text="x" * 13000)
        with self.assertRaises(rr.RelayError):
            rr.encode_relay(huge)

    def test_first_acceptance_is_new(self):
        raw = rr.encode_relay(envelope())
        decision = rr.plan_acceptance(raw, **EXPECTED)
        self.assertEqual(decision["decision"], "accept-new")
        self.assertEqual(decision["receipt"]["attempt"], 3)
        self.assertEqual(decision["receipt"]["raw_relay_sha256"], rr.sha256_utf8(raw))

    def test_exact_duplicate_is_idempotent(self):
        raw = rr.encode_relay(envelope())
        first = rr.plan_acceptance(raw, **EXPECTED)
        second = rr.plan_acceptance(raw, existing_receipt=first["receipt"], **EXPECTED)
        self.assertEqual(second["decision"], "already-accepted")

    def test_different_relay_after_acceptance_is_conflict(self):
        raw = rr.encode_relay(envelope())
        first = rr.plan_acceptance(raw, **EXPECTED)
        changed = envelope(payload_text="different")
        changed["payload_sha256"] = rr.sha256_utf8(changed["payload_text"])
        changed_raw = rr.encode_relay(changed)
        with self.assertRaisesRegex(rr.RelayError, "already exists"):
            rr.plan_acceptance(changed_raw, existing_receipt=first["receipt"], **EXPECTED)

    def test_legacy_v1_not_accepted_as_new_result(self):
        legacy = 'ACP_RUNTIME_RELAY_V1|{"schema_version":1}'
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(legacy, **EXPECTED)


if __name__ == "__main__":
    unittest.main()

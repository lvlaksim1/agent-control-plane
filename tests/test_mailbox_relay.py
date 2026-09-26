import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import mailbox_relay as mr


def envelope(**overrides):
    payload = overrides.pop("payload_text", "RESULT=PASS\\nCHECK=101*103=10403")
    base = {
        "schema_version": 1,
        "relay_id": "MBX-RELAY-1",
        "producer_task_id": "producer-1",
        "mailbox_task_id": "mailbox-task-1",
        "mailbox_id": "mailbox-C",
        "mailbox_generation": 1,
        "admission_nonce": "ADM-C-1",
        "task_id": "TASK-1",
        "logical_attempt": 2,
        "request_digest": "sha256:" + "a" * 64,
        "request_blob_sha": "b" * 40,
        "execution_id": "exec-1",
        "execution_generation": 57,
        "relay_nonce": "RLY-C-1",
        "author_id": "execution-worker",
        "author_kind": "infrastructure",
        "status": "complete",
        "terminal": True,
        "payload_kind": "mailbox-acp-e2e-proof",
        "payload_encoding": "utf-8",
        "payload_text": payload,
        "payload_sha256": mr.sha256_utf8(payload),
        "authored_at_msk": "2026-09-26T03:00:00+03:00",
    }
    base.update(overrides)
    return base


EXPECTED = {
    "relay_id": "MBX-RELAY-1",
    "producer_task_id": "producer-1",
    "mailbox_task_id": "mailbox-task-1",
    "mailbox_id": "mailbox-C",
    "mailbox_generation": 1,
    "admission_nonce": "ADM-C-1",
    "task_id": "TASK-1",
    "logical_attempt": 2,
    "request_digest": "sha256:" + "a" * 64,
    "request_blob_sha": "b" * 40,
    "execution_id": "exec-1",
    "execution_generation": 57,
    "relay_nonce": "RLY-C-1",
    "author_id": "execution-worker",
    "allowed_payload_kinds": {"mailbox-acp-e2e-proof"},
}


class MailboxRelayTests(unittest.TestCase):
    def test_valid_round_trip(self):
        raw = mr.encode_relay(envelope())
        out = mr.validate_raw_relay(raw, **EXPECTED)
        self.assertEqual(out["execution_generation"], 57)

    def test_stale_logical_attempt_rejected(self):
        raw = mr.encode_relay(envelope(logical_attempt=1))
        with self.assertRaisesRegex(mr.MailboxRelayError, "logical_attempt binding mismatch"):
            mr.validate_raw_relay(raw, **EXPECTED)

    def test_wrong_execution_rejected(self):
        raw = mr.encode_relay(envelope(execution_id="old-exec"))
        with self.assertRaisesRegex(mr.MailboxRelayError, "execution_id binding mismatch"):
            mr.validate_raw_relay(raw, **EXPECTED)

    def test_wrong_generation_rejected(self):
        raw = mr.encode_relay(envelope(execution_generation=56))
        with self.assertRaisesRegex(mr.MailboxRelayError, "execution_generation binding mismatch"):
            mr.validate_raw_relay(raw, **EXPECTED)

    def test_wrong_mailbox_rejected(self):
        raw = mr.encode_relay(envelope(mailbox_task_id="old-mailbox"))
        with self.assertRaisesRegex(mr.MailboxRelayError, "mailbox_task_id binding mismatch"):
            mr.validate_raw_relay(raw, **EXPECTED)

    def test_wrong_admission_nonce_rejected(self):
        raw = mr.encode_relay(envelope(admission_nonce="old"))
        with self.assertRaisesRegex(mr.MailboxRelayError, "admission_nonce binding mismatch"):
            mr.validate_raw_relay(raw, **EXPECTED)

    def test_payload_hash_rejected(self):
        raw = mr.encode_relay(envelope(payload_sha256="sha256:" + "0" * 64))
        with self.assertRaisesRegex(mr.MailboxRelayError, "payload_sha256 mismatch"):
            mr.validate_raw_relay(raw, **EXPECTED)


if __name__ == "__main__":
    unittest.main()

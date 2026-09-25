import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import result_relay as rr

def envelope(**overrides):
    base={
      "schema_version":1,
      "relay_id":"RELAY-TEST-001",
      "transport_task_id":"jawbone-1",
      "task_id":"TASK-1",
      "request_digest":"sha256:"+"a"*64,
      "request_blob_sha":"b"*40,
      "relay_nonce":"nonce-123456789",
      "author_id":"execution-worker",
      "author_kind":"infrastructure",
      "status":"complete",
      "payload_kind":"probe",
      "payload":{"answer":"ok"},
      "authored_at_msk":"2026-09-25T18:52:32+03:00",
    }
    base.update(overrides)
    return base

EXPECTED={
  "relay_id":"RELAY-TEST-001",
  "transport_task_id":"jawbone-1",
  "task_id":"TASK-1",
  "request_digest":"sha256:"+"a"*64,
  "request_blob_sha":"b"*40,
  "relay_nonce":"nonce-123456789",
  "author_id":"execution-worker",
  "allowed_payload_kinds":{"probe"},
}

class RelayTests(unittest.TestCase):
    def test_valid_round_trip(self):
        raw=rr.encode_relay(envelope())
        out=rr.validate_raw_relay(raw,**EXPECTED)
        self.assertEqual(out["payload"]["answer"],"ok")

    def test_wrong_transport_task_rejected(self):
        raw=rr.encode_relay(envelope(transport_task_id="other"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw,**EXPECTED)

    def test_wrong_nonce_rejected(self):
        raw=rr.encode_relay(envelope(relay_nonce="old"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw,**EXPECTED)

    def test_wrong_author_rejected(self):
        raw=rr.encode_relay(envelope(author_id="other"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw,**EXPECTED)

    def test_wrong_request_binding_rejected(self):
        raw=rr.encode_relay(envelope(request_blob_sha="c"*40))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw,**EXPECTED)

    def test_non_moscow_timestamp_rejected(self):
        raw=rr.encode_relay(envelope(authored_at_msk="2026-09-25T15:52:32+00:00"))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw,**EXPECTED)

    def test_blocked_requires_reason(self):
        raw=rr.encode_relay(envelope(status="blocked",payload={}))
        with self.assertRaises(rr.RelayError):
            rr.validate_raw_relay(raw,**EXPECTED)
        raw=rr.encode_relay(envelope(status="blocked",payload={"reason":"base drift"}))
        rr.validate_raw_relay(raw,**EXPECTED)

    def test_oversize_rejected(self):
        huge=envelope(payload={"data":"x"*13000})
        with self.assertRaises(rr.RelayError):
            rr.encode_relay(huge)

if __name__=="__main__":
    unittest.main()

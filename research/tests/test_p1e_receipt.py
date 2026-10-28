import base64
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from research.p1e_protocol import VERSION, canonical, digest, strict_json
from research.p1e_receipt import DOMAIN, AttemptJournal, verify_receipt, digest_key
from research.tests.p1e_support import proposal

NOW = datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)
REVIEW = "a"*40


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        # Test-only ephemeral key; never written, enrolled or included in evidence.
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        m = proposal()
        self.payload = {"schema": "p1e-human-receipt-v1", "decision": "AUTHORIZE_STAGE_A_ONCE",
                        "source_head": m["source_head"], "review_head": REVIEW, "manifest_sha256": digest(m),
                        "jobs_sha256": digest(m["jobs"]), "limits": m["limits"], "worker_version": VERSION,
                        "evidence_root": m["evidence_root"], "nonce": "b"*64,
                        "issued_at": "2026-10-28T07:59:00Z", "expires_at": "2026-10-28T09:00:00Z"}

    def signed(self, payload=None):
        payload = payload or self.payload
        return canonical({"payload": payload, "key_id": digest_key(self.public),
                          "signature": base64.b64encode(self.private.sign(DOMAIN+canonical(payload))).decode()})

    def trusted(self):
        return patch("research.p1e_receipt.TRUSTED_LEAD_KEYS", (self.public,))

    def test_default_empty_trust_rejects_even_cryptographically_valid_test_signature(self):
        with self.assertRaises(ValueError): verify_receipt(self.signed(), proposal(), REVIEW, now=NOW)

    def test_real_crypto_verification_with_test_only_pinned_public_key(self):
        with self.trusted():
            self.assertEqual(verify_receipt(self.signed(), proposal(), REVIEW, now=NOW), self.payload)

    def test_modified_signature_and_payload_rejected(self):
        envelope = strict_json(self.signed()); envelope["signature"] = base64.b64encode(b"x"*64).decode()
        with self.trusted(), self.assertRaises(InvalidSignature):
            verify_receipt(canonical(envelope), proposal(), REVIEW, now=NOW)
        envelope = strict_json(self.signed()); envelope["payload"]["nonce"] = "c"*64
        with self.trusted(), self.assertRaises(InvalidSignature):
            verify_receipt(canonical(envelope), proposal(), REVIEW, now=NOW)

    def test_source_job_review_budget_and_destination_bindings(self):
        for field, value in (("source_head", "c"*40), ("review_head", "c"*40),
                             ("manifest_sha256", "c"*64), ("jobs_sha256", "c"*64),
                             ("evidence_root", "results/elsewhere"), ("limits", {}),
                             ("worker_version", "v999"), ("decision", "APPROVE_TRUE")):
            payload = {**self.payload, field: value}
            with self.subTest(field=field), self.trusted(), self.assertRaises(ValueError):
                verify_receipt(self.signed(payload), proposal(), REVIEW, now=NOW)

    def test_absent_unsigned_boolean_and_proposal_digest_not_receipts(self):
        for value in (True, {"approval": True}, {"proposal_digest": digest(proposal())},
                      {"payload": self.payload, "key_id": digest_key(self.public), "signature": None}):
            with self.trusted(), self.assertRaises(ValueError): verify_receipt(canonical(value), proposal(), REVIEW, now=NOW)

    def test_expired_future_or_overlong_signature(self):
        for now in (NOW-timedelta(hours=1), NOW+timedelta(hours=2)):
            with self.trusted(), self.assertRaises(ValueError): verify_receipt(self.signed(), proposal(), REVIEW, now=now)
        p = {**self.payload, "expires_at": "2026-10-30T09:00:00Z"}
        with self.trusted(), self.assertRaises(ValueError): verify_receipt(self.signed(p), proposal(), REVIEW, now=NOW)

    def test_persistent_receipt_claim_prevents_replay_after_restart(self):
        with tempfile.TemporaryDirectory() as td, self.trusted():
            AttemptJournal(td, self.signed(), proposal(), REVIEW, now=NOW)
            with self.assertRaises(FileExistsError): AttemptJournal(td, self.signed(), proposal(), REVIEW, now=NOW)

    def test_exact_order_caps_and_no_retry(self):
        with tempfile.TemporaryDirectory() as td, self.trusted():
            journal = AttemptJournal(td, self.signed(), proposal(), REVIEW, now=NOW)
            for job in proposal()["jobs"]: self.assertEqual(journal.reserve(job["key"]), job)
            self.assertEqual(journal.counts, {"cpsat": 24, "oracle": 8})
            with self.assertRaises(ValueError): journal.reserve(proposal()["jobs"][0]["key"])
            self.assertEqual(len(list(journal.path.glob("attempt-*.json"))), 32)

    def test_failure_order_mismatch_and_expiry_close_stage(self):
        with tempfile.TemporaryDirectory() as td, self.trusted():
            journal = AttemptJournal(td, self.signed(), proposal(), REVIEW, now=NOW)
            with self.assertRaises(ValueError): journal.reserve("wrong-key")
            with self.assertRaises(ValueError): journal.reserve(proposal()["jobs"][0]["key"])
            self.assertTrue((journal.path/"STOPPED.json").exists())
        with tempfile.TemporaryDirectory() as td, self.trusted():
            journal = AttemptJournal(td, self.signed(), proposal(), REVIEW, now=NOW)
            journal.clock = lambda: NOW+timedelta(hours=2)
            with self.assertRaises(ValueError): journal.reserve(proposal()["jobs"][0]["key"])
            self.assertEqual(journal.ordinal, 0)

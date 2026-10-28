"""Offline Ed25519 human receipt verifier and durable, single-use attempt journal.

No signing operation or private key is provided by this module. A public key
must be enrolled out of band by a separately reviewed change. Empty = deny.
"""
import base64
from datetime import datetime, timezone
import os
from pathlib import Path

from research.p1e_protocol import (VERSION, canonical, digest, exact, hash_text,
                                  strict_json, validate_manifest)

TRUSTED_LEAD_KEYS = ()  # tuple of enrolled raw Ed25519 public keys; no real enrollment in P1e
DOMAIN = b"3d-container-loading/P1e/StageA/v1\0"


def verify_receipt(data, manifest, review_head, *, now=None):
    validate_manifest(manifest)
    hash_text(review_head, 40)
    envelope = strict_json(data, 16384)
    exact(envelope, "payload key_id signature")
    payload = envelope["payload"]
    exact(payload, "schema decision source_head review_head manifest_sha256 jobs_sha256 limits worker_version evidence_root nonce issued_at expires_at")
    expected = {"schema": "p1e-human-receipt-v1", "decision": "AUTHORIZE_STAGE_A_ONCE",
                "source_head": manifest["source_head"], "review_head": review_head,
                "manifest_sha256": digest(manifest), "jobs_sha256": digest(manifest["jobs"]),
                "limits": manifest["limits"], "worker_version": VERSION,
                "evidence_root": manifest["evidence_root"]}
    for key, value in expected.items():
        if canonical(payload[key]) != canonical(value): raise ValueError("receipt binding mismatch: "+key)
    hash_text(payload["nonce"])
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None: raise ValueError("UTC-aware trusted clock required")
    def stamp(value):
        if not isinstance(value, str): raise ValueError("explicit UTC receipt time required")
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    issued, expiry = stamp(payload["issued_at"]), stamp(payload["expires_at"])
    if not issued <= current < expiry or not 0 < (expiry-issued).total_seconds() <= 86400:
        raise ValueError("expired/future/overlong receipt")
    hash_text(envelope["key_id"])
    keys = [key for key in TRUSTED_LEAD_KEYS if digest_key(key) == envelope["key_id"]]
    if len(keys) != 1: raise ValueError("no enrolled human authority for this key")
    if not isinstance(envelope["signature"], str): raise ValueError("signature absent")
    signature = base64.b64decode(envelope["signature"], validate=True)
    if len(signature) != 64: raise ValueError("Ed25519 signature must be 64 bytes")
    # Standard library is intentionally not used to implement cryptography.
    # Missing/unsupported crypto backend is a failure, never an unsigned fallback.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(keys[0]).verify(signature, DOMAIN+canonical(payload))
    return strict_json(canonical(payload))  # detached, not a mutable caller object


def digest_key(key):
    from research.p1e_protocol import sha_bytes
    if not isinstance(key, bytes) or len(key) != 32: raise ValueError("invalid pinned public key")
    return sha_bytes(key)


def _new_record(path, value):
    # A write/fsync failure leaves the exclusive claim burned, never reusable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())


class AttemptJournal:
    """Trusted local ledger directory; not an ACL/hostile-same-user boundary."""
    def __init__(self, directory, receipt, manifest, review_head, *, now=None):
        payload = verify_receipt(receipt, manifest, review_head, now=now)
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # Receipt nonce is the replay key even if the human re-signs the payload.
        self.claim_id = digest({"nonce": payload["nonce"], "key": strict_json(receipt)["key_id"]})
        self.path = self.root/self.claim_id
        self.path.mkdir(exist_ok=False)  # atomic cross-process claim, including parent restart
        _new_record(self.path/"receipt.json", payload)
        self.manifest = strict_json(canonical(manifest), 1_000_000)
        self.receipt, self.review_head = bytes(receipt), review_head
        self.clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
        self.ordinal, self.counts, self.stopped = 0, {"cpsat": 0, "oracle": 0}, False

    def reserve(self, key):
        if self.stopped or self.ordinal >= len(self.manifest["jobs"]):
            raise ValueError("closed/exhausted stage; no retry")
        try:
            verify_receipt(self.receipt, self.manifest, self.review_head, now=self.clock())
        except Exception:
            self.stop("receipt no longer valid")
            raise
        job = self.manifest["jobs"][self.ordinal]
        if key != job["key"]:
            self.stop("job order mismatch")
            raise ValueError("out-of-order/repeated job")
        kind = job["kind"]
        if self.counts[kind] >= self.manifest["limits"]["max_"+kind+"_calls"]:
            self.stop("call cap"); raise ValueError("call cap exhausted")
        _new_record(self.path/f"attempt-{self.ordinal:02}.json",
                    {"job_sha256": job["job_sha256"], "kind": kind, "state": "reserved_before_launch"})
        self.counts[kind] += 1
        self.ordinal += 1
        return strict_json(canonical(job))

    def stop(self, reason):
        self.stopped = True
        path = self.path/"STOPPED.json"
        if not path.exists(): _new_record(path, {"reason": str(reason), "counts": self.counts})

"""Harmless stdout/stderr/process-tree fixture; no project imports."""
import os
from pathlib import Path
import subprocess
import sys
import time

PROBE_ENTRY_NS = time.monotonic_ns()
directory, mode = Path(sys.argv[1]), sys.argv[2]
os.write(1, b"native-stdout\n"); os.write(2, b"native-stderr\n")
if mode == "flood":
    for _ in range(256): os.write(1, b"x"*4096)
elif mode == "child": time.sleep(3)
elif mode == "tree":
    subprocess.Popen([sys.executable, "-I", "-S", "-B", __file__, str(directory), "child"],
                     stdout=sys.stdout, stderr=sys.stderr, creationflags=0x08000000)
    time.sleep(3)
elif mode == "dependencies":
    # Fixed harmless child dependency probe, NOT a native adapter invocation.
    # -I keeps environment path injection out; only the fixed repository is added.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import json
    from research.symmetry_guard import ZeroSolveGuard
    with ZeroSolveGuard() as guard:
        from research.p1f_workers import bootstrap_crypto
        bootstrap_crypto()
        from research.p1e_plan import critical_versions
        (directory/"dependency.json").write_text(json.dumps({"versions":critical_versions(),"guard":guard.evidence(),
            "numeric_environment":{k:os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS")}}))
elif mode in ("preflight_cp", "preflight_oracle"):
    # Fixed test-only workload. NEVER calls worker_cp/worker_oracle/_run_claimed.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import base64
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch
    from research.symmetry_guard import ZeroSolveGuard
    with ZeroSolveGuard() as guard:
        guard_ready = time.monotonic_ns()
        from research.p1f_workers import bootstrap_crypto, _child_preflight
        bootstrap_crypto()
        from research import p1e_receipt as receipts
        from research.p1e_protocol import canonical, digest, strict_json
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        m = strict_json((directory/"proposal.json").read_bytes(),1_000_000)
        review = strict_json((directory/"review.json").read_bytes())["review"]
        key = Ed25519PrivateKey.generate()  # ephemeral TEST key, never human authority
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        now = datetime.now(timezone.utc)
        payload = {"schema":receipts.RECEIPT_SCHEMA,"decision":"AUTHORIZE_STAGE_A_ONCE","source_head":m["source_head"],
                   "review_head":review,"manifest_sha256":digest(m),"jobs_sha256":digest(m["jobs"]),"limits":m["limits"],
                   "worker_version":m["worker_version"],"evidence_root":m["evidence_root"],"nonce":digest(public.hex()),
                   "issued_at":(now-timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "expires_at":(now+timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        receipt=canonical({"payload":payload,"key_id":receipts.digest_key(public),
                           "signature":base64.b64encode(key.sign(receipts.DOMAIN+canonical(payload))).decode()})
        roots = directory/"test-ledger", directory/"test-evidence"
        with patch.object(receipts,"TRUSTED_LEAD_KEYS",(public,)), patch.object(receipts,"trusted_stage_paths",return_value=roots):
            journal=receipts.AttemptJournal(roots[0],receipt,m,review)
            ordinal=1 if mode=="preflight_cp" else 0
            # Synthetic predecessor validation is a fixture, NOT an Oracle result.
            for i in range(ordinal+1):
                job=journal.reserve(m["jobs"][i]["key"])
                if i<ordinal:receipts._new_record(journal.path/f"validated-{i:02}.json",{"job_sha256":job["job_sha256"],"state":"validated"})
            target=roots[1]/m["evidence_root"]/"jobs"/f"{ordinal:02}";target.mkdir(parents=True)
            job=m["jobs"][ordinal]
            request={"schema":f"activation-{job['kind']}-request-v1","manifest":m,"ordinal":ordinal,"review_head":review,
                     "receipt_b64":base64.b64encode(receipt).decode(),
                     "runtime_lease":{"fingerprint":digest(m["versions"]),"state":"parent-held-through-cleanup"},
                     "attempt":{"job_sha256":job["job_sha256"],"kind":job["kind"],"state":"reserved_before_launch"}}
            prepared,_=_child_preflight(Path(__file__).resolve().parents[1],request,job["kind"],target)
            (directory/"preflight-probe.json").write_bytes(canonical({"mode":mode,"evidence_kind":"harmless_zero_solve_preflight",
                "probe_entry_ns":PROBE_ENTRY_NS,"guard_ready_ns":guard_ready,"preflight_done_ns":time.monotonic_ns(),
                "worker_phases":prepared.phases,"guard":guard.evidence(),"native_entry_calls":0,
                "scope":"real source/runtime-core/receipt/proto/durable launch claim; ephemeral TEST authority and synthetic predecessor; no native adapter body"}))
elif mode != "normal": raise SystemExit(9)
(directory/"result.json").write_bytes(b'{"kind":"dummy_ok"}')

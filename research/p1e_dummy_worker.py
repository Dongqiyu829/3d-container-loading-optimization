"""Fixed harmless protocol worker: stdlib only, never imports research/solvers."""
import hashlib
import json
from pathlib import Path
import sys
import time

VERSION = "p1e-worker-v1"
MODES = {"ok", "partial", "mismatch", "unknown", "instrumentation", "crash",
         "timeout", "memory", "flood", "oversized_response", "cpu"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result: raise ValueError("duplicate key")
        result[key] = value
    return result


class OutputLimit(RuntimeError):
    pass


class BoundedStdout:
    def __init__(self, handle):
        self.handle, self.used = handle, 0

    def write(self, value):
        data = value.encode("utf-8")
        if self.used+len(data) > 16384: raise OutputLimit("stdout quota")
        self.handle.write(data); self.handle.flush(); self.used += len(data)
        return len(value)

    def flush(self):
        self.handle.flush()


def main():
    directory, mode = Path(sys.argv[1]), sys.argv[2]
    if mode not in MODES: return 9
    with (directory/"request.json").open("rb") as handle:
        raw = handle.read(65537)
    if len(raw) > 65536: return 9
    request = json.loads(raw, object_pairs_hook=pairs)
    if (set(request) != {"schema", "dispatch", "source_head", "manifest_sha256", "job", "input", "worker_sha256"}
            or request["schema"] != VERSION or request["dispatch"] != "dummy_only"
            or canonical(request) != raw or sha(Path(__file__).read_bytes()) != request["worker_sha256"]):
        return 9
    job = request["job"]
    expected = {"oracle": "research.p1e_protocol:forbidden_oracle", "cpsat": "research.p1e_protocol:forbidden_cpsat"}
    if (job["entrypoint"] != expected.get(job["kind"])
            or sha(canonical({k: v for k, v in job.items() if k != "job_sha256"})) != job["job_sha256"]
            or sha(canonical(request["input"]["payload"])) != job["input_sha256"]):
        return 9
    status, detail = "DUMMY_OK", "fixed harmless worker; no solver result"
    response = directory/"response.json"
    original_stdout, original_stderr = sys.stdout, sys.stderr
    with (directory/"stdout.txt").open("xb") as log:
        sink = BoundedStdout(log)
        sys.stdout = sys.stderr = sink  # cooperative bounded capture, no OS pipe inheritance
        try:
            print("P1e dummy protocol only")
            if mode == "timeout": time.sleep(3)
            if mode == "cpu":
                started, end = time.process_time(), time.monotonic()+3
                while time.process_time()-started < 2 and time.monotonic() < end: sum(range(1000))
            if mode == "memory":
                chunks = []
                for _ in range(32): chunks.append(bytearray(8*1024**2))
            if mode == "flood":
                for _ in range(400): sys.stdout.write("x"*128)
            if mode in ("partial", "crash"):
                response.write_bytes(b'{"schema":')
                if mode == "crash":
                    sys.stdout, sys.stderr = original_stdout, original_stderr
                    return 7
            elif mode == "oversized_response": response.write_bytes(b"x"*65537)
            else:
                if mode == "unknown": status = "UNKNOWN"
                if mode == "instrumentation": status = "INSTRUMENTATION_CENSORED"
        except MemoryError:
            status, detail = "RESOURCE_EXHAUSTED", "dummy allocation denied; not calibrated native diagnosis"
        except OutputLimit:
            status, detail = "OUTPUT_LIMIT", "cooperative stdout quota reached"
        if mode not in ("partial", "oversized_response"):
            result = {"schema": VERSION, "evidence_kind": "dummy", "request_sha256": sha(raw),
                      "job_sha256": "0"*64 if mode == "mismatch" else job["job_sha256"],
                      "worker_sha256": request["worker_sha256"], "status": status,
                      "reported_bound": None, "stdout_bytes": sink.used, "detail": detail,
                      "actual_cpsat_calls": 0, "actual_oracle_calls": 0}
            response.write_bytes(canonical(result))
    sys.stdout, sys.stderr = original_stdout, original_stderr
    # P1d watchdog validates this control marker; protocol result is validated
    # separately, and a dummy marker can never authorize a scientific result.
    (directory/"result.json").write_bytes(b'{"kind":"dummy_ok"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

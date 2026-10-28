"""Prepare exact 24 CP protos + 8 Oracle descriptors; never execute a worker."""
from dataclasses import asdict
import importlib.metadata
import importlib.util
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile
import os

from baseline_common import load_instance
from research.symmetry_canonical_input import load_oracle_input
from research.symmetry_integration import prepare_run, RunSpec
from research.symmetry_guard import ZeroSolveGuard
from research.p1e_protocol import (SOURCES, PREDICTIONS, LIMITS, CONTROLS, VERSION, ENTRYPOINTS,
                                  MANIFEST_SCHEMA, digest, sha_bytes, job_hash, validate_manifest, oracle_identity)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def verify_sources(root, m, *, lease=None):
    verify_repository(root, m)
    if lease is None:
        if runtime_versions() != m["versions"]: raise ValueError("runtime binary/version drift")
    else: lease.check(m["versions"])


def verify_repository(root, m):
    validate_manifest(m)  # reject unknown paths before any source-path read
    if git(root, "rev-parse", "HEAD") != m["source_head"]: raise ValueError("source checkout HEAD drift")
    oracle_identity(Path(root)/"research/tiny_oracle.py")
    for path, record in m["sources"].items():
        data = (Path(root)/path).read_bytes()
        if (sha_bytes(data) != record["runtime_sha256"] or len(data) != record["bytes"]
                or git(root, "rev-parse", m["source_head"]+":"+path) != record["git_blob"]):
            raise ValueError("source bytes/blob drift: "+path)


def runtime_versions(reader=None):
    return {**critical_versions(reader), "runtime_packages_sha256": digest(runtime_packages(reader)),
            "python_stdlib_sha256": digest(python_stdlib(reader))}


def critical_versions(reader=None):
    read = reader or (lambda p: p.read_bytes())
    import ortools
    import cryptography
    import _cffi_backend
    native_root = Path(ortools.__file__).parent
    native_files = {p.relative_to(native_root).as_posix(): sha_bytes(read(p))
                    for p in sorted(native_root.rglob("*")) if p.suffix.lower() in (".dll", ".pyd")}
    if not native_files: raise ValueError("missing native OR-Tools binaries")
    crypto_binary = Path(importlib.util.find_spec("cryptography.hazmat.bindings._rust").origin)
    python_dll = Path(sys.base_prefix)/f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    return {"python": platform.python_version(), "platform": sys.platform, "pointer_bits": struct.calcsize("P")*8,
            **{key: importlib.metadata.version(key) for key in ("ortools", "protobuf")},
            "cryptography": cryptography.__version__,
            "python_executable_sha256": sha_bytes(read(Path(sys.executable))),
            "python_base_sha256": sha_bytes(read(Path(sys._base_executable))),
            "python_dll_sha256": sha_bytes(read(python_dll)),
            "ortools_binaries_sha256": digest(native_files), "crypto_backend_sha256": sha_bytes(read(crypto_binary)),
            "cffi_backend_sha256": sha_bytes(read(Path(_cffi_backend.__file__))),
            "windows_build": sys.getwindowsversion().build}


def runtime_packages(reader=None):
    """Declared runtime dependency closure; hash installed code AND metadata."""
    from packaging.requirements import Requirement
    read = reader or (lambda p: p.read_bytes())
    pending, result = ["ortools", "cryptography", "packaging"], {}
    import cryptography
    fallback = Path(cryptography.__file__).parent.parent
    while pending:
        name = pending.pop().lower().replace("_", "-")
        if name in result: continue
        try: dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            matches = list(fallback.glob(name.replace("-", "_")+"-*.dist-info"))
            if len(matches) != 1: raise ImportError("missing exact dependency metadata: "+name)
            dist = importlib.metadata.Distribution.at(matches[0])
        files = {}
        for entry in dist.files or ():
            label = str(entry).replace("\\", "/")
            if "/tests/" in "/"+label or "/test/" in "/"+label: continue
            if Path(label).suffix.lower() in (".py", ".pyi", ".pyd", ".dll") or Path(label).name in ("METADATA", "RECORD"):
                files[label] = sha_bytes(read(Path(dist.locate_file(entry))))
        if not files: raise ValueError("empty dependency inventory: "+name)
        result[name] = {"version": dist.version, "files": files}
        for text in dist.requires or ():
            req = Requirement(text)
            if req.marker is None or req.marker.evaluate({"extra": ""}): pending.append(req.name)
    return result


def python_stdlib(reader=None):
    read = reader or (lambda p: p.read_bytes())
    root = Path(sys.base_prefix)
    files = {}
    for folder in ("Lib", "DLLs"):
        for parent, dirs, names in os.walk(root/folder):
            dirs[:] = [d for d in dirs if d not in ("site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip")]
            for name in names:
                p = Path(parent)/name
                if p.suffix.lower() in (".py", ".pyd", ".dll"):
                    files[p.relative_to(root).as_posix()] = sha_bytes(read(p))
    return files


class RuntimeLease:
    """Windows read/share-read handles hold the hashed runtime immutable per stage.

    Not a defense against kernel/raw-disk or hostile same-user code closing our
    handles. No runtime-path cache is accepted after lease close.
    """
    def __init__(self, expected):
        import ctypes as C
        from ctypes import wintypes as W
        if os.name != "nt": raise OSError("runtime lease requires Windows")
        self.api, self.handles, self.closed = C.WinDLL("kernel32", use_last_error=True), {}, False
        self.api.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
        self.api.CreateFileW.restype = W.HANDLE
        self.api.CloseHandle.argtypes = [W.HANDLE]; self.api.CloseHandle.restype = W.BOOL
        try:
            self.versions = runtime_versions(reader=self._read_locked)
            if self.versions != expected: raise ValueError("leased runtime identity mismatch")
        except BaseException:
            self.close(); raise

    def _read_locked(self, path):
        import ctypes as C
        path = Path(path).resolve()
        if path not in self.handles:
            # GENERIC_READ, FILE_SHARE_READ only, OPEN_EXISTING; no inherit.
            h = self.api.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
            if h == C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
            self.handles[path] = h
        return path.read_bytes()  # lock is held before hashing the bytes

    def check(self, expected):
        if self.closed or not self.handles or self.versions != expected:
            raise ValueError("missing/closed/mismatched runtime lease")

    def close(self):
        errors = []
        for path, h in list(self.handles.items()):
            if self.api.CloseHandle(h): del self.handles[path]
            else: errors.append(str(path.name))
        self.closed = not self.handles
        if errors: raise OSError("runtime lease close failed")


def build_proposal(root):
    if ZeroSolveGuard.current is None: raise RuntimeError("proposal requires zero-Solve guard")
    root = Path(root)
    oracle_identity(root/"research/tiny_oracle.py")
    head = git(root, "rev-parse", "HEAD")
    subprocess.run(["git", "-C", str(root), "diff", "--exit-code", "HEAD", "--", *SOURCES],
                   check=True, stdout=subprocess.DEVNULL)
    sources = {}
    for path in SOURCES:
        data = (root/path).read_bytes()
        sources[path] = {"runtime_sha256": sha_bytes(data), "bytes": len(data),
                         "git_blob": git(root, "rev-parse", head+":"+path)}
    inputs, jobs, params_pool = {}, [], {}
    for case in PREDICTIONS:
        path = root/f"docs/research/symmetry-search-bias/fixtures/{case}.json"
        snapshot = load_oracle_input(path)
        raw_bytes = path.read_bytes()
        from research.p1e_protocol import strict_json
        if digest(strict_json(raw_bytes)) != snapshot.sha256: raise ValueError("fixture changed during preparation")
        # Model preparation loads a PRIVATE copy of the frozen validated bytes,
        # never the original path again. Both objectives consume the same input.
        with tempfile.TemporaryDirectory(prefix="p1e-model-input-") as td:
            frozen = Path(td)/"snapshot.json"
            frozen.write_bytes(snapshot.canonical_json)
            instance = load_instance(frozen)
        inputs[case] = {"raw_file_sha256": sha_bytes(raw_bytes), "snapshot_sha256": snapshot.sha256,
                        "payload": snapshot.raw_copy(), "provenance": "load_oracle_input/frozen-canonical-json"}
        for objective in ("volume", "count"):
            for variant in ("ORACLE", "M0", "M1", "M2"):
                if variant == "ORACLE":
                    kind, config, proto = "oracle", {"objective": objective, "max_nodes": 200000}, None
                    params = config
                else:
                    kind = "cpsat"
                    spec = RunSpec(objective, variant)
                    prepared = prepare_run(instance, spec)
                    config, params, proto = asdict(spec), prepared.metadata["resolved_parameters"], prepared.metadata["model_sha256"]
                params_sha = digest(params); params_pool[params_sha] = params
                i = len(jobs)
                job = {"ordinal": i, "key": f"{case}:{objective}:{variant}", "kind": kind,
                       "entrypoint": ENTRYPOINTS[kind], "case_id": case, "objective": objective,
                       "variant": variant, "input_sha256": snapshot.sha256, "config": config,
                       "config_sha256": digest(config), "params_sha256": params_sha, "proto_sha256": proto,
                       "manual_prediction": PREDICTIONS[case][objective], "prediction_status": "manual_not_solved",
                       "output_rel": f"jobs/{i:02}/result.json"}
                job["job_sha256"] = job_hash(job); jobs.append(job)
    versions = runtime_versions()
    proposal = {"schema": MANIFEST_SCHEMA, "source_head": head, "worker_version": VERSION,
                "versions": versions, "sources": sources, "inputs": inputs, "controls": dict(CONTROLS),
                "limits": dict(LIMITS), "parameters": params_pool, "jobs": jobs,
                "evidence_root": "results/stage-a-p1f-review-v1", "execution_authorized": False}
    validate_manifest(proposal)
    # runtime_versions was computed immediately above; do not rehash its entire
    # inventory a second time during non-executing proposal serialization.
    verify_repository(root, proposal)
    return proposal

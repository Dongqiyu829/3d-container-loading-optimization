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

from baseline_common import load_instance
from research.symmetry_canonical_input import load_oracle_input
from research.symmetry_integration import prepare_run, RunSpec
from research.symmetry_guard import ZeroSolveGuard
from research.p1e_protocol import (SOURCES, PREDICTIONS, LIMITS, CONTROLS, VERSION, ENTRYPOINTS,
                                  digest, sha_bytes, job_hash, validate_manifest, oracle_identity)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def verify_sources(root, m):
    validate_manifest(m)  # reject unknown paths before any source-path read
    if git(root, "rev-parse", "HEAD") != m["source_head"]: raise ValueError("source checkout HEAD drift")
    oracle_identity(Path(root)/"research/tiny_oracle.py")
    if runtime_versions() != m["versions"]: raise ValueError("runtime binary/version drift")
    for path, record in m["sources"].items():
        data = (Path(root)/path).read_bytes()
        if (sha_bytes(data) != record["runtime_sha256"] or len(data) != record["bytes"]
                or git(root, "rev-parse", m["source_head"]+":"+path) != record["git_blob"]):
            raise ValueError("source bytes/blob drift: "+path)


def runtime_versions():
    import ortools
    import cryptography
    native_root = Path(ortools.__file__).parent
    native_files = {p.relative_to(native_root).as_posix(): sha_bytes(p.read_bytes())
                    for p in sorted(native_root.rglob("*")) if p.suffix.lower() in (".dll", ".pyd")}
    if not native_files: raise ValueError("missing native OR-Tools binaries")
    crypto_binary = Path(importlib.util.find_spec("cryptography.hazmat.bindings._rust").origin)
    python_dll = Path(sys.base_prefix)/f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    return {"python": platform.python_version(), "platform": sys.platform, "pointer_bits": struct.calcsize("P")*8,
            **{key: importlib.metadata.version(key) for key in ("ortools", "protobuf")},
            "cryptography": cryptography.__version__,
            "python_executable_sha256": sha_bytes(Path(sys.executable).read_bytes()),
            "python_base_sha256": sha_bytes(Path(sys._base_executable).read_bytes()),
            "python_dll_sha256": sha_bytes(python_dll.read_bytes()),
            "ortools_binaries_sha256": digest(native_files), "crypto_backend_sha256": sha_bytes(crypto_binary.read_bytes())}


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
    proposal = {"schema": "p1e-stage-a-unapproved-v1", "source_head": head, "worker_version": VERSION,
                "versions": versions, "sources": sources, "inputs": inputs, "controls": dict(CONTROLS),
                "limits": dict(LIMITS), "parameters": params_pool, "jobs": jobs,
                "evidence_root": "results/stage-a-p1e-review-v1", "execution_authorized": False}
    validate_manifest(proposal)
    verify_sources(root, proposal)
    return proposal

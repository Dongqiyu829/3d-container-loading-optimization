"""Explicit P1e/P1d-regression allowlist. Never legacy discovery or real Solve."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from research.symmetry_guard import ZeroSolveGuard
from research.run_p1d_zero_tests import RecordingResult

MODULES = ("research.tests.test_p1d_input", "research.tests.test_p1d_watchdog.ControllerTests",
           "research.tests.test_p1e_contract", "research.tests.test_p1e_receipt",
           "research.tests.test_p1e_bridge.BridgePureTests")


def load_test_crypto(site):
    # Load only the explicitly requested existing package namespace. Adding an
    # entire foreign site-packages directory can poison pandas/NumPy imports.
    try:
        import cryptography
        return
    except ModuleNotFoundError:
        if site is None: raise
    # This existing crypto build requires CFFI. Load just its dependency
    # namespaces rather than exposing the foreign site's optional ML packages.
    if importlib.util.find_spec("_cffi_backend") is None:
        backends = list(site.resolve().glob("_cffi_backend*.pyd"))
        if len(backends) != 1: raise ImportError("one compatible CFFI backend required")
        backend_spec = importlib.util.spec_from_file_location("_cffi_backend", backends[0])
        backend = importlib.util.module_from_spec(backend_spec)
        sys.modules["_cffi_backend"] = backend
        backend_spec.loader.exec_module(backend)
    if importlib.util.find_spec("cffi") is None:
        package = site.resolve()/"cffi"
        ffi_spec = importlib.util.spec_from_file_location("cffi", package/"__init__.py",
                                                        submodule_search_locations=[str(package)])
        ffi = importlib.util.module_from_spec(ffi_spec)
        sys.modules["cffi"] = ffi
        ffi_spec.loader.exec_module(ffi)
    package = site.resolve()/"cryptography"
    spec = importlib.util.spec_from_file_location("cryptography", package/"__init__.py",
                                                submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["cryptography"] = module
    spec.loader.exec_module(module)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--proposal-out", type=Path, required=True)
    p.add_argument("--crypto-site", type=Path, help="test-only read-only fallback package directory")
    p.add_argument("--os-tests", action="store_true")
    p.add_argument("--max-cpsat-calls", type=int, default=0)
    p.add_argument("--max-oracle-calls", type=int, default=0)
    a = p.parse_args(argv)
    if a.max_cpsat_calls != 0 or a.max_oracle_calls != 0: p.error("only zero Solve budgets allowed")
    if a.evidence.exists() or a.proposal_out.exists(): p.error("refuse overwrite evidence/proposal")
    modules = list(MODULES)
    if a.os_tests: modules.append("research.tests.test_p1e_bridge.ProtocolWindowsTests")
    with ZeroSolveGuard() as guard:
        load_test_crypto(a.crypto_site)
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
        from research.tests.p1e_support import proposal, ROOT
        from research.tests.test_p1e_bridge import OS_OBSERVATIONS
        m = proposal()
        files = ["research/run_p1e_zero_tests.py", "research/tests/p1e_support.py",
                 "research/tests/test_p1e_contract.py", "research/tests/test_p1e_receipt.py",
                 "research/tests/test_p1e_bridge.py", *m["sources"]]
        data = {"schema": "p1e-zero-solve-tests-v1", "source_head": m["source_head"],
                "manifest_sha256": __import__("research.p1e_protocol", fromlist=["digest"]).digest(m),
                "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                "skips": len(result.skipped), "test_allowlist": modules, "test_results": result.records,
                "versions": m["versions"], "os_protocol_observations": OS_OBSERVATIONS,
                "source_sha256": {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in files},
                "real_human_receipt_present": False, "real_key_enrollment": False,
                "receipt_tests": "ephemeral test-only key; no key/credential serialized", **guard.evidence()}
        for path, value in ((a.evidence, data), (a.proposal_out, m)):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, indent=2, allow_nan=False); handle.write("\n")
        print(json.dumps({k: data[k] for k in ("tests_run", "failures", "errors", "skips",
                                               "executed_cpsat_calls", "executed_oracle_calls")}))
        return 0 if result.wasSuccessful() and not any(guard.blocked.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

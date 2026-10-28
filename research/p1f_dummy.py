"""Harmless stdout/stderr/process-tree fixture; no project imports."""
import os
from pathlib import Path
import subprocess
import sys
import time

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
        (directory/"dependency.json").write_text(json.dumps({"versions":critical_versions(),"guard":guard.evidence()}))
elif mode != "normal": raise SystemExit(9)
(directory/"result.json").write_bytes(b'{"kind":"dummy_ok"}')

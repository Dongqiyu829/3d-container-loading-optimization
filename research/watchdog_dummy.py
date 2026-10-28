"""Bounded stdlib-only OS test worker. Never imports project or solver modules."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def burn(seconds):
    start = time.process_time()
    end = time.monotonic() + 3  # independent fail-safe, not the watchdog proof
    while time.process_time() - start < seconds and time.monotonic() < end:
        sum(range(1000))


def main():
    mode, directory = sys.argv[1], Path(sys.argv[2])
    output = directory / "result.json"
    if mode == "descendant":
        (directory / "descendant-ready").write_text(str(os.getpid()))
        time.sleep(3)
        return 0
    if mode in ("tree", "orphan", "child_cpu"):
        child = subprocess.Popen([sys.executable, "-I", "-S", "-B", __file__,
                                  "short_cpu" if mode == "child_cpu" else "descendant", str(directory)],
                                 creationflags=0x08000000)
        if mode == "child_cpu":
            child.wait(timeout=4)
        else:
            deadline = time.monotonic() + 1
            while not (directory / "descendant-ready").exists() and time.monotonic() < deadline:
                time.sleep(.005)
            if mode == "tree":
                time.sleep(3)
    elif mode == "short_cpu":
        burn(.12)
        return 0
    elif mode == "cpu":
        burn(2)
    elif mode == "sleep":
        time.sleep(3)
    elif mode == "partial":
        output.write_text('{"kind":')
        return 0
    elif mode == "crash":
        output.write_text('{"kind":')
        return 7
    elif mode == "memory":
        chunks = []
        try:
            for _ in range(32):  # bounded at 256 MiB even without enforcement
                chunks.append(bytearray(8 * 1024 * 1024))
        except MemoryError:
            output.write_text(json.dumps({"kind": "memory_exhausted",
                                          "allocated_chunk_bytes": len(chunks)*8*1024*1024}))
            return 3
        output.write_text(json.dumps({"kind": "memory_not_limited"}))
        return 4
    elif mode != "ok":
        return 9
    output.write_text(json.dumps({"kind": "dummy_ok"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

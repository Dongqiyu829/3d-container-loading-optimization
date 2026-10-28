"""Owned Windows OS stdout/stderr pipes; bounded incremental files, no threads."""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import sys
import tempfile

from research._windows_job import WindowsJob
from research.symmetry_watchdog import _supervise
from research.p1e_protocol import canonical, CHILD_ENV


class SecurityAttributes(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", C.c_void_p), ("inherit", W.BOOL)]


class PipeCapture:
    def __init__(self, directory, cap=16384):
        if os.name != "nt": raise OSError("Windows pipes unavailable")
        if type(cap) is not int or not 1 <= cap <= 16384: raise ValueError("stream cap")
        self.api = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreatePipe": ([C.POINTER(W.HANDLE), C.POINTER(W.HANDLE), C.c_void_p, W.DWORD], W.BOOL),
            "SetHandleInformation": ([W.HANDLE, W.DWORD, W.DWORD], W.BOOL),
            "PeekNamedPipe": ([W.HANDLE, C.c_void_p, W.DWORD, C.c_void_p, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            "ReadFile": ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            "CloseHandle": ([W.HANDLE], W.BOOL)}
        for name, (args, result) in signatures.items():
            fn = getattr(self.api, name); fn.argtypes, fn.restype = args, result
        self.handles, self.readers, self.child, self.files = [], [], [], []
        self.cap, self.saved, self.observed, self.exceeded = cap, 0, 0, False
        self.closed = False
        try:
            sa = SecurityAttributes(C.sizeof(SecurityAttributes), None, True)
            for label in ("stdin", "stdout", "stderr"):
                read, write = W.HANDLE(), W.HANDLE()
                self.check(self.api.CreatePipe(C.byref(read), C.byref(write), C.byref(sa), 4096))
                self.handles.extend([read.value, write.value])
                if label == "stdin":
                    self.child.append(read.value)
                    self.close_handle(write.value)  # stdin EOF; no arbitrary input pipe
                else:
                    self.check(self.api.SetHandleInformation(read, 1, 0))
                    self.readers.append(read.value); self.child.append(write.value)
                    self.files.append((Path(directory)/(label+".bin")).open("xb"))
        except BaseException:
            self.close(); raise

    @staticmethod
    def check(ok):
        if not ok: raise C.WinError(C.get_last_error())

    def close_handle(self, handle):
        if handle in self.handles:
            self.check(self.api.CloseHandle(handle)); self.handles.remove(handle)

    def child_started(self):
        for handle in self.child: self.close_handle(handle)

    def poll(self):
        for read, file in zip(self.readers, self.files):
            for _ in range(4):  # bounded per OS poll; one consumer per synchronous pipe
                available = W.DWORD()
                if not self.api.PeekNamedPipe(read, None, 0, None, C.byref(available), None):
                    if C.get_last_error() in (109, 232): break  # broken/closing pipe
                    raise C.WinError(C.get_last_error())
                if not available.value: break
                count = min(4096, available.value)
                buf, got = C.create_string_buffer(count), W.DWORD()
                self.check(self.api.ReadFile(read, buf, count, C.byref(got), None))
                data = buf.raw[:got.value]; self.observed += len(data)
                keep = data[:max(0, self.cap-self.saved)]
                file.write(keep); file.flush(); self.saved += len(keep)
                if len(keep) != len(data): self.exceeded = True

    def close(self):
        errors = []
        for handle in list(self.handles):
            try: self.close_handle(handle)
            except OSError as exc: errors.append(type(exc).__name__)
        for file in self.files:
            if not file.closed: file.flush(); os.fsync(file.fileno()); file.close()
        self.closed = not self.handles
        if errors: raise OSError("pipe close unconfirmed")


class CapturedJob(WindowsJob):
    def __init__(self, capture, **limits):
        self.capture = capture
        super().__init__(**limits)

    def start(self, argv, cwd):
        try: super().start(argv, cwd, stdio=tuple(self.capture.child), environment=CHILD_ENV)
        finally: self.capture.child_started()

    def sample(self):
        record = super().sample(); self.capture.poll(); return record

    def close(self):
        try: super().close()
        finally:
            try: self.capture.poll()
            finally: self.capture.close()


def run_harmless(mode, stage, *, proposal=None, review=None):
    if mode not in ("normal", "flood", "tree", "dependencies", "preflight_cp", "preflight_oracle"): raise ValueError("fixed dummy modes only")
    worker = Path(__file__).with_name("p1f_dummy.py")
    with tempfile.TemporaryDirectory(prefix="p1f-pipes-") as td:
        if mode.startswith("preflight_"):
            write_new(td, "proposal.json", proposal, 1_000_000)
            write_new(td, "review.json", {"review":review})
        capture = PipeCapture(td)
        factory = lambda **kw: CapturedJob(capture, **kw)
        try:
            flags = ["-I", "-B"] if mode == "dependencies" or mode.startswith("preflight_") else ["-I", "-S", "-B"]
            result = _supervise([sys.executable, *flags, str(worker), td, mode], worker.parent,
                                 Path(td)/"result.json", stage, "pipe-dummy", backend=factory,
                                 cancelled=lambda: capture.exceeded)
        finally:
            if not capture.closed: capture.close()
        result.update(evidence_kind="real_os_pipe_dummy", pipe_bytes_saved=capture.saved,
                      pipe_bytes_observed=capture.observed, output_quota_exceeded=capture.exceeded,
                      pipe_handles_closed=capture.closed,
                      stdout_hex=(Path(td)/"stdout.bin").read_bytes().hex(),
                      stderr_hex=(Path(td)/"stderr.bin").read_bytes().hex())
        for marker in ("phase-imports.json", "phase-preflight.json", "preflight-probe.json"):
            found = list(Path(td).rglob(marker))
            if len(found) == 1:
                from research.p1e_protocol import strict_json
                result[marker] = strict_json(found[0].read_bytes())
        if mode == "dependencies" and (Path(td)/"dependency.json").exists():
            from research.p1e_protocol import strict_json
            with (Path(td)/"dependency.json").open("rb") as f:
                result["dependency_probe"] = strict_json(f.read(65537))
        if capture.exceeded: stage.stopped = True; result["classification"] = "output_limit"
        else: result["classification"] = "dummy_complete" if result["complete"] else "supervisor_incomplete"
        return result


def write_new(directory, name, value, cap=65536):
    """Incremental, exclusive evidence; partial writes are never successful records."""
    data = canonical(value)
    if len(data) > cap: raise ValueError("evidence quota exceeded")
    path = Path(directory)/name
    if path.parent != Path(directory) or path.name != name: raise ValueError("fixed evidence filename")
    with path.open("xb") as handle:
        handle.write(data); handle.flush(); os.fsync(handle.fileno())

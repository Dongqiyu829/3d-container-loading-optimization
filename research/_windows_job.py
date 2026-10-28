"""Private Win32 Job Object backend. No solver imports or shell commands.

Uses atomic PROC_THREAD_ATTRIBUTE_JOB_LIST assignment (Windows 10+) instead of
the create-suspended/AssignProcess race. Unsupported hosts fail before launch.
"""
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess

SIZE_T = C.c_size_t
ULONG_PTR = C.c_size_t
HANDLE = W.HANDLE


class BasicLimits(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_longlong),
                ("PerJobUserTimeLimit", C.c_longlong), ("LimitFlags", W.DWORD),
                ("MinimumWorkingSetSize", SIZE_T), ("MaximumWorkingSetSize", SIZE_T),
                ("ActiveProcessLimit", W.DWORD), ("Affinity", ULONG_PTR),
                ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class IoCounters(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimits(C.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", SIZE_T), ("JobMemoryLimit", SIZE_T),
                ("PeakProcessMemoryUsed", SIZE_T), ("PeakJobMemoryUsed", SIZE_T)]


class Accounting(C.Structure):
    _fields_ = [(name, C.c_longlong) for name in
                ("TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")]
    _fields_ += [(name, W.DWORD) for name in
                 ("TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]


class StartupInfo(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR),
                ("lpTitle", W.LPWSTR), ("dwX", W.DWORD), ("dwY", W.DWORD),
                ("dwXSize", W.DWORD), ("dwYSize", W.DWORD), ("dwXCountChars", W.DWORD),
                ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", C.POINTER(W.BYTE)), ("hStdInput", HANDLE),
                ("hStdOutput", HANDLE), ("hStdError", HANDLE)]


class StartupInfoEx(C.Structure):
    _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", C.c_void_p)]


class ProcessInformation(C.Structure):
    _fields_ = [("hProcess", HANDLE), ("hThread", HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


class WindowsJob:
    def __init__(self, *, memory_bytes, cpu_seconds):
        if os.name != "nt":
            raise OSError("Windows Job Object backend unavailable; no fallback")
        if C.sizeof(C.c_void_p) != 8:
            raise OSError("only reviewed 64-bit Win32 ABI supported")
        self.api = C.WinDLL("kernel32", use_last_error=True)
        self.job = self.process = self.thread = None
        self.pid = None
        signatures = {
            "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], HANDLE),
            "SetInformationJobObject": ([HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
            "QueryInformationJobObject": ([HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
            "TerminateJobObject": ([HANDLE, W.UINT], W.BOOL),
            "CloseHandle": ([HANDLE], W.BOOL),
            "InitializeProcThreadAttributeList": ([C.c_void_p, W.DWORD, W.DWORD, C.POINTER(SIZE_T)], W.BOOL),
            "UpdateProcThreadAttribute": ([C.c_void_p, W.DWORD, ULONG_PTR, C.c_void_p, SIZE_T, C.c_void_p, C.c_void_p], W.BOOL),
            "DeleteProcThreadAttributeList": ([C.c_void_p], None),
            "CreateProcessW": ([W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL,
                                W.DWORD, C.c_void_p, W.LPCWSTR, C.c_void_p,
                                C.POINTER(ProcessInformation)], W.BOOL),
            "ResumeThread": ([HANDLE], W.DWORD),
            "GetExitCodeProcess": ([HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            "WaitForSingleObject": ([HANDLE, W.DWORD], W.DWORD),
        }
        for name, (args, restype) in signatures.items():
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = args, restype
        self.job = self.api.CreateJobObjectW(None, None)  # non-inheritable, unnamed
        self._check(self.job)
        try:
            limits = ExtendedLimits()
            # No BREAKAWAY flags. Descendants stay in the job. Commit memory
            # limits deny allocations; they are not RSS limits/automatic kills.
            limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x200 | 0x8 | 0x4
            limits.BasicLimitInformation.ActiveProcessLimit = 4
            # OS user-CPU backstop only. Parent accounts user + kernel separately.
            limits.BasicLimitInformation.PerJobUserTimeLimit = max(1, int(cpu_seconds * 10_000_000))
            limits.JobMemoryLimit = memory_bytes
            self._check(self.api.SetInformationJobObject(self.job, 9, C.byref(limits), C.sizeof(limits)))
            preflight = self.sample()  # no launch if accounting is unavailable
            if preflight["configured_job_memory_limit_bytes"] != memory_bytes:
                raise OSError("job memory limit readback mismatch")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check(ok):
        if not ok:
            raise C.WinError(C.get_last_error())

    def start(self, argv, cwd, *, stdio=None):
        if self.process:
            raise RuntimeError("one launch per owned job")
        size = SIZE_T()
        attributes = 2 if stdio is not None else 1
        self.api.InitializeProcThreadAttributeList(None, attributes, 0, C.byref(size))
        if not size.value:
            raise C.WinError(C.get_last_error())
        buf = C.create_string_buffer(size.value)
        self._check(self.api.InitializeProcThreadAttributeList(buf, attributes, 0, C.byref(size)))
        try:
            jobs = (HANDLE * 1)(self.job)
            self._check(self.api.UpdateProcThreadAttribute(
                buf, 0, 0x0002000D, jobs, C.sizeof(jobs), None, None))
            startup = StartupInfoEx()
            startup.StartupInfo.cb = C.sizeof(startup)
            startup.lpAttributeList = C.cast(buf, C.c_void_p)
            if stdio is not None:
                if len(stdio) != 3: raise ValueError("exact stdin/stdout/stderr handles required")
                handles = (HANDLE * 3)(*stdio)
                self._check(self.api.UpdateProcThreadAttribute(buf, 0, 0x00020002, handles, C.sizeof(handles), None, None))
                startup.StartupInfo.dwFlags |= 0x100  # STARTF_USESTDHANDLES
                startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = stdio
            pi = ProcessInformation()
            command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
            self._check(self.api.CreateProcessW(
                argv[0], command, None, None, stdio is not None,
                0x00080000 | 0x00000004 | 0x08000000,  # extended, suspended, no window
                None, str(cwd), C.byref(startup), C.byref(pi)))
            self.process, self.thread, self.pid = pi.hProcess, pi.hThread, pi.dwProcessId
            # Already in job: failures or parent death cannot leave an unowned
            # suspended process. KILL_ON_JOB_CLOSE applies even before resume.
            self.sample()
            if self.api.ResumeThread(self.thread) == 0xFFFFFFFF:
                raise C.WinError(C.get_last_error())
        finally:
            self.api.DeleteProcThreadAttributeList(buf)

    def sample(self):
        a, limits = Accounting(), ExtendedLimits()
        self._check(self.api.QueryInformationJobObject(self.job, 1, C.byref(a), C.sizeof(a), None))
        self._check(self.api.QueryInformationJobObject(self.job, 9, C.byref(limits), C.sizeof(limits), None))
        return {"cpu_seconds": (a.TotalUserTime + a.TotalKernelTime) / 10_000_000,
                "active_processes": a.ActiveProcesses, "total_processes": a.TotalProcesses,
                "terminated_processes": a.TotalTerminatedProcesses,
                "peak_job_memory_bytes": limits.PeakJobMemoryUsed,
                "configured_job_memory_limit_bytes": limits.JobMemoryLimit}

    def exit_code(self):
        if self.process is None:
            return None
        wait = self.api.WaitForSingleObject(self.process, 0)
        if wait == 0x102:  # WAIT_TIMEOUT; exit code 259 itself is legal
            return None
        if wait != 0:
            raise C.WinError(C.get_last_error())
        code = W.DWORD()
        self._check(self.api.GetExitCodeProcess(self.process, C.byref(code)))
        return code.value

    def terminate(self):
        self._check(self.api.TerminateJobObject(self.job, 0xE0000001))

    def close(self):
        errors = []
        # Close job first: last-handle close is an independent tree-kill backstop.
        for name in ("job", "thread", "process"):
            handle = getattr(self, name)
            if handle:
                if not self.api.CloseHandle(handle):
                    errors.append(C.get_last_error())
                setattr(self, name, None)
        if errors:
            raise OSError("CloseHandle failed: " + repr(errors))

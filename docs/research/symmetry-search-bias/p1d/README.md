# P1d: canonical input parity and Windows watchdog, zero solves

Task: [#37](https://github.com/Dongqiyu829/3d-container-loading-optimization/issues/37).
Base: accepted P1c `003d54c65e826935cefef3ee61187f5c44ba38fe` / Draft PR #35.
This is a new isolated, stacked branch, not a merge of any research PR.

## Scope and source provenance

All eight new Python files were authored for P1d. Only research modules, their
tests and this new documentation/evidence directory are added. No production,
GUI, defaults, requirements, old plans/evidence or historical output is edited.
No additional October source, data, log or commit ancestry is imported.

`research/tiny_oracle.py` stays the accepted source: 7432 raw bytes,
SHA-256 `8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8`,
Git blob `02d9eed12e422666088028a021e21ef1ee2c519a`. DFS, pruning and budgets
are untouched. The new worktree initially converted it to CRLF on checkout;
its working bytes were restored from the accepted Git blob without rewriting
source. It has no committed diff. Future checkouts must recheck raw bytes.

## Canonical adapter

`load_oracle_input(path)` calls the original `baseline_common.load_instance`,
including its complete existing `validate_solution(raw, empty_witness)` path.
It serializes that same in-memory `instance.raw`; it never reopens the input
after validation. A frozen byte snapshot and its SHA-256 are returned.
`raw_copy()` returns detached JSON for later transport. This SHA identifies the
sorted JSON snapshot, not the original pretty-printed input file's bytes.

No fields are repaired, dropped or defaulted to hide schema errors. Tests cover
explicit null weight without capacity, unknown top/type keys, malformed units,
nonpositive/bool/fractional dimensions, missing capacity weights, invalid and
duplicate orientation tokens, all eight existing fixtures, consumer mutation
and replacement of the source file during validation. These are validation
tests, not fixture solving or optimality acceptance.

There is no Oracle invocation here. A future reviewed worker must use this
adapter and pass this exact snapshot immediately to the unchanged Oracle;
it must not reload an unvalidated path or accept caller-mutated raw JSON.
The unchanged standalone Oracle CLI remains a legacy bypass of prevalidation;
it is not an approved experiment entry. No claim of blocking manual Python or
hostile code in the same interpreter is made.

## OS backend and controller

`_windows_job.WindowsJob` uses ctypes/kernel32, no third-party dependency:

- An unnamed, non-inheritable Job Object with KILL_ON_JOB_CLOSE, no breakaway,
  active-process limit 4 and job commit-memory limit is created before launch.
- Extended STARTUPINFO + PROC_THREAD_ATTRIBUTE_JOB_LIST assigns the process
  atomically at creation. CREATE_SUSPENDED allows an accounting check before
  resume; CREATE_NO_WINDOW hides workers. There is no create-then-assign gap.
- No handle inheritance, shell, PID scanning, taskkill or broad process kill.
  Descendants inherit the job. Unsupported attribute/nesting/ABI/accounting
  fails closed; no unowned subprocess fallback exists. Only 64-bit Windows
  10+ ABI/API is implemented; the observed host was build 26200.
- QueryInformationJobObject reads TotalUserTime + TotalKernelTime, including
  exited descendants, in 100-ns units. Final accounting is retained before
  closing the job. No parent CPU, wall time or live-PID-only estimate replaces
  cumulative child CPU.
- PerJobUserTimeLimit is an OS **user-mode CPU** backstop. The parent separately
  polls aggregate user+kernel CPU and adds each completed/failed job's final
  CPU into the sequential stage ledger. It does not reset that ledger per job.
- Parent monotonic deadlines begin before backend setup/CreateProcess, covering
  process startup/import/build. Stage wall starts on stage creation. Timeout,
  accounting failure, unexpected root exit with live descendants, or any failed
  job closes the stage. Reserve before launch; repeated keys/attempt expansion
  are refused; no child launch retries exist.
- TerminateJobObject targets the whole owned tree. Cleanup requires zero active
  members **and** a signaled root process, then reads final CPU before closing
  handles. KILL_ON_JOB_CLOSE is the last-handle backstop. Unknown final CPU or
  unconfirmed cleanup is never reported as complete and forbids another job.
- After a root exit, refresh accounting and allow up to 100 ms for asynchronous
  job-member counters to drain before diagnosing a remaining descendant. Wall,
  stage and CPU limits remain live throughout; this never enlarges a deadline.
- Output is read only after exit/cleanup, capped at 64 KiB. Missing/malformed/
  partial/nonzero output does not establish completion. Resource and supervisor
  failures retain distinct reason fields. Final CPU/deadlines are checked again
  after cleanup/output processing so late budget crossing cannot become success.

`symmetry_watchdog.run_dummy` exposes only a fixed mode allowlist and fixed
`sys.executable -I -S -B watchdog_dummy.py ...` argv. Dummy code imports only
stdlib, has independent bounded work (3-second sleeps / bounded CPU / at most
256 MiB attempted allocation), and cannot receive instance/solver/shell argv.
Its disposable output directory is not its CWD. Private backend seams exist
for testing, not as an approved general command/experiment dispatcher.

## Evidence: simulation versus real OS observations

Final command (Python 3.12.11, Windows 10.0.26200, 64-bit):

```powershell
python -B -m research.run_p1d_zero_tests --os-tests --evidence results/NEW-p1d-tests.json
```

Omit `--os-tests` for the 35 input/gate/controller tests only. Always use a fresh
evidence path. The runner installs ZeroSolveGuard before its explicit P1d-only
test allowlist; legacy discovery/full suite is not used. It refuses evidence
overwrite. Child dummy interpreters exclude site/project imports via `-I -S`.

Final record: **45/45 pass, 0 failures/errors/skips** = 35 pure/mock tests +
10 real Windows tests; 11 dummy root launch attempts in the final suite.
Every final OS observation has final CPU known, handles closed and active job
process count zero. CP-SAT/Oracle calls and guard-blocked attempts are all zero.
See [tests.json](evidence/tests.json), [test.log](evidence/test.log), and the
byte-level [publication manifest](evidence/publication-manifest.json).

| Real dummy case | Observed result in final record |
|---|---|
| normal, two-job cumulative CPU | complete; CPU 0.046875 + 0.046875 = 0.09375 s for the paired stage |
| descendant CPU | complete; whole-job CPU 0.21875 s, TotalProcesses 6 |
| root exit leaving descendant | ORPHANED_DESCENDANT; tree stopped, final active 0 |
| tree timeout, child cap 0.6 s | CHILD_WALL_LIMIT; inclusive cleanup wall 0.609 s, final active 0 |
| stage deadline 0.4 s | STAGE_WALL_LIMIT; inclusive wall 0.422 s; subsequent reservation denied |
| CPU cap 0.1 s | CUMULATIVE_CPU_LIMIT; observed final CPU 0.109375 s |
| memory commit cap 100663296 bytes | allocation denied after 83886080 chunk bytes / MemoryError reported; configured limit read back unchanged; observed peak 103108608 bytes |
| partial JSON / exit 7 | PARTIAL_OR_MISSING_OUTPUT / CHILD_ERROR; neither is completion |

TotalProcesses is the OS job counter, not a hand-count of unique Python PIDs;
this environment's venv redirector/process chain affects the values (normal 3,
descendant cases 6). These observations are bounded smoke tests on one host,
not benchmark/performance data or native solver validation.

Mock-only coverage includes prelaunch accounting failure, launch failure,
query/decreasing/final-over-budget CPU, kill/close failure, stage admission,
no retry, slow setup inclusion and live-descendant detection. Those injected
errors are **not actual Win32 failure experiments**.

Development failures are retained in [development-runs.json](evidence/development-runs.json):
30 tests initially had one Oracle newline-identity failure; first 40-test OS
round had a peak-memory assertion failure and temp-CWD cleanup error. The latter
led to explicit root-signal confirmation and non-disposable CWD. The memory test
now checks actual configured-limit readback and allocation rejection, reporting
peak independently instead of falsely asserting peak/RSS never exceeds the cap.
The subsequent 44-test review round exposed three false orphan classifications
from asynchronous job counters; the bounded drain and two race regressions
resolve those in the final 45-test record. Four OS development rounds launched
11 fixed dummy roots each (44 total), always in fresh stages after code changes,
not automatic retries of experimental jobs. All rounds had zero solver calls.
These are new P1d test observations, not October historical artifacts.

## Limits of protection and portability

Wall and combined CPU are supervised by a scheduled parent, with poll interval
and termination/cleanup latency. They are **not mathematical hard real-time**
deadlines. The above wall/CPU overshoots are recorded, not hidden. OS job user
time checking also has granularity and does not itself limit kernel CPU.
Parent suspension/hang, system starvation, crash during accounting, handle
duplication by hostile same-user code, PPL/protected processes and adversarial
escapes have not been validated. KILL_ON_JOB_CLOSE is configured/documented;
parent-crash behavior was not separately fault-injected in real OS tests.

The memory limit controls committed job memory, not RSS. The observed peak
exceeded its configured value by 2445312 bytes while allocations were denied;
this round does not certify a zero-overshoot memory ceiling. Memory exhaustion
is dummy-reported, not a calibrated generic diagnosis for future native workers.
Review safety margins/classification before any experiment run approval.

Other Windows versions, nesting policies, restricted accounts and 32-bit hosts
are unvalidated; unsupported setup aborts. POSIX has no enforcement backend and
fails closed; Windows tests are explicitly skipped there, never called OS proof.
Current dummy limits are test settings, **not approved Stage-A resources**.

## Approval and measurement gates

All inherited positive-budget entries remain unmodified and refuse execution.
`request_native_execution` unconditionally refuses even an approval boolean,
digest or zero budget. `proposal_digest` merely validates/binds explicit source,
config, job/input hashes, per-kind caps and wall/CPU/memory resources; it is
neither signed approval nor an implemented receipt verifier/dispatcher.
No real CP/Oracle worker or Stage A is available in P1d.

Trace overflow in existing capture causes StopSearch/trace_overflow; classify
it as **instrumentation_censored**, not an ordinary time-limited observation.
The new pure classification helper is tested; no live callback was exercised.
Later A/A calibration must separately bind identical source/proto/input/hints/
parameters/seed/order, alternate capture/logging off/on, and record extraction,
inclusive callback, total wall, terminal deterministic time and overflow. No
overhead estimate or LP/presolve grammar calibration follows from these tests.

Before any Stage A: mentor review, remaining watchdog/memory/portability risks,
separate approved immutable manifest + exact per-kind/resource caps, reviewed
native worker/receipt verification and a separate run authorization. P1d itself
does not authorize these implementations/runs. All research PRs stay draft and
unmerged. CI is intentionally skipped because inherited workflows solve models;
no CI success is claimed. Stop after issue handoff.

## Primary API references

- [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
  (membership, breakaway and last-handle close behavior).
- [UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
  (atomic job-list creation attribute, Windows 10+).
- [Job accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)
  (active and exited members' user/kernel CPU).
- [Basic limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)
  and [extended limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)
  (user CPU, active process and commit-memory semantics).
- [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)
  (termination of job/child jobs).

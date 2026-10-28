# P1f: minimal native adapters and fail-closed chain, ZERO Solve

Task #41, stacked on P1e PR #40 at `732caeaf25fc4ba192b14d00d20a47f403535ce9`.
No production/Oracle/default edits, no October data/history, no merge or Stage A.
Existing p1e_* modules are reused and upgraded to p1f schema/domain/entrypoints;
P1e manifests/receipts are historical and explicitly rejected. No new framework.

## Minimal closure

`p1f_workers` freezes canonical input through the accepted adapter, reconstructs
existing M0/M1/M2 and verifies deterministic proto/full resolved parameters.
Separate CP and Oracle request/result schemas prevent CP bound fields on Oracle.
CP body binds existing Capture/make_callback/collect_terminal to the prepared
solver. Oracle body calls only the original physical problem and max_nodes200000;
ResourceLimit maps to incomplete, not OPTIMAL/UNSAT. The actual Oracle import
and both native calls exist only AFTER an unconditional execution refusal.
Public stage, native supervisor, worker functions and worker CLI remain closed;
test keys, approval flags and positive budgets cannot turn them on.

Private adapter bodies are exercised ONLY with Mock engines and supplied
responses; they are not a security sandbox against arbitrary same-user Python.
Final validation reuses physical geometry/weight/orientation checks, count or
volume recomputation and Forward/Reverse labels. UNKNOWN never supplies a usable
solver UB. Oracle has no CP best bound. Trace overflow is instrumentation_censored.
Intermediate callback events remain reported-only; A/A/LP/event-DT calibration
is still separate. Mock validation never establishes native solver provenance.

`p1f_stage` joins exact source/review/proposal checks, real receipt verification,
durable attempt reservation, exclusive evidence, owned supervision and final
physical/Oracle/manual cross-check. The real supervisor binding is itself
unconditionally closed. Tests drive the private chain using an explicit mock
review/supervisor, ephemeral test authority and real attempt journal, not a
fake runtime authorization flag. Failed creation consumes the attempt; retries,
order/expiry/resource/cleanup errors stop. No successful control marker alone
establishes a valid scientific result.

## Dependencies and runtime lifetime

P1e's list missed indirect repository imports (benchmark/greedy/BR helpers).
The new static AST import closure includes packages/nested imports without
running legacy experiments. It hashes only existing/public sources; no BR raw
corpus is needed for these fixtures. Every actual repo file byte/Git blob is
bound. Oracle raw bytes must stay7432 / SHA256
`8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8` /
blob `02d9eed12e422666088028a021e21ef1ee2c519a`; CRLF fails, never normalizes
silently. A fresh checkout's EOL was restored from the accepted blob before work.

Runtime identity includes declared transitive packages, actual installed runtime
code and METADATA/RECORD (excluding unused tests), core standard library/DLLs
(excluding site packages/tests/GUI tooling), executable/native binaries, versions
and Windows build. Full audit initially inspected35 repo sources,14 packages,
1262 package code/metadata files and625 stdlib files; code growth may enlarge
the repo closure. It took about9s, so it cannot be repeated inside a2s worker.

The parent RuntimeLease hashes while holding non-inheritable Windows read handles
with FILE_SHARE_READ only; standard writes/deletes are denied through cleanup.
The stage pays this once; every job rehashes repo sources/proto and checks the
live lease. The child rehashes core binaries/source and binds the exact parent's
lease claim/attempt/receipt. The lease claim is a trusted-parent protocol claim,
NOT cryptographic proof against a hostile manual child invocation. Supported
entrypoints are closed anyway. Trust assumptions remain a controlled host,
audited parent and protected source/ledger directories, not hostile same-user
code/raw-disk/kernel access. Lease close forbids reuse; test handles are released.

The current test interpreter borrows existing crypto/CFFI namespaces read-only.
A future native child must have the same pinned dependency identities; missing
or different packages fail preflight, with no unsigned/degraded fallback. Actual
child dependency/bootstrap timing has not been calibrated by solver execution.

## OS stdout/stderr and evidence

Existing WindowsJob gains optional explicit stdio handles. Atomic job assignment
is retained; STARTF_USESTDHANDLES plus a3-handle inheritance allowlist keeps all
other parent handles, including runtime leases, out of the child. Parent alone
polls PeekNamedPipe/ReadFile (one reader per synchronous pipe), drains bounded
chunks, writes stdout/stderr incrementally to exclusive files, and kills the
owned job on a shared16KiB quota. No callback disk I/O and no unbounded pipe buffer
or capture thread. Files/results are new-only, capped and fsynced. Raw OS resource
evidence is preserved even when parsing fails. Native response logs are separately
bounded; overflow/incomplete data stops rather than certifying an optimum.

Harmless fixtures use os.write to real stdout/stderr, bounded flood and a bounded
descendant tree. They do not import project code/solvers. One host's OS tests do
not prove parent-crash, nested-job/other Windows policy, synchronous-pipe behavior
under other concurrency models or zero resource overshoot. Job commit != RSS;
user+kernel CPU/wall polling and termination have latency. No parent-crash fault
injection is claimed. Parent failure leaves the receipt consumed and missing
terminal evidence is incomplete; no automatic restart.

## Source/review freeze and test entry

Freeze source S, run the explicit guarded suite at S, then append evidence R
without source edits. Generate a NEW32-job p1f proposal: T00-T03 volume/count,
Oracle/M0/M1/M2;24 CP +8 Oracle proposed only. Bounds/controls/order/budgets remain
as reviewed: worker1/seed0/LP2/SYM2/presolve/probing2/cold/B0/source order, exact
gaps0, trace128, child ceiling2s/stage90s/CPU75s/commit256MiB, stop margins1.8s/
88s/70s. Parent ledger uses the same existing sequential watchdog with these
manifest limits. No resource increase or run authorization. Full preflight and
child startup costs may still cause safe early stopping; do not enlarge silently.

```powershell
python -B -m research.run_p1f_zero_tests --crypto-site <existing-read-only-site-packages> --evidence results/NEW-tests.json --proposal-out results/NEW-proposal.json
```

Only explicit source/proto/mock and fixed harmless OS tests run. Trust registry
stays empty; human keys are never generated/enrolled by the agent. Tests use
ephemeral non-human keys only, never publish credentials. Signed receipt/journal
reuse P1e implementation with new domain/schema; actual human enrollment and
separate immutable-manifest authorization remain required. P1f acceptance alone
does not authorize Stage A. CI skipped because inherited workflow solves models.
Stop after source/evidence PR and Issue #41 handoff for ACCEPT/REVISE/BLOCK.

Primary API references: Microsoft Learn UpdateProcThreadAttribute (HANDLE_LIST,
JOB_LIST) and PeekNamedPipe. Their documented handle/concurrency requirements
are not replaced by the submitted one-host tests.

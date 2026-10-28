# P1b: zero-solve research integration architecture

Task [#34](https://github.com/Dongqiyu829/3d-container-loading-optimization/issues/34);
accepted P1a base bda901daf5a802a50dcc1f69e1b2a2c782d2fd1b.
This is a stacked review branch; PR #33 is not merged or modified.
Production, old diagnostic runners, canonical loader, grouping and GUI stay unchanged.

## Source reconciliation and publication boundary

source-reconciliation.json records exact Git-blob bytes and SHA-256, API/import
AST review, both branches' SHA and decisions. The existing October tiny Oracle
needs just ONE source file (research/tiny_oracle.py, 7432bytes, SHA-256
8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8).
It depends only on Python standard library; no additional dependency needed.
Its source file publication is **pending explicit user consent to this allowlist**,
as required by #34. The file is NOT in this PR. The source inventory contains
hashes/AST API facts, not an embedded source capsule or old results.

The existing validator, loader, grouping, reverse diagnostic helper and pinned
requirements are byte-identical in October and P1a. Production CP-SAT differs in
post-solve bound handling, but its two model-construction functions have identical
AST. No need to merge those production fixes: new research extraction uses P1a
pure bound contracts. Do not reuse the legacy diagnostic Solve path for new runs.

Excluded: October parent commits, oracle_acceptance.py (unconditionally solves),
old tests that solve, all historical raw results/logs/corpus, reports, GUI,
production bound patches and README divergence. No project-level license found;
do not invent licensing or redistribute third-party BR data. The source allowlist
was inspected for private paths/credentials/machine IDs and result payloads.

## Implemented adapters (not an execution stage)

- symmetry_integration.prepare_run builds existing M0/M1/M2 via P1a adapter,
  applies explicit volume/count, group/order/volume-bound and CP parameters.
  It constructs a Python CpSolver configuration holder, not a native SolveWrapper.
- Full resolved parameter defaults and explicit settings, raw proto hash,
  pre-model counts and per-order paired M0 key are captured. Interleaving changes
  whole construction/pair order, not a pure representative.
- make_callback constructs a real CpSolverSolutionCallback, never starts search.
  Capture stores <=128 scalar events and **one** first-incumbent witness of <=5
  boxes. No geometry validation/IO in callback. Further events contain only
  scalars; overflow requests StopSearch in the callback binding.
- collect_terminal consumes an already supplied response/variable reader:
  reused extraction, independent physical validator, objective recomputation,
  M1/M2 selected-label direction, exact-gap OPTIMAL consistency, UNKNOWN
  raw/usable/independent bounds, LP iterations/logging, presolve and clocks.
- First/terminal witness verification is offline. Intermediate scalars are
  reported_only, not claimed independently validated packings. First capture
  extraction cost and inclusive callback cost are separately named; neither is
  a calibrated observer-effect measurement.
- compare_oracle_response validates a **supplied** original-problem Oracle result,
  not invokes Oracle. Its witness need not use prefix labels. It checks
  objective, witness, exact CP status and manual prediction; incomplete/wrong
  objective/invalid witness/mismatch stop. Mock agreement is not native evidence.
- Native LP/presolve grammar remains uncalibrated; event DT always unusable.
  Raw/scalar clocks stay separate, invalid wall clocks/trace overflow/LP0
  contradictions are stop reasons. No mechanism or performance claim.

The old plan CLI is retained unchanged. New integration plan is also plan-only;
fake approval flags cannot open an execution path. There is NO worker dispatcher,
subprocess launcher, real Oracle call or CP-SAT Solve in the new integration code.

## Allowed reproduction

Python3.12.11 / OR-Tools9.14.6206, repository root, fresh output names:

~~~powershell
python -B -m research.run_p1b_zero_tests --evidence results/NEW-ID-tests.json
python -B -m research.symmetry_integration_plan --stage plan --max-cpsat-calls 0 --max-oracle-calls 0 --output-dir results/NEW-ID-plan
~~~

The runner installs the inherited guard BEFORE its explicit four-module allowlist.
Existing legacy test discovery must NOT run. Expected intentional probes remain
four denied CP API aliases, one denied native constructor and one denied Oracle
stub; any other blocked attempt fails. Captured evidence reports executed calls0/0.
Mocks are labeled mock; no solver-generated packing or native log is published.

## Watchdog and remaining gates

symmetry_budget is a **pure simulated decision model**, not OS enforcement:
reserve attempted-call slots before future launch, reject retry expansion, stop
at child wall2s, cumulative child CPU75s or stage wall90s, fail closed if CPU
accounting is unavailable. Decisions only describe terminate/kill for owned
children; no process is launched or killed in P1b.

Before Stage A, separately review/implement a parent supervisor with owned child
handles/process-tree cleanup (Windows Job Object or equivalent), monotonic
deadline started before import/build, cumulative child CPU accounting including
failed/timeout jobs and no parent-only accounting. Parent must enforce hard
limits independently of cooperative solver limits/Oracle node limits.
Absence of this supervisor means Stage A is BLOCKED, not safely executable yet.

Observer A/A calibration remains separately approved: fixed source, proto,
instance, hints, parameters and paired execution order; tracing/logging off/on
with extraction/inclusive callback/total wall costs, terminal DT and overflow.
Do not interpret wall-time causality from mocks or uncalibrated capture.

Review source consent, adapter/measurement invariants and supervisor design
first. No automatic source publication, Stage A, P2, A/A, benchmark or PR merge.
All commits keep [skip ci] because inherited CI runs solver tests and smoke.

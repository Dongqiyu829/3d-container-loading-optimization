# P1a — research-only, zero-solve infrastructure

Task: [#32](https://github.com/Dongqiyu829/3d-container-loading-optimization/issues/32).
Design: [#30](https://github.com/Dongqiyu829/3d-container-loading-optimization/issues/30#issuecomment-6460151999).
Clarifications: [acceptance](https://github.com/Dongqiyu829/3d-container-loading-optimization/issues/30#issuecomment-6460287813).
Framework PR #28 remains draft, unmerged.

## Provenance and scope

This isolated branch starts at **remote main ec368323080a12f6efe8e44db78d24e30c0d7adf**.
It does not merge or publish local October 7e867cd or ignored historical results.
Changes are additions under research/ and this documentation tree. Production
CP-SAT, canonical loader, grouping generator, Hybrid, GUI and existing diagnostic
runners are unchanged.

The local October tiny Oracle is an existing dependency for a later gate.
Its relative source path, unpublished commit and SHA-256 are recorded in
micro-v1.json. **Its source is not copied here; plan mode does not import or
invoke it.** Source publication/reuse in an executable stage needs a separate
approved source review. There is no substitute/reimplemented Oracle.

## Mathematics and fixtures

Let F contain feasible labeled **selected physical states**. The group
Gamma = product_g Sym(G_g) permutes whole selected states within groups with
identical type, dimensions, permitted tokens, weight, objective coefficient and
individual restrictions. Unselected free variables and separator witnesses are
outside this physical equivalence relation.

Define q:F -> F/Gamma. Forward F1 and reverse F2 intersect every orbit:
**q(F1) = q(F2) = F/Gamma**. They do not equal the quotient or select a unique
full representative: k! selected label/position permutations remain.
Moving whole selected states to first/last k labels preserves geometry, weight
and objective. This proves physical optimum preservation under these assumptions,
not better search speed.

T00–T07 are new multi-copy JSON fixtures matching the approved design. Their
volume/count manual predictions are (0,0), (2,2), (3,3), (3,2), (2,1), (8,2),
(4,1), (1,1). These are **manual predictions, not solver results**.
Pure canonical-input validation/model construction passed; Oracle/CP optimality
comparisons have not happened.

## Run only the guarded allowlist and plan

From the repository root with Python3.12.11 and OR-Tools9.14.6206:

~~~powershell
python -B -m research.run_zero_tests --evidence results/NEW-ID-tests.json
python -B -m research.symmetry_micro_acceptance --stage plan --max-cpsat-calls 0 --max-oracle-calls 0 --output-dir results/NEW-ID-plan
~~~

Paths must be new. Do not use legacy unittest discovery: existing tests solve
models. The dedicated runner installs its guard BEFORE importing an explicit
three-module allowlist. It patches four CP-SAT Python API aliases and the native
SolveWrapper constructor; Oracle is a denying stub. Expected intentional mock
probes are counted separately from executed backend calls. Unexpected blocked
attempts fail the runner. This closed Python harness guard is not an OS security
boundary for arbitrary native code or previously cached foreign references.

CLI accepts only stage=plan and exactly zero budgets. No executable stage exists;
execute_plan refuses even fake approval flags. The 48 CP/16 Oracle entries are
future core-a/core-b counts, not permission. Each proposes 24 CP/8 Oracle,
per-call2s, stage wall90s/CPU75s; plan mode neither runs nor enforces solver budgets.

Research model adapter reuses the existing CP builder/reverse helper. It adds no
variables/new packing formulation, supports volume/count explicitly, reports
actual/potential edges and keeps M0 matched per full construction order.
Multi-type interleaving also changes pairwise construction order; it is **not a
pure representative intervention**. Single-group interleaving can be degenerate.
M3/M4 and hint-run orchestration remain deferred.

## Evidence and risks

See DATA_CONTRACT.md, bound-record.schema.json and evidence/p1a/.
The committed 43-test log and generated plan have zero executed CP/Oracle calls.
Log tests use synthetic grammar fixtures, not native-run logs. Geometry checks
use hand-constructed witnesses, not solved ones.

Telemetry is NOT wired into old run_diagnostic_solve. Its UNKNOWN-bound/count
limitations remain; do not use that solve path for new research until approved
integration. No performance, real LP activity, presolve timing, tiny optimality
or callback-overhead result is claimed.

BoundedTrace accepts at most128 scalar events by default (configuration max4096),
rejects witness payloads, does no geometry/IO and reports overflow. It is a pure
recorder, **not an installed callback**. Recorder processing excludes extraction
and is not total callback overhead. Offline witness validation and bounded
extraction still need approved wiring.

Before wall-time causality, separately approve instrumentation A/A: identical
source/model/instance/hints/parameters; paired logging/scalar capture off/on
repeats, interleaved execution order, extraction/processing cost, dropped events,
total wall and terminal DT. Keep future witnesses bounded (first/final or target,
<=5 boxes here), validate offline, stop on overflow/material measurement bias.
Do not silently enlarge traces or interpolate uncalibrated event DT.

Commit uses [skip ci]: existing push/PR CI otherwise runs solver tests/benchmark
smoke. Checks may be pending/skipped; **CI success is not claimed**.
[GitHub skip behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).

Stop after draft review. Stage A, October publication, benchmarks, Solve-path
integration, A/A calibration and PR #28 merge each require new approval.

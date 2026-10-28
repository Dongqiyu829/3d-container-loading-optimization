# Proposed Stage A (NOT authorized / NOT executed)

Inputs T00–T03; each volume and count. For each input/objective:
one independent Oracle result, then M0/M1/M2 separately. Total **8 Oracle
references and24 CP attempts**,32 owned child jobs, no retries. Each case's
manual predictions remain T00(0,0),T01(2,2),T02(3,3),T03(3,2).
T04–T07 (another24CP/8Oracle) is a separate later gate.

Current plan-only manifest enumerates all48 future CP rows/16 Oracle references,
with core-a/core-b labels. Static candidate counts for T00–T07 are
0,6,9,8,3,6,8,8. These are closed-form counts, not enumerated placements,
Oracle search or optimum verification.

## Frozen controls and call accounting

- Source baseline/approved Oracle source SHA, Python3.12.11, OR-Tools9.14.6206.
- worker1,seed0,LP2,symmetry2,presolve true,probing2,nohint,volume_bound false,
  exact absolute/relative gap0,source construction order. No tuning.
- CP internal Solve limit2s. Oracle default200000 DFS nodes, <=5 boxes,
  <=64 cells,<=2000 candidate placements; no enlargement.
- Proposed external child hard wall2s FROM PROCESS START, including imports/build.
  This is stricter than just solver time. Early timeout is incomplete; do not
  silently enlarge it if startup consumes budget.
- Stage hard wall90s, cumulative participating child CPU75s. Charge every
  launched/failed/timed-out attempt. CPU accounting unavailable => do not start.
- Model preparation and parsing are not valid replacements for external OS
  enforcement. That supervisor is not implemented in P1b.
- Each child gets one immutable job key/source/config/instance hash and a new
  output path; no overwriting old data. Artifact serialization/validation/startup
  costs are part of parent stage wall. Only owned children can be terminated.

## Future approval/launch design

Current CLI refuses all positive budgets, non-plan stages and fake approval flags.
After separate review, a narrowly scoped execution worker/supervisor could be
introduced. The authorization must bind exact source/job manifest hash and
call/resource caps, not an arbitrary boolean or reusable blanket approval.
The parent watchdog starts BEFORE imports/build. Before child launch reserve its
attempted-call slot; retries consume a new slot and require scope review.

Each Oracle result is on the original physical problem (no prefix logic copied
into Oracle). Require exact OPTIMAL and validator acceptance; ResourceLimit,
INCOMPLETE or process timeout does not mean UNSAT. Compare each CP optimum and
validated witness with that reference and the registered manual prediction.
M1/M2 witness also satisfies its selected-label direction; do not require the
Oracle witness to be prefix-labeled or identical to the CP witness.
No actual comparison has occurred in P1b.

Stop on model/proto/source drift, invalid witness, any value mismatch, UNKNOWN
or incomplete Oracle acceptance, contradiction in status/bounds, callback
overflow/invalid wall clock, missing required evidence or budget exhaustion.
Preserve first failure; no expansion, alternate seed or automatic rerun.

## Evidence and inference limits

Terminal raw response/log, proto/input/params/source hashes, actual calls and
external wall/CPU accounting, first/final witness, offline validation, reported
scalar trace and explicit missing metrics should be written incrementally.
Publish only reviewed sanitized new artifacts with a byte manifest; old dirty
source/results are never silently promoted to exact reproduction.

Micro fixtures are correctness/telemetry cases, not a performance population.
LP2 zero iterations can be legitimate; no LP mechanism inference. Event DT
and native parsers need calibration. Instrumentation A/A and P2 get separate
budgets, review and stop criteria.

# Issue45 — two one-shot harmless preflight calibrations

Source executed: `fd504269bd13b00fc605672626c8d09d00932030` (S*).
Reviewed artifact/Manifest: `53f44b8fd5e5ac67cf204fd17566b2fd533f7609` (R*).
Permission: explicit owner instruction for Issue45, preflight_cp and preflight_oracle once each, no native Solve. This evidence-only commit is NOT a replacement Stage-A source/review/authorization freeze.

**Calibration PASS; actual Stage A remains unapproved/NO-GO.** Exactly two harmless OS roots were created, no retries, no other dummy modes/tests/native workers. CP-SAT Solve0 / Oracle Solve0 / benchmark0 / Stage A0. No human key enrollment/signing, production/Oracle edit, Stage-A budget/Manifest edit or merge.

## Code reuse and separate calibration caps

No reviewed runtime code changed. An isolated source-S checkout reproduced the45 recorded source/fixture byte identities using the accepted checkout recipe;9 research/Oracle checkout EOLs were restored to their existing approved Git bytes, with no Git source diff. Original workspaces/results were preserved.

Only existing ZeroSolveGuard, RuntimeLease, DummyLimits/DummyStage, run_harmless and fixed test-only child signature/preflight code ran. The invocation is preserved verbatim in invocation.py.txt as an audit record, not a new production entrypoint. No test suite or proposal rebuild was run. CP probe reconstructs its frozen T00/M0 Proto; Oracle probe validates original physical input, never its DFS.

run_harmless uses one fixed ledger key. Each distinct probe therefore has a one-attempt DummyStage; neither ledger is cleared/reused. The caller computes the next stage's limits from the SAME elapsed wall and already charged final tree CPU. No fresh20s/10s allowance is granted to the second probe. A failure, unknown final CPU, bad guard, over-budget peak or incomplete cleanup stops before any next probe.

Approved maxima: child nominal5s/stop4.5s; overall stage<=20s; cumulative child user+kernel CPU<=10s; Job commit256MiB; active process limit4; poll10ms; stdout+stderr16KiB. Actual cleanup cap0.5s (tighter than allowed1s), with0.5s global cleanup reserve. The nominal child allowance is not a solver parameter. These DummyLimits are accepted by the existing generic validator; ManifestLimits/32-job constants are untouched.

The original32-job Manifest remains canonical SHA256 `13260212c82fc207e32d0e6298633f0bde54af3220e791a7f7c5dc8ab6983a54`, file-byte SHA256 `1f443bedd1c4948250e73eb5833620ce9a69d967736209c1e606f2866e395852`, with2/1.8s child,90/88s stage,75/70s CPU and256MiB. No real authority is installed. Temporary Ed25519 TEST keys exist only inside each already-reviewed fixed dummy process; no private key is published or persisted as human authority.

## Observed outcomes

| Measure | preflight_cp (T00 volume/M0) | preflight_oracle (T00 volume) |
| --- | --- | --- |
| attempts / real harmless roots |1 /1|1 /1|
| outcome / exit |complete /0|complete /0|
| stop reason |null|null|
| total child wall, including cleanup |1.281s|1.266s|
| user+kernel Job CPU |1.15625s|1.15625s|
| peak Job commit bytes |103804928|104226816|
| configured Job commit bytes |268435456|268435456|
| final active processes |0|0|
| Job total_processes counter |13|13|
| cleanup / Job handles / pipes |all confirmed|all confirmed|
| captured stdout+stderr |28 bytes|28 bytes|
| child Guard active / blocked attempts |true /all0|true /all0|
| child executed CP / Oracle / native-entry |0 /0 /0|0 /0 /0|
| complete preflight report |present|present|

Total calibration wall including parent Guard/import/review, source/runtime locks and final close: **5.078s**; cumulative child tree CPU: **2.3125s**.1931 runtime/source files were read-locked, all released. All caller acceptance-check lists are empty. Parent Guard remained active with all blocked attempts0 and CP/Oracle executions0. Child reports independently contain the same zero-call evidence.

Ownership uses the accepted atomic JobList/no-breakaway/KILL_ON_JOB_CLOSE path; root_created/launch_attempted are true and final owned-job active count0. Job total_processes13 includes cumulative process-tree activity (the preflight invokes Git), not13 probes or13 simultaneous active processes. Existing interface exports no root/descendant PID list or observed peak-active-process count; those are unavailable, not fabricated. Process limit4 is configured by the unchanged reviewed WindowsJob code.

The fixed probe never calls worker_cp, worker_oracle, _run_claimed or native adapter bodies. The CP synthetic predecessor-validation marker/test authority is a harness fixture, not an Oracle result. Successful preflight is not CP/Oracle correctness agreement or a scientific solver measurement.

## Phase readout and precision limits

Raw marker timestamps and complete guard/resource records are in calibration.json and the per-probe result files. Derived values are in phase-readout.json.

Clock: Windows GetTickCount64(), reported resolution0.015625s. A same-tick duration remains unresolved/null rather than an asserted zero. The figures below are coarse one-shot measurements.

| Phase | CP | Oracle |
| --- | --- | --- |
| launch to first dummy marker, approximate bracket |0.062s|0.062-0.078s|
| dummy Guard/test imports setup |0.391s|0.391s|
| worker project imports after Guard |0.203s|0.219s|
| bootstrap crypto/test key/journal fixture setup |0.094s|0.062s|
| receipt/review/journal verification |0.234s|0.235s|
| prepare manifest/source/core-runtime verification |0.140s|0.141s|
| input loading |same clock tick, unresolved|same clock tick, unresolved|
| CP model/Proto preparation |same clock tick, unresolved|not applicable|
| claim/phase-file finish |0.016s|0.016s|
| entire _child_preflight function |0.406s|0.407s|
| report stamp to cleanup begin (combined write/exit/poll) |0.094s|0.109s|
| parent cleanup |0.016s|same tick, unresolved|
| native call / pure search |not entered; unavailable|not entered; unavailable|

Exclusive result-writing time is NOT separately instrumented. The launch bracket includes interpreter/fixed-dummy stdlib startup; it is not isolated pure-Python startup. Worker import numbers exclude CP libraries already imported by Guard. Test authority/journal setup differs from the eventual production receipt path. No inference that native Worker startup is exactly1.281/1.266s.

Parent components: Guard/initial imports0.593s; remaining imports/Manifest/review0.563s; full runtime/source read-lease acquisition1.203s; release0.047s. No new32-job proposal construction took place. These costs are separate from child windows but contribute to the overall stage wall. Other small serialization/temporary-directory/poll overhead is included in the5.078s total.

## Recommendation — no automatic budget/source change

These two probes completed comfortably under4.5s on this occasion. They also completed in less than1.8s, whereas the earlier e58 source probes timed out at1.828/1.829s. Different source snapshot/system/cache conditions and n=1 per mode prevent a causal claim that raising the limit made execution faster, or a reliable startup quantile/worst-case bound. No A/A repeat was authorized/performed.

A separately reviewed candidate for future Stage A is **child nominal5s/stop4.5s**, keeping CP internal2s and Oracle200000 nodes,256MiB memory and other controls. Observed worst child preflight envelope1.281s plus a full2s CP call is approximately3.281s before unmeasured production differences/output costs; about1.219s remains to4.5s in that illustrative sum. This is headroom estimation, NOT a completion guarantee, and T00 is not representative of all eight physical jobs.

Do not infer that all32 native attempts fit historical90/88s stage or75/70s CPU. Extrapolating only startup1.281x32 plus CP2x24 already gives about89s before parent work and uncertain Oracle/native costs. This is an illustrative arithmetic scenario, not a forecast. A conservative review candidate remains stage180/170s and cumulative CPU120/110s, with strict failure-stop/no retries; these numbers were NOT used or adopted and may still stop early.

Owner must independently approve any native-envelope/source/key patch, re-freeze new S/R/Manifest, and separately authorize exact solver attempts/signing. Current empty authority and historical2/1.8s plan remain unchanged. No mechanism/LP/search-bias conclusion or full3D correctness claim follows from this calibration.

## Integrity and publication

calibration.json is an exact copy of the one-shot local record:9783 bytes, SHA256 `1ea2b1d3435845760b4cdd9e72bda90895c85d1bb02c4f59d2671f38c0c12414`. Per-probe attempt/result files were copied unchanged. The publication inventory supplies byte hashes/Git blobs for all other evidence files; its own identity and this evidence commit SHA are supplied in Issue45.

After both probes and all read-handle closure, the evidence branch was based on accepted R* solely to append this directory. It does not edit runtime code, existing reports or the frozen32-job Manifest. No experiment ran at the evidence-commit HEAD. No new PR or merge is needed; immutable commit links support independent review.

STOP after Issue45 handoff. Calibration-only owner permission is exhausted (two probes, once each). No automatic retry, third probe, native Solve, benchmark, Stage A, key enrollment or budget change.

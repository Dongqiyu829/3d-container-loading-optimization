# Stage A minimal activation patch — zero-Solve handoff

Owner scope: Issue #43 accepted audit comment6468838730 plus explicit code-only implementation instruction. Base PR #42 review: `a903a7dd972f499706e731b41b9749124f9ad976`. Final source S*: `fd504269bd13b00fc605672626c8d09d00932030`. Evidence/review R* is supplied by the PR head and Issue #43 handoff, avoiding a self-referencing commit hash. R* adds only this documentation/evidence directory; runtime blobs must equal S*.

**No real CP-SAT Solve, Oracle Solve, benchmark or Stage A ran. Human authority registry remains empty. Stage A is still NO-GO for authority AND resource-envelope reasons.** This patch is a code-only candidate for independent acceptance, not execution approval.

## Minimal implementation and invariant boundary

Eight existing research modules changed: p1e_protocol, p1e_plan, p1e_receipt, p1f_stage, p1f_workers, p1f_io, p1f_dummy and symmetry_watchdog. Two research test/runner files added. No new scheduling/authorization framework.

Production CP/Hybrid/GUI, model builders, physical validator, canonical fixtures, independent tiny Oracle, historical results and October ancestry are unchanged from base. Oracle actual bytes remain7432, SHA256 `8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8`, blob `02d9eed12e422666088028a021e21ef1ee2c519a`. New checkout EOL identity was restored from the existing approved blob before work; no Oracle diff. Count/volume, M0/M1 forward/M2 reverse and all solver parameters are reused, not redefined. No Full Placement Lex is introduced.

Public `execute_stage(manifest, review_head, receipt)` is the sole supported live orchestration entry. It fixes source root, trusted storage and supervisor, loops ordinals0..31, validates each result and stops on any exception. It has no custom command, supervisor, key, budget, retry or state-root argument. Without a valid enrolled human receipt it refuses before journal claim or child creation.

Five old blanket-refusal sites are now concrete validation chains, not global no-op toggles: stage, native supervisor, CLI, CP worker and Oracle worker. Legacy execution_closed/old experiment entrypoints remain closed. Test-only monkeypatch seams are inside ZeroSolveGuard, not production CLI flags.

Chain: receipt -> full runtime/source read handles -> exact current source HEAD and immutable review/manifest -> canonical input/proto/params -> persistent nonce claim and reserve/fsync -> fixed owned launch -> child receipt/source/review/on-disk reserved slot -> single-use launch claim -> one selected native binding -> cleanup/final OS accounting -> strict result/physics/objective validation -> Oracle/manual comparison -> terminal journal. Failures consume attempts; STOPPED dominates any earlier all_tasks_validated/COMPLETED marker. No automatic resume.

The signed proposal stays execution_authorized=false: proposal alone is never authority. New version/domain/schema reject prior P1f manifests and receipts. Owner enrollment/signing is NOT implemented by this delivery: TRUSTED_LEAD_KEYS is still (). Future owner-supplied public-key pinning changes source and invalidates S*/R*/Manifest; freeze again before any human signing or actual run.

## Single-use claims and source/runtime protection

Trusted state derives from the shared Git common directory under research-stage-a-activation/{ledger,evidence}; all normal worktrees share it. Public API cannot switch roots. This is a controlled single-host ledger, not anti-rollback/multi-host/hostile-user protection. Do not delete/replace it or use another clone to bypass replay state.

Child verifies actual receipt.json and attempt-NN.json, previous ordinal's validated marker and exact expected evidence directory. It creates launch-NN.json with O_EXCL+fsync, binds job/kind/PID and refuses reuse. Native-enter/return markers are separately exclusive and PID-bound. There is no return without a matching enter. Test authority/journals live only in temporary test contexts.

RuntimeLease now reuses Windows FILE_SHARE_READ handles for all41 source files as well as pinned runtime dependencies. Source bytes are verified while handles are held through tree cleanup. Primary lease1931 files; real source read/write-open denial was tested without writing any bytes. Regression tests also own a separate runtime-only lease. Both are closed by the runner. Chain tests borrow the real source/runtime handles but mock their per-chain closure wrapper; do not confuse that wrapper with an OS handle-close test.

Actual repository bytes/Git blobs, runtime metadata/code, interpreter/native binaries and Windows build are pinned. The source-checkout-bytes.json recipe explicitly records32 inherited source files and4 fixtures with checkout CRLF versus Git LF; edited sources and Oracle are raw LF. This is a raw-byte freeze, not a promise that arbitrary checkout settings reproduce it. Reviewers can reproduce each recorded transform and verify its hash; runtime verification never silently normalizes input. No production Git blob changed. Runtime inventory publishes14 packages/1262 code+metadata hashes and625 core stdlib/DLL hashes, not third-party source. No project production package installation was changed. Read locks plus controlled source/ledger roots are assumptions; no malicious same-user/kernel/raw-disk or dynamic host-attestation guarantee.

## Result provenance, failure preservation and final resources

CP/Oracle schemas remain separate. UNKNOWN has no usable solver UB; FEASIBLE remains incomplete; exact OPTIMAL requires validated objective and reported bound agreement. Oracle has no CP best bound; ResourceLimit maps to INCOMPLETE without an objective/witness. Both reuse physical validation and count/volume recomputation; only CP M1/M2 enforce prefix labels. Scalar trace overflow is instrumentation_censored; callback DT stays uncalibrated.

Native supervisor removes inherited dummy actual_CP=0/Oracle=0/dummy_payload fields. It records owned OS process/PID, reserved-attempt kind, native-entry/return markers and parser/validation evidence separately. Missing/interrupted native-entry or return stays unknown, with the reservation consumed. A failed creation is native_launch_not_created, never fake native success. Parent-only run-provenance may certify a physically validated owned native return; Mock results remain mock. These native positive paths have never been exercised with real engines.

Final acceptance requires known user+kernel CPU, valid commit accounting, peak<=256MiB, active processes0, confirmed Job/pipe handle close, bounded output and child/stage deadlines. The264MiB review field is NOT allocation permission or acceptance slack. Checks repeat after physical validation/evidence fsync and terminal summary, and after source/runtime handle closure and final journal fsync. A late STOPPED overrides an earlier all-tasks-valid marker.

Raw stdout/stderr and worker-result are exclusive; OS-terminal persists before response parsing. A targeted final fix preserves terminal accounting even if pipe close raises. Partial/missing outputs or failed evidence writes are incomplete and stop, not scientific infeasibility.

Windows Job Object algorithm/default dummy behavior is retained. Controller additions are phase timestamps and a fixed transport control_kind (dummy_ok versus worker_terminal). Atomic ownership/no breakaway/KILL_ON_JOB_CLOSE, CPU backstop and bounded capture are reused.

## Phase clocks and measured budget failure

Parent controller records setup/launch begin and return/cleanup timestamps. Child records first module entry, imports complete, receipt/review/journal verification, source verification/input load/model preparation, preflight complete, engine-enter/return, adapter return and result-written. Engine-call elapsed includes native presolve/search, not pure search. Adapter extraction/validation is outside engine-call elapsed. Startup is an approximate bracket using parent launch interval and child first-entry, not a precise isolated Python-only clock.

Phase files are sparse outside callbacks. If killed before a marker, missing durations remain censored/unknown. No callback disk I/O or new unbounded telemetry. Existing terminal solver clocks/LP/presolve contracts remain conservative; log completeness false does not certify LP activity. A/A and native event-clock calibration remain separately gated.

Observed fixed harmless preflight probes at earlier source `e58b61c47b30edd9cfa9deae47cc540a92669753` (run02):

| Probe | Stop / inclusive wall | User+kernel CPU | Job commit peak |
| --- | --- | --- | --- |
| CP T00/M0 | CHILD_WALL_LIMIT / 1.828s |1.734375s|103694336 bytes|
| Oracle T00 | CHILD_WALL_LIMIT /1.829s|1.640625s|103485440 bytes|

Both stopped under unchanged1.8s controller threshold before a full preflight return, with active processes0, cleanup confirmed and handles closed. Partial phase-imports files survived; no native adapter body was called. They include ZeroSolveGuard setup, ephemeral TEST key/journal setup and synthetic predecessor fixture work, so they are representative zero-Solve workloads, NOT measured native Worker startup. They do not establish an upper bound on native startup or a completed preflight duration. No child terminal guard record exists after timeout; do not synthesize one. Zero native calls follow from the fixed dummy code path plus parent harness guard, not a fabricated child terminal response.

Three other actual harmless roots in run02: normal complete0.125s; output flood cancelled0.110s; descendant timeout1.812s. Total5 evidenced root workers; descendant and OS total_processes counters are preserved separately. All cleanup confirmed. No preflight dummy was retried after the two timeouts.

Original nominal2s/stop1.8s includes CreateProcess, interpreter/imports, verification/model preparation, native call, output and cleanup. CP internal max_time=2 cannot fit a guaranteed full2s call within that envelope. Stage90s/stop88s also includes parent work. Final zero-worker run measured guarded proposal/proto preparation1.25182s and full runtime/source lease acquisition2.02290s on this host, paid outside child windows but within a real stage's wall budget. These are one-host observations, not universal constants or solver performance.

**Budget recommendation, NOT applied:** first approve a fresh zero-Solve-only calibration envelope (candidate child5s/stop4.5s for the two fixed probes) to obtain complete phase evidence. If proceeding to a separately approved Stage A, a provisional candidate is child5/4.5s, stage180/170s, cumulative child CPU120/110s, all other caps including256MiB unchanged. These candidate numbers are engineering headroom, NOT measured completion guarantees; derive/review final caps from completed calibration before signing. Current code and Manifest still have2/1.8,90/88,75/70. Any cap/key/source change requires a new freeze, Manifest and independent approval. No trial or budget increase is authorized by this recommendation.

## Exact test versions and scope

- Run02 at e58b61c...:55 tests,0 failures/errors/skips,60.191s. Includes real five-root harmless OS observations and source-lock write-open denial; also actual Git review objects, real test signatures/journal and mock full32 loop. Guard reports0 blocked attempts /0 CP/0 Oracle.
- Final run03 at S* fd50426...:53 tests,0 failures/errors/skips,49.726s, explicit --no-worker-tests. Adds pipe-close-error preservation Mock regression and rebuilds proposal/protos at S*. No worker processes launched; no retry of timed-out probes. Real source read-lock denial repeats, with all test leases closed. Guard0/0/0.
- The earlier OS observations are NOT claimed to be a final-S* OS rerun. Final source differs by native terminal-error preservation plus test/runner changes; dummy/OS/preflight Worker implementation and all resource caps are unchanged between those versions. Evidence retains exact source SHA and local immutable review-fixture object per run. The review fixture is created with a separate temporary Git index/commit-tree, no branch/working-file changes; it is not final R* or owner authorization.
- Initial launcher01 failed to open its Tee log because the fresh results directory was missing. No JSON/log was produced, so it is not accepted test evidence or an attestation of root counts. history.json preserves this recording failure. A results directory was created and run02 used new names. No existing results overwritten.
- No full legacy suite/solver-running CI. Commits use [skip ci]; no CI-pass claim. Raw test logs are available with exact hashes in publication manifest. All test keys are ephemeral and never published as human credentials.

Example zero-worker check (placeholders, not instructions to run Stage A):

~~~powershell
New-Item -ItemType Directory -Path <NEW_EVIDENCE_DIRECTORY>
& '<PINNED_PYTHON_EXE>' -B -m research.run_stage_a_activation_zero_tests --crypto-site '<EXISTING_READ_ONLY_CRYPTO_SITE>' --no-worker-tests --evidence <NEW_EVIDENCE_DIRECTORY>/tests.json --proposal-out <NEW_EVIDENCE_DIRECTORY>/proposal.json
~~~

Only the explicit allowlist runs. Tests use Mock engines under patched CP APIs/native factory/Oracle delegation. Mock public32 loops are NOT real Stage A. Actual positive native dispatch, callback/log behavior, scientific correctness agreement and solve timing remain unverified.

## New immutable proposal and stop

New canonical Manifest SHA256: `13260212c82fc207e32d0e6298633f0bde54af3220e791a7f7c5dc8ab6983a54`; pretty file-byte SHA256 `1f443bedd1c4948250e73eb5833620ce9a69d967736209c1e606f2866e395852`. Source is S* above,32 ordered T00-T03 x volume/count x Oracle/M0/M1/M2. CP24/Oracle8 are proposed attempt ceilings only. Controls remain worker1/seed0/LP2/SYM2/presolve/probing2/cold/B0/source-order/exact gaps0/trace128/numeric child threads1; Oracle200000 nodes. No model/proto/parameter change from P1f other than source/transport identity;24 Proto descriptors cover18 distinct hashes.

No enrolled human key, no signed receipt, no real execution permission. Old P1f S/R/Manifest cannot authorize this code; this unsigned template has null review/key/signature/nonce/times. After any future key or budget patch, new S/R/Manifest is mandatory. A protected execution checkout must be at source S, with review object R available; running at docs-only R instead is deliberately rejected by exact HEAD identity check.

Request mentor ACCEPT / REVISE / BLOCK for code-only zero-Solve scope. Runtime activation and1.8s readiness remain NO-GO; stop after delivery. No automatic Stage A/benchmark/key enrollment/budget change/merge.

Remaining limits: trusted host/state roots, no anti-rollback or arbitrary same-user isolation; source/runtime leases are not OS attestation. Parent-crash fault injection, nested-job policy/other-host guarantees, native LP/log/callback/A-A behavior and new resource envelope are unverified. CPU/wall/commit overshoot is real; commit!=RSS. Censored failed evidence is preserved, never optimum/UNSAT.

Primary API semantics: [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [CreateFile share modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew), [OR-Tools time limits](https://developers.google.com/optimization/cp/cp_tasks). These do not substitute for the submitted one-host tests.

# Stage A budget revision — code-only, ZERO Solve

Base: accepted Draft PR #44 at review `53f44b8fd5e5ac67cf204fd17566b2fd533f7609`. Issue45 calibration ACCEPT comment6471811785 is context, not native execution permission. Owner separately authorized only this budget patch and zero-Solve tests.

**Source S:** `ea0d44a52e8a7e53b427e52f525208d75fdc1f6a`.
**Review R:** the subsequent docs/evidence-only PR head, supplied exactly in the PR and Issue45 handoff to avoid a self-referencing commit.
**Manifest canonical SHA256:** `1b4db2143bf1cbbd55414b3694603c961b6b4261f81be346cc80c60a1dc3187b`.
**Manifest file-byte SHA256:** `d0feaa5698da747e3d21d200c570539fc85f994f3e52de209bd8ab917701607d`.

New Manifest stays at the existing verifier's fixed path:
`docs/research/symmetry-search-bias/stage-a-activation/stage-a-manifest.json`.
It is still execution_authorized=false and is NOT a signed receipt.

## Complete implementation scope

Exactly two research code/test paths changed:

1. research/p1e_protocol.py: **six integer replacements only** in LIMITS; no schema/version/entrypoint/authorization/model change.
2. research/tests/test_stage_a_activation.py: threshold tests derive stop lines from LIMITS instead of old1.8/70/90; two new budget/receipt contracts.

The source commit diff is44 additions/8 deletions across these two files. Production CP/Hybrid/GUI, Oracle bytes/DFS/node budget, model builders, validator, worker/controller/journal/signature algorithms, runner and fixtures are unchanged. No new framework.

Existing stages use ManifestLimits derived from the same LIMITS. Manifest validation requires exact controls/resources, while receipt verification binds source, review, full Manifest/job digests and limits. Therefore no crypto or dispatcher edit is necessary; unchanged schema/domain does NOT allow stale receipts because S/R/Manifest/limits bindings change.

| Envelope | Old nominal / stop | New nominal / stop |
| --- | --- | --- |
| OS child inclusive wall |2s /1.8s|**5s /4.5s**|
| Stage inclusive wall |90s /88s|**180s /170s**|
| Cumulative child-tree CPU |75s /70s|**120s /110s**|

Unchanged: CP-SAT internal max_time_in_seconds=2; Oracle max_nodes=200000; Job commit256MiB;264MiB peak-review field gives no allocation slack (peak>256MiB still fails);32 ordered jobs/24CP+8Oracle; workers1/seed0/LP2/symmetry2/presolve/probing2/no hints/B0/source order/exact gaps0/trace128/numeric threads1; active-process cap4/poll10ms/cleanup1s/result64KiB/stdout+stderr16KiB; all failure-stop/no-retry rules.

## Tests at exact S

Existing explicit runner, with --no-worker-tests, under ZeroSolveGuard:
**55 tests /0 failures /0 errors /0 skips;55.014s**.
Raw per-test evidence/log: evidence/tests.json and evidence/test.log.
worker_tests_executed=false; observations=[]; live_stage_launched=false.
Parent guard blocked attempts cpsat_api/native_factory/oracle are all0; executed CP/Oracle are0.
No Windows calibration, Dummy/Job launch, benchmark, Stage A or retry occurred.

Mock/Proto coverage retains the original53 non-worker cases and adds:

- Exact six-field delta relative to immutable base Manifest; every other limit, controls, all32 complete job records, all inputs and full resolved parameter pool are equal. Rebuilt24 CP Proto descriptors remain18 unique hashes, exactly matching base.
- Runtime ManifestLimits is4.5/170/110; old controller stop configurations reject; old Manifest fails exact-resource validation.
- A freshly cryptographically valid ephemeral TEST signature bound to old caps, with otherwise current S/R/Manifest fields, is rejected specifically for limits before journal claim or supervisor call. The public key is a temporary test patch, never real human enrollment.
- Final child4.5/CPU110 boundaries and stage170 exhaustion after validation/terminal IO fail closed.

Other tests cover real immutable Git review objects, synthetic32-job orchestration, test receipt replay/order/expiry, disk attempt claims, Mock engine/witness/bound/censor contracts and final-accounting failure paths. Positive orchestration is Mock, never empirical solver validation.

Identity verification uses existing Windows read handles (1931 primary runtime/source files) and a read/write-open-denial assertion that writes no bytes. This is file identity protection, **not an OS worker/calibration run**. Test per-chain lease-close wrapper is borrowed/mocked; runner closes all actual leases, including the separate regression runtime lease.

Neutral reproduction command (not a real execution command):

~~~powershell
New-Item -ItemType Directory -Path <NEW_EVIDENCE_DIRECTORY>
& '<PINNED_PYTHON_EXE>' -B -m research.run_stage_a_activation_zero_tests --crypto-site '<EXISTING_READ_ONLY_CRYPTO_SITE>' --no-worker-tests --evidence <NEW_EVIDENCE_DIRECTORY>/tests.json --proposal-out <NEW_EVIDENCE_DIRECTORY>/proposal.json
~~~

No full legacy suite or solver-running CI; commits use [skip ci], no CI-pass claim. No failed test run or automatic retry in this budget revision.

## Source/runtime and historical evidence boundaries

Runtime versions/binary/package/stdlib fingerprints exactly match base. evidence/runtime-identity.json references the immutable original14-package/1262-code-and-metadata/625-stdlib inventory with its own size/SHA; the full read-locked audit is reused, not a second dependency system.

evidence/source-checkout-bytes.json records actual source/test/fixture bytes and Git blobs/EOL reproduction. Source41-file allowlist is unchanged; protocol is the only runtime source blob changed. Oracle remains7432 raw bytes / SHA256 `8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8` / blob `02d9eed12e422666088028a021e21ef1ee2c519a`. Fresh-checkout research EOL restoration reproduced approved base bytes before editing, without production/Oracle Git changes.

The Manifest at the fixed path is replaced only on this new budget branch. The old Manifest and inherited activation EVIDENCE/publication inventory are **historical artifacts of base R=53f44b8...**, available by immutable Git links; their old source/budget/hash statements are not current-budget attestations. This directory plus its new publication inventory attests the new R. Historical records were not rewritten or rerun.

The successful Issue45 calibration evidence E=2584d132... was NOT repeated, copied as new measurements, or treated as execution authority. No extra October source/results/log/history was published or local ignored results overwritten. New branch is based on PR #44, not the calibration evidence branch.

## Remaining gates and risks

TRUSTED_LEAD_KEYS remains (). No real human key/signature is generated, enrolled or used. Unsigned template has null review/key/signature/nonce/times and UNSIGNED_NOT_AUTHORIZED; source and new budget are explicit. No receipt/proposal boolean bypass. Native code remains conditionally reachable only through the existing real-authority chain; absent a genuine enrolled credential, public entry refuses. This is not a permanent unconditional native lock claim.

Budget acceptance is NOT Stage A permission, solver correctness, callback/LP/presolve/event-DT/A-A calibration or a guarantee that32 jobs finish. Earlier n=1 harmless preflights at another immutable source do not certify this source's native startup/search time. No new OS timing/cleanup tests were run. Keep actual native unknown/censored provenance and strict failure-stop.

Existing controlled-host/ledger trust, Job commit!=RSS, CPU/wall polling/cleanup overshoot, parent-crash/nested-job/other-host uncertainty remain. Source checkout must exactly match new S and raw-byte identities while review R is separately verified. A future owner public-key pinning change modifies source and requires yet another S/R/Manifest before signing; do not sign or execute using stale freezes.

Submit Draft PR and Issue45 report for independent ACCEPT / REVISE / BLOCK for **budget-code/zero-Solve scope only**. STOP. Actual CP Solve0 / Oracle Solve0 / benchmark0 / Stage A0 / OS probe roots0. No merge, key enrollment, retry or automatic next phase.

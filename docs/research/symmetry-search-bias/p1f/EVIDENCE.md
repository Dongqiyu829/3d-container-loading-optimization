# P1f handoff evidence (ZERO native solves)

Task: #41. Base: accepted P1e evidence HEAD `732caeaf25fc4ba192b14d00d20a47f403535ce9` (PR #40). This is an isolated stacked branch; no existing PR is merged. Implementation source freeze S: `29b0ffeb305be2ad8ee2bc8042e320f9a1c14e88`. The initial evidence review R0 was `bc0b329908e6688349c99328eb309593233fdb9d`. The current review R is the subsequent docs-only privacy correction at the immutable PR head; its exact SHA is supplied by the updated PR description and Issue #41 change record (avoids a self-referencing commit hash). R supersedes R0 for any future human review/authorization binding. Runtime source blobs remain identical to S, and the unapproved experiment manifest is unchanged. This correction issues no authorization.

## Delivered change allowlist and provenance

Modified existing research files: `research/_windows_job.py`, `research/p1e_dummy_worker.py`, `research/p1e_plan.py`, `research/p1e_protocol.py`, `research/p1e_receipt.py`.
New research files: `research/p1f_workers.py`, `research/p1f_stage.py`, `research/p1f_io.py`, `research/p1f_dummy.py`, `research/run_p1f_zero_tests.py`, `research/tests/test_p1f.py`.
New documentation/evidence: only `docs/research/symmetry-search-bias/p1f/`.
All other paths, production models/defaults, GUI, approved Oracle, fixtures and existing evidence are unchanged from base. These five existing modules are reused, not a second signature/ledger/model/watchdog framework. Existing WindowsJob's default stdio/environment path is retained and covered by its explicit prior normal-exit regression.

The original model constructors, validator, telemetry, tiny Oracle and watchdog are inherited from the accepted stacked GitHub source. No additional October source, result, log or commit ancestry is introduced. Only new P1f harmless-test evidence is published. The approved Oracle is unchanged: 7432 raw bytes; SHA256 `8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8`; Git blob `02d9eed12e422666088028a021e21ef1ee2c519a`. Initial checkout CRLF bytes were restored from that existing accepted Git blob, with no Oracle diff. Identity validation rejects conversion, never normalizes silently.

## Smallest future native closure, still unconditionally CLOSED

- Validated frozen physical input reuses `load_oracle_input`, original validator, frozen canonical JSON and existing model `prepare_run`. Proto and full resolved parameters are reconstructed and checked. Mutation of prepared input/proto/params fails.
- `p1f-cpsat-request-v1` / `p1f-cpsat-result-v1`: CP binding reuses Capture, make_callback and collect_terminal. Status/objective/witness, CP bound contract and bounded telemetry are separate from Oracle. UNKNOWN has null witness/objective and no usable solver UB; an independent physical UB remains explicitly distinct. FEASIBLE remains incomplete. OPTIMAL must have validated objective = reported bound. 128-event overflow is instrumentation_censored; events are reported-only. Missing LP/presolve/event deterministic-time evidence remains unavailable, not measured zero.
- `p1f-oracle-request-v1` / `p1f-oracle-result-v1`: ONLY original physical input, original objective and default max_nodes=200000; no Prefix restriction. Oracle OPTIMAL has independent witness and counters; ResourceLimit maps to INCOMPLETE with no witness/objective. There is no CP best-bound field. Cross-kind/extraneous fields fail. Unsupported/errors remain typed failures.
- Final validation calls original physics validator, recomputes count/volume, checks CP M1/M2 selection direction, CP telemetry/header/bounds agreement and Oracle/manual cross-check. It never promotes mock evidence to native provenance (`native_verified=false`).
- One existing-component chain: signature verification -> live dependency read lease -> exact source/review/manifest -> durable journal -> immutable job/proto -> fresh signature/source/resource checks -> durable reserve-before-launch -> fixed owned OS supervision -> cleanup/CPU/peak/output checks -> strict parse -> physics/objective/cross-check -> terminal evidence. Failure consumes the attempt and stops. No retry, changed order, expired authority or missing accounting fallback.
- Public stage, native supervisor, worker functions and CLI all call an unconditional execution refusal. Trusted human authority registry remains empty. No generated/enrolled human key, approval flag, unsigned proposal or test signature can enable dispatch. Private mock seams are ordinary Python test seams, not a sandbox against arbitrary same-user code. Actual native bodies have NOT run.

## Full source/runtime identity and OS evidence

The manifest lists 41 repository dependency files discovered through static AST imports, including nested/indirect production helper imports, packages, validator/schema and requirements. Reading/importing a helper does not run its benchmark main. No raw BR data is required. `tests.json` also fingerprints the two explicit test-runner/test files. Only immutable Git trees are cached by SHA; current HEAD and actual working bytes are freshly checked.

`runtime-inventory.json` publishes 14 declared packages / 1262 actual installed runtime code+metadata files, 625 core Python library/DLL files, executable/native-backend fingerprints and Windows build26200. It contains paths relative to package/interpreter roots and hashes, no third-party source contents. Inventory digests match the manifest. It is a declared code dependency audit, not OS/host attestation or proof of arbitrary dynamic imports. Runtime identity: Python3.12.11, ORTools9.14.6206, protobuf6.31.1, cryptography42.0.5.

Actual Windows RuntimeLease opens before hashing and retains 1890 non-inheritable FILE_SHARE_READ handles until stage cleanup; a guarded real OS test confirms an attempted read/write open is denied WITHOUT writing any bytes. All handles are released. Full audit is paid once per stage; child checks source/core binaries and parent's exact lease claim. That claim is a trusted-parent assertion, not cryptographic proof against a hostile manually launched child. Controlled host and protected source/journal directories are assumptions.

Existing atomic Job Object assignment now accepts optional fixed stdio handles, an explicit 3-handle inheritance allowlist and fixed Unicode research child environment. Only captured research children pin OpenBLAS/OMP/MKL/NumExpr threads=1; production/parent defaults stay unchanged. Python path/home/startup injection variables are excluded. Actual stdout/stderr are read via Win32 pipes by the parent (one reader per pipe, no capture thread), saved incrementally/fsynced to exclusive bounded files, shared quota16KiB. Quota overflow terminates the owned job; control files alone cannot certify success. Native output bindings exist but are behind the closed native gate.

## Exact verification (not empirical solver validation)

Final explicit suite at S: **52 tests, 0 failures, 0 errors, 0 skips**, 6.691s; exact names and observations in `evidence/tests.json`, complete output `evidence/test.log`.

Command (existing local interpreter; no installation or environment mutation):

```powershell
& '<PINNED_PYTHON_EXE>' -B -m research.run_p1f_zero_tests --crypto-site '<READ_ONLY_CRYPTO_SITE_PACKAGES>' --evidence results/p1f-04-tests.json --proposal-out results/p1f-04-proposal.json
```

The explicit allowlist is 18 old ControllerTests + new P1f tests + one old WindowsDummy normal-exit test. Of52,46 are pure/proto/mock/signature cases and6 touch actual Windows enforcement (one lease-write-denial test, four captured-process cases and one default-stdio process case). No legacy suite/discovery is run. Chain tests use real ephemeral test signatures, durable journal and physics validation; **review checking and supervisor are mocked**, with a borrowed separately tested real OS runtime lease. Post-publication static review/source equality is checked separately at R, without running any job.

Final round launches **5 harmless root workers** (four captured plus one baseline). Tree mode also creates a harmless bounded descendant. Job accounting total_processes is an OS counter and is preserved verbatim; do not reinterpret it as this explicit root-launch count.

| Actual OS case | Outcome | Selected observed evidence |
| --- | --- | --- |
| Dependency bootstrap | dummy_complete | wall0.875s, commit peak97972224/268435456 bytes; own guard all0; core fingerprints/4 environment values match |
| Output flood | output_limit/incomplete | saved16384 bytes, observed20508; wall0.109s; killed/cleaned |
| stdout + stderr | dummy_complete | 28 captured bytes; wall0.094s |
| Descendant timeout | supervisor_incomplete | CHILD_WALL_LIMIT, wall0.515s for0.5s cap; cleanup confirmed |
| Prior default stdio | complete | wall0.079s; inherited behavior regression |

All five report active_processes=0, confirmed cleanup and closed handles. Real lease-write-denial also passed. These are genuine OS harmless-process observations on this host, distinct from resource-exhaustion/cpu/launch-failure Mock cases. They do NOT prove native solve behavior or universal Windows reliability.

ZeroSolveGuard is installed before test imports; CP APIs/native SolveWrapper construction/Oracle delegation are patched closed. Parent and guarded dependency child report **blocked attempts0 and executed CP0/Oracle0**. The other dummy modes are fixed stdlib-only code. Benchmark0. Guards are audited-harness assertions, not protection from arbitrary malicious native code. No native worker was dispatched, no new solver optimum/result was measured.

Development history is preserved in `evidence/development-runs.json`: round01 51/51 pass (4 roots), round02 51/52 pass (5 roots), rounds03/04 52/52 pass (5 roots each); total19 harmless roots across distinct source-revision tests, never automatic research retries. Round02 failed during dependency NumPy/OpenBLAS import under the smaller128MiB pipe-dummy cap before any engine. Its measured peak158265344 exceeded configured134217728; job commit is NOT RSS and resource overshoot is real. The fix pins child numeric threads and aligns dependency dummy to the ALREADY proposed256MiB Stage-A cap, not a new Stage-A budget. Round04 speedup batches Git object queries; this is engineering-test time, not solver performance. Original ignored results are retained locally; earlier private-path diagnostic traces are not published. Their source/evidence hashes and failure account are available.

## Newly frozen proposal: PRE-REGISTERED, NOT AUTHORIZED

`stage-a-manifest.json`: source S above; canonical JSON SHA256 **`a622895df696c06708b8b3f3d360f334d25d45098f7121b4f7426e5b64a3d20a`** (canonical digest differs from pretty file byte hash in publication manifest). T00-T03 x volume/count x ORACLE/M0/M1/M2 =32 proposed jobs, **24 CP +8 Oracle**. P1e manifest/domain/S/R are historical and invalid for P1f.

Controls: one worker, seed0, LP2, symmetry2, presolve on/probing2, no hints, volume bound off, source construction order, exact gaps0, trace cap128, fixed numeric child environment1. No LP-off/hint/permutation/volume-bound comparisons added.

Budgets unchanged: Oracle200000 nodes; child ceiling2s/stop1.8s; stage90s/stop88s; cumulative CPU75s/stop70s; Job commit256MiB, peak review264MiB; active-process cap4; polling10ms; cleanup1s; worker result64KiB; native stdout/stderr shared16KiB. Parent supervision uses the conservative stop margins; checks and startup can consume the budget and stop early. Do not silently increase budgets. Proposed call counts are NOT enabled execution budgets.

`unsigned-receipt-template.json` has null review/key/signature/nonce/times and UNSIGNED_NOT_AUTHORIZED. Later human enrollment (outside agent control), exact S/R/manifest/budget review and a separate explicit Stage-A task remain required. This PR never removes the hard refusal.

## Unresolved risks and stopping gate

No native CP/Oracle startup/search/callback/LP/event-DT timing or actual cross-validation is established; final chain success is mock only. CP adapter deliberately supplies log_complete=false, so undocumented partial LP/presolve data remains unavailable. A/A overhead calibration is deferred to separate approval. Full preflight, cold imports, exclusive evidence/fsync and pipe backpressure may exhaust2s/90s budgets. One dependency-only child fit this host's limit, not evidence that real solves will fit. Read leases protect ordinary Windows writes, not hostile same-user/kernel actions; no cross-host/rollback-proof journal claim.

CPU/wall polling and termination can overshoot; commit!=RSS. Parent-crash fault injection, nested-job policy variations and other hosts are untested; synchronous PeekNamedPipe behavior under different host concurrency is unproven. No universal zero-overshoot or parent-crash recovery is claimed. Parent failure consumes the receipt; missing terminal evidence remains incomplete/no retry. Every source/runtime change invalidates this proposal. New scientific claims require actual later approved native runs.

P1f is submitted for mentor **ACCEPT / REVISE / BLOCK** only. STOP after PR/Issue handoff. No Stage A, benchmark, next phase, merge or extra October publication.

Primary API references: [CreateFileW share modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew), [UpdateProcThreadAttribute HANDLE_LIST/JOB_LIST](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute), [PeekNamedPipe concurrency requirements](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe). Actual enforcement evidence is limited to the cases above.

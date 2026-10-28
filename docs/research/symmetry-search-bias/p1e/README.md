# P1e: immutable worker protocol and human receipt, zero Solve

Task [#39](https://github.com/Dongqiyu829/3d-container-loading-optimization/issues/39).
Base: P1d `e118a58663fde0c312a8df7341a93d80768a720a`, Draft PR #38.
Production, Oracle algorithm/defaults and October history/results stay unchanged.
The only inherited source change is an optional cancellation predicate in the
research watchdog; its default is unchanged. Existing adapters/models/OS backend
are reused, not replaced.

## Recovery and immutable source freeze

[Read-only recovery inventory](https://github.com/Dongqiyu829/3d-container-loading-optimization/issues/39#issuecomment-6464393485):
P1e worktree and branch existed at P1d, clean, with no P1e code, tests, results,
receipts, commits or remote branch. Reflog contained only creation. Four other
worktrees were clean. Existing ignored results and local-only October commits
were preserved. No clean/reset/stash/rebase, forced push or old data publication.

Avoid a self-referential Git hash: freeze implementation at source commit S,
then run guarded tests/proto preparation at S. Publish manifest/evidence at a
later artifact commit R without changing runtime code. The proposal binds S;
a future external receipt must bind BOTH S and R plus the complete manifest,
jobs, caps, worker version and destination. Runtime requires checkout HEAD S
and exact approved working bytes. R is review evidence, not execution approval.

`p1e_plan` prepares 24 model protos via existing `prepare_run` and 8 Oracle
descriptors, never SolveWrapper/Solve/Oracle imports. Input uses accepted
`load_oracle_input`; model preparation reads a private frozen snapshot copy,
not a worker-supplied original path. Raw fixture SHA and canonical snapshot SHA
are separate. Sources pin Git blob and actual working bytes separately for EOL.
Oracle raw identity must be exactly 7432 bytes, SHA-256
`8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8`, blob
`02d9eed12e422666088028a021e21ef1ee2c519a`; CRLF conversion fails closed.

Strict schema binds source/runtime/input/config/resolved-parameter/proto/job
hashes, exact order and fixed entries. Unknown fields, duplicate JSON keys,
non-finite values, arbitrary executables and traversal/absolute/Windows device
paths are rejected. Python executable/base/DLL, OR-Tools DLL/PYD inventory and
crypto backend fingerprints supplement pinned versions. No caller module is
dynamically imported. Native fixed entries unconditionally raise SolveForbidden.

## Human receipt and no replay

`p1e_receipt` uses maintained cryptography Ed25519 verification, not custom
cryptography. There is no signing function/private key in the implementation.
The trusted-public-key registry is EMPTY; no real key enrollment or human
receipt exists. Test keys are ephemeral, patched into test policy and never
serialized. Self-supplied keys, unsigned templates, approval booleans and
proposal digests are not authority.

Future human enrollment needs out-of-band public-key verification and separate
source review; the private key must remain inaccessible to the agent. Because
enrollment changes source identity, it requires a NEW proposal and review.
The human signs domain-separated canonical bytes with explicit decision,
source/review heads, manifest/jobs hashes, exact caps, worker version, evidence
root, nonce and <=24h UTC validity. Verify again before every attempt.

The trusted local journal atomically claims the nonce/key with exclusive
directory creation and fsynced records before launch. Per-job exclusive records
consume slots in exact order, including failed attempts. Replay/restart/retry
is denied; failures burn the claim. Requires trusted persistent storage and OS
ACLs: rollback/deletion, hostile same-user Python, multi-host replay and power
loss durability are not solved here. Native dispatch stays closed even with a
cryptographically verified receipt. No real receipt is verified/consumed in P1e.

## Dummy-only transport and result contract

`p1e_bridge` validates schema and actual sources before launching fixed
`p1e_dummy_worker.py` with `-I -S -B`, allowed mode and private transport folder.
Child imports stdlib only, checks its own raw hash and request/job/input hashes,
and returns dummy evidence bound to request/job/worker. No instance-path reload,
CP/Oracle execution or solver evidence is possible through this public path.
Existing WindowsJob/_supervise retains ownership, wall/CPU/commit-memory limits,
tree kill, cleanup and accounting. Optional cancellation requests tree shutdown.

Request/response cap64KiB. Stdout/stderr use a cooperative 16KiB child sink;
parent checks file size. This is NOT adversarial/native OS pipe capture. No
stdout handles are inherited. A separate control marker cannot validate a bad
protocol response. Partial/mismatched/oversize/nonzero, timeout/exhaustion,
UNKNOWN and overflow stop the stage. UNKNOWN supplies no usable bound; overflow
is instrumentation_censored. No automatic retries.

Supplied terminal mock witnesses reuse physical validation and Forward/Reverse
label checks, recompute count/volume and require exact bound/manual consistency.
They never become native acceptance. Oracle witness labels need no Prefix.
Future real terminal integration and native worker dispatch remain unavailable.

## Stage A pre-registration, NOT authorization

Exactly T00,T01,T02,T03; volume then count; each block Oracle,M0,M1 Forward,M2
Reverse: 8 Oracle descriptors +24 CP descriptors. No T04-T07/48-row expansion.
Fixed order is for correctness/telemetry; position bias remains and this is not
a performance population. Manual predictions (volume,count): T00(0,0), T01(2,2),
T02(3,3), T03(3,2), still not solved.

Worker1, seed0, source construction/index order, LP2, symmetry2, presolve true,
probing2, no hints, no added volume bound, exact gaps0, trace cap128. Complete
resolved parameters and each actual model-proto byte hash are bound.

Proposed ceilings: child2s/stage90s/cumulative child user+kernel CPU75s,
job commit256MiB/active processes4/no retries. Proposed stop-request margins:
child1.8s/stage88s/CPU70s; poll10ms, cleanup1s, peak review threshold264MiB.
These are registered proposal values, NOT an implemented/calibrated Stage-A
runner. Peak review is not an RSS hard bound. Oracle max_nodes stays200000.
Require exact OPTIMAL, physical first/final witnesses, objective/prefix and
independent Oracle/manual agreement, source/proto/config consistency and complete
resource evidence. Stop on mismatch, UNKNOWN/incomplete, overflow, missing data,
unsupported OS/accounting, parent/child crash, cleanup uncertainty or exhaustion.
Parent restart retains a consumed claim; missing terminal data is incomplete,
never UNSAT/OPTIMAL. Separate human run approval and worker audit remain gates.

## Testing and limits

Use only the explicit guarded test allowlist, never legacy discovery:

```powershell
python -B -m research.run_p1e_zero_tests --os-tests --evidence results/NEW-tests.json --proposal-out results/NEW-proposal.json
```

Optional test-only `--crypto-site` loads only an existing read-only crypto package
when cryptography is absent from the solver environment. No install or production
dependency change. Target: Python3.12.11, OR-Tools9.14.6206, protobuf6.31.1,
cryptography42.0.5, Windows x64. Missing/changed dependencies fail closed. The
fallback path is not added to sys.path or worker argv. Guard precedes explicit test imports; positive
test-run Solve budgets are rejected. Evidence separates P1d pure regressions,
new pure/proto/mock tests and real OS protocol dummies. Old P1d OS evidence is
historical, not a new rerun claim.

One-host dummy tests do not establish general Windows reliability. Commit
memory is not RSS; observed peaks and polled wall/user+kernel CPU can overshoot.
OS user-CPU backstop differs. Parent-crash enforcement, parent hang/starvation,
other Windows/nesting policies and POSIX enforcement remain unvalidated. No
arbitrary-process/same-user security sandbox claim. Callback A/A/event DT/LP
grammar calibration remain separate gates. CI is skipped because inherited
workflows solve models; no CI success claimed. Keep all PRs draft/unmerged and
stop after Issue #39 handoff.

API reference: [cryptography Ed25519](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).

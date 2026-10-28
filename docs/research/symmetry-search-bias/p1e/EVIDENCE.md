# P1e final evidence and review request

Source freeze S: `723d0783dac7c3b6396f4d71203e5cfd484a3c83`.
Base: accepted P1d `e118a58663fde0c312a8df7341a93d80768a720a`.
This artifact commit R adds evidence only. Runtime source at R equals S;
future execution must use checkout S, and a future human receipt must also bind
the exact review commit R. No real credential or trusted public key exists.

## Final verification

Exact command at S, using the existing Python3.12.11 solver interpreter:

```powershell
python -B -m research.run_p1e_zero_tests --os-tests --crypto-site <existing-read-only-site-packages> --evidence results/p1e-resume-03-tests.json --proposal-out results/p1e-resume-03-proposal.json
```

The test-only fallback loads only cryptography/CFFI namespaces, not a whole
foreign site-packages path. No package installation/production dependency edit.

**71/71 passed, 0 failures/errors/skips**, in the recorded final run:
35 P1d pure regression cases, 24 new pure/proto/mock/signature cases,
12 real Windows protocol-dummy tests with 13 actual dummy root creations.
All 13 final OS records confirm final CPU known, handles closed and active
processes zero. API/native factory/Oracle blocked-attempt counters are all zero.
**CP-SAT Solve=0, Oracle Solve=0, benchmark=0.** The guard is scoped, not a
global guarantee for arbitrary host code. Dummy children are fixed stdlib
interpreters with -I -S -B; no native experiment worker is available.

[Final test evidence](evidence/tests.json) and [exact final test log](evidence/test.log)
are copied byte-for-byte. [Development record](evidence/development-runs.json)
preserves the bootstrap dependency failure and the cancellation-test timing
error. Previous local logs/results remain untouched. Across the two completed
OS test rounds, 12 then13 dummy roots were created; these are engineering test
stages, not retrying research experiments. The aborted bootstrap launched none.

## Unapproved immutable Stage A proposal

[stage-a-manifest.json](stage-a-manifest.json) is the exact prepared proposal.
Canonical manifest SHA-256:
`93ea25b97de5440953d22586c4a733250c587beb0bd6906036d821eea3713fdd`.

Its file-byte SHA is recorded separately in the publication manifest.
T00-T03 only, volume then count, each Oracle/M0/M1/M2: 8 Oracle descriptors and
24 actual CP model-proto hashes. Deterministic reconstruction test prepared a
second set of24 protos and confirmed the same proposal: model construction
is not solving. Three resolved parameter pools cover CP and the two Oracle
objectives. Manual predictions remain unsolved.

[unsigned-receipt-template.json](unsigned-receipt-template.json) is deliberately
INVALID: unsigned decision, null review head/key/signature/nonce/times. It is
not authority and cannot open dispatch. Public-key enrollment needs separate
human verification/source review and therefore a new source/proposal identity.
No real human signature was minted, verified or consumed.

## Actual OS limits and remaining risk

- Cancellation was armed after real CreateProcess: CANCELLED, final tree empty.
- Child deadline0.35s: observed inclusive cleanup wall0.359s; timeout, not completion.
- CPU cap0.1s: final aggregate user+kernel0.109375s; stopped.
- Commit-memory cap100663296 bytes: dummy allocation denied, but peak103460864
  (2797568 bytes above the configured value). No strict peak/RSS ceiling claim.
- Flooded stdout: cooperative16KiB sink stopped output; parent verified quota.
  This is not a hardened native OS pipe-capture implementation.
- Partial/oversized/mismatched responses, nonzero exit, UNKNOWN and trace censoring
  were classified and stage closure/no retry checked. A passed control marker
  alone does not mean a protocol result is complete or scientific evidence.

These are one-host Windows x64 observations. Mock failures (CPU/accounting,
job creation/kill/close), unsupported-platform checks and temporary-signature
policy tests are separately labeled. No actual parent-crash enforcement fault
injection, hostile same-user defense, other Windows/nesting policy, POSIX
backend, multi-host replay, rollback-proof ledger or power-loss durability is
established. Parent hang/starvation and polling/termination overshoot remain.
The journal's expiry and exclusive claim close future attempts after a crash;
unknown/missing terminal data never becomes UNSAT/OPTIMAL.

Proposed Stage-A ceilings2s/90s/75CPU-s/256MiB commit and stop-request margins
1.8s/88s/70CPU-s are pre-registration values, NOT exercised Stage-A controls.
A/A overhead, event DT and native LP/presolve calibration remain unapproved.
All true native entrypoints unconditionally refuse even a verified receipt.

Please review for **ACCEPT / REVISE / BLOCK**. P1e is submitted, not self-accepted.
All research PRs remain Draft/unmerged. No Stage A/P2/benchmark was launched.

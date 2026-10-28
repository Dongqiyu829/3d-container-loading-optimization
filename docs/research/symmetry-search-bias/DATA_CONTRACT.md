# Research data contract v1

New research utilities only; no historical JSON is overwritten.

| Contract | Semantics |
|---|---|
| reported_solver_best_bound | Finite raw numbers retained, including UNKNOWN zero/positive. Malformed/nonfinite becomes null plus invalid_reported_bound_repr; strict JSON stays serializable. |
| usable_solver_upper_bound | Conservative study policy: FEASIBLE/OPTIMAL, validated solver witness, finite noncontradictory bound. UNKNOWN may have a meaningful bound but a bare number does not certify it for this study. |
| independent_bound | Volume=min(total box volume, container volume); count=physical box count. No secondary volume objective for count. |
| effective_upper_bound | Min of usable solver and independent bound; otherwise independent only. Raw UNKNOWN zero does not invalidate a validated independent fallback. Trusted-status bound below LB invalidates analysis. |
| validated LB/source | Null without validated witness. UNKNOWN cannot invent solver incumbent; independent_validated fallback separate. Legitimate empty optimal packing stays zero. |
| invalid/infeasible | Excluded from normal comparison. Original optional-box problem has empty packing, so caller must stop on INFEASIBLE. |
| relative gap | (effective UB-LB)/LB only for LB>0. LB0 uses null division and separate bounds_coincide. No proof gap from unverified raw numbers. |
| LP | LP0/2 setting, final response iterations and matching complete versioned log summary. LP2 zero=activity not observed; LP0 positive=contradiction. Missing/truncated/unsupported remains unverified. |
| cuts/root bound | Presence flags only; unsupported numeric metrics null with reason. Preserve full native log in later runs. |
| clocks | Solver event wall, callback receipt wall, raw event DT and terminal DT distinct. Even increasing event DT remains uncalibrated/unusable. No interpolation. |
| no incumbent | Null time plus censored flag; hint is not solver incumbent at t0. Witness validation must happen offline in later integration. |
| presolve | Narrow v9.14.6206 grammar, synthetic-tested only. Post counts carry source line numbers. Missing/ambiguous/truncated/early-close => null and reason. Response booleans are not post model count. |
| presolve time | Exclusive time always null. Rounded start-presolve to start-search interval is approximate combined phase cost, not pure presolve. |
| BoundedTrace | Registered finite numeric/null scalars only; no witness/geometry/IO. Overflow explicit, trajectory_complete=false. Processing wall is not total callback cost. |
| manifests | Exact artifact bytes; explicit relative allowlist; traversal/symlinks/duplicates/>64files/>2MiB rejected. Source text hashes explicitly normalize UTF-8/LF; original worktree-byte hash is diagnostic, not portable key. |

Native source pointers from accepted P1 design:
- OR-Tools v9.14 ortools/sat/sat_parameters.proto, blob fb7d23f541d816cb50416d50a8e42bdd1c9836f4.
- ortools/sat/cp_model.proto, blob d52fd8bfe3aa1dde6c54ad178dca9376c397bc8e.
- ortools/sat/cp_model_solver.cc, blob 8aef798e1fe304f60b312875cfda74d755c54742.

All log records set parser_runtime_calibrated=false. Synthetic parsing does not
validate actual solver logging/activity. Exceptions, schema/key mismatches and
contradictory trusted bounds must stop analysis. The JSON Schema describes bound
record fields; pure functions enforce additional cross-field semantic invariants.
No new external schema-validation dependency is added.

## Evidence portability and reconciliation

P1a publishes only new code, unsolved fixtures, zero-call plan/test evidence.
No October source or historical capsule. Later publication must be separately
reviewed: retain historical dirty-source provenance, distinguish source commit
from runtime digest, redact private paths/machine IDs, record original/published
hashes if redaction changes bytes, preserve licenses and immutable links.
Checksums alone are not downloadable data. Do not incidentally merge divergent
branches. Evidence files use nested byte-preserving Git attributes.

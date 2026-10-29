# Experimental Protocol (proposal, not executed)
**Version:** 0.1 — 2026-10-28. **Status:** approval pending. This is a pre-registration draft; no runs are authorized by this document.

## 1. What was actually implemented
At remote baseline `cpsat_baseline.py`: `selection_prefix_symmetry` adds adjacent inequalities `s_i >= s_(i+1)` to groups defined in `identical_box_symmetry_audit.py`. It canonicalizes *selected labels*, not ordered positions. For `m` identical copies, `k` selected physical positions: original label assignments are `m!/(m-k)!`, and selection prefix leaves `k!`, a reduction factor `C(m,k)`; at `k=m` it breaks none of the selected-position permutations. This counting assumes distinct occupied positions and the specified label-exchange group. Position/pose lex rules would be a **new** formulation and require separate proof and encoding-cost analysis.

## 2. Read-only evidence gate (P0)
Before any edit or run, inventory:
- `git rev-parse HEAD`, current branch, `git status --short`, `git log`, `git diff` and divergence from `origin/main`, without altering working tree;
- local `docs/research/audit-and-roadmap-20261027.md`, `docs/research/HANDOFF.md`, historical findings, uncommitted changes, ignored `results/`, benchmark configs and schema;
- whether a *full placement Lex* or only selection-prefix was implemented in any local code or branch;
- exact version/dependency/CPU/OS, seed, workers, budgets, initialization/hints, symmetry level and LP parameters in prior experiments;
- provenance matrix: **code verified / raw log verified / report only / proposed / missing**.

Stop and post P0 to the tracking issue with links/evidence. Do not modify the existing local user worktree or discard files.

## 3. Treatments (P1/P2: only after explicit review)
- `M0`: original model; manual prefix OFF.
- `M1`: full *selection-prefix chain* FORWARD, opt-in.
- `M2`: selection-prefix chain REVERSE with the same conservative groups.
- `M3`: **partial selection prefix**, predefine strength as proportion of adjacent inequalities *or* number of groups covered; specify which and register exact deterministic selection rule before looking at results.
- `M4`: full *placement* lex-leader among selected interchangeable copies, if independently proved valid and given a separate encoding-cost accounting; this is a separate high-risk exploratory treatment, **not** a prerequisite for P2.
- For label-index permutation experiments, construct **a separate M0 baseline per permutation**, and pair with matched-encoding M1/M2; changing indexed variable order itself changes a solver's behavior.

Cold vs hinted (including canonicalized hints) and volume bound are separate strata; do not confound them with symmetry treatment. Hold objective, box geometry, formulation, validator and environment fixed within comparisons.

## 4. Controls
Mechanism pilot: one worker, pinned OR-Tools and Python versions, machine/OS/CPU, deterministic cutoff with a generous wall safety cap, fixed `random_seed=0`, fixed `symmetry_level` initially (default 2, plus selected controlled level-0 cases), and `linearization_level` 0 vs 2 where supported. **Check actual LP stats/logs before claiming LP disabled**. Only expand to seeds 0–4 or more after P2 review. Randomized seeds may yield identical paths; record this as an outcome, not independent stochastic evidence. No uncontrolled default-worker comparisons in mechanism attribution.

Prespecify 8–12 *diagnostic* cases with a mix of historical regressions/neutral/improvements, varying copy-group size and difficulty. Keep separate untouched holdouts for generalization. Avoid choosing only regressions then claiming a population effect. Confirm identical objective/physical feasibility and hint behavior. Pin model/instance fingerprints and all controls.

## 5. Instrumentation and measurements
Per run, record at least:
- run ID, UTC, git SHA + dirty-state/hash, configuration JSON, OR-Tools/Python version, hardware/OS, exact instance file/hash, grouping, count of added constraints, model/proto hash;
- status (`UNKNOWN`, `FEASIBLE`, `OPTIMAL`, etc.), independently validated packed volume/utilization, raw best objective bound and physical adjusted upper bound **separately**, relevant gap;
- first-incumbent time and value; timestamped incumbent-improvement trajectory, time-to-pre-registered target; timeout/censoring represented as missing, never zero;
- build time, presolve time if available, solve wall time and deterministic time; conflicts, branches, propagations, restarts, `num_lp_iterations` and solver log LP/cut details where available;
- pre-/post-presolve variable and constraint counts if obtained from logs; record any missing field with reason.

For fixed-time quality comparison, keep all timeout/UNKNOWN cases; report incumbent availability separately. For time-to-target, report censored outcomes and use appropriate empirical survival/performance curves. Do not equate smaller branch count with solver efficiency.

## 6. Diagnostic decision rules
- LP-off persistence is evidence *against an LP-only explanation*, not proof of a particular heuristic.
- Differences confined to LP-on warrant inspecting LP iterations, root bounds, cuts, wall cost vs deterministic cost.
- Identical number/form of prefix constraints but markedly different forward/reverse results support representative-order sensitivity, subject to paired index-order baselines.
- Increased presolve/model-size/propagation costs support encoding burden; correlate costs with performance, avoid unsupported causality.
- If first incumbent improves but later improvements regress, label **primal improvement trajectory regression**, not necessarily slower time-to-first-solution.
- If P2 finds no robust differential, publish negative or null result and stop rather than force a positive narrative.

## 7. Data contract and analysis
Write to new unique `results/symmetry-search-bias/<run-id>/` (no overwrites); preserve original instance JSON, `config.json`, `environment.json`, `model_fingerprints.json`, per-run records JSON/CSV, improvement traces, validation report and `manifest.json` with SHA-256 of source artifacts. The repository's existing conventions may take precedence after P0 audit if equivalent. Never commit large uncontrolled runs automatically.

Compare paired within instance/seed/worker/LP regime and report distribution of *quality delta at fixed budget*, fraction finding incumbents, time-to-target, bounds, and relative time/cost. Use bootstrap confidence intervals or suitable paired nonparametric statistics after checking design; avoid treating multiple seeds or time budgets as independent problem instances. Present both representative improvements and degradations.

## 8. Acceptance gates
- **P0:** exact feature lineage and evidence classification; raw artifacts vs historical claims differentiated.
- **P1:** tiny-oracle/model-proto tests and proof argument; no silent changes to production flags.
- **P2:** complete reproducible paired pilot and logs; hypothesis assessment with rival explanations.
- **P3:** held-out data, multiple seeds, uncertainty, limits and truthful novelty positioning.
- **P4:** any new method needs correctness proof and measured generalization beyond the tuning set.

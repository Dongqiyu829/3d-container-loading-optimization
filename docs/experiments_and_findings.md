# Experiments and Research Findings

## 1. Purpose and methodology

This document records the controlled experiments that shaped the current solver architecture. It is organized by research question rather than chronology. Machine-readable JSON/CSV remains the evidence layer; this Markdown records the interpretation and engineering decision.

Unless a section says otherwise, comparisons use the same canonical instance, independent post-solve validation, packed volume as the objective, one OR-Tools worker, and random seed 0. Wall-clock cutoffs are timing-sensitive. Deterministic-time cutoffs are used where repeatability matters, and their units are not seconds.

Three data families are kept distinct:

- 28 deterministic, repository-designed internal instances;
- 60 fixed-seed synthetic distributional instances;
- 700 Bischoff–Ratcliff (BR) instances imported from OR-Library.

Results across families are not claims of industry-wide generalization. In particular, raw volume has a different scale across datasets, so normalized utilization is the appropriate cross-dataset quality measure. A CP-SAT mean conditioned on finding an incumbent must always be read together with incumbent availability.

Generated experiment outputs under `results/` are normally Git-ignored and may not exist in a fresh clone. The runners, benchmark definitions, import code, tests, and source manifests are committed so the studies can be reproduced. Historical claims not supported by these artifacts remain classified in `historical_artifacts.md` and are not promoted here.

## 2. Baseline architecture

### Canonical data

`schemas/container_loading_instance.schema.json` defines versioned instances with container dimensions, explicit physical box IDs and type IDs, dimensions, quantities, and allowed canonical orientations. `schemas/container_loading_solution.schema.json` defines selected physical IDs, orientation IDs, coordinates, and realized dimensions. Optional selection means an unselected candidate may be absent from a solution; duplicate selected IDs and references to unknown IDs are errors.

### Independent validation

`validate_solution.py` is independent of both solvers. It checks identity, allowed orientations, realized dimensions, container containment, pairwise non-overlap, packed volume, and utilization. Solver success alone is never treated as geometric validity.

### Historical Greedy

`Bin_packing_3D.cpp` preserves the original volume ordering, orientation trial order, candidate-point construction, collision checks, placement loop, and adjustment behavior. Its machine-readable mode carries canonical box/type identity and allowed orientations without replacing the historical interactive path. `greedy_baseline.py` adapts canonical JSON to this backend and converts its output back to the canonical solution format.

### CP-SAT baseline

`cpsat_baseline.py` implements optional per-box selection, exactly one allowed orientation when selected, realized dimensions, bounded integer coordinates, container boundaries, and pairwise disjunctive non-overlap. The objective is

\[
\max \sum_i v_i s_i,
\]

where `s_i` selects physical box `i` and `v_i` is its orientation-invariant volume. `FEASIBLE` means a validated incumbent under the cutoff; only `OPTIMAL` proves optimality. Low-level hints and aggregate-volume tightening default to off, preserving the cold baseline.

**Decision — Adopted foundation.** Canonical identity, common solution output, independent validation, accurate status semantics, and non-overwriting metadata are prerequisites for every later comparison.

## 3. Greedy policy studies

### Historical behavior reconstruction

#### Question

Which parts of the historical heuristic limit packing quality, and can narrowly scoped policy variants expose useful complementary behavior without rewriting the placement engine?

#### Change / formulation

The diagnostic phase instrumented placements, candidate points, rejection causes, and adjustment activity without altering outcomes. Two controlled policies were then evaluated:

- `planar-inclusive` retains planar contact candidates that the historical filter rejects;
- `geometry-first` prioritizes geometric candidate quality while retaining the same underlying placement machinery.

The canonical identity/orientation interface changes are separate correctness work, not heuristic improvements.

### Planar-inclusive

Across the 28 deterministic instances, planar-inclusive beat/tied/lost to historical on packed volume in 23/5/0 cases. Mean utilization rose from 0.7517 to 0.9014. The study supports the diagnosis that the historical planar rejection rule discards useful placements on this suite; it does not prove planar-inclusive dominates on all distributions.

### Geometry-first

On the same 28 instances, geometry-first also recorded 23/5/0 against historical and mean utilization 0.9098. Against planar-inclusive it recorded 5/21/2, showing both strength and complementarity rather than universal dominance.

On the 60 fixed-seed distributional instances, mean utilization was 0.6607 historical, 0.7568 planar-inclusive, and 0.7659 geometry-first. Geometry-first versus historical was 48/10/2; geometry-first versus planar-inclusive was 15/40/5.

### Key deterministic examples

| Instance | Historical | Planar-inclusive | Geometry-first |
|---|---:|---:|---:|
| `benchmark-medium-mixed-24` | 342 (0.7125) | 480 (1.0000) | 480 (1.0000) |
| `benchmark-fragmentation-filler-02` | 176 (0.7333) | 216 (0.9000) | 216 (0.9000) |
| `benchmark-selection-pressure-02` | 120 (0.6250) | 156 (0.8125) | 156 (0.8125) |

Values are packed volume with utilization in parentheses. They are deterministic examples, not a representative performance table.

### Decision

**Adopted as portfolio constituents.** Geometry-first is generally stronger than historical on the tested internal/distributional sets, while planar-inclusive contributes distinct wins. The historical mode remains a reproducibility baseline.

### Reproducibility

- Runner: `greedy_ablation_benchmark.py`
- Distributional runner: `greedy_distributional_benchmark.py`
- Output families: `results/greedy-planar-ablation/<run-id>/` and `results/greedy-distributional/<run-id>/`

## 4. Greedy portfolios

### Portfolio-IG and Portfolio-HIG

#### Question

Can deterministic policy complementarity be captured with a small validated portfolio, and is adding the historical policy worth its extra latency?

#### Change / formulation

Portfolio-IG runs planar-inclusive and geometry-first, validates both, and selects maximum packed volume with a fixed tie priority. Portfolio-HIG additionally runs historical. A portfolio never combines geometries; it chooses one complete validated constituent solution.

#### Experimental design

The full study evaluated all 788 instances: 28 internal, 60 distributional, and 700 BR. Every constituent and selected solution was independently validated. End-to-end times include process/adaptation and validation overhead, not just the C++ core timer.

### Internal benchmarks

On the 28 deterministic cases, mean utilization was 0.9128 for Portfolio-IG. It matched the empirical best of all three policies on every case; adding historical produced no additional win in this dataset. Mean end-to-end time was 0.0258 seconds for IG and 0.0393 seconds for HIG in this run.

### Distributional benchmarks

On 60 fixed-seed cases, mean utilization was 0.7699 for IG and 0.7702 for HIG. HIG improved exactly one instance beyond IG (12 packed-volume units, 1.90 utilization percentage points). Mean end-to-end time was 0.0263 seconds for IG and 0.0378 seconds for HIG.

### OR-Library Bischoff–Ratcliff evaluation

All 700 BR instances were imported from the source files recorded in `benchmarks/external/orlib_br/source_manifest.json`. Mean utilization was 0.8185 historical, 0.8325 planar-inclusive, 0.8391 geometry-first, 0.8437 Portfolio-IG, and 0.8450 Portfolio-HIG. IG matched HIG on 618 cases; historical supplied an HIG-only improvement on 82. Mean end-to-end time was 0.0571 seconds for IG and 0.0825 seconds for HIG.

These figures describe this importer, feasible-set interpretation, and implementation. They are not comparisons with published BR values unless constraints, subsets, and metrics are first shown identical.

### Latency / quality tradeoff and decision

HIG is empirically the best-of-three envelope and gives a small robustness gain, most visibly on BR, but always pays for a third run. IG captures most of the observed complementarity at lower latency.

**User-facing — Portfolio-IG is Fast.** **Research option — Portfolio-HIG.** Historical remains directly runnable for reproducibility.

### Reproducibility

- Orchestration: `greedy_portfolio.py`
- Full runner: `greedy_portfolio_benchmark.py`
- BR runner/importer: `external_br_benchmark.py`, `benchmarks/external/orlib_br/adapter.py`
- Outputs: `results/greedy-portfolio/<run-id>/`, `results/external-br/<run-id>/`

## 5. CP-SAT warm starts

### Portfolio-to-CP-SAT hint construction

#### Question

Does a validated Portfolio geometry improve finite-budget CP-SAT search without changing the model's feasible region?

#### Change / formulation

The mapper resolves every physical box ID, selected bit, orientation bit, coordinate, and realized dimension from a validated Portfolio solution into `AddHint` values. Unselected boxes are mapped consistently. Hints guide search; they are not constraints and do not make the Portfolio assignment mandatory.

### Pilot results

The 13-instance pilot used wall budgets 0.25, 0.5, 1, 2, 5, and 10 seconds, workers 1, seed 0. At 0.25 seconds, hinted versus cold incumbent quality was 3/9/1 better/tie/worse and the mean utilization difference was +7.14 percentage points. The one finite-cutoff regression persisted in the paired pilot, showing that hints can redirect search unfavorably even when they supply a valid incumbent.

### Repeated wall-time and deterministic-time robustness

Selected internal and external conditions were repeated five times. Deterministic-time one-worker outcomes and counters were highly repeatable; wall-time outcomes were often stable while branch/conflict counters varied with timing. The strongest short-budget cases reproduced the Portfolio target immediately, but later deterministic budgets included cases where cold search overtook the hinted trajectory.

### Bound effects

Across the pilot and robustness work, hints primarily affected the primal incumbent. Raw/effective upper bounds were usually tied. A hint can change the search path, but it does not add a proof-strengthening inequality.

### Decision

**Adopted as a Hybrid component, not a universal standalone default.** The early-incumbent benefit is useful when protected by validated fallback selection; finite-cutoff regressions make unconditional replacement of cold CP-SAT inappropriate.

### Reproducibility

- Runners: `cpsat_warmstart_experiment.py`, `cpsat_warmstart_robustness.py`
- Outputs: `results/cpsat-warmstart/<run-id>/`, `results/cpsat-warmstart-robustness/<run-id>/`

## 6. Aggregate-volume tightening

### Mathematical inequality and validity

The isolated redundant inequality is

\[
\sum_i v_i s_i \le V_{container}.
\]

Every selected box is contained in the container, selected boxes have non-overlapping positive-volume interiors, and allowed axis permutations preserve volume. Therefore their summed volume cannot exceed container volume. No current optional-selection or orientation semantic violates this argument.

### Cold versus hinted experiment

The controlled 2 × 2 study compared baseline/volume-bound models against cold/Portfolio-hinted initialization at wall budgets 0.25–10 seconds and deterministic budgets 0.005, 0.01, 0.05, and 0.2. Model fingerprints distinguished the extra inequality, and proto inspection verified the exact coefficients `v_i` and right-hand side `V_container`.

The inequality can tighten a raw objective bound that otherwise reflects total candidate volume rather than physical capacity. It need not improve incumbent discovery and can perturb search under a cutoff. When total candidate volume is already at or below container volume, it may be non-binding.

### `medium-mixed-24`

Candidate volume is 592 and container volume is 480. The un-tightened solver could report raw bound 592 even though the known physical upper bound is 480. Portfolio-IG supplies a validated full-volume solution of 480. With the bound, objective upper capacity is 480; with the Portfolio hint, the solver can close the matching feasible/upper interval rapidly. In the later Hybrid campaign, hinted + bound returned `OPTIMAL` at volume/bound 480 for every tested budget, reaching the Portfolio target in roughly 0.19–0.23 seconds.

Candidate volume is not physical feasibility: the equality at 480 is certified here only because a valid 480 packing exists and the upper bound is 480.

### External behavior and decision

The BR subset confirmed that the inequality is valid but not uniformly faster or uniformly better for finite-cutoff incumbents. Its clearest value is dual/proof tightening when candidate volume exceeds capacity; a strong hint supplies the complementary primal side.

**Adopted inside Hybrid Optimize.** **Opt-in at the low-level CP-SAT API (`False` by default).** No other tightening was bundled into this experiment.

### Reproducibility

- Runner: `cpsat_volume_bound_experiment.py`
- Outputs: `results/cpsat-volume-bound/<run-id>/`

## 7. Box-level incompatibility

### Criterion and question

For two physical boxes, enumerate allowed realized orientations and ask whether every orientation pairing is impossible to separate on all three container axes. If so, `s_i + s_j <= 1` is valid.

### Corpus prevalence and result

The solver-independent scan covered 788 instances and 6,927,817 physical pairs: 3,257 internal, 41,571 distributional, and 6,882,989 BR. It found zero universally incompatible physical pairs. The criterion is mathematically sound, but it would add no constraint to the current corpus.

### Decision

**Closed direction for the current datasets.** The geometry helper and prevalence runner remain useful reproducibility infrastructure; no permanent production CP-SAT option is justified.

### Reproducibility

- Geometry: `pairwise_incompatibility.py`
- Runner: `cpsat_pairwise_incompatibility_experiment.py`
- Outputs: `results/cpsat-pairwise-incompatibility/<run-id>/`

## 8. Orientation-pair incompatibility

### Criterion

For a particular allowed orientation of each box, the pair is incompatible if the two realized extents cannot be separated along any container axis. A cut on the two orientation choices is then valid.

### Unary versus genuine pair incompatibility

An apparent incompatible pair may merely contain an orientation that cannot fit the container by itself. The audit separates these unary-infeasible cases from genuine pair interaction; only the latter represents new pairwise information.

### Prevalence and result

Across 146,168,337 canonical orientation-pair combinations, 51,536 appeared incompatible, but 51,419 involved unary infeasibility. Only 117 were genuine pairwise cases, affecting 14 of 6,927,817 physical pairs. All 700 BR instances contributed zero genuine cases, and no physical pair had all orientations incompatible.

The potential cuts were negligible relative to the existing disjunctive model. A valid cut family can still be operationally useless when prevalence is this low.

### Decision

**Closed direction.** Keep the audit and focused correctness tests; do not add production orientation-pair cuts.

### Reproducibility

- Runner: `orientation_incompatibility_audit.py`
- Outputs: `results/cpsat-orientation-incompatibility-audit/<run-id>/`

## 9. Identical-copy symmetry prevalence

### Source and grouping semantics

Canonical quantities expand to physical IDs. Boxes with the same type, dimensions, allowed realized orientations, and selection semantics are physically interchangeable even though the validator preserves identity. The audit groups only mathematically equivalent copies; it does not merge IDs or alter solutions.

### Prevalence

Across 788 instances, 97,370 of 97,407 candidate boxes belonged to non-singleton interchangeable groups (99.962%). The scan found 7,590 such groups, largest size 167, and 89,780 possible adjacent prefix constraints. On BR alone, 94,874 of 94,891 boxes were in non-singleton groups.

### Candidate prefix formulation and warm-start implications

For an ordered group, the valid selection-prefix constraints are `s_k >= s_{k+1}`. They select a canonical representative subset without changing the physical packing intent. A hint selecting later copies must be canonicalized consistently; otherwise it conflicts with the chosen representative convention.

**Decision — Experiment warranted, not adoption.** High prevalence made prefix symmetry worth testing, but prevalence alone says nothing about search quality.

### Reproducibility

- Runner: `identical_box_symmetry_audit.py`
- Outputs: `results/cpsat-identical-box-symmetry-audit/<run-id>/`

## 10. Manual selection-prefix symmetry experiment

### Formulation and design

The experiment added only adjacent selection implications inside interchangeable groups and compared no-prefix versus forward-prefix models, cold and hinted, with identical objective, non-overlap, worker count, seed, and deterministic/wall effort.

### Branch reduction and incumbent regressions

Prefix constraints often reduced the branch count dramatically. They did not consistently improve proof bounds and frequently worsened finite-budget incumbent quality. This is not a validity failure: choosing a representative changes propagation and the search path even when all representatives are physically equivalent.

Internal medium/selection cases, distributional cases, and the smallest expanded BR representative from BR1–BR7 all showed that fewer branches was not a reliable proxy for better packing progress. Hints did not remove the pathology.

### Decision

**Research-only, default off.** Do not use manual prefix symmetry in Hybrid or the user interface.

### Reproducibility

- Runner: `cpsat_selection_prefix_experiment.py`
- Outputs: `results/cpsat-selection-prefix-symmetry/<run-id>/`

## 11. Prefix search diagnostics

### First feasible versus later improvement

Event traces separated time to first incumbent from subsequent improvements. Prefix models could find an initial feasible solution with less search while losing productive routes to higher-quality incumbents later.

### Forward versus reverse prefix

Forward and reverse representative orders are physically equivalent but produced different search trajectories and outcomes. This established indexed-representative sensitivity rather than a geometric difference.

### Pure textual-ID reversal

Renaming textual IDs alone, while preserving the indexed model, did not change the mathematical proto or search behavior. The effect therefore was not caused by lexicographic spelling of IDs.

### Indexed-representative sensitivity and interpretation

Changing which indexed copy is forced to represent a selected subset changes how implications, hints, and non-overlap literals interact with propagation. Symmetry removal can eliminate redundant states while also removing a search trajectory that happened to improve the incumbent efficiently.

**Decision — Closed as a production direction.** Branch count reduction is insufficient evidence for manual symmetry breaking in this formulation.

### Reproducibility

- Runner: `cpsat_prefix_search_diagnostics.py`
- Outputs: `results/cpsat-prefix-search-diagnostics/<run-id>/`

## 12. Built-in OR-Tools symmetry interaction

### Level 0 versus level 2 interaction

The interaction study crossed manual prefix order with OR-Tools `symmetry_level` 0 and 2. Some cases, especially `medium-mixed-24`, were sensitive to both controls. Removing built-in symmetry changed the size of the manual-prefix penalty on certain runs.

### Level 1/4 observations

Limited level 1 and 4 spot checks helped distinguish a solver-parameter interaction from a new model effect. They did not supply a consistent replacement policy.

### Interpretation

Severe manual-prefix pathologies also remained at `symmetry_level=0`. Built-in processing was therefore not the sole cause. The experiment supported testing the built-in level separately on the ordinary no-prefix model.

### Reproducibility

- Runner: `cpsat_symmetry_level_interaction.py`
- Outputs: `results/cpsat-symmetry-level-interaction/<run-id>/`

## 13. Built-in symmetry-level ablation

### No-prefix level 0/1/2 experiment

The ordinary no-prefix model was solved at levels 0, 1, and 2 with identical model fingerprints. Workers were 1, seed 0, and primary deterministic budgets were 0.01, 0.05, and 0.2. Cold and Portfolio-hinted initialization were evaluated across 39 internal/preselected distributional instances plus seven BR representatives; a limited wall confirmation covered sensitive cases.

### Incumbents, bounds, and search

Levels 1 and 2 produced identical incumbent comparisons throughout the primary campaign and identical raw-bound comparisons. Level 0 was mixed: on the internal/distributional set, cold level 0 versus level 2 produced 13 wins, 91 ties, 9 losses, and 4 not-comparable results; hinted produced 2 wins, 99 ties, 11 losses, and 5 not-comparable results. Bounds were almost entirely tied. BR comparisons were mostly ties/not-comparable, with one cold level-0 win and no consistent hinted advantage.

Branch/conflict changes confirmed that the parameter changes search, but no level improved incumbent quality and proof progress consistently across cold/hinted modes and datasets.

### Final decision

**Keep OR-Tools' default `symmetry_level=2`; expose no user-facing override.** Manual symmetry-breaking research is closed for the current formulation. This is an empirical engineering decision, not a universal claim about CP-SAT symmetry processing.

### Reproducibility

- Runner: `cpsat_symmetry_parameter_ablation.py`
- Outputs: `results/cpsat-symmetry-parameter-ablation/<run-id>/`

## 14. Hybrid Optimize

### Motivation and architecture

Portfolio-IG provides fast, validated availability but cannot prove optimality. CP-SAT can improve or prove a solution but may return no incumbent or a weaker incumbent under a short cutoff. The hint study showed a strong primal effect; the volume-bound study showed complementary dual tightening. Hybrid Optimize combines those established components without changing either underlying algorithm:

```text
Portfolio-IG -> independent validation
             -> CP-SAT hint + aggregate-volume bound
             -> independent validation
             -> best valid result -> final validation
```

The ordinary OR-Tools symmetry default is retained and manual prefix symmetry is not used.

### Fallback invariant

If Portfolio-IG returns a valid solution `P`, Hybrid selects CP-SAT solution `C` only when `C` is independently valid and

\[
volume(C) > volume(P).
\]

Exact ties retain `P`. Therefore orchestration enforces `volume(H) >= volume(P)` whenever a valid Portfolio fallback exists. This is not a claim that CP-SAT improves Portfolio, an approximation ratio, a global-optimality guarantee, or a universal runtime/quality guarantee.

### Controlled 46-instance evaluation

The authoritative campaign used 46 predeclared instances: all 28 internal cases, 11 preselected distributional cases, and the smallest expanded representative from each BR1–BR7 class. It compared Portfolio (`P`), standalone cold CP-SAT (`C`), and Hybrid (`H`) at 0.25, 0.5, 1, 2, 5, and 10 second CP-SAT budgets, workers 1, seed 0.

| CP-SAT budget (s) | P mean util. | C incumbent availability | H mean util. | H fallback rate | H improvement rate | H vs C W/T/L | H mean end-to-end (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.25 | 0.8650 | 0.7609 | 0.8844 | 0.7609 | 0.2391 | 21/21/4 | 0.5970 |
| 0.50 | 0.8650 | 0.7826 | 0.8900 | 0.7174 | 0.2826 | 20/21/5 | 0.6901 |
| 1.00 | 0.8650 | 0.8478 | 0.8927 | 0.6957 | 0.3043 | 18/24/4 | 0.9399 |
| 2.00 | 0.8650 | 0.8478 | 0.8958 | 0.6957 | 0.3043 | 16/25/5 | 1.3841 |
| 5.00 | 0.8650 | 0.8913 | 0.8987 | 0.6304 | 0.3696 | 17/28/1 | 2.5255 |
| 10.00 | 0.8650 | 1.0000 | 0.8993 | 0.5870 | 0.4130 | 17/28/1 | 4.6690 |

Cold CP-SAT utilization is deliberately omitted from this table: its mean is conditioned on finding an incumbent, so showing it without availability invites a biased comparison. The campaign had zero observed Hybrid dominance violations, zero Portfolio/cold/Hybrid validation failures for emitted solutions, and 100% Hybrid valid-result availability. CP-SAT's improvement fraction rose from 23.9% to 41.3% as the budget increased.

### Budget curve and dataset findings

Portfolio mean utilization is budget-independent. Hybrid mean utilization rose monotonically in this campaign while fallback use declined. At 0.25/10 seconds respectively:

- internal: 0.9438 / 0.9537 Hybrid mean utilization versus 0.9128 Portfolio;
- distributional: 0.7696 / 0.8037 versus 0.7675 Portfolio;
- seven BR representatives: 0.8271 / 0.8317 versus 0.8271 Portfolio.

These subsets have unequal sizes and different volume scales. They support the fallback/optimization architecture, not a broad claim about all future instances.

### `medium-mixed-24`

Portfolio packed the full container volume 480. Hybrid's hinted, volume-bounded CP-SAT run proved volume/bound 480 `OPTIMAL` at all six budgets and reached the target in about 0.19–0.23 seconds. Exact ties retained the Portfolio geometry. Cold CP-SAT found volumes 114, 440, 440, 454, 454, and 454 across the same budgets, illustrating both the hint's primal value and the bound's proof value on this diagnostic case.

### GUI integration and decision

The GUI exposes only **Fast**, **Optimize**, and **Compare**. Optimize time is the CP-SAT search budget; Portfolio, setup, validation, and orchestration add end-to-end overhead. Compare reuses its displayed Fast candidate and compares it with the final Hybrid result.

**User-facing — Hybrid Optimize is Optimize.** It is adopted as orchestration around validated components. Standalone cold CP-SAT remains available for backend/research use.

### Reproducibility

- Orchestration: `hybrid_optimizer.py`
- Runner: `hybrid_optimize_experiment.py`
- Outputs: `results/hybrid-optimize/<run-id>/`
- Authoritative local campaign convention: `results/hybrid-optimize/primary-46-P-C-H-20260813-v2/`

## 15. Current architecture

```text
Canonical instance
  +-- Fast: Portfolio-IG
  |     +-- independent validation
  |
  +-- Optimize: Portfolio-IG
        +-- validate
        +-- CP-SAT hint + aggregate-volume bound
        +-- validate CP-SAT
        +-- best valid result / Portfolio fallback
        +-- final validation

GUI: Fast | Optimize | Compare
```

Standalone CP-SAT remains a supported backend/research path. The historical Greedy policy remains a reproducibility baseline. Canonical schemas and the validator are shared by every path.

## 16. Decision table

| Idea | Evidence | Decision |
|---|---|---|
| Portfolio-IG | Strong complementarity across internal, distributional, and BR studies | **Fast / user-facing** |
| Portfolio-HIG | Small robustness gain, especially on BR, with extra latency | **Research option** |
| Portfolio CP-SAT hint | Strong early-incumbent effect; finite-cutoff path sensitivity | **Hybrid component** |
| Aggregate volume bound | Valid, useful objective-bound tightening | **Hybrid component; low-level opt-in** |
| Universal box incompatibility | Zero usable edges in 6,927,817 pairs | **Closed** |
| Orientation incompatibility | 117 genuine combinations; zero on BR | **Closed** |
| Selection-prefix symmetry | Fewer branches but frequent incumbent regressions | **Research-only / closed** |
| `symmetry_level` override | Mixed level-0 results; levels 1/2 identical in campaign | **Keep OR-Tools default** |
| Hybrid Optimize | Validated fallback plus useful CP-SAT improvements | **Optimize / user-facing** |

## 17. Closed research directions

- Production box-level or orientation-pair incompatibility cuts on the current corpus.
- Manual selection-prefix or deeper manual symmetry breaking for the current CP-SAT formulation.
- A project-wide override of OR-Tools' default symmetry level.
- Treating hinting alone as a guarantee of better finite-cutoff CP-SAT output.

Closed means the current evidence does not justify production complexity. The reproducibility helpers remain available if the model or datasets change materially.

## 18. Open questions / future work

- Stronger exact formulations and bounds that are evaluated one change at a time.
- Support, stability, weight, balance, load-bearing, and unloading-order constraints.
- Broader external validation with explicitly matched feasible-set semantics.
- Adaptive budget policies for Hybrid Optimize based on instance/model size.
- Parallel or diversified exact search, evaluated separately from the deterministic one-worker baseline.
- Completed learning-guided methods only after canonical output, independent validation, and controlled evaluation are in place.

The existing reinforcement-learning notebook is unfinished exploratory work and supplies no validated benchmark result.

Future learning studies should use the reproducible, label-free infrastructure described in `docs/ml_framework.md`. That scaffold has not trained or evaluated a model and is not connected to the validated solver stack.

## 19. Reproducibility map

| Experiment | Committed entry point | Generated output family |
|---|---|---|
| Greedy policy ablation | `greedy_ablation_benchmark.py` | `results/greedy-planar-ablation/<run-id>/` |
| Distributional Greedy | `greedy_distributional_benchmark.py` | `results/greedy-distributional/<run-id>/` |
| Greedy portfolios | `greedy_portfolio_benchmark.py` | `results/greedy-portfolio/<run-id>/` |
| Full BR evaluation | `external_br_benchmark.py` | `results/external-br/<run-id>/` |
| CP-SAT warm-start pilot | `cpsat_warmstart_experiment.py` | `results/cpsat-warmstart/<run-id>/` |
| Warm-start robustness | `cpsat_warmstart_robustness.py` | `results/cpsat-warmstart-robustness/<run-id>/` |
| Aggregate-volume bound | `cpsat_volume_bound_experiment.py` | `results/cpsat-volume-bound/<run-id>/` |
| Box incompatibility | `cpsat_pairwise_incompatibility_experiment.py` | `results/cpsat-pairwise-incompatibility/<run-id>/` |
| Orientation incompatibility | `orientation_incompatibility_audit.py` | `results/cpsat-orientation-incompatibility-audit/<run-id>/` |
| Identical-copy prevalence | `identical_box_symmetry_audit.py` | `results/cpsat-identical-box-symmetry-audit/<run-id>/` |
| Selection-prefix experiment | `cpsat_selection_prefix_experiment.py` | `results/cpsat-selection-prefix-symmetry/<run-id>/` |
| Prefix diagnostics | `cpsat_prefix_search_diagnostics.py` | `results/cpsat-prefix-search-diagnostics/<run-id>/` |
| Built-in/manual interaction | `cpsat_symmetry_level_interaction.py` | `results/cpsat-symmetry-level-interaction/<run-id>/` |
| Built-in level ablation | `cpsat_symmetry_parameter_ablation.py` | `results/cpsat-symmetry-parameter-ablation/<run-id>/` |
| Hybrid Optimize | `hybrid_optimize_experiment.py` | `results/hybrid-optimize/<run-id>/` |

Benchmark definitions under `benchmarks/`, schemas under `schemas/`, tests under `tests/`, BR source hashes/license, and all runners above are committed. Generated `results/` directories are normally ignored and must be regenerated or preserved separately. Dirty experimental runs record the HEAD commit and a source-state digest when explicitly allowed.

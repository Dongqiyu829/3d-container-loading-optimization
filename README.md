# 3D Container Loading Optimization

Fast heuristic packing and CP-SAT optimization for axis-aligned 3D container loading, with independent geometric validation, desktop visualization, and reproducible benchmarks.

![CP-SAT packing example](assets/cp_sat_packing_example.png)

## Highlights

- **Fast validated Greedy Portfolio-IG** — deterministic, independently checked, and designed for low-latency packing.
- **CP-SAT optimization** — OR-Tools model with selection, orientation, and non-overlap constraints, with optimality proofs when reached.
- **Experimental hybrid pipeline** — Portfolio solution hint + aggregate-volume tightening for CP-SAT.
- **Interactive desktop GUI** — PySide6 with Matplotlib 3D visualization and side-by-side comparison.
- **Reproducible benchmarks** — deterministic internal suite, fixed-seed distributional data, and all 700 Bischoff-Ratcliff OR-Library instances.
- **Independent validator** — every solver output is checked for identity, orientation, bounds, and non-overlap.

## Quick Start

```cmd
python -m pip install -r requirements.txt
python -m pip install -r requirements-gui.txt    # GUI only
```

Run a solver on a canonical instance:

```cmd
python run_solver.py --solver greedy --instance benchmarks/instances/benchmark-tiny-two-cubes.json
python run_solver.py --solver cpsat  --instance benchmarks/instances/benchmark-tiny-two-cubes.json --time-limit 10 --workers 1 --random-seed 0
```

Run the internal benchmark suite (non-overwriting results):

```cmd
python benchmark.py --solver all --time-limit 10 --workers 1 --random-seed 0
```

Run tests:

```cmd
python -m unittest discover -s tests -v
```

CP-SAT requires a working native OR-Tools runtime; a dedicated virtual environment is recommended. The large precompiled OR-Tools C++ SDK is not vendored.

## Desktop GUI

The PySide6 application supports instance entry, **Greedy Portfolio**, **CP-SAT**, and **Compare Both** runs, independent validation, interactive 3D visualization, and canonical solution JSON export.

On Windows, use the bundled launchers:

```cmd
Launch_GUI.bat          # normal
Launch_GUI_Debug.bat    # with console output
```

The `.bat` files are configured for a local Windows environment; edit them to point at your own Python interpreter if needed. Research-only model switches are not exposed in the GUI.

## Solver Modes

### Fast — Greedy Portfolio-IG

A deterministic sequential portfolio of `planar-inclusive` and `geometry-first` policies. Both solutions are independently validated and the higher-volume valid result is returned (fixed tie-break priority). This is the GUI's fast solver and the recommended default for quick packing.

The larger research portfolio, Portfolio-HIG, additionally includes the historical policy; it was slightly more robust in experiments but has higher latency.

### Optimize — CP-SAT

The OR-Tools CP-SAT model uses per-box selection Booleans, exactly-one orientation logic, integer coordinates, container boundary constraints, pairwise separating-axis non-overlap, and a maximum-packed-volume objective. Solver statuses are preserved: a time-limited `FEASIBLE` result is a validated incumbent, not a proof of optimality; only `OPTIMAL` is proven optimal.

### Experimental — Hybrid Greedy to CP-SAT

Portfolio-IG can feed a validated feasible packing as an optional CP-SAT solution hint. Controlled experiments show this mainly improves early incumbent quality; it does not consistently improve upper bounds or guarantee a better final result. The optional aggregate-volume inequality

```text
sum_i(box_volume_i * selected_i) <= container_volume
```

can materially tighten the solver bound when candidate volume exceeds container volume, especially with a strong Portfolio incumbent. Both warm start and volume tightening default to off and remain backend experimental capabilities.

## Benchmarks

The repository includes three benchmark families:

- **Internal** — committed deterministic instances (`benchmarks/suite.json`).
- **Distributional** — fixed-seed generated instances (`benchmarks/distributional/`).
- **External** — all 700 Bischoff-Ratcliff instances from OR-Library (`benchmarks/external/orlib_br/`).

Each run records canonical solutions, independent validation, solver metadata, Git provenance, and machine-readable JSON/CSV summaries. Reference runs require a clean Git worktree by default; `--allow-dirty` records a source-state digest.

## Research Findings

Extensive controlled experiments found no production-worthy manual symmetry or incompatibility cuts, so OR-Tools' built-in symmetry processing is kept at its default. Two positive results stand out:

- **Greedy Portfolio-IG** is fast, robust across benchmark families, and independently validated.
- **Portfolio hint + aggregate-volume bound** gives complementary primal/dual improvement in CP-SAT (stronger incumbent and tighter bound).

<details>
<summary>Detailed negative results</summary>

- **Universal box-level incompatibility:** valid geometric criterion, but zero opportunities among 6,927,817 physical pairs across 788 instances. Not production-enabled.
- **Orientation-pair incompatibility:** only 117 genuine incompatible orientation-pair combinations (affecting 14 physical pairs) among 146,168,337 combinations; none in the 700 BR instances. Not pursued.
- **Manual selection-prefix symmetry:** sharply reduces branches but often damages incumbent-improvement trajectories; forward/reverse orders are search-sensitive. Research-only, default-off.
- **Built-in `symmetry_level` ablation (0/1/2, 46 instances, cold and hinted runs):** levels 1 and 2 identical throughout; level 0 has mixed wins and losses with no consistent advantage. Project retains the level-2 default.

</details>

These are empirical findings on the stated corpus and budgets; they do not change the formulation's mathematical guarantees.

## Component Status

**User-facing / stable**

- Portfolio-IG as the GUI fast solver.
- CP-SAT with OR-Tools' default symmetry processing.
- Independent validator, canonical formats, benchmark infrastructure, and GUI.

**Experimental**

- Portfolio-to-CP-SAT solution hints.
- Aggregate-volume tightening (off by default).

**Research-only / reproducibility**

- Manual selection-prefix symmetry (off by default, not recommended).
- Historical Greedy modes (kept for reproducibility; `run_solver.py --solver greedy` preserves the historical default).
- Universal box-level and orientation-pair incompatibility cuts (negative results).
- Overriding OR-Tools' default `symmetry_level` (not supported by the completed ablation).

## Repository Structure

```text
Core solving
  Bin_packing_3D.cpp            historical and deterministic Greedy policies
  greedy_baseline.py            C++ adapter and canonical solution conversion
  greedy_portfolio.py           validated Portfolio-IG / Portfolio-HIG orchestration
  cpsat_baseline.py             canonical CP-SAT model, hints, and optional tightenings
  run_solver.py                 unified single-instance baseline CLI
Validation and schemas
  validate_solution.py          independent solution validator
  baseline_common.py            canonical loading and shared helpers
  schemas/                      versioned instance and solution JSON schemas
  historical_artifacts.md       provenance classification for legacy outputs
GUI
  gui/                          PySide6 application, worker, models, and 3D view
  Launch_GUI*.bat               normal and debug Windows launchers
  requirements-gui.txt          GUI-only dependency pins
Benchmarks
  benchmark.py                  internal benchmark runner and result aggregation
  benchmarks/instances/         deterministic committed internal instances
  benchmarks/distributional/    fixed-seed generated benchmark family
  benchmarks/external/orlib_br/ OR-Library BR sources, adapter, manifest, and license
  external_br_benchmark.py      external evaluation runner
Research experiments
  greedy_*benchmark.py          Greedy ablations, distributional studies, portfolios
  cpsat_*experiment.py          warm starts and controlled model/search experiments
  *_audit.py                    solver-independent prevalence and symmetry audits
Tests
  tests/                        fast unit and integration tests
  tests/data/                   hand-verifiable canonical fixtures
```

## Historical Notes

Earlier C++ prototypes and the historical CP-SAT notebook are preserved for attribution and reproducibility. `historical_artifacts.md` classifies legacy outputs by provenance. The notebook's 55-box / 87.7007% packing was independently validated as feasible but not proven optimal; legacy utilization comparisons without raw data are not treated as reproducible benchmarks.

An unfinished reinforcement-learning exploration notebook is preserved for development history only and is not part of the validated solver stack; no RL performance claim is made.

## Scope and Limitations

The current geometric model does not include support/stability, weight, balance, load-bearing strength, unloading order, or routing constraints. Future work may add stronger exact formulations, support-aware constraints, and learning-guided search — any learning component must be completed and independently evaluated before presentation as a solver.

## External Attribution

The Bischoff-Ratcliff datasets are sourced from J. E. Beasley's OR-Library and attributed to E. E. Bischoff and M. S. W. Ratcliff, *Issues in the Development of Approaches to Container Loading*, OMEGA 23(4), 1995, 377-390. See `benchmarks/external/orlib_br/source_manifest.json` and `benchmarks/external/orlib_br/LICENSE-ORLIB.txt` for authoritative URLs, hashes, and license text.

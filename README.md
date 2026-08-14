# 3D Container Loading Optimization

Fast heuristic packing and CP-SAT optimization for axis-aligned 3D container loading, with independent geometric validation, desktop visualization, and reproducible benchmarks.

---

## Download Windows App / 下载 Windows 应用

### 🌟 **Download Windows Installer / 下载 Windows 安装版**

[![Download Windows Installer](https://img.shields.io/badge/Download%20Windows%20Installer-3DContainerLoading%20v1.1.0-2563eb?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Dongqiyu829/3d-container-loading-optimization/releases/latest/download/3DContainerLoading-Windows-x64-Setup.exe)

[Download Windows Installer / 下载 Windows 安装版](https://github.com/Dongqiyu829/3d-container-loading-optimization/releases/latest/download/3DContainerLoading-Windows-x64-Setup.exe)

**Windows 10/11 x64.** No Python, Conda, Git, or compiler required.  
**Windows 10/11 x64。** 无需 Python、Conda、Git 或编译器。

- Portable ZIP / 便携版 ZIP: [Download Portable ZIP / 下载便携版 ZIP](https://github.com/Dongqiyu829/3d-container-loading-optimization/releases/latest/download/3DContainerLoading-Windows-x64-Portable.zip)
- Latest Release / 最新发布: [View Latest Release / 查看最新发布](https://github.com/Dongqiyu829/3d-container-loading-optimization/releases/latest)

**Recommended for ordinary users / 普通用户推荐：** Download the Windows Installer above for the easiest setup.  
**普通用户优先推荐：** 请直接下载上方 Windows 安装版，最省事。

---

## Source / Developer Setup

For command-line solvers, validation, and benchmarks:

```cmd
python -m pip install -r requirements.txt
```

For the desktop GUI, install the GUI requirements instead; they include the core requirements:

```cmd
python -m pip install -r requirements-gui.txt
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

Independently recheck a committed fixture solution:

```cmd
python validate_solution.py --json tests/data/two_cubes.instance.json tests/data/two_cubes.valid.solution.json
```

Export a small deterministic, label-free learning dataset:

```cmd
python -m learning.export_dataset --output learning_exports/internal.jsonl --families internal --limit 10
```

Greedy execution compiles `Bin_packing_3D.cpp` and therefore requires `g++` with C++17 support (or an explicit compatible compiler via `--cxx`). CP-SAT requires a working native OR-Tools runtime; see the solver and environment notes in the docs for details.
Optional legacy notebook/data-analysis conveniences are listed in `requirements-research.txt`; TensorFlow is deliberately excluded because the unfinished RL notebook is unsupported.

## Desktop GUI

The PySide6 application accepts canonical instances and provides four user-facing modes:

- **Fast:** run validated Portfolio-IG for low-latency packing.
- **Optimize:** run Portfolio-IG, validate it, seed CP-SAT with that solution, enable the aggregate-volume bound, validate the CP-SAT candidate, and retain the better valid result. A tie, `UNKNOWN`, or invalid candidate falls back to the validated Portfolio result.
- **Compare:** show Fast beside the final Optimize result for the same instance, including gain and additional optimization effort. The Fast candidate is reused rather than recomputed.
- **CP-SAT:** run the standalone solver with either a packed-volume objective or packed-box-count objective and, optionally, an integer total cargo weight capacity.

Solving runs in a background worker so the interface remains responsive. The **Optimize time** setting is the CP-SAT search budget, not a strict end-to-end deadline: Portfolio construction, model preparation, and validation are included in the total GUI run.

On Windows, source/development checkouts can use these launchers:

```cmd
Launch_GUI.bat          # normal
Launch_GUI_Debug.bat    # with console output
```

On any supported platform, the direct entry point is:

```cmd
python -m gui.app
```

These development launchers require Python and installed dependencies. They prefer a repository-local `.venv`, then Python on `PATH`; `GUI_PYTHONW` or `GUI_PYTHON` can select a specific interpreter.

## Solver Modes

### Fast — Greedy Portfolio-IG

A deterministic sequential portfolio of `planar-inclusive` and `geometry-first` policies. Both solutions are independently validated and the higher-volume valid result is returned with a fixed time budget.

Portfolio-HIG additionally includes the historical policy. It remains a research option: experiments found a small robustness benefit at higher latency.

### Optimize — Hybrid Optimize

```text
Portfolio-IG -> validate -> CP-SAT hint + aggregate-volume bound
             -> validate CP-SAT -> return the better valid result
```

Exact packed-volume ties retain Portfolio deterministically. If a valid Portfolio fallback exists, orchestration prevents the selected Hybrid result from having lower packed volume than that fallback.

### Standalone CP-SAT

The standalone OR-Tools model uses per-box selection Booleans, exactly-one orientation logic, integer coordinates, container boundaries, and pairwise separating-axis non-overlap. **Maximize packed volume** is the default objective; packed-box-count mode remains available for comparison.

Canonical instances may optionally declare a top-level integer `max_total_weight` and `weight_unit`, with a positive integer `weight` on every box type. CP-SAT then enforces `sum(weight_i * selected_i)` against the container capacity.

Direct cold CP-SAT remains available through the CLI and research runners. Its low-level hint and aggregate-volume options keep their existing opt-in defaults; Hybrid Optimize enables both deliberately.

## Benchmarks

The repository includes three benchmark families:

- **Internal:** 28 committed deterministic instances (`benchmarks/suite.json`).
- **Distributional:** 60 fixed-seed generated instances (`benchmarks/distributional/`).
- **External:** all 700 Bischoff–Ratcliff instances from OR-Library (`benchmarks/external/orlib_br/`).

Runs record canonical solutions, independent validation, solver metadata, Git provenance, and machine-readable JSON/CSV summaries. Reference runs require a clean Git worktree by default; `--allow-dirty` is opt-in.

## Research Findings

The strongest adopted results are:

- **Portfolio-IG** combines complementary Greedy policies and is the user-facing Fast solver.
- **Hybrid Optimize** combines a validated fallback with hinted, volume-tightened CP-SAT and best-valid selection.
- Portfolio hints primarily improve early incumbent quality, while the aggregate-volume inequality primarily strengthens the objective-bound/proof side; their roles are complementary.

In the controlled 46-instance Hybrid campaign (28 internal, 11 preselected distributional, and one representative from each BR class), every final Hybrid result validated, no Hybrid result fell below the Portfolio fallback, and the median packed-volume gain was positive.

<details>
<summary>Detailed negative results</summary>

- **Universal box-level incompatibility:** zero opportunities among 6,927,817 physical pairs across 788 instances. Not production-enabled.
- **Orientation-pair incompatibility:** only 117 genuine incompatible orientation-pair combinations, affecting 14 physical pairs among 146,168,337 combinations; none occurred in the 700 BR instances. Not production-enabled.
- **Manual selection-prefix symmetry:** sharply reduced branches but often damaged incumbent-improvement trajectories; forward/reverse representative orders were search-sensitive. Research-only and not user-facing.
- **Built-in `symmetry_level` ablation:** levels 1 and 2 were identical in the no-prefix campaign; level 0 had mixed wins and losses. The project keeps OR-Tools' default level 2.

</details>

For experimental methodology, results, negative findings, and the decisions that led to this architecture, see [Experiments and Research Findings](docs/experiments_and_findings.md).

Developer references: [Architecture](docs/architecture.md), [Learning Framework](docs/ml_framework.md), [Roadmap](docs/roadmap.md), [Release Checklist](docs/release_checklist.md), and [Draft v1.0 Plan](docs/draft_v1_plan.md).

## Component Status

**User-facing / stable**

- Fast = validated Portfolio-IG.
- Optimize = Hybrid Optimize with validated Portfolio fallback.
- Compare = Fast versus final Optimize result.
- Independent validator, canonical formats, GUI, and benchmark infrastructure.

**Backend / research capability**

- Standalone CP-SAT with volume/count objective selection and optional total weight capacity, plus the direct historical Greedy baseline.
- Portfolio-HIG.
- Individual Portfolio-hint and aggregate-volume controls; both remain opt-in in the low-level CP-SAT API.
- Label-free learning feature/dataset infrastructure, isolated from solver behavior.

**Research-only / closed directions**

- Manual selection-prefix and deeper manual symmetry breaking.
- Box-level and orientation-pair incompatibility injection.
- Overriding OR-Tools' default `symmetry_level` based on the completed ablation.

This status describes the current tested project interface; it is not a claim of industrial production readiness.

## Repository Structure

```text
Core solving
  Bin_packing_3D.cpp             historical and deterministic Greedy policies
  greedy_baseline.py             C++ adapter and canonical solution conversion
  greedy_portfolio.py            validated Portfolio-IG / Portfolio-HIG orchestration
  cpsat_baseline.py              canonical CP-SAT model, hints, and optional tightening
  hybrid_optimizer.py            Hybrid Optimize orchestration
  run_solver.py                  unified single-instance baseline CLI
Validation and schemas
  validate_solution.py           independent solution validator
  baseline_common.py             canonical loading and shared helpers
  schemas/                       versioned instance and solution JSON schemas
  historical_artifacts.md        provenance classification for legacy outputs
GUI
  gui/                           PySide6 application, worker, models, and 3D view
  Launch_GUI*.bat                normal and debug Windows launchers
  requirements-gui.txt           GUI-only dependency pins
Benchmarks
  benchmark.py                   internal benchmark runner and result aggregation
  benchmarks/instances/          deterministic committed internal instances
  benchmarks/distributional/     fixed-seed generated benchmark family
  benchmarks/external/orlib_br/  OR-Library BR sources, adapter, manifest, and license
  external_br_benchmark.py       external evaluation runner
Research experiments
  hybrid_optimize_experiment.py  controlled Portfolio / cold CP-SAT / Hybrid evaluation
  greedy_*benchmark.py           Greedy ablations, distributional studies, portfolios
  cpsat_*experiment.py           warm starts and controlled model/search experiments
  *_audit.py                     solver-independent prevalence and symmetry audits
  docs/experiments_and_findings.md curated experiment history and engineering decisions
Learning
  learning/                      feature, dataset, split, label, and export scaffold only
Tests
  tests/                         fast unit and integration tests
  tests/data/                    hand-verifiable canonical fixtures
```

## Historical Notes

Earlier C++ prototypes and the historical CP-SAT notebook are preserved for attribution and reproducibility. `historical_artifacts.md` classifies legacy outputs by provenance. The notebook's 55-benchmark results remain available as research history.

The unfinished reinforcement-learning notebook and root `test.py` TensorFlow environment probe are preserved for development history only. They are not part of the validated solver stack or supported workflow.

## Scope and Limitations

The model does not include support/stability, balance, center of gravity, load-bearing strength, floor or axle loading, unloading order, or routing constraints. Optional total cargo weight is only a scalar capacity.

## External Attribution

The Bischoff–Ratcliff datasets are sourced from J. E. Beasley's OR-Library and attributed to E. E. Bischoff and M. S. W. Ratcliff, *Issues in the Development of Approaches to Container Loading*.

# v1.0.0 Release Notes — Draft

> **DRAFT:** These notes describe a proposed first public release. No release or tag has been created.

## Highlights

- Versioned canonical JSON formats for container-loading instances and solutions.
- Independent validation of identity, orientations, boundaries, non-overlap, packed volume, and utilization.
- Fast validated Greedy Portfolio-IG packing.
- Hybrid Optimize with a validated Portfolio fallback and additional hinted CP-SAT search.
- Standalone OR-Tools CP-SAT with volume/count objective selection, optional total cargo weight capacity, and honest `FEASIBLE`/`OPTIMAL` status reporting.
- PySide6 desktop GUI with Fast, Optimize, Compare, standalone CP-SAT, 3D visualization, and canonical export.
- Deterministic internal/distributional benchmarks and complete OR-Library Bischoff–Ratcliff import infrastructure.
- Reproducible research runners and curated experiment findings.
- Framework-neutral learning feature/dataset infrastructure for future work.

## Fast, Optimize, and Compare

**Fast** runs Portfolio-IG and independently validates its selected packing. **Optimize** validates that Fast candidate, supplies it as a CP-SAT hint, enables the aggregate selected-volume bound, validates any CP-SAT candidate, and selects CP-SAT only when its packed volume is strictly greater. Ties and unsuccessful optimization retain the validated Fast solution. **Compare** presents Fast beside the final Optimize result on the same instance.

This fallback behavior is an orchestration invariant, not an approximation ratio or a guarantee that CP-SAT will improve the heuristic result.

Standalone CP-SAT can maximize either packed volume or the number of selected physical boxes. It can also enforce an optional integer scalar weight capacity when every box type has an explicit weight in one declared unit. This is separate from the fixed volume-oriented Fast, Optimize, and Compare workflows.

## Validation and reproducibility

Solver-specific metadata remains separate from the canonical solution format. Generated user-facing solutions pass through `validate_solution.py`, and benchmark runners preserve status, configuration, runtime, bound, validation, and Git provenance without overwriting previous runs.

The normal automated suite includes offscreen GUI tests, CP-SAT/Greedy integration tests, and a compiled Greedy smoke. Large research campaigns and exhaustive prevalence audits remain explicit opt-in workflows.

## Benchmarks

The repository contains 28 deterministic internal instances, 60 fixed-seed distributional instances, and import/manifest/license support for all 700 Bischoff–Ratcliff OR-Library cases. Generated experiment result directories are normally ignored and may not be present in a fresh clone; committed runners, instances, manifests, raw external sources, and documentation provide the reproducible path.

## Learning infrastructure

`learning_features_v1` provides deterministic physical features, repository dataset enumeration, explicit portable label provenance, stable dataset splitting, non-overwriting export, and framework-neutral predictor/scorer interfaces.

**No trained ML or RL model is part of v1.0.0 or the validated user-facing solver stack.** The legacy RL notebook is unfinished development history, not a benchmark or supported workflow.

## Known limitations

- Boxes and containers are orthogonal rectangular cuboids with axis-aligned placements.
- Optional total cargo weight is only a scalar capacity; balance, center of gravity, support, stability, structural/floor/axle loading, stacking strength, accessibility, and loading order are not modeled.
- Finite CP-SAT budgets may return `FEASIBLE`, which is not proof of global optimality.
- CP-SAT memory and runtime can scale combinatorially with instance size.
- Generated research results are not all committed and may require rerunning the documented experiment runner.
- The GUI has Windows launchers, while other platforms use `python -m gui.app`.
- The legacy RL notebook is not complete, validated, or included in the supported dependency set.

## Research decisions

The adopted Portfolio, warm-start, aggregate-volume tightening, incompatibility, symmetry, and Hybrid decisions are summarized in [Experiments and Research Findings](experiments_and_findings.md). Detailed limitations and provenance classifications remain authoritative there and in the [Historical Artifact Manifest](../historical_artifacts.md).

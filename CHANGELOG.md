# Changelog

## [1.1.0] - Unreleased

### Added

- Human-readable six-button orientation selection that preserves exact canonical orientation identities and order.
- Centralized source/frozen resource and Greedy-backend resolution.
- Reproducible PyInstaller onedir, Inno Setup, portable ZIP, checksum, and Windows artifact workflow definitions.
- Packaged-application self-test and clean Windows acceptance plan.

### Changed

- Packaged GUI runs use a bundled precompiled Greedy executable; source/development mode retains compile-on-demand behavior.
- The application release version is shown independently from unchanged canonical schema version `1.0`.

## [1.0.0] - 2026-08-13

### Added

- Versioned canonical instance and solution formats with an independent geometric validator.
- Reproducible historical Greedy and standalone CP-SAT execution paths.
- Validated Greedy Portfolio-IG/Portfolio-HIG orchestration.
- Hybrid Optimize with validated Portfolio fallback, CP-SAT hinting, aggregate-volume tightening, and strict best-valid selection.
- PySide6 Fast / Optimize / Compare / standalone CP-SAT desktop interface with background solving and 3D visualization.
- Standalone CP-SAT packed-volume/packed-box-count objective selection and optional independently validated integer total cargo weight capacity.
- Deterministic internal, fixed-seed distributional, and OR-Library BR benchmark infrastructure.
- Lightweight `learning_features_v1` extraction, dataset, split, label-provenance, interface, and export scaffold for future research.
- GitHub Actions CI for Python 3.12 tests, offscreen GUI coverage, core imports, and a validated C++ Greedy smoke.

### Research

- Greedy planar-inclusive and geometry-first ablations and portfolio evaluation.
- Portfolio-to-CP-SAT warm-start and repeated robustness studies.
- Aggregate-volume-bound tightening experiment.
- Box-level and orientation-pair incompatibility prevalence audits.
- Identical-copy, manual-prefix, and built-in OR-Tools symmetry studies.
- Controlled 46-instance Portfolio / cold CP-SAT / Hybrid evaluation.

### Documentation

- Concise user-facing README for Fast / Optimize / Compare.
- Curated experiment findings and engineering decisions.
- Architecture, learning-framework, and roadmap documentation.
- Historical-artifact provenance classification.
- Practical release checklist and draft v1.0.0 release notes.

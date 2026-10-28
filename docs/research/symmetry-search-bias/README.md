# Symmetry Breaking vs. Search Bias — Research Hub
> Status: **PROTOCOL PROPOSED / NOT YET APPROVED FOR BENCHMARKS**. Created 2026-10-28. This document is a research coordination proposal, not a claim of new findings. No solver code or benchmark was changed or run in creating this framework.

## Question
In the CP-SAT 3D container-loading formulation, how do static representative-selection constraints interact with the solver's propagation, primal heuristics, LP machinery, and branching? Under what circumstances do they **hurt finite-budget incumbent quality** despite reducing labeled search states?

Do **not** assert neural-network-style convergence or implicit regularization. Treat them as analogies until supported by measurements. Do **not** claim novelty of “symmetry breaking can slow down search”; that interaction is established in the literature.

## Verified repository baseline (remote `main` at framework creation)
- GitHub `main` was at `ec368323080a12f6efe8e44db78d24e30c0d7adf` (last observed commit 2026-08-14); the user's **local** Windows repository and October 27 research documents may be newer. The remote state must not be represented as local state.
- `cpsat_baseline.py` implements optional **selection-prefix** `selected[first] >= selected[second]` for conservatively grouped interchangeable copies, **off by default**. This is *not* a full coordinate/placement lex-leader.
- `cpsat_selection_prefix_experiment.py`, `cpsat_prefix_search_diagnostics.py`, `cpsat_symmetry_level_interaction.py`, and `cpsat_symmetry_parameter_ablation.py` already exist. Reuse their infrastructure; do not build a replacement without a documented gap.
- `docs/experiments_and_findings.md` §§9–13 records historical results: fewer branches can coincide with worse finite-budget incumbent quality; forward and reverse prefixes can behave differently; changing solver `symmetry_level` did not eliminate all pathologies. These are **historical report claims**, not independently rerun under this protocol.
- `results/` is normally git-ignored. Missing raw outputs and provenance must be reported explicitly.

## Research hypotheses (pre-registered, non-exclusive)
- **H1 Representative sensitivity:** fixed-strength symmetry breaking with alternate valid representative orders changes search trajectories/finite-budget performance.
- **H2 Non-LP mechanism:** some prefix penalties persist with LP linearization disabled; this rules out an exclusively LP-driven explanation, not all numerical effects.
- **H3 Encoding/propagation overhead:** constraint growth or presolve/propagation explains part of the penalty.
- **H4 Partial breaking:** a properly defined subset of safe prefix constraints may outperform either no manual breaking or full selection prefix on some problem families.

## Work phases / gates
- **P0 Evidence recovery — read-only.** Determine local branch, status, diff against remote, prior reports, commits, artifacts, solver dependencies and exact settings. Publish evidence inventory, including missing outputs. No rebuild, edits, or benchmark.
- **P1 Design and tiny validation.** Specify experiments, implement only after approval, prove/evaluate physical-solution preservation with tiny independent oracle and verify model-proto diffs. No long runs.
- **P2 Mechanism pilot — approval required.** Paired cases, one worker, pinned solver version, controlled LP/prefix/solver-symmetry settings; collect traces and costs. No expansion without gate review.
- **P3 Broader validation and paper decision.** Multi-seed, holdout instances, robust statistics, negative results included; decide whether new algorithm warranted.
- **P4 Optional method and manuscript.** Adaptive/solver-aware breaking only if P2–P3 identify transferable patterns.

## Collaboration and source of truth
- **GitHub Issues:** questions, assignments, decisions, handoffs, and evidence summaries. One issue per scoped task; link every related PR.
- **GitHub PRs:** proposed code/docs/analysis changes. Never directly rewrite production CP-SAT from a research task. No merge without tests and human approval.
- **Versioned docs:** this hub, [protocol](EXPERIMENT_PROTOCOL.md), [handoff contract](HANDOFF.md), and [paper roadmap](PAPER_ROADMAP.md).
- **Raw results:** use immutable run IDs + commit/hash + environment/instance manifest. Commit only reviewed, reasonably sized, reproducible evidence with source and checksum; never silently depend on local ignored files. For larger logs, use an explicitly named versioned archive/release asset and cite its immutable identity. GitHub Actions artifacts alone may expire.

## Collaboration invariants
1. No assistant has invisible access to another assistant's chat. The issue/PR comment is the communication channel, not an implicit synchronization feature.
2. Every agent reads the current linked Issue and docs, posts a structured handoff comment, and cites commits/paths/configuration before saying “done.”
3. Never claim `OPTIMAL` from `FEASIBLE`/ `UNKNOWN`, a reproduced effect from a historical narrative, or selection prefix from “full Lex.”
4. Prior production decisions remain unchanged; all novel experiments start isolated and off by default.
5. No long-running benchmark or implementation outside the explicitly approved stage.

## Initial action
Start **P0**; stop after the read-only provenance report. Human/research review determines P1 scope.

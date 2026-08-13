# Release Checklist

Use this checklist for the eventual `v1.0.0` release. It does not itself authorize a tag or publication.

## Repository state

- [ ] `main` is clean and matches `origin/main`.
- [ ] The release branch is based directly on the intended `main` commit.
- [ ] No merge/rebase operation or conflict is pending.
- [ ] The reviewed release commit contains no unintended generated files.

## Automated verification

- [ ] GitHub Actions CI is green on the final pull request.
- [ ] The full normal unit/integration suite is green.
- [ ] The two intended exhaustive research skips are understood and remain explicitly opt-in.
- [ ] Python source compilation and core-import checks pass.
- [ ] The C++17 Greedy compile and independently validated tiny smoke pass.

The normal CI job uses Ubuntu, Python 3.12, offscreen Qt, the ordinary test suite, and a tiny Greedy CLI/validator smoke. It does not run the 700-instance optimization campaign, the 46-instance Hybrid campaign, exhaustive prevalence audits, long CP-SAT experiments, notebooks, or ML training. Those remain explicit local/research workflows.

## GUI

- [ ] Fast, Optimize with a short budget, and Compare complete in a real or offscreen Qt event loop.
- [ ] Standalone CP-SAT is visible and completes with both volume and count objectives.
- [ ] Standalone CP-SAT weight OFF, weight ON, and count + weight combinations validate independently.
- [ ] Weighted canonical instances save and reload without losing unit, capacity, or per-type weights.
- [ ] Large integer capacities, including `30,000,000` and the GUI maximum `2,147,483,647`, survive an exact canonical round trip.
- [ ] Switching from CP-SAT to Fast/Optimize/Compare clears unsupported objective/weight state.
- [ ] A geometrically valid overweight solution is rejected by the independent validator.
- [ ] Legacy no-weight instances and workflows remain compatible.
- [ ] Result selection and 3D visualization show the selected canonical solution.
- [ ] Canonical solution and metadata sidecar save correctly and reload where applicable.
- [ ] Loading a new instance clears stale results.
- [ ] Active-worker instance replacement and window close are blocked safely.
- [ ] Windows launchers pass both `.venv` and PATH/override checks on a Windows release machine.
- [ ] The final release code passes a visible Windows GUI smoke after automated offscreen checks.

## Solver invariants

- [ ] User-facing outputs remain independently validated.
- [ ] A valid Portfolio fallback is never replaced by a lower-volume CP-SAT result.
- [ ] Equal packed volume retains Portfolio.
- [ ] `FEASIBLE` is not described as proven optimal.
- [ ] Low-level CP-SAT aggregate-volume and manual-prefix options retain their accepted defaults.
- [ ] OR-Tools built-in symmetry behavior remains at its accepted default.

## Documentation

- [ ] Every README command is tested from repository-relative paths.
- [ ] Relative Markdown links resolve.
- [ ] `CHANGELOG.md` is current and still marks the release as unreleased until tagging.
- [ ] Roadmap and draft release notes are current.
- [ ] Learning documentation states that no trained model is integrated.
- [ ] The unfinished RL notebook remains classified as unsupported development history.

## Reproducibility

- [ ] Internal/distributional benchmark manifests and committed instances are present.
- [ ] OR-Library BR sources, attribution, license, byte hashes, and `-text` rule are intact.
- [ ] Generated/local results are distinguished from committed definitions and runners.
- [ ] No normal command requires a developer-specific absolute path.
- [ ] Representative generated solutions validate independently.

## Packaging and portability

- [ ] Core requirements install in a clean Python 3.12 environment.
- [ ] GUI requirements install and `pip check` passes.
- [ ] Core, GUI, validator, benchmark, Hybrid, and learning modules import cleanly.
- [ ] `g++` or another documented C++17 compiler is available for Greedy execution.
- [ ] Windows launchers are manually checked because Ubuntu CI does not exercise batch files.

## Release metadata

- [ ] Confirm version `v1.0.0` with maintainers.
- [ ] Review and finalize the [draft v1.0.0 release notes](release_notes_v1.0.0-draft.md).
- [ ] Create an annotated `v1.0.0` tag only after final approval.
- [ ] Draft and review the GitHub release from the final tag.
- [ ] Publish only after binaries/assets, links, and checksums are reviewed.

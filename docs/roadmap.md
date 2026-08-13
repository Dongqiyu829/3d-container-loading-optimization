# Roadmap

This roadmap identifies possible next work without promises or dates. Changes to solver behavior should continue to use isolated, reproducible ablations and independent validation.

## Near-term release work

- Complete final human review of the consolidated Hybrid/GUI/documentation diff.
- Verify portable launchers from a fresh `.venv` and a PATH-based Python environment.
- Perform final packaging/dependency and clean-clone audits.
- Review screenshots/demo assets and prepare a first release candidate.
- Keep the release marked Unreleased until a deliberate tag/release decision.

## Optimization research

- Evaluate stronger formulations one valid inequality or formulation change at a time.
- Study search strategies only when a clear hypothesis and model-identity control exist.
- Broaden CP-SAT external benchmarking with explicitly matched feasible-set semantics.
- Keep Greedy and CP-SAT quality, proof progress, availability, and runtime as separate metrics.
- Do not reopen manual symmetry breaking without materially new evidence or a changed formulation.

## Learning-guided optimization

1. Export reproducible physical features with `learning_features_v1`.
2. Normalize and explicitly join validated Hybrid outcome labels.
3. Predict whether CP-SAT will improve Portfolio within budget `t`.
4. Predict a useful CP-SAT search budget.
5. Evaluate against trivial policies and leakage-aware held-out splits.
6. Only then consider learning-guided ranking of existing validated heuristic policies.

No trained model is currently part of Fast, Optimize, or Compare. See `docs/ml_framework.md` for the validation boundary and integration rules.

## Physical realism

Potential future model extensions include:

- support and stability;
- weight distribution and container balance beyond the supported scalar total cargo weight capacity;
- load-bearing limits;
- loading/unloading order and accessibility;
- routing or multi-container constraints.

Each addition changes the feasible set and therefore requires schema, validator, solver, and benchmark design together.

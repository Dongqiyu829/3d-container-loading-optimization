# Publication roadmap — conditional, not a novelty claim
Status: exploratory (2026-10-28). Goal: distinguish a useful computation-science contribution from a known solver phenomenon.

## Core framing
**Working title:** *When Does Symmetry Breaking Hurt Primal Search? A Mechanistic Study of CP-SAT for 3D Container Loading.*

The question is not whether symmetric optima are mathematically redundant (they are), nor whether static symmetry breaking can hurt performance (known). The question is whether a **model-specific, reproducible and generalizable mechanism** can be isolated and exploited.

## Existing related work to verify against published versions
- Katsirelos & Walsh (2010), *Symmetries of Symmetry Breaking Constraints*: branching heuristics can interact strongly with static symmetry-breaking representatives.
- van Doornmalen & Hojny (2024/2025), *A Unified Framework for Symmetry Handling*: static/dynamic symmetry reductions and propagation.
- Anders, Codel & Heule (SAT 2026), *Simplify, Order, Break, Repeat*: formula/encoding cost and symmetry handling.
- Erascu & Middeke (2026), *When Algebraic Symmetry Breaking Meets Solvers: An Experimental Study*: packing-related solver-dependent performance; not necessarily CP-SAT and not the same 3D formulation.
- Perron, Didier & Gay (CP 2023), *The CP-SAT-LP Solver*: actual solver mechanisms.
Do not imply originality from rediscovering a published effect. Verify each paper's DOI, date, scope and findings before citation in a manuscript.

## Potential deliverables
1. **Replication/negative-results study:** faithful historical reproduction and isolated mechanisms; good open research artifact, technical report or focused workshop submission if sufficiently differentiated.
2. **Mechanistic empirical study:** controlled LP on/off, representative-index, encoding and heuristic-trajectory evidence across representative and holdout packing classes; stronger workshop/CPAIOR applied contribution if methodologically robust.
3. **Algorithm paper:** provably safe solver-aware/partial breaking or representative-selection policy, with pre-registered holdouts and convincing multi-seed gains beyond no-prefix + fixed-prefix; potential full CP/CPAIOR research submission or operations-research journal with broader evidence.

## Contribution thresholds
- **No-go for strong novelty claim:** only branch count decreases; only one convenient seed or one instance; no raw evidence; gains only by retuning on test set; merely observes slower Lex.
- **Go for extended experiment:** matched settings, reproducible opposite effects and clean explanation candidates.
- **Go for method paper:** new algorithm + mathematical preservation proof + reliable held-out improvement, explicit cost of selecting a representative, benchmark/data/code release.
- **If null:** report negative results honestly and return to production solver priorities.

## Suggested paper skeleton (future)
Introduction and research question → related work → 3D formulation and symmetry group → selection-prefix vs full placement lex → controlled experiment design → mechanism diagnostics → proposed remedy (if any) → held-out evaluation → limitations/reproducibility.

## Intellectual guardrail
“Implicit regularization / favorable landscape” is an intuition, not a statement about CP-SAT's convergence. Define an actual state graph, heuristic violation metric, search traces, or LP polyhedron before advancing a geometric mechanism.

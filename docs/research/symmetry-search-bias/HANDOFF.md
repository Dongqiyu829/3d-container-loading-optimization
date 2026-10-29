# Cross-agent handoff contract
**GitHub is the message bus, not the chat memory.** No model automatically sees another model's private conversation; each agent must explicitly read the linked GitHub issue, relevant PR and documentation before acting. The human approves merges and stage transitions.

## Roles
- **Research lead (ChatGPT conversation):** literature/novelty checks, hypothesis changes, methodological review, accept/reject, next issue scope.
- **Engineer (Codex local checkout):** read-only audit first; once approved, isolated implementation, short validation, instrumented experiments, raw evidence and PR.
- **Optional adversarial reviewer (separate agent/model):** check mathematical equivalence, leakage, confounders and statistical claims; file independent review in issue or PR.
- **Human owner:** chooses compute budget, approves branch changes/runs/merges and paper release.

## One-cycle operating sequence
1. Read this hub, current issue, relevant PR comments and the source/commit/manifest mentioned in them.
2. Post a concise execution plan and list of invariants/risks to the issue.
3. Execute **only** the explicitly approved task; no opportunistic refactor, no long benchmark or file reset.
4. Create branch and PR for changes; place a stable report and evidence index in the repository. Summarize in issue comment with PR and file links.
5. Research lead reviews the exact latest SHA, source files, tests, and evidence; records `ACCEPT`, `REVISE`, or `BLOCK` with rationale, plus next task.
6. Human merges approved PR. Next agent starts from the resulting commit, not from a pasted chat excerpt.

## Mandatory comment template
```markdown
### Research handoff — <UTC date / agent / task ID>
- Stage and status: P0/P1/P2/P3/P4; PLAN / DONE / BLOCKED
- Branch / HEAD / base SHA / dirty worktree:
- Scope performed; scope explicitly NOT performed:
- Files reviewed or changed (permalink+lines or commit):
- Evidence level: code / raw log / report only / proposed / missing
- Model variants and mathematical equivalence checks:
- Exact command/configuration; version; worker/seed/LP/symmetry; time budgets:
- Results: statuses, objective, bound, first incumbent, quality trajectory, branches, conflicts, LP iterations; missing metrics:
- Test results and validation status (including skipped):
- Raw data locations, hashes and reproducibility instructions:
- Surprises, risks, rival hypotheses, unresolved questions:
- Proposed next step / resource budget / approval requested:
```

For a **read-only P0** report, write `no runs conducted` in experiment fields. Never invent absent metrics.

## File layout suggestion
```text
docs/research/symmetry-search-bias/
  README.md                 # scope and status
  EXPERIMENT_PROTOCOL.md    # pre-registered comparisons
  HANDOFF.md                # agent communication standard
  PAPER_ROADMAP.md          # novelty and publication gates
  reports/                  # future dated, reviewed analysis (not created yet)
```
Do not create or commit a local experiment runner or raw result under this framework without an issue and review gate.

## Permanent rules
- Use exact GitHub issue/PR links and git SHA, not “as discussed earlier”.
- Never mix a historical report, a design hypothesis and new measured evidence.
- A link to a local Windows path is not accessible to remote agents; if relevant, provide a versioned text report with no secrets or private data.
- No one claims approval, auto-merge, CI success or data upload until verified.

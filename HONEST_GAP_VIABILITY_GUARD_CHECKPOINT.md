# Honest-Gap Viability Guard Checkpoint

Date: 2026-08-12
Status: accepted production-path checkpoint; not end-to-end interview-quality acceptance

## Objective

Prevent the production interviewer from repeatedly drilling an unavailable evidence surface after a candidate gives an honest knowledge boundary. The accepted behavior allows one bounded recovery, rotates to a genuinely distinct untested surface, and gracefully closes after sustained gaps while preserving a truthful insufficient-data report.

## Architecture

- A canonical, latest-revision semantic event ledger owns gap pressure. One candidate utterance remains one event across transcript revisions.
- Fast and background paths use the same gap-route materializer.
- Stale background work cannot overwrite a newer turn's agenda, coverage, application state, gap state, or staged question.
- Non-current historical revisions fail closed before state mutation.
- `turn_id` is required at partial-transcript, process-turn, and voice-commit boundaries; TypeScript process/commit helpers require it too.
- Low-evidence closure produces `INSUFFICIENT_DATA` consistently in the final evaluation, persisted report, and session state, with empty scores and failure-surface conclusions.

## Adversarial blockers closed

1. Packet follow-ups cannot preempt mandatory rotate/close.
2. Fast/background processing cannot double-count one answer.
3. Same-turn revisions replace rather than accumulate semantic pressure.
4. Empty turn identities fail before dispatch.
5. Old background work cannot regress newer state or stage a stale question.
6. Semantic background upgrades preserve prior-turn pressure.
7. Older-turn revisions cannot borrow current question/focus metadata or corrupt history.
8. Target-aware duplicate checks allow a similar question intent on a genuinely different surface.
9. Evidence-bearing scoped answers do not become whole-answer knowledge gaps.
10. Graceful low-evidence reports do not retain strong scores, verified claims, role-fit conclusions, or failure-surface conclusions.

## Verification

- Root reproduction: 83 focused pytest checks passed before the final independent gate.
- Final independent adversarial gate: 13/13 focused cases passed, including pytest-discovered async production probes.
- Historical-revision probe preserved the complete stored state and performed zero saves.
- Blank-ID probes returned HTTP 422 before dispatch on all three boundaries.
- A deliberately strong evaluator result was canonicalized across evaluation, session state, and persisted report to `INSUFFICIENT_DATA`, empty scores, and empty failure surface.
- `python3 -m py_compile` and `git diff --check` passed.
- Direct no-provider contract script passed with `PYTHONPATH=.`.
- No provider calls were made for this repair or its review.

## Deliberate limitations

- Historical answer revisions are unsupported and rejected rather than reconciled.
- The guard is a safety/control checkpoint, not proof that question selection is globally excellent.
- The accepted deterministic runner remains a control-plane proof; the next semantic run must use a question-responsive CandidateActor rather than a fixed fact sequence.
- The five frozen CandidateWorlds are sufficient for the next phase; more worlds are not yet the bottleneck.
- A full TypeScript compile was not reproducible inside the isolated worktree because it has no local `node_modules`; current live-room call sites were inspected and always supply generated turn UUIDs. The helper signatures are now aligned with the backend requirement.

## Next prerequisite

Build and independently accept a question-responsive CandidateActor simulation seam over the existing five worlds. It must map each exact interviewer question to only relevant currently available world facts, answer with an honest boundary when evidence is unavailable, preserve disclosure chronology and ownership, and emit exact question-to-fact-to-answer lineage. Only then rerun the same failed real-semantic interview through the accepted production path.

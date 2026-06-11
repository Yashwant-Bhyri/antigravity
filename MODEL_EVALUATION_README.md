# Antigravity Model Evaluation Ledger

This file records model-quality, latency, cost, and scaffolding findings from controlled Antigravity evaluation runs.

Use it as the running memory for model policy decisions. Every serious model/prompt/scaffolding iteration should add a dated entry with:

- what was tested,
- which models were tested,
- fixtures/cases used,
- pass/fail numbers,
- latency/cost,
- artifacts,
- interpretation,
- decision or next step.

Important principle: do not compare models only by pass rate or latency. Antigravity's priority order is:

1. Reliability and schema stability.
2. Report/interview quality.
3. Fairness and evidence grounding.
4. Cost.
5. Latency.

Latency matters much less for final reports than for live interview turns. A final report can arrive on the admin dashboard minutes after the interview if quality is materially better.

---

## Current Model Policy Snapshot

As of 2026-06-01:

- Small structured tasks: Gemini 3.1 Flash Lite remains the leading replacement candidate for Haiku-class work, based on earlier small-tier quality tests.
- Medium live interview tasks: Gemini 3.5 Flash is promising after prompt/schema repair, but Sonnet remains safer for high-stakes weakness/follow-up/checker behavior.
- DeepSeek V4 Flash/Pro: useful as cheap advisory/offline audit only for now. Direct probes showed it can reason, but provider latency/output stability is not reliable enough for blocking live flow.
- Final report / large-tier writing: Report V2 passed with Sonnet 4.6, Gemini 3.1 Pro Preview, and Gemini 3.5 Flash. Because report latency is not user-facing, reliability and quality should decide final routing.
- Sonnet 4.6: reliable quality authority, but slow and often returns fenced JSON. Keep as authority/rescue/checker.
- Gemini 3.1 Pro Preview: strong final-report candidate after Report V2 gates, much faster than Sonnet in the isolated matrix.
- Gemini 3.5 Flash: fastest final-report candidate in the isolated matrix, passed after deterministic V2 guards; keep under normalizer/checker until full interview evidence confirms.

---

## 2026-06-02 — Silverline Phase-1 Production Readiness Gate

### Purpose

Run the final production-readiness suite in phased batches. This pass intentionally fixed low-risk scaffolding first, then ran only the first two paid cases:

- strong product analyst / hireable;
- strong technical AI engineer.

The goal was to stop on real blockers instead of spending through all six cases.

### Code And Policy Changes

- Application-transfer anchor extraction now uses `grounded transfer anchor` language instead of `implementation detail` / ownership-dominant language.
- Overlong application-transfer voice repair now has deterministic checks plus a cheap verifier and one verifier-guided retry.
- Repaired app-transfer questions must preserve role relevance, assessment intent, answer space, and avoid unsupported assumptions.
- The robust simulation suite now includes six cases, including a messy/noisy resume case.
- Early focus pivots are no longer counted as true second-anchor attempts.
- Premature repeated synthesis is bounded by a turn-13 floor.
- After the paid run exposed strong-AI hidden-internal assumptions, `interview_map.py` gained a deterministic guard against unsupported terms such as latent/diffusion/identity-embedding style internals unless seed evidence supports them.

### No-Credit Gate

Latest deterministic audit:

- Artifact: `/tmp/antigravity_scaffolding_audit_20260602_043959.{json,md}`
- Total cases: 76
- Solved: 58
- Historical unknowns: 17
- Low hardcoding-risk warnings: 1
- High-severity failures: 0
- Green for paid confirmation: true

Additional checks run:

- compile on touched backend files;
- parser contracts;
- agenda contracts;
- policy checker contracts;
- final report contracts;
- `git diff --check` on touched Silverline files.

### Paid Phase 1 Evidence

Artifacts:

- `/tmp/antigravity_silverline_phase1_final_20260602_full_gate.{json,md}`
- `/tmp/antigravity_silverline_phase1_final_20260602_full_all.{json,md}`

Result:

- `best_product`: structurally passed. 15 turns, report ready, app transfer on turn 5, coverage after transfer, second anchor reached, final `MAYBE 6.2`. The overlong app-transfer question was repaired and accepted by the new verifier.
- `strong_ai`: structurally completed, but failed production quality. It asked hidden technical-internal questions around identity embeddings/latent behavior before the candidate had established that layer, and it showed premature synthesis/second-anchor rhythm warnings.

Interpretation:

The system is not Silverline production-ready yet. The best-product case shows the product analyst path is close, but the strong-AI case proves the map/interviewer can still over-infer technical internals from resume wording. Structural completion alone is not enough.

### Decision

Do not run all six simulations yet. Next paid confirmation should rerun `strong_ai` first, or `best_product,strong_ai` if budget allows, after the hidden-internals guard. Continue to `average_partial`, `honest_gap`, `trap_overclaim`, and `messy_resume` only after the strong-AI semantic blocker is cleared.

---

## 2026-06-01 — Report V2 Large-Tier Paid Gate

### Purpose

Verify the final report and large-tier path end to end before spending on full 15-turn interview simulations.

This intentionally isolated the report writer from map generation and live interview orchestration. The goal was to answer:

- Does Report V2 preserve evidence-first philosophy?
- Does it avoid punitive/candidate-wide rejection under narrow coverage?
- Does it preserve honest correction and alternate-fit strengths?
- Does the schema hold across real model calls?
- Which large-tier report writer is reliable enough to consider?

### Code Under Test

- `backend/models/final_report.py`
- `backend/agents/evaluation_agent.py`
- `backend/services/orchestrator.py`
- `backend/api/routes.py`
- `app/report/[session_id]/page.tsx`
- `backend/test_final_report_quality_matrix.py`
- `backend/test_final_report_contract.py`

### Fixtures

Five report-only transcript fixtures:

| Case | Purpose |
|---|---|
| `best_product_strong` | Strong product analyst with role-relevant analytics, conversion, taxonomy, coverage, and dashboard evidence. |
| `narrow_tunneled_product` | Bad interview coverage: over-focus on off-role CV internship. Must become `INSUFFICIENT_DATA`, not `NO HIRE`. |
| `honest_gap_corrected_overclaim` | Candidate corrects/narrows an overclaim. Honesty should be preserved, not punished as fraud. |
| `trap_inflated_claim` | Candidate gives vague ownership/denominator-free AI/RAG/OCR claims. `NO HIRE` can stand only with enough coverage. |
| `alternate_fit_product_ui` | Weak target-role backend fit but strong verified adjacent product/UI/analytics signal. Must preserve alternate fit. |

### Models

| Label | OpenRouter ID | Role In Test |
|---|---|---|
| Sonnet 4.6 | `anthropic/claude-sonnet-4.6` | Quality authority / reliability baseline |
| Gemini 3.1 Pro Preview | `google/gemini-3.1-pro-preview` | Large-tier report candidate |
| Gemini 3.5 Flash | `google/gemini-3.5-flash` | Faster report candidate |
| Gemini 3.1 Flash Lite | `google/gemini-3.1-flash-lite` | Advisory reviewer for every report |

### Final Green Result

Final artifact:

- `/tmp/antigravity_report_v2_quality_matrix_20260601_055244.json`
- `/tmp/antigravity_report_v2_quality_matrix_20260601_055244.md`

Result:

| Model | Passes | Cases | Average Latency |
|---|---:|---:|---:|
| Sonnet 4.6 | 5 | 5 | ~84.9s |
| Gemini 3.1 Pro Preview | 5 | 5 | ~33.8s |
| Gemini 3.5 Flash | 5 | 5 | ~26.4s |

Overall:

- 15/15 model/case runs passed.
- 0 retries.
- 0 parse failures.
- 0 provider errors.

### Token And Cost Audit

Artifacts:

- `/tmp/antigravity_report_v2_token_audit_20260601_055244_1780274102.json`
- `/tmp/antigravity_report_v2_token_audit_20260601_055244_1780274102.md`

Summary:

| Metric | Value |
|---|---:|
| Calls | 30 |
| Billable prompt tokens | 197,883 |
| Billable completion tokens | 62,724 |
| Billable total tokens | 260,607 |
| Estimated cost | `$0.921536` |

By model:

| Model | Calls | Billable Tokens |
|---|---:|---:|
| Gemini 3.1 Flash Lite advisory reviewer | 15 | 113,938 |
| Gemini 3.5 Flash | 5 | 52,381 |
| Sonnet 4.6 | 5 | 47,861 |
| Gemini 3.1 Pro Preview | 5 | 46,427 |

Interpretation:

- The advisory review pass is cheap per token but still carries a large prompt burden because it sees the evidence packet and primary report.
- Report generation often uses a lot of completion budget. Do not cut `REPORT_MAX_TOKENS` yet.
- Gemini 3.5 Flash came closest to full output utilization on some calls, so it especially needs the current report token room.

### Quality Audit

Artifacts:

- `/tmp/antigravity_report_v2_llm_quality_audit_20260601_055244_1780274102.json`
- `/tmp/antigravity_report_v2_llm_quality_audit_20260601_055244_1780274102.md`

Summary:

- 30 aggregate calls.
- 30 attempts.
- 0 retries.
- 0 parse failures.
- 0 provider errors.
- Sonnet returned fenced JSON / non-JSON prefix formatting noise in all 5 report calls, but parsing succeeded.

### Issues Found During Gate

The first paid matrix did not pass cleanly. It exposed useful report-scaffolding issues:

1. Gemini 3.1 Pro could produce `NO HIRE` while also giving a high score and strong alternate-fit prose.
2. Gemini 3.5 Flash could return valid JSON with a truncated/incomplete summary.
3. Gemini 3.5 Flash could under-fill the `human_calibration_lens` even when the evidence packet contained honest claim-narrowing.

### Fixes Made

Implemented in `backend/models/final_report.py`:

- High-score `NO HIRE` plus verified alternate-fit evidence is softened to `MAYBE`, with reconciliation recorded.
- Incomplete summaries are replaced with an evidence-packet fallback summary.
- Honest claim-narrowing is preserved in the human-calibration lens even if the report writer misses it.
- Review reconciliation now records accepted normalization changes or advisory concerns.

Contract coverage added in `backend/test_final_report_contract.py`:

- high-score alternate-fit `NO HIRE` softening,
- incomplete-summary fallback,
- honest-correction preservation even with a missing/empty human lens.

### Decision

Report V2 / large-tier path has a green signal for isolated report generation.

Do not interpret this as a full-product green signal yet. The next gate must test full live interview behavior:

- map quality,
- agenda adherence,
- no tunneling,
- application transfer timing,
- coverage after transfer,
- second-anchor pivot,
- final report consistency with the actual live transcript.

### Model Policy Interpretation

Sonnet 4.6 is still the safest authority model, but it is slow. Since report latency is not user-facing, it remains acceptable for high-risk cases. However, the isolated evidence says Gemini 3.1 Pro and Gemini 3.5 Flash are viable report-writer candidates behind Report V2 normalization.

Suggested next policy to test in the full 15-turn gate:

```text
Primary report writer: Gemini 3.1 Pro Preview or Gemini 3.5 Flash
Advisory reviewer: Gemini 3.1 Flash Lite
Authority/rescue: Sonnet 4.6 for failed gates, high-risk contradictions, or reviewer/report mismatch
No Opus default
DeepSeek: async advisory only
```

Because quality matters more than report latency, do not choose Gemini only because it is faster. Choose it only if the full interview report remains grounded and fair.

### Verification Commands

Commands run:

```bash
python3 -m py_compile backend/models/final_report.py backend/agents/evaluation_agent.py backend/services/orchestrator.py backend/api/routes.py backend/test_final_report_contract.py backend/test_final_report_quality_matrix.py
PYTHONPATH=. python3 backend/test_final_report_contract.py
npm run build
```

Paid matrix command shape:

```bash
LLM_USAGE_AUDIT=1 \
LLM_QUALITY_AUDIT=1 \
LLM_QUALITY_CAPTURE_TEXT=1 \
ENABLE_REPORT_ADVISORY_REVIEW=1 \
REPORT_MAX_TOKENS=5000 \
REPORT_REVIEW_MAX_TOKENS=1200 \
PYTHONPATH=. python3 backend/test_final_report_quality_matrix.py
```

Audit report commands:

```bash
PYTHONPATH=. python3 backend/llm_token_audit_report.py --usage-dir <usage_dir> --out-prefix /tmp/antigravity_report_v2_token_audit --fetch-pricing
PYTHONPATH=. python3 backend/llm_quality_audit_report.py --quality-dir <quality_dir> --usage-dir <usage_dir> --out-prefix /tmp/antigravity_report_v2_llm_quality_audit
```

---

## 2026-06-01 — Full Apparao Gate With Report V2 And Token Audit

### Purpose

Run the paid full 15-turn Apparao-style gate after the Report V2 isolated matrix, with token and quality audit enabled.

This tested the actual live loop again:

- map generation and critic behavior,
- agenda phase control,
- application-transfer timing,
- post-transfer coverage,
- second-anchor routing,
- Report V2 finalization,
- token/cost shape,
- and whether the synthetic "best candidate" answer harness is faithful enough to trust.

### Code Changes Before The Reruns

- `backend/services/interview_map.py`
  - relaxed launch-readiness so harmless opener notes like `None`, `minor`, `strong`, or `acceptable` do not block startup;
  - added top-two critic authority, so `top_two_ready` plus a strong critic score can launch without forcing repair first;
  - deferred local startup repairs instead of blocking the first turn when the pass-one map is already launch-ready;
  - used compact critic prompts for repair-stage critique;
  - reduced false taxonomy-boundary drift by classifying conversion/dashboard intent before taxonomy;
  - stopped cheap local repair targets from automatically marking the whole map unready.
- `backend/services/orchestrator.py`
  - map build errors now preserve the exception type when `str(e)` is empty, so `TimeoutError` is visible.
- `backend/test_robust_interview_simulation_suite.py`
  - expanded the Apparao answer bank and added question-aware buckets for trial causality, track-end denominators, live feature transfer, session-end diagnostics, off-app tracking, retention diagnostics, and dashboard/attribution probes.

### Paid Runs

| Run | Artifact | Result | Notes |
|---|---|---|---|
| `20260601_061540` | `/tmp/antigravity_full_gate_20260601_061540_full_gate.{json,md}` | Failed before turn 1 | Map repair/critic timed out before any interview question. Token audit recorded 17 calls, 109,881 tokens, roughly `$0.56` by current model prices. This exposed the over-blocking startup repair path. |
| `20260601_063720` | `/tmp/antigravity_full_gate_20260601_063720_full_gate.{json,md}` | Structural pass | 15 turns, app transfer turn 5, coverage turns 6-10, second anchor turn 11, max focus streak 4, report complete. Verdict was still `NO HIRE` because the synthetic answerer mismatched several generated questions. |
| `20260601_064856` | `/tmp/antigravity_full_gate_20260601_064856_full_gate.{json,md}` | Structural pass | Same structural shape after the first answer-bank expansion. Still failed substantive "best candidate" meaning because more question buckets were mismatched. |
| `20260601_070050` | `/tmp/antigravity_full_gate_20260601_070050_full_gate.{json,md}` | Structural pass | Latest ground truth: 15 turns, app transfer turn 5, coverage 6-10, second anchor 11, max same-focus streak 3, no generic flags, map adherence 90, Report V2 ready/complete. Verdict stayed `NO HIRE` 2.5 because the synthetic answers still did not faithfully answer several questions. |

Latest token/quality artifacts:

- `/tmp/antigravity_full_gate_token_audit_20260601_070050_1780278048.{json,md}`
- `/tmp/antigravity_full_gate_quality_audit_20260601_070050_1780278048.{json,md}`

Latest token audit:

| Metric | Value |
|---|---:|
| Calls | 118 |
| Billable prompt tokens | 159,807 |
| Billable completion tokens | 58,165 |
| Billable total tokens | 217,972 |
| Retries | 0 |
| Parse/provider failures in quality audit | 0 |

Approximate cost from the current known prices was about `$1.06` for the latest full gate:

| Model | Tokens | Approx Cost |
|---|---:|---:|
| Sonnet 4.6 | 141,437 | `~$0.91` |
| Gemini 3.1 Flash Lite | 40,744 | `~$0.013` |
| Gemini 3.5 Flash | 25,343 | `~$0.14` |
| DeepSeek V4 Flash | 10,448 | `~$0.001` |

### Interpretation

Backend structural gate is green for the Apparao case:

- no empty completed session,
- no completed session without report,
- 15 turns completed,
- application transfer served on time,
- coverage asked after transfer,
- second anchor reached,
- focus streak stayed within the anti-tunnel gate,
- no silent generic sprint opener after turn 5,
- Report V2 completed with token/quality audit.

Substantive product-quality gate is not green yet.

The main blocker is the simulation harness, not the agenda controller. The latest transcript still contains synthetic answer mismatches:

- track-end trigger questions received guardrail/threshold answers;
- retention hypothesis and trial-causality questions sometimes received generic taxonomy answers;
- one coverage question about 40% non-use received a closing-summary answer;
- the voice-journaling second-anchor question received a social-sharing answer;
- later concurrent-feature questions received generic primary-claim answers.

Because the candidate answer stream looked evasive/repetitive, Report V2 reasonably produced a harsh `NO HIRE`. That means the full loop is structurally healthy, but this cannot be used as evidence that the best-case candidate experience is product-ready.

### Next Fix Before Five Full Simulations

Do not run the full five 15-turn suite yet.

The next work should make the answer simulation faithful:

1. Replace brittle keyword buckets with a stronger question classifier, or use a low-cost LLM answerer constrained by the case answer profile.
2. Re-run the one Apparao gate and require a strong-candidate transcript that actually answers the generated questions.
3. Then inspect whether Report V2 gives a fair positive/mixed verdict when the transcript is genuinely strong.
4. After that, run the five-resume map-only suite, then the full five-case suite.

Secondary issues found:

- map startup is still slow, roughly 2 minutes in the latest structural pass;
- final report and advisory review are among the largest prompt consumers;
- per-answer scoring calls request a very high max-token budget relative to actual completions and should be tightened after quality is stable;
- application-transfer wording can still be overpacked and should go through the readability gate more aggressively.

---

## 2026-06-01 — Cheap LLM Candidate Answerer Gate

### Purpose

Replace the brittle keyword answer bank with a cheap question-aware LLM answerer, then rerun the Apparao full gate.

The answerer uses Gemini 3.1 Flash Lite by default:

```text
SIM_ANSWER_MODE=llm
SIM_ANSWER_MODEL=google/gemini-3.1-flash-lite
```

It receives the current generated question, the case resume, the case behavior profile, recent turns, and the old answer-bank suggestion as a fallback. It must return one JSON object with a direct first-person candidate answer while staying inside the case facts.

### Code Changes

- `backend/test_robust_interview_simulation_suite.py`
  - added `_llm_answer_for()` as a cheap structured candidate simulator;
  - kept the old answer bank as fallback;
  - added answer metadata to JSON/Markdown reports: model, fallback usage, edge signal, rationale, latency;
  - exposed `SIM_ANSWER_MODE`, `SIM_ANSWER_MODEL`, `SIM_ANSWER_TIMEOUT`, and `SIM_ANSWER_MAX_TOKENS`.
- `backend/agents/weakness_agent.py`
  - normalized common invalid weakness/probe enum variants instead of crashing the background pipeline.
- `backend/services/orchestrator.py`
  - blocked stale background pipelines from re-staging application transfer after the fast path already served it;
  - reconciled final `question_count` upward to history length before final evaluation when the committed history is ahead of the counter.

### Runs

| Run | Artifact | Result | Interpretation |
|---|---|---|---|
| `20260601_072916` | `/tmp/antigravity_llm_answerer_gate_20260601_072916_full_gate.{json,md}` | Completed but gate failed | Cheap answerer worked: 0 answerer fallbacks, mostly `strong_direct` answers, verdict improved to `MAYBE` 6.2. But orchestration exposed duplicate application transfer, background WeaknessAgent enum crash, and `history_len=15` vs `question_count=14`. |
| `20260601_074126` | `/tmp/antigravity_llm_answerer_gate2_20260601_074126_full_gate.{json,md}` | Failed before turn 1 | After fixing the obvious orchestration issues, this run hit the map path: Sonnet critic marked pass-one map `ready=false`, `overall_score=6.2`, `top_two_score=7.8` because focus area 3 was mis-anchored into CV despite a marketing/dashboard label. Full plan repair was triggered and timed out. |

### Findings

The cheap LLM answerer is a real improvement. In the completed run:

- answerer fallbacks: `0`;
- edge signals: mostly `strong_direct`, one `partial_specific`;
- candidate answers were much more aligned to the generated questions;
- Report V2 moved from fake harsh `NO HIRE` to `MAYBE` 6.2.

But the run caught two product vulnerabilities:

1. **Stale background staging can corrupt route sequence.**
   A slower background pipeline can still make a routing decision based on pre-fast-path state. This caused application transfer to be served twice before the stale-stage guard was patched.

2. **Map startup is still not robust under plan-level critic failure.**
   When Gemini 3.5 Flash produces a map with one wrongly promoted/off-role focus, Sonnet correctly catches it. But the repair path still uses full plan regeneration and can burn minutes before timing out. This is now the primary blocker before five full simulations.

### Decision

Do not run the five full interviews yet.

Next engineering target:

- make map plan repair bounded and local enough that one bad focus does not force a full blocking startup regeneration;
- preserve pass-one launchable tracks when only the later pivot track is bad;
- if the first two tracks are strong but a third/fourth track is wrong, start the interview and repair/defer later tracks asynchronously;
- rerun one Apparao LLM-answerer gate after map-startup repair is bounded.

---

## Next Planned Gate

Run one more full paid 15-turn Apparao-style interview with token and quality audit enabled, but only after map plan repair is bounded so one bad later focus cannot force a full blocking startup timeout.

Why:

- The report layer is now isolated-green.
- The answer stream is now trustworthy enough to expose the next blocker.
- The remaining risk is full-system behavior with bounded map startup repair: map generation, agenda controller, answer-aware simulation, application transfer, coverage, second anchor, and final report integration.

Acceptance focus:

- `question_count >= 15`
- history length matches question count
- application transfer served at the right time
- coverage asked after transfer
- at least two substantive focus/sub-focus areas tested
- second anchor attempted
- max same-surface streak stays within gate
- final report V2 generated
- verdict obeys coverage gate
- token/cost audit generated
- no generic fallback route after turn 5

Suggested run order:

1. Bound map plan repair so launch-ready priority tracks can start even if later tracks need repair.
2. One full Apparao 15-turn gate with `SIM_ANSWER_MODE=llm`.
3. Inspect transcript, route sequence, focus/sub-focus sequence, report, token audit, quality audit.
4. If clean, run five-resume map-only suite again.
5. If map-only remains sane, run the full five 15-turn simulations.

---

## 2026-06-01 - Bounded Launch-Ready Map Prep Gate

### Code Change

Implemented bounded map startup:

- focus/sub-focus plan first;
- generate only two launch tracks before turn 1;
- Sonnet critiques only launch tracks;
- DeepSeek V4 Flash audits only the compact focus plan with soft timeout;
- later tracks move to `deferred_focus_plan` / `pending_hydration_focus_keys`;
- async hydration appends accepted tracks and quarantines rejected tracks;
- launch metadata is persisted: `launch_ready`, `full_map_ready`, `needs_async_hydration`, `launch_focus_keys`, `map_quarantine`;
- indexed critic paths such as `focus_areas[1].opener` now localize to exact field repairs;
- major launch opener/readability issues trigger bounded surgical repair; noncritical local notes can defer.

### Paid Map-Only Evidence

Latest Apparao map-only gate:

- Artifact: `/tmp/antigravity_bounded_launch_map4_20260601_map_policy.{json,md}`
- Result: pass
- Startup: ~138.9s
- Launch tracks: 2
- Deferred tracks: `marketing_performance_attribution`
- CV promotion: none
- DeepSeek: advisory audit only, no blocking wait
- Repairs: 3 surgical launch repairs, accepted by field verifier
- Map quality: overall 8.7, boundary 10.0, opener 9.0, dimension 8.6, readability 6.0

Latency shape:

- Focus plan: ~15.0s
- Launch track generation: ~62.8s
- Sonnet launch critic: ~51.5s
- Surgical launch repair: ~9.6s
- Full-map startup critic: removed
- Full-plan/full-track startup repair loop: removed for non-launch tracks

### Paid 15-Turn Evidence

Full Apparao gate:

- Raw artifact: `/tmp/antigravity_bounded_launch_full_gate_20260601_full_gate.{json,md}`
- Phase-aware rejudged artifact: `/tmp/antigravity_bounded_launch_full_gate_20260601_full_gate_rejudged.{json,md}`
- Result: pass after using phase-aware effective focus streak
- Question count: 15
- History length: 15
- Application transfer: turn 6
- Coverage turns: 7, 8, 9
- Second anchor: turn 10
- Report: ready
- Finalization: complete
- Verdict: `MAYBE`, score 6.8
- Generic late fallback: none

Important interpretation:

- The raw transcript focus sequence reported a max streak of 5 because it attributed application-transfer and coverage expansion back to the source resume focus.
- Backend `assessment_coverage.max_same_focus_streak` was 3 because it is phase-aware. The robust gate now uses `effective_max_same_focus_streak` for this reason.
- This is not hiding tunneling; it separates "same resume source being used for transfer/coverage expansion" from "same issue repeatedly drilled as normal depth."

### Remaining Model/Latency Finding

The bounded contract fixed the structural problem, but not all latency:

- Gemini 3.5 Flash still falls through to Sonnet rescue for some launch-track generation.
- Sonnet launch-track generation can take ~50-60s.
- Sonnet launch critic can take ~50s even on two tracks.

Next model-policy work should test:

- Gemini 3.5 Flash or Gemini 3.1 Pro as launch-track critic first-pass;
- Sonnet as authority only when structural/quality checks fail;
- preserving Sonnet for final/improver roles, not every launch-track path;
- keeping DeepSeek V4 Flash async/advisory only.

### Five-Resume Map-Only Follow-Up

Initial broad map-only batch:

- Artifact: `/tmp/antigravity_bounded_launch_five_map_20260601_map_policy.{json,md}`
- Result: 4/5 launch-ready.
- Passes: best product analyst, strong technical AI engineer, average partial product/data analyst, honest-gap corrected overclaim.
- Failure: trap inflated-claim candidate failed closed after bounded repair/replacement.

The trap failure was then isolated:

- Artifact before boundary fix: `/tmp/antigravity_bounded_launch_trap_rerun_20260601_map_policy.{json,md}`
- Result: launch-ready in ~73.5s, but map scorecard reported boundary score `0.0`.
- Diagnosis: deterministic boundary checker treated retention/churn `campaign` language as dashboard leakage.

Patch result:

- Artifact after boundary fix: `/tmp/antigravity_bounded_launch_trap_fixed_20260601_map_policy.{json,md}`
- Result: launch-ready in ~74.4s.
- Launch tracks: `retention_churn_modeling`, `funnel_optimization_pricing_experiments`.
- Pending hydration: `product_instrumentation_engagement`.
- Boundary score: `10.0`.
- Overall map score: `9.2`.
- Repairs: `0`.
- DeepSeek: advisory-only ranking concern, no startup block.

Fixed five-case rerun:

- Artifact: `/tmp/antigravity_bounded_launch_five_map_fixed_20260601_map_policy.{json,md}`
- Result: 5/5 launch-ready.
- All cases had `first_two_launch_ready=true`.
- No quarantines.
- All cases deferred a third track for async hydration.
- Scores:
  - Best product analyst: overall 9.1, boundary 10.0, readability 9.2.
  - Strong technical AI engineer: overall 9.1, boundary 10.0, readability 10.0.
  - Average partial product/data analyst: overall 8.2, boundary 10.0, readability 2.0.
  - Honest gap/corrected overclaim: overall 9.1, boundary 10.0, readability 8.4.
  - Trap inflated-claim candidate: overall 8.8, boundary 10.0, readability 7.6.

Interpretation:

The bounded launch architecture is now green at the map-only layer across the five deliberate resumes. The remaining map concern is not readiness; it is question voice/readability on the average partial case. The next paid step can be full five 15-turn simulations, with transcript quality and report fairness reviewed manually in addition to structural gates.

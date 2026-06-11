# Antigravity — Pre-Production Problem Audit

**Compiled from:** full codebase read, two completed session exports (Praveen / Mahesh), one prepared session, three design documents.
**Date:** 2026-05-16
**Status:** This is the honest list. Not filtered for optimism.

---

## Severity Legend

- **CRITICAL** — Breaks sessions or produces wrong verdicts. Cannot ship.
- **HIGH** — Significantly degrades quality on most sessions. Should not ship.
- **MEDIUM** — Quality issues appearing in some sessions. Should fix before scale.
- **DESIGN** — Architectural or philosophical gaps requiring rethinking, not just patching.

---

---

# CRITICAL ISSUES

---

## C-1: Resume Parser Fails on Virtually Every Real Resume

**What's broken:**
`resume_agent.py` is producing catastrophically wrong output on both structured and semi-structured resumes. Confirmed across all three sessions read.

**Observed output (AppsForBharat resume):**
```json
"skills": [],
"projects": [],
"experiences": [],
"claims": [
  { "text": "Built and scaled Golang microservices for Puja, Chadhava, Astrology, Wallet, and Temple domains, serving" }
]
```
The claim is cut mid-sentence at a line break. Skills, projects, and experiences are empty despite being richly present in the resume. Tools array contains `"CI"` and `"CD"` as separate entries because the parser split on commas inside the line `"CI/CD pipelines"`.

**Observed output (Praveen resume):**
```json
"projects": [
  { "name": "gmail.com ï LinkedIn § GitHub Ð LeetCode" },
  { "name": "B.Tech in Computer Science and Engineering CGPA: 7.63/10" }
]
```
Contact info and a degree are being classified as projects.

**Why it matters:**
`parsed_resume` is used by:
- `FollowUpAgent._build_resume_context()` — every follow-up LLM call gets garbage resume context
- Experience tier calculation — produces "junior" for a Golang engineer at 10M users
- Ownership level / contribution type classification — feeds into probe framing
- `ResumeAgent._merge_with_fallback()` — the heuristic fallback is also producing wrong output

The interview map generation survives because it reads the raw `resume` string directly. Everything else downstream does not.

**Why it's not crashing sessions:**
The LLM models are resilient enough to produce coherent questions despite the junk context. The failure is silent — no exception, just wrong data silently degrading quality on every session.

**Fix direction:**
The heuristic parser (`_heuristic_parse()`) is the likely failure point — it's splitting on line breaks and commas without understanding the resume's section structure. Options:
1. Pre-process the raw resume string to identify section boundaries (regex on common headers: "Experience", "Projects", "Skills", "Education") before parsing
2. Make the LLM parse pass mandatory with a more robust prompt that handles malformatted PDFs/text — explicit instruction to not split bullet points at line breaks
3. Add a validation pass: if `len(parsed_resume.projects) == 0` and the raw resume contains project keywords, mark parse as failed and retry with a different strategy

---

## C-2: `_infer_focus()` Returns Empty on Every Turn

**What's broken:**
Every turn in both completed sessions shows `focus_key: ""` and `focus_label: ""` in the history. The `_infer_focus()` function in `orchestrator.py` is consistently returning empty string.

**Cascading failures this causes:**

| Downstream system | What breaks |
|---|---|
| Fast path trajectory map selection | Can't ground questions to the right focus area |
| Coverage map dimension tracking | Can't mark which dimensions were addressed |
| Bridge mechanism | Can't detect "this focus area is exhausted" |
| Speculative cache lookup | Keyed on focus_key — lookups return nothing |
| `select_from_trajectory_map()` | Gets called with empty focus_key, picks arbitrary branches |

**Suspected cause:**
`_infer_focus()` likely computes token overlap between `(question + answer)` and each focus area's `anchor_context`. If the overlap threshold is too high or the focus area keys don't match the format being looked up, it always returns empty. The active_question_packet already carries the correct `focus_key` from when the question was staged — this data exists and is being discarded.

**Fix direction:**
- As an immediate fix: propagate `active_question_packet.focus_key` into the turn's `focus_key` field instead of re-inferring it — the packet already knows which focus area it belongs to
- Log what `_infer_focus()` is actually computing to find why the threshold is never met
- The re-inference approach can coexist as a fallback when the packet has no focus_key

---

## C-3: Bridge Never Fires — Interviews Get Stuck on One Topic

**What's broken:**
Mahesh's session (confirmed resume fraud on Turn 6): the interview ran all 15 turns on CMS/RBAC and never reached Golang microservices, Redis caching, CI/CD, LLM integration — all on the resume, potentially areas where he had real knowledge.

`consecutive_high_weakness_count` shows `0` at session end despite 8+ high-severity weaknesses across 14 turns.

**Why this is critical:**
A stuck interview produces an incomplete assessment regardless of how good the analysis layer is. For a borderline candidate this could flip the verdict. For a resume-fraud candidate like Mahesh, we got NO HIRE on incomplete evidence — we got lucky that RBAC was clearly fraudulent. What if the stuck topic had been ambiguous?

**Root cause (likely two separate bugs combining):**
1. `consecutive_high_weakness_count` is not incrementing — either `_apply_staged_analysis()` isn't updating it correctly, or it's being reset to 0 somewhere in the turn lifecycle
2. Even if it incremented, the bridge selection can't fire because `focus_key` is empty (C-2), so the system can't identify which focus area is exhausted

**Fix direction:**
- Instrument `consecutive_high_weakness_count` with logging at every turn to find where it resets
- The bridge trigger should not require `focus_key` — it should trigger from `inferred_focus_key` in the weakness ledger, which IS being populated correctly by WeaknessAgent
- Hard rule: if `weaknesses` contains >= 3 entries with the same `inferred_focus_key` and severity medium/high, force `bridge_to_next_focus` regardless of normal routing priority
- Hard cap: no single focus area should be probed more than 5 turns total

---

## C-4: Trajectory Map Underutilized at Runtime — `sprint_seed` Dominates

**What's broken:**
In Praveen's session: 7 of 15 turns served from `sprint_seed`. The trajectory map costs 2-3 Sonnet calls per focus area to generate, plus a critic pass and optional repair — then is largely bypassed at runtime in favor of on-the-fly Haiku improvisation.

**Why it matters:**
The map questions are hypothesis-driven, resume-anchored, and critic-validated. Seed questions are general-purpose smart improvisation. When the map is bypassed, the interview quality drops significantly. The map is the product's core differentiator. Not using it at runtime is the central quality failure.

**Likely causes:**
1. `focus_key` empty (C-2) means `select_from_trajectory_map()` can't navigate the map properly
2. `prepped_next_packet` from the background pipeline isn't reliably staging map-sourced questions
3. The priority chain falls through to `sprint_seed` more often than designed because earlier priorities don't match

**Fix direction:**
- Fix C-2 first — most of this likely resolves once focus_key propagates correctly
- Add explicit route_kind logging in the background pipeline to identify exactly where the fallthrough happens
- If `prepped_next_packet` is empty more than expected, the background pipeline may be timing out or crashing silently — add error logging with the route_kind that would have been served

---

---

# HIGH PRIORITY ISSUES

---

## H-1: Experience Tier Miscalibrated Across All Sessions

**What's broken:**
- AppsForBharat candidate (Golang at 10M users, AWS ECS, TDD, Grafana): tagged `experience_tier: "junior"`
- Praveen (1 month SDE-1, side projects): tagged `experience_tier: "mid"`

Both wrong. `experience_tier` feeds into persona question framing, expected ownership depth, and what the critic considers "appropriate" boundary probes.

**Compounding factor:**
The broken `parsed_resume` (C-1) means experience counters `ml: 0, swe: 0, data_eng: 0` for active engineers. The `years_experience` field from the frontend (`"0-1"`, `"1-2"`) is the only surviving signal and it's not being used as primary tier signal.

**Fix direction:**
- Derive `experience_tier` from `years_experience` input as primary signal, not from broken parsed_resume counters
- `years_experience: "0-1"` → junior (feature-level decisions, specific implementation choices)
- `years_experience: "1-3"` → mid (service-level design, tradeoff awareness)
- `years_experience: "3+"` → senior (system-level architecture, cross-team impact)
- Add tier calibration to the trajectory map critic — flag if boundary probes are pitched at the wrong depth for stated experience level

---

## H-2: "Ownership" Language Over-Applied Across All Tiers

**What's broken:**
The trajectory map and follow-up agent use "owned", "architected", "you personally designed" framing for all candidates regardless of experience tier. A 1-year engineer being asked "what did you personally architect?" is being set up to fail — not because they lack knowledge but because they haven't had the opportunity to architect anything.

**The real distinction:**
Ownership exists at every tier but means different things. A junior's ownership is: "I wrote this function, I debugged this error, I made this call within my scope." Asking them about architectural ownership produces false claims or confused answers — neither reveals real signal.

**Fix direction:**
- Add experience-tier-aware prompt overlays to the track generation system prompt
- For junior/mid: replace "what did you own/architect" with "what specific decision within your scope did you make and have to explain or defend to someone?"
- The critic should penalize ownership-depth mismatches with experience tier the same way it penalizes generic questions

---

## H-3: No Conversational Pressure Gauge — Cumulative Epistemic Aggression

**What's broken:**
The system tracks candidate disengagement (skip, deflection) but nothing tracks the interviewer's cumulative pressure output. The pattern `challenge → verify → probe → boundary → corner` repeats without any signal that the conversational atmosphere has become adversarial beyond productive.

**Observed:**
Mahesh Turn 7: even when he gave a correct conceptual answer (identifying human bottleneck in approval flow), the system moved immediately to another probe with no acknowledgment. Praveen's session: 14 consecutive weaknesses detected, zero moments of "that's a useful framing, let's go deeper on that."

**Why this matters:**
Unrelenting pressure past the point of useful signal produces defensive responses that look worse than the candidate's actual capability. The system may be underselling real knowledge by maintaining adversarial posture too long.

**Fix direction:**
- Add `pressure_level` counter to session state: increments on `challenge/discrepancy/boundary` routes, decrements on `surface/opener/seed` routes
- When `pressure_level >= threshold`, force next question to be a `surface` or `candidate_q4_options` type — a genuine curiosity question
- Add a "acknowledge a correct answer" path: when WeaknessAgent returns `severity: low` AND discrepancy is `none`, the next question should open rather than probe

---

## H-4: No "Follow the Interesting Signal" Branch

**What's broken:**
The fast path has nine priority levels, all variations on "probe a weakness" or "serve pre-planned question." There is no branch for: "the candidate said something specific and interesting — follow that thread deeper."

Human interviewers extract the most signal by pulling on unexpected specificity. When a candidate mentions a non-obvious implementation detail or concrete metric, a skilled interviewer says "wait, tell me more about that" rather than moving to the next planned probe. This is what separates interviews that feel like conversations from ones that feel like tests.

**Fix direction:**
- New routing condition: when `weakness.severity == "low"` AND `reasoning_behavior.structure_score >= 2` AND the answer contains specific technical tokens (tool names, metrics, concrete design decisions), trigger "explore strength" branch
- This branch calls `FollowUpAgent.generate()` with a new `probe_direction: "explore_strength"` that asks for more depth on what the candidate just said — not a challenge, a genuine "tell me more"
- Add `"explore_strength"` to `PROBE_DIRECTION_INSTRUCTIONS` in `followup_agent.py`

---

## H-5: Sprint 1 Running Short — Fence-Post in Sprint Advance Logic

**What's broken:**
In Praveen's session, Sprint 1 ended after 4 candidate answers, not 5. `QUESTIONS_PER_SPRINT = 5` but the sprint advanced prematurely.

**Likely cause:**
`sprint_question_count` may start at 1 (counting the fixed intro question Q0) or the advance check fires after incrementing rather than before. If Q0 counts as a sprint question, Sprint 1 effectively gets 4 candidate answers instead of 5.

**Fix direction:**
- Clarify whether Q0 (the fixed intro question) counts toward `sprint_question_count` — it probably shouldn't, since the candidate's intro answer is pre-structured and doesn't consume a real sprint question
- If it does count, change the advance check to `sprint_question_count > QUESTIONS_PER_SPRINT` rather than `>= QUESTIONS_PER_SPRINT`
- Add a log at sprint advance to confirm the actual count at the moment of transition

---

---

# MEDIUM PRIORITY ISSUES

---

## M-1: STT Noise Passed Raw to All Agents

**What's broken:**
Deepgram STT output is passed directly to WeaknessAgent, DiscrepancyAgent, FollowUpAgent, and EvaluationAgent without any normalization.

**Observed in sessions:**
- "item button" = "idempotent"
- "replay limiting" = "rate limiting"
- "backup strategy" = "backoff strategy"
- "item dependency key" = "idempotency key"
- "radius operations" = "Redis operations"

The LLMs handle this partially by inferring meaning from context, but it introduces evaluation noise. A candidate who knows "idempotency" but pronounces it unclearly gets their answer analyzed with "item button" in the text.

**Fix direction:**
- Add a lightweight normalization pass on the final transcript before agent dispatch: a small Haiku call or a phonetic/regex lookup for common technical term misrecognitions in the target domain
- As a cheaper interim: add to all agent system prompts an explicit instruction — "the transcript may contain STT artifacts from speech-to-text conversion; interpret technical-sounding mispronunciations charitably and infer the intended technical term from context"

---

## M-2: Non-Engagement Detection Too Slow

**What's broken:**
Mahesh answered "hello" to a technical question on Turn 2. The system correctly flagged it (`deflection, severity: high`) but continued the interview for 13 more turns. The disengagement increment for `social_deflection` is +1.0, requiring 3 explicit non-answers to trigger the level-3 forced exit.

A single one-word answer to a specific technical question is already a strong non-engagement signal.

**Fix direction:**
- Increase `zero_content` weight from +0.5 to +1.5 for a one-word non-answer to a technical question
- Add `non_engagement_consecutive` counter: if the last 2 turns have answers under 10 words, change posture — pivot to a simpler diagnostic question or explicitly reframe ("Let me try a different angle...")
- After 2 consecutive near-empty technical answers, do not escalate complexity — simplify or check for technical issues (audio, comprehension)

---

## M-3: Parsed Claims Are Line-Break Truncated

**What's broken:**
Resume bullet points wrapping across lines are stored as truncated claims. Example: `"Built and scaled Golang microservices for Puja, Chadhava, Astrology, Wallet, and Temple domains, serving"` — cut mid-sentence at the PDF line break.

These truncated claims are passed to DiscrepancyAgent as ground truth. A truncated claim is harder to verify correctly — the agent may miss the falsifiable part (`"10M+ global users"`) that the full claim would expose.

**Fix direction:**
- Pre-process raw resume to join continuation lines — lines that don't start with bullet markers, section headers, or capitalized new sentences should be joined to the previous line
- Validate claims array after parsing: any claim under 15 words that ends without a period or specific technical term is likely truncated and should be flagged for re-extraction

---

## M-4: Coverage Gap Not Explained in Final Report

**What's broken:**
Mahesh's report lists 5 major untested dimensions with no explanation of why they weren't tested. A recruiter reading this just sees a list of gaps with no context.

The real reason (routing stuck on one topic) is not communicated. The recruiter can't make an informed decision about whether to schedule a follow-up screen or act on this verdict.

**Fix direction:**
- Add `coverage_gap_reason` to the final evaluation: if `untested_dimensions` is non-empty AND tested dimensions all belong to one focus area, add a natural language note: "Interview coverage was concentrated on [focus_area] because [repeated confirmation failures / candidate non-engagement]. Recommend a follow-up screen specifically covering [untested areas] before making a final decision."
- This requires no routing fix — just report generation improvement

---

## M-5: `current_answer_response` Field Contains Question Text, Not Answer Text

**What's broken:**
In Mahesh's session, `current_answer_response` at session end contains an AI question text, not a candidate response. Field naming is confusing and the assignment appears incorrect somewhere in the turn lifecycle.

**Fix direction:**
- Rename for clarity: `current_answer_response` → `current_staged_response` or `current_ai_next_question`
- Audit the field assignment in the orchestrator to confirm it holds the question being staged for the candidate, not the candidate's prior answer

---

## M-6: Speculative Generation Doesn't Know Session Is Ending

**What's broken:**
In Mahesh's session, the final `active_question_packet` is `route_kind: "speculative_fast"` — speculative staged a Redis caching question during the closing turn. Good question, but the session ended. Wasted LLM call and misleading session state.

**Fix direction:**
- Add `if question_count >= 13: skip speculative generation` — closing phase is imminent, speculative is irrelevant
- Or: clear `speculative_cache` when Phase 6 close activates

---

---

# DESIGN ISSUES

---

## D-1: The Orchestrator Is Not Actually Acting as the Interviewer

**What this means:**
The architecture principle — "LLM as renderer, system as orchestrator" — is the right philosophy but isn't executing. The routing bugs (C-2, C-3, C-4) mean the orchestrator can't direct the interview. Each turn falls through to whatever the LLM improvises. The system has the right design intention but the routing layer can't fulfill it.

The LLM ends up making interview strategy decisions (what to probe, when to move on, whether to acknowledge or challenge) that the orchestrator should be making. This is backwards from the intended architecture.

**What needs to change:**
Fix the routing bugs first (C-1 through C-4). Until focus_key propagates, the bridge fires, and the map is used, "LLM as renderer" is aspirational. The LLM being a capable improviser is masking the routing failures — it shouldn't have to be.

---

## D-2: Adversarial-First Philosophy Baked Into Map Critic

**What this means:**
The trajectory map critic rewards "boundary probes requiring real ownership" and "hypothesis-style openers that force immediate analytical position." Both correct for senior engineers and strong claim verification. But the critic has no component scoring for curiosity, narrative invitation, or psychological accessibility.

Every map, for every candidate, opens with a challenge. The first question sets the psychological contract for the whole interview. Starting adversarial means the candidate defends from Q1 rather than showing what they know.

**Fix direction:**
- Add `curiosity_score` alongside existing `opener_quality_score` and `dimension_depth_score` in the critic
- The Sprint 1 opener should score high for both narrative invitation (activates storytelling, memory reconstruction) AND implementation specificity — not just for forcing immediate analytical position
- Adversarial posture should be earned through the conversation as the candidate demonstrates what they know, not applied from the first turn

---

## D-3: No Narrative Invitation Mode in Question Generation

**What this means:**
All FollowUpAgent questions are implementation probes, scenario probes, or boundary challenges. There is no "narrative mode" — questions designed to activate storytelling and open memory.

Narrative questions ("At what point did that project stop feeling like background work and start mattering?") extract different signal than implementation probes ("What was your retry strategy?"). They reveal context, ownership indicators, timeline awareness, and judgment under uncertainty. They also create psychological breathing room that makes the adversarial questions feel proportionate rather than relentless.

**Fix direction:**
- Add `probe_direction: "narrative_anchor"` to `PROBE_DIRECTION_INSTRUCTIONS` in `followup_agent.py`
- Narrative anchor questions should be time-anchored, emotionally accessible, and avoid specific technical recall demands
- The orchestrator should insert narrative anchor questions after 3-4 consecutive implementation probes as a pressure release — this requires the `pressure_level` counter from H-3

---

## D-4: Questions Not Anchored to What Was Actually Said

**What this means:**
Trajectory map questions (surface/mechanism/boundary) are generated before the interview. They're good templates but can't incorporate what the candidate actually said. `adapt_followup()` does surface-level tone modification — it doesn't rebuild the question from the candidate's specific answer.

If a candidate in Turn 3 mentions they used BullMQ specifically, Turn 4's question should reference BullMQ. Instead it says "your queue system" — a generic template.

**Fix direction:**
- The background pipeline's FollowUpAgent call should always receive the candidate's specific answer from the current turn and be explicitly instructed to anchor the next question to specific terms, tools, or systems named by the candidate
- This is already partially the intent of `adapt_followup()` — it should be the default behavior of all `generate()` calls, not an optional adaptation step
- Add to the FollowUpAgent system prompt: "Reference specific tools, systems, or numbers the candidate named in their answer. Never ask about 'your queue system' if the candidate named BullMQ."

---

## D-5: Weakness Ledger Grows Without Triggering Strategic Decisions

**What this means:**
The `weaknesses` array accumulates every detected weakness across the full interview but nothing looks at the accumulated pattern to make interview-level strategic decisions.

Useful patterns being ignored:
- "4 weaknesses all about the same `inferred_focus_key` — we have enough signal here, move on"
- "Two `type: incorrect` entries — this isn't shallow knowledge, this is a wrong mental model — flag differently"
- "All weaknesses are `severity: medium` — consistent shallowness across the board vs. deep gap in one area — adjust evaluation framing"

**Fix direction:**
- After `_apply_staged_analysis()`, scan the last N weaknesses and compute the pattern
- "Same focus_key repeated 3+ times" → set a `focus_exhausted` flag → trigger bridge
- "type: incorrect appears twice" → set `mental_model_gap` flag → affects final evaluation framing
- "All severity: low" → set `confidence_above_knowledge` flag → adjust next question type

---

## D-6: Sprint Transitions Count-Only, Not Signal-Based

**What this means:**
Sprint advancement happens at `sprint_question_count >= 5` regardless of whether the sprint's focus areas are actually covered or whether the candidate is in the middle of revealing something important. All candidates get exactly the same number of questions per sprint regardless of how the conversation is going.

**Fix direction:**
This is complex to get right — tackle after Phase 1 and 2 fixes are stable. The pragmatic interim:
- Allow early sprint advance at question 4 if `consecutive_high_weakness_count >= 3` (candidate is stuck)
- Delay sprint advance until question 7 if the last 2 answers had `severity: low` and `structure_score >= 2` (candidate is actively showing depth)
- Never delay past question 7 — hard cap to prevent Sprint 1 consuming the whole interview

---

---

# Priority Summary

## Cannot ship to production:
**C-1, C-2, C-3, C-4** — these four bugs mean the architecture is not actually running as designed in any session.

## Should fix before any public users:
**H-1, H-2, H-3, H-4, H-5** — these degrade quality systematically across all sessions and will generate user complaints immediately.

## Fix before scale (>100 sessions):
**M-1 through M-6** — these are quality issues that become more visible and more damaging at scale.

## Redesign track (parallel to engineering work):
**D-1 through D-6** — these require philosophical and architectural rethinking that shouldn't block the engineering fixes but should be designed in parallel so the Phase 1/2 fixes don't entrench the wrong design.

---

## Recommended Fix Sequence

**Phase 1 — Unblock the architecture:**
1. Resume parser overhaul (C-1)
2. Focus key propagation from active_question_packet (C-2)
3. Instrument and fix consecutive_high_weakness_count (C-3)
4. Add route_kind logging to trace sprint_seed fallthrough (C-4)

**Phase 2 — Systematic quality:**
5. Experience tier from years_experience input (H-1)
6. Tier-aware ownership depth in track generation (H-2)
7. Pressure gauge + forced curiosity branch (H-3)
8. "Follow interesting signal" routing branch (H-4)
9. Sprint count fence-post fix (H-5)
10. STT normalization pass (M-1)
11. Non-engagement detection recalibration (M-2)
12. Coverage gap explanation in report (M-4)

**Phase 3 — Redesign:**
13. Narrative invitation mode in FollowUpAgent (D-3)
14. Adversarial-first recalibration in map critic (D-2)
15. Weakness ledger → strategic routing decisions (D-5)
16. Question anchoring to actual candidate answers (D-4)
17. Signal-based sprint transitions (D-6)

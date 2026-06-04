# Codex Session Handoff — 2026-04-14

This document is the fastest way to resume work in a new Codex session without losing the real context of the current system state.

It does **not** replace the required onboarding in [AGENTS.md](/Users/yash/antigravity/AGENTS.md), [COLLAB.md](/Users/yash/antigravity/COLLAB.md), [README.md](/Users/yash/antigravity/README.md), and the core backend/frontend files. It is a focused operational handoff.

## 1. Product State Right Now

Antigravity is no longer a raw prototype. The interview loop is real, the route mix is better, and the system can expose obvious bluffing. But the current pain is not mainly question quality anymore.

The current pain is:
- Turn 1 steering can still go wrong
- transcript assembly is still too fragmentary
- TTS is now working again, but latency is too high
- one contradiction family can still monopolize the interview
- background prep is still slower than we want

In short:
- question quality: improved
- route quality: improved
- verdict quality on obvious bad candidates: acceptable
- transcript quality: still weak
- user-perceived speed: still weak

## 2. Current Architecture Reality

### Backend
- Brain: [orchestrator.py](/Users/yash/antigravity/backend/services/orchestrator.py)
- TTS service: [tts_service.py](/Users/yash/antigravity/backend/services/tts_service.py)
- LLM routing: [llm_router.py](/Users/yash/antigravity/backend/models/llm_router.py)
- Main route surface: [routes.py](/Users/yash/antigravity/backend/api/routes.py)

### Frontend
- Interview page: [page.tsx](/Users/yash/antigravity/app/interview/[session_id]/page.tsx)
- Audio utilities: [audio.ts](/Users/yash/antigravity/lib/audio.ts)

### Important behavior changes already made
- split-answer path was hardened with answer-draft merging
- filler-first was removed from the main answer playback path because it was making latency feel worse
- Cartesia TTS support was added and is now working
- follow-up routing now includes:
  - `clarification_fast`
  - `attack_probe`
  - `discrepancy_challenge`
  - `bank_followup_fast`
  - `sprint_seed`

## 3. TTS State

### What was wrong before
Earlier runs were not reliably using backend audio. Logs showed repeated ElevenLabs `502` failures and browser speech synthesis fallback.

### What is true now
Cartesia support was implemented in [tts_service.py](/Users/yash/antigravity/backend/services/tts_service.py), and the current backend `/api/tts` path is returning real audio successfully.

Important facts:
- provider now prefers Cartesia when configured
- valid Cartesia voice currently used:
  - `9626c31c-bec5-4cca-baa8-f8ba9e84c8bc`
- earlier user-provided `CARTESIA_VOICE_ID=21m00Tcm4TlvDq8ikWAM` was invalid for Cartesia because Cartesia expects a UUID

### Current TTS problem
TTS is no longer “broken,” but it is too slow.

In the latest clean run, TTS prefetch was often the largest visible delay:
- about `2.5s` to `5.5s` just for `tts_prefetch`

So the next TTS work is latency reduction, not provider resurrection.

## 4. Most Important Recent Session Analysis

### Session analyzed deeply
- `5fd83c3f-5d42-4b22-b9ce-a0969d344a35`

### Why this session matters
This was a much cleaner artifact than the earlier broken runs, so it is a good reference session for current system behavior.

### What happened
- 8 answered turns
- interview stopped in Sprint 2
- dummy candidate was correctly exposed
- final verdict was directionally fair for that run

### What this session proved
1. The system can correctly fail an obviously weak/dummy candidate.
2. Follow-up route variety is better now.
3. TTS backend audio is working in the current provider path.

### What this session exposed
1. **Turn 1 seed misrouting**
   - The candidate’s first fragment pointed at Wondershare/video editing.
   - Turn 2 still jumped to TinyML.
   - This means Turn 1 seed logic can still override live first-answer semantics.

2. **Breadth is still too weak**
   - The system tunneled into TinyML/audio/quantization.
   - Wondershare/AIGC was mostly left untested.

3. **Transcript quality is still too fragmentary**
   - Answers are still clipped fragments too often.

4. **Background prep is still too slow**
   - Example backend staging times from that run:
     - `clarification_fast` staged in ~12.7s
     - `attack_probe` staged in ~28.0s
     - `discrepancy_challenge` staged in ~18.1s
     - `bank_followup_fast` staged in ~11.0s

5. **Duplicate same-turn background work still exists**
   - Turn 1 staging fired twice in the live trace

## 5. Latency Findings

These are from the current frontend log and live backend trace for the cleaner latest run.

### Route-level frontend readiness times
- `prepped_next_question`: ~3949ms, ~4086ms
- `clarification_fast`: ~4202ms, ~3722ms
- `attack_probe`: ~4728ms
- `discrepancy_challenge`: ~10659ms, ~7118ms, ~6132ms
- `bank_followup_fast`: ~4530ms

### Interpretation
- normal turns are still usually around `3.7s` to `4.7s`
- heavier contradiction turns are still around `6s` to `10s`
- backend fast-track serving itself is often okay
- TTS prefetch is the main visible bottleneck now

## 6. Follow-Up Quality Read

The questions are better than before.

The route progression in the clean latest run was:
- `prepped_next_question`
- `prepped_next_question`
- `clarification_fast`
- `attack_probe`
- `clarification_fast`
- `discrepancy_challenge`
- `discrepancy_challenge`
- `bank_followup_fast`

That is healthier than the earlier “attack one thing forever” behavior.

But there are still two real issues:
- Turn 1 seed can steer to the wrong project family
- once the system finds a contradiction family, it still stays there too long

## 7. Transcript / STT Read

The worst split-answer regression was repaired, but STT/turn assembly is still not strong enough.

Current reality:
- answers still come through as clipped fragments too often
- the frontend turn assembler still needs another tightening pass
- this is especially important before using any report as strong evidence in a real candidate run

Do **not** assume transcript quality is fully repaired.

## 8. Most Important Open Priorities

This is the current recommended order of work.

### P0. Fix Turn 1 seed handoff
Primary file:
- [orchestrator.py](/Users/yash/antigravity/backend/services/orchestrator.py)

Goal:
- seeded Turn 1 follow-up should not override clear semantics from the candidate’s first real answer

Desired behavior:
- treat `_seed_first_question()` as a fallback
- after the first committed answer, if live answer semantics point to a different claim family, invalidate or downgrade the seeded question
- Turn 2 should choose between:
  - seeded question
  - answer-aligned clarification
  using a relevance check

### P1. Tighten transcript assembly again
Primary file:
- [page.tsx](/Users/yash/antigravity/app/interview/[session_id]/page.tsx)

Goal:
- fewer clipped fragments
- cleaner single-answer sealing
- less garbage entering backend reasoning

### P2. Reduce TTS latency
Primary files:
- [page.tsx](/Users/yash/antigravity/app/interview/[session_id]/page.tsx)
- [audio.ts](/Users/yash/antigravity/lib/audio.ts)
- [tts_service.py](/Users/yash/antigravity/backend/services/tts_service.py)

Goal:
- bring normal follow-ups closer to ~2s user-visible latency instead of ~4-5s

Things to inspect:
- provider-side response time
- full-prefetch vs earlier playback
- question-length trimming without harming quality
- connection warming / provider warmup

### P3. Strengthen post-contradiction breadth guard
Primary file:
- [orchestrator.py](/Users/yash/antigravity/backend/services/orchestrator.py)

Goal:
- after one or two strong contradictions, move to another flagship claim family sooner

### P4. Eliminate duplicate same-turn background staging
Primary file:
- [orchestrator.py](/Users/yash/antigravity/backend/services/orchestrator.py)

Goal:
- one background pipeline result per committed answer turn

## 9. Claude / Team Discussion State

The latest useful shared alignment is:
- proportional probing is still the intended direction
- we are not trying to weaken the product
- the current system should stay adversarial, but smarter about:
  - clarification
  - confrontation
  - contradiction escalation
- follow-up quality has improved enough that the next work should focus more on:
  - speed
  - steering
  - transcript integrity

A fresh Codex session should read the latest section of [COLLAB.md](/Users/yash/antigravity/COLLAB.md) after this file.

## 10. Runtime Notes

At the time of writing:
- local backend was serving on `127.0.0.1:8000`
- local frontend logs of interest were in:
  - [next-development.log](/Users/yash/antigravity/.next/dev/logs/next-development.log)

If the next session needs to analyze a run:
- use `/api/state/<session_id>`
- use `/api/report/<session_id>`
- cross-check against `next-development.log`
- do not trust old ElevenLabs fallback logs to judge the current Cartesia-backed state unless the timestamps line up with the latest run

## 11. Recommended Resume Procedure For Next Codex Session

1. Read:
   - [AGENTS.md](/Users/yash/antigravity/AGENTS.md)
   - [COLLAB.md](/Users/yash/antigravity/COLLAB.md)
   - this handoff file
2. Re-open:
   - [orchestrator.py](/Users/yash/antigravity/backend/services/orchestrator.py)
   - [page.tsx](/Users/yash/antigravity/app/interview/[session_id]/page.tsx)
   - [audio.ts](/Users/yash/antigravity/lib/audio.ts)
   - [tts_service.py](/Users/yash/antigravity/backend/services/tts_service.py)
3. Start with:
   - Turn 1 seed invalidation/relevance logic
4. Then:
   - TTS latency reduction
5. Only after that:
   - transcript tightening
   - breadth guard refinement
   - duplicate background staging cleanup

## 12. One-Line State Summary

Antigravity is asking better questions now, but the next wins are no longer in prompt quality alone; they are in first-turn steering, transcript integrity, and faster audio handoff.

Best next-session bootstrap is:

read AGENTS.md
read COLLAB.md
read CODEX_SESSION_HANDOFF_2026-04-14.md
No runtime code changed in this step beyond creating the handoff document.
# Antigravity Interview Redesign — Master Plan

> Built from session analysis (e5170a7a, 98c80520) + design discussion
> Date: 2026-05-06
> Status: Planning — pre-implementation

---

## Table of Contents

1. [What the Sessions Actually Proved](#1-what-the-sessions-actually-proved)
2. [The Core Philosophy Shift](#2-the-core-philosophy-shift)
3. [New Interview Architecture — Turn by Turn](#3-new-interview-architecture--turn-by-turn)
4. [New System Component: Candidate State Tracker](#4-new-system-component-candidate-state-tracker)
5. [New System Component: Answer Coverage Map](#5-new-system-component-answer-coverage-map)
6. [New System Component: Application Transfer Generator](#6-new-system-component-application-transfer-generator)
7. [New System Component: Coverage-Guided Follow-up](#7-new-system-component-coverage-guided-follow-up)
8. [Evaluation Redesign — Coverage Portrait](#8-evaluation-redesign--coverage-portrait)
9. [Implementation Plan — Prioritized](#9-implementation-plan--prioritized)
10. [Trade-off Table](#10-trade-off-table)
11. [What the Current System Keeps](#11-what-the-current-system-keeps)
12. [Interview Map Generation — Diagnosed Failures](#12-interview-map-generation--diagnosed-failures)
12. [Live Map Audit — What the Current Map Generation Actually Does Wrong](#12-live-map-audit--what-the-current-map-generation-actually-does-wrong)

---

## 1. What the Sessions Actually Proved

### Session e5170a7a (AI Intern — Veo-3 / CUHK-Shenzhen)

**Hard evidence of system failures, not candidate failures:**

| Turn | What Candidate Said | What System Did | Problem |
|------|---------------------|-----------------|---------|
| Q1 | First response, nervous repetition | `attack_probe` route, mechanism question | Opening promise ("ease in") violated immediately |
| Q4 | "could you skip to the next question please" | Asked another Veo-3 question | Explicit pivot request ignored |
| Q5 | "i want you to skip to another topic" | Asked another Veo-3 question | Second explicit pivot request ignored |
| Q7 | "you have been holding on to that for the longest time" | Asked another Veo-3 question | Candidate explicitly complained — ignored |
| Q12 | "yeah yeah no no i'm good i'm good don't worry don't worry" | Asked another question | Candidate in social-survival mode, not interview mode |
| Q13 | "i'm good without answering this one thank you" | Asked another question | Polite refusal — ignored |
| Q14 | "yeah no no no i'm good i'm good with the thank you i'm good yeah" | Asked another question | Final withdrawal — ignored |
| Q15 | "on what exactly" | Interview ends | 13 of 15 questions were about Veo-3 |

**Verdict issued:** NO HIRE, confidence 0.5 — with 13 untested dimensions.
**Actual verdict that was warranted:** INSUFFICIENT_DATA — candidate disengaged, coverage too narrow.

---

### Session 98c80520 (Analyst — S Apparao)

**Evidence of two separate problems conflated:**

| Turn | What Candidate Said | Actual Problem |
|------|---------------------|----------------|
| Q1 | "while while while... for for that" | ESL communication under pressure, not technical failure |
| Q5 | "nothing" | Complete communicative shutdown — system kept going |
| Q6 | "sort will sort all the video frames" | Genuine technical misconception — correct signal |
| Q9 | "data logs is the log which will trigger when the data is logs" | Circular definition — confirmed discrepancy. Valid. |
| Q13 | "so road and the conclusion is a conclusion we i i'll conclude it because of conclusion" | Full cognitive/linguistic collapse under pressure |

**What's valid:** The system correctly identified that SORT was fundamentally misunderstood, and that "data logs" definition was circular (DiscrepancyAgent: confirmed conflict). These were real signals.
**What's wrong:** The system treated Q1 ESL patterns identically to Q6 incorrect answers. It had no mode for "this candidate is struggling to communicate" vs "this candidate doesn't know the answer."

---

### Root Causes (Structural)

**1. Anti-tunneling is topic-count-based, not language-based.**
It tracks `weakness_type` counts but has no semantic parser for candidate meta-language ("skip", "move on", "different topic"). These utterances are analyzed as technical answers and scored as deflections.

**2. No Candidate State layer exists.**
The system tracks `candidate_model` (what they know) but not `candidate_state` (their current engagement level, communication mode, distress signals). An interviewer without a face can't read the room — but it can read the language.

**3. Topic exhaustion has no ratio check.**
Anti-tunneling fires when the same *weakness type* is overprobed. It doesn't fire when the same *focus_key* dominates 80% of questions. These are different things. You can ask 13 different questions about Veo-3 without triggering anti-tunneling if each question targets a different weakness dimension.

**4. The opening preamble is decoupled from the route.**
"Let's ease in with something you know really well" is a universal prefix, hardcoded. But Q1's route can be `attack_probe`. The warmth signal and the adversarial probe are contradictory — and the candidate registers the contradiction instantly.

**5. Evaluation has no INSUFFICIENT_DATA tier.**
Low confidence + narrow coverage still produces a hire recommendation. These should gate each other: below coverage threshold → verdict is INSUFFICIENT_DATA, not a low-confidence NO_HIRE.

**6. Two failure modes (claim inflation vs. communication collapse) are scored identically.**
The evaluation treats deflection-as-avoidance and deflection-as-communication-failure the same way. They warrant different follow-up modes and different verdict language.

---

## 2. The Core Philosophy Shift

### Current System: Lie Detector

```
Resume → Hypothesis Graph → Evidence Extraction Engine
Goal: Catch contradictions. Verify claims. Surface fraud.
Mechanism: Attack the claim directly. Probe where they'll slip.
```

**What it produces:** A test of whether the candidate accurately remembers what they did.
**What it misses:** Whether they understand it well enough to use it.

### New System: Capability Demonstrator

```
Resume → Domain Context → Application Transfer Test
Goal: Test whether claimed knowledge is real and usable.
Mechanism: Understand what they built, then give them a new problem in the same domain.
```

**What it produces:** Evidence of whether the candidate can think with the knowledge they claim.
**Why it's harder to fake:** You can memorize your own project. You cannot memorize the extension of your project to a scenario you've never seen, anchored to the specific implementation details you just described.

### The Key Insight

> Claim verification answers: "Did they really do this?"
> Application transfer answers: "Can they actually think in this domain?"

The second question is what you're hiring for. The first is a proxy, and a weak one. Someone who genuinely built a system and internalized the knowledge will be able to extend it. Someone who inflated their resume will be exposed precisely because the extension question is anchored to what *they said*, not to what the internet says.

### What Stays the Same Philosophically

- Resume is still a hypothesis graph — claims are taken as starting points, not facts
- Evidence extraction still happens — but the evidence is *capability demonstration*, not *claim recall*
- Weaknesses are still tracked — but as *coverage gaps*, not *deficits against perfection*
- Discrepancy detection stays — but as a background signal, not the interview driver

---

## 3. New Interview Architecture — Turn by Turn

```
Phase 1: Warm Open      [Turns 1-2]    Genuine ease-in, self-intro, recent experience narration
Phase 2: Deep Narration [Turns 3-4]    Unpack the most recent experience — what they built, how they built it
Phase 3: Application    [Turn 5]       Application transfer — new scenario, same domain, situational framing
Phase 4: Coverage surf  [Turns 6-10]   Coverage-guided follow-ups, one per gap, exploratory not adversarial
Phase 5: Second anchor  [Turns 11-13]  Brief pass on second-most-recent experience they surfaced naturally
Phase 6: Close          [Turns 14-15]  Human, low-stakes close — leave them feeling respected
```

> **Resume coverage principle:** The interview does not attempt to cover the whole resume. It covers the top two most recent experiences the candidate naturally surfaces — first in their self-intro (Turn 1), second in whatever they organically bring up during the session. If something else on their resume is truly important to them, they will find a way to mention it. Chasing the whole resume produces shallow 1-question-per-section coverage that tests nothing deeply.

---

### Phase 1: Warm Open (Turns 1-2)

**Purpose:** Genuinely ease the candidate's nerves. Get them talking comfortably before any probing begins. Collect speech pattern data (fluency, ESL markers, communication style). Let them surface which experience they feel most confident about.

**The principle here:** Most candidates are nervous. If you start technical immediately, the nerves contaminate the signal — you're measuring anxiety, not knowledge. Two low-stakes turns cost nothing and meaningfully improve the quality of everything that follows.

**Turn 1 (always — fixed, warm, human):**
> "Hey, thanks so much for coming in — really glad to have you here. Let's start easy. Just give me a quick intro about yourself — who you are, what you've been up to lately, whatever feels natural."

Why this phrasing:
- "Thanks so much for coming in" — genuine acknowledgment, not performative
- "Let's start easy" — sets the actual tone, doesn't lie about it
- "Whatever feels natural" — removes the anxiety of a structured performance; they can say anything
- No mention of the resume yet — this is about the person, not the document

**Turn 2 (adaptive, based on what they mentioned in Turn 1):**
> "Great, that's really helpful context. So tell me more about [most recent / most prominent thing they mentioned] — like, what were you actually doing there? What did you build, what tech were you working with, feel free to just walk me through it."

Why this phrasing:
- "That's really helpful context" — validates what they said without being hollow
- "What were you actually doing there" — invites the real story, not the resume bullet
- "What did you build, what tech" — two concrete anchors, easy to grab onto
- "Feel free to just walk me through it" — permission to narrate freely, no right format

**System role during Phase 1:**
- Begin building `candidate_state` — detect ESL patterns, disengagement risk, communication style
- Set `communication_mode` based on speech patterns detected across both turns
- Identify which experience and which specific detail they described most — this becomes the anchor for Phase 3
- Do NOT probe for weaknesses yet — these two turns are observation only

**What this solves:**
The "ease in" promise is genuinely kept. Two turns of actual warmth before examination mode. By the end of Turn 2, the candidate has described their work in their own words, the system has real speech data, and there is a specific implementation detail to anchor Phase 3 to.

---

### Phase 2: Depth Probe (Turns 3-4)

**Purpose:** Dual purpose — and both must be served. First: extract the specific implementation detail (`implementation_anchor`) to build the application transfer question from. Second, and equally important: *actually test* whether the candidate knows what they claim at a level beyond resume phrasing. This is where you find out if they genuinely did the work.

**The core principle of this phase:**
Warmth is in the *framing*. Depth is in the *specificity demand*. These are independent axes. A question can be conversational in tone and still demand specific, mechanistic answers. "That's interesting — what did you actually write to make that work?" is warm AND probing. Phase 2 needs to operate at this intersection — the candidate should feel heard and respected, but the questions should be specific enough that a person who inflated their resume cannot answer them comfortably.

**The probing ladder — surface → mechanism → boundary:**

This is the same three-level structure the interview map already uses internally. Phase 2 applies it conversationally across Turns 3 and 4:

- **Surface** (Turn 3): Understand what they built and what their role was
- **Mechanism** (Turn 4a): Understand *how* the key part actually worked — what they specifically wrote or figured out
- **Boundary** (Turn 4b): Probe where the implementation has edges — what it doesn't handle, what surprised them, where it broke

A candidate who truly did the work can walk all three levels. A candidate who was peripheral or inflated will drop off at mechanism or boundary — they can describe what it does but not how it works, or they've never thought about where it breaks.

---

**Turn 3 — Surface + Ownership:**
> "Okay, so [specific thing they described in Turn 2] — walk me through how that actually worked. What were the main components, and what specifically was your part of it?"

The embedded ownership signal is "what specifically was your part" — it's not accusatory, it's natural, but it forces the candidate to distinguish what they personally did from what the team or system did. This matters because vague answers here ("we built a pipeline that...") vs specific answers ("I wrote the ingestion layer that pulled from...") are themselves signal.

**Turn 4a — Mechanism (the critical depth probe):**

This is the most important question in the interview. Its purpose is to test whether the candidate knows what they claim at implementation level — not just what it does, but how it works.

The question pattern: **force them to describe what they personally wrote, configured, or figured out at a level of specificity that cannot be faked.**

> "In [the most specific component they named in Turn 3] — what did you actually have to write or figure out to make that work? Walk me through it."

**The signal gradient — what to listen for:**

| Answer Type | What It Sounds Like | What It Means |
|-------------|---------------------|---------------|
| **Mechanism-deep** | Names a specific function, class, config, algorithm, or design choice. Uses first-person ("I wrote", "I had to figure out"). Has a number or constraint attached. | They did it. The `implementation_anchor` is here. |
| **System-language** | Describes what the system does, not what they built. Passive voice. "The model was trained on...", "The pipeline would then..." | They were adjacent. Ownership is questionable. |
| **Vocabulary-only** | Uses correct terminology but can't describe any specific artifact or decision. "We leveraged collaborative filtering with SVD." | They read about it. Surface familiarity, not implementation experience. |
| **Generic** | "We handled it appropriately" / "we made sure it was efficient" / "the standard approach" | No real knowledge here. Strong inflation signal. |

The key heuristic: **a real practitioner answers in nouns and verbs — specific things they made.** A peripheral contributor answers in adjectives and process language — what things are or what they're supposed to do.

**Turn 4b — Boundary (conditionally fired, agent-driven):**

Only fires if Turn 4a produced a mechanism-level answer. If Turn 4a was vague, move to Phase 3 immediately — piling on a boundary probe when mechanism failed is the old system's trap.

> "And [specific mechanism they described] — when did that break, or when did it not do what you expected? What happened?"

This is the boundary probe. Its job: distinguish someone who *used* a system from someone who *understands* it. Edge cases, failure modes, unexpected behaviors — these only surface through real use. Someone who ran a model knows what happens when predictions go wrong. Someone who read the docs doesn't.

**What "good" and "vague" look like at boundary level:**

Good boundary answer: *"When we had very sparse interaction data — like users who'd only interacted once — the SVD decomposition was unstable, recommendations became weird. I had to add a minimum-interaction threshold and route sparse users to a popularity fallback."*

Vague boundary answer: *"There were some edge cases we handled" / "we made sure to test for that" / "error handling was in place."*

The difference: good answers name a specific failure mode, describe what they observed, and explain what they did about it. Vague answers assert that handling existed without describing it.

**What the agents do during Phase 2:**
- **ConceptAgent**: extracts technical vocabulary — does it match resume claims? Is it specific or generic?
- **WeaknessAgent**: classifies Turn 4a answer quality — mechanism-deep / system-language / vocabulary-only / generic. Flags `anchor_confidence`.
- **DiscrepancyAgent**: watches for mismatches between what they're describing now and what the resume claims (e.g., resume says "architected" but answers use "we helped with")
- **FollowUpAgent**: if Turn 4a was system-language or vocabulary-only, generates a sharpened mechanism follow-up before the boundary probe. The candidate gets one more chance to show mechanism knowledge before Phase 3.

**System role — `anchor_confidence` flag:**
- `high`: Turn 4a produced specific mechanism detail — a named function, class, algorithm, parameter, or design decision with first-person ownership
- `medium`: Turn 4a produced surface-correct vocabulary but no specific artifact or decision
- `low`: Turn 4a was system-language, generic, or ownership-unclear

If `anchor_confidence` is `low`, Phase 3 becomes more open-ended and fundamentals-testing — a harder test for a candidate who couldn't demonstrate mechanism-level knowledge in Phase 2.

**The balance Antigravity is aiming for:**

| Too cold (old system) | Too warm (overcorrected) | Target |
|-----------------------|--------------------------|--------|
| Attack probe on Q1, no warmth | "Walk me through it" — pure narration | Warm framing, specific demand |
| "What decision would you defend?" | "What was hardest?" — no signal | "What did you write to make that work?" |
| Probe every resume claim | Accept everything at face value | Probe the one claim they lead with, three levels deep |
| Chase each weakness with 4 questions | Move on after any answer | Surface → mechanism → boundary, one question each, then move |

---

### Phase 3: Application Transfer (Turn 5)

**Purpose:** Test whether the claimed knowledge is genuinely internalized by giving them a new scenario in the same domain — built specifically from what THEY said, not from generic domain knowledge.

**The principle here:** Application transfer is fundamentally harder to fake than claim recall. You can memorize what you built. You cannot memorize the extension of your specific implementation to a scenario you've never seen, especially when the question references the exact details you just described.

**The governing rules:**
1. **Same domain** as what they described — don't jump to a different tech stack or problem class
2. **One new constraint** — not five new requirements, just one meaningful shift (batch→real-time, single-user→multi-tenant, low-scale→high-scale)
3. **Anchored to their description** — must reference something specific they said, so it cannot be answered generically
4. **Situational framing** — not "what breaks if," but "imagine your PM comes to you tomorrow and says..." — this is how real work actually arrives
5. **Calibrated to `anchor_confidence`** — if Phase 2 produced a strong mechanism-level anchor, the application question extends that mechanism. If Phase 2 produced only surface-level description, the application question becomes more open-ended and fundamentals-testing — which is itself a harder test for a candidate who didn't demonstrate depth

**Example construction:**

Candidate described in Turns 3-4: *"I built a recommendation system using collaborative filtering, trained weekly on user history, outputs a daily batch of recommended content per user."*

Application question:
> "Okay so imagine you're back at work tomorrow and your PM comes to you and says — hey, we want the recommendations to update based on what a user is doing in the current session, not just their historical data. Like, if they just watched three videos on cooking, we want to adjust immediately. How would you even start thinking about how to change what you built?"

Why this phrasing:
- "Imagine you're back at work tomorrow" — situational, concrete, human. This is how real problems arrive.
- "Your PM comes to you and says" — realistic framing removes the "exam" feeling
- "How would you even start thinking about how to change what you built" — open, no pressure, invites thinking-out-loud
- The question references their specific system (weekly batch, historical data) — cannot be answered generically

**What this is NOT:**
- ~~"What breaks first if I told you..."~~ — too abrupt, sounds like a gotcha
- ~~"Redesign your system to be real-time"~~ — too directive, skips the thinking process
- Not a generic system design question — it must reference their specific approach

**System role during Phase 3:**
- Fire the pre-generated application question
- Log the candidate's full response before any follow-up — do not interrupt
- Map their response to the answer coverage map in background

---

### Phase 4: Coverage-Guided Follow-up (Turns 6-10)

**Purpose:** Surface the dimensions the candidate didn't cover in their application answer. One exploratory prompt per uncovered dimension. Build the coverage portrait — and where the candidate recovers, probe deep enough to know whether that recovery was real understanding or just recognition.

**The governing rules:**
1. One surfacing prompt per new dimension — never two *opening* questions on the same gap
2. **Exception — depth-of-recovery follow-up:** If the candidate recovers a surfaced dimension at surface level (names the concept, can't explain the mechanism), one additional mechanism follow-up is allowed on that same dimension before moving on. This is not a second chance to find the answer — it's a single probe to distinguish *recognized the concept* from *understands how to implement it*. These are different things and they score differently.
3. Framing is exploratory and collaborative, not interrogative — "I didn't hear you mention X" not "you failed to address X"
4. After surfacing + optional mechanism follow-up, score and move to next dimension
5. Maximum 3 dimensions surfaced (opening questions) — remaining gaps are noted but not pursued

**Turn pattern — surfacing + depth-of-recovery:**

If candidate covered serving architecture and latency handling but missed data freshness and cold-start:

*Turn 6 — surface data freshness:*
> "One thing I'm curious about — for users where the session signal and their historical behavior are pointing in totally different directions, how does your system handle that? Which one wins?"

→ **If they recover at mechanism level** (explain specifically how the system adjudicates, what logic runs, what tradeoffs they made): score `recovered_deep`, move on.

→ **If they recover at surface level** (name the concept — "we'd need to weight them somehow", "session data should probably win" — but no implementation): fire Turn 6b.

*Turn 6b — depth-of-recovery follow-up (conditional):*
> "Right — so in terms of how you actually made that happen in [the specific implementation they described], what did that look like concretely? Where did that weighting decision live?"

→ **If mechanism emerges**: score `recovered_deep`. If it doesn't: score `recovered_surface`. Either way — move on. No third question.

*Turn 7 — surface cold-start:*
> "And what about someone who's completely new — they just downloaded the app today and haven't watched anything. What does your updated system do for them?"

→ Same two-step pattern applies. If they surface and explain the mechanism: `recovered_deep`. If they name it but not the implementation: Turn 7b. If nothing: `missed_even_prompted`.

*Turn 8 (if needed — surface next gap):*
> "Got it. One more angle — [dimension D framed as a situation or question, not a gotcha]"

**Framing rule for surfacing questions:**
- Name the **situation or tension** (new user with no history, conflicting signals, system under load)
- Do NOT name the **solution** (caching, fallback algorithm, feature store)
- The candidate should recognize the problem from their own experience — if they do, they know the domain; if they don't, they don't

**Why the two-step matters:**

"Recovered when prompted" is not a single state. A candidate who says "oh right, you'd need to handle cold-start users with a fallback to popularity rankings — we actually used a decay-weighted popularity score for the first week until they had enough interactions" has recovered deep. A candidate who says "yeah cold-start is a known problem in recommenders" has recovered at the vocabulary level — they know the term, not the solution.

These candidates score very differently in a hiring decision. The two-step recovers that distinction without adding a full extra question per dimension.

**Scoring per dimension:**

```
covered_voluntarily      → 1.0   (addressed without prompting — they had it)
recovered_deep           → 0.7   (prompted, explained mechanism — real knowledge, just not top-of-mind)
recovered_surface        → 0.4   (prompted, named the concept, couldn't go deeper — recognition without implementation)
missed_even_prompted     → 0.0   (surfaced directly, still nothing — genuine blind spot)
answered_incorrectly     → -0.2  (incorrect response — conceptual misunderstanding, worse than silence)
```

**What this solves:**
Distinguishes "didn't think to mention it" from "knows the name but not the implementation" from "doesn't know it at all." All three are real states and they warrant different verdicts. The two-step surfacing pattern captures all three without adding excessive questioning.

---

### Phase 5: Second Anchor (Turns 11-13)

**Purpose:** Brief treatment of the second experience the candidate naturally surfaced — in their self-intro, their narration, or a mention during Phase 4. Not a sweep of the whole resume. Not a separate deep-dive. Just enough to get a second signal.

**The principle here:** The full resume does not need to be covered. Candidates will surface what matters to them. If they mentioned a second project, internship, or experience during the session, that is worth 2-3 questions. Everything else on the resume that they didn't bring up is either older, less relevant, or less confident — and chasing it produces no useful signal.

**Turn 11 (orient to the second thing they mentioned):**
> "Yeah, you mentioned [second thing they brought up earlier] — tell me about that one. What were you doing there, what did you build?"

**Turn 12 (find the implementation detail):**
> "And in that project — what was the most interesting or tricky thing you worked on?"

("Most interesting or tricky" — accessible version of "what was hardest." Same signal, less clinical.)

**Turn 13 — Technical Boundary Probe:**

> "In [the most specific component they named in Turn 12] — where does that approach actually break? Like what's the scenario where you'd hit the limit of it and have to do something different?"

Or if they described a specific decision or technique in Turn 12:
> "You mentioned [specific approach or decision from Turn 12] — when is that the wrong call? What conditions would make you not use it?"

**Why this instead of a mini-application transfer:**

A condensed application transfer — "what if someone gave you this problem but now with one new constraint?" — asks the candidate to think forward: construct an extension of the system. That works well in Phase 3 because we have a deep anchor built over two full turns of mechanism-level probing. In Phase 5, after only two turns on the second experience, the anchor is shallow. An application transfer built on a shallow anchor becomes a generic system design question, answerable without real domain knowledge.

A technical boundary probe tests in the opposite direction — not "what would you build if," but "where did this break, or where would it." That question is only answerable by someone who genuinely worked with the technology close enough to encounter or anticipate its limits:

- A real practitioner names a specific failure mode, edge case, or architectural constraint — something they observed or had to design around
- A peripheral contributor knows problems exist in general but describes them abstractly, without a specific case
- Someone who inflated their resume says "it worked well for what we needed" or expresses flat confidence with no specific edges

The boundary probe is also harder to prepare for. A candidate who anticipated "what would you change" can rehearse an answer. A candidate who anticipated nothing specific about where their exact implementation breaks cannot coach their way through Turn 13.

**The signal gradient for boundary answers:**

| Answer Type | What It Sounds Like | What It Means |
|-------------|---------------------|---------------|
| **Boundary-real** | Specific condition, specific behavior, specific response. "When [X happened], [component] would [Y], so we had to [Z]." Has a named edge case, observed output, or a decision that was made in response to it. | Genuinely worked with it. Second-domain depth confirmed. |
| **Boundary-adjacent** | Knows the general class of failure. "At high throughput, you'd start seeing [type of bottleneck]." Correct direction, no specific case. | Familiar with the domain at a conceptual level. Probably adjacent to the work. |
| **Boundary-absent** | "It worked fine for our use case" / "we made sure to test for edge cases" / "I'd have to run more experiments to say." Zero specificity. | Did not engage with the implementation at depth. Strong inflation signal on this claim. |

**What NOT to ask here:**
- ~~"What would you redo?"~~ — invites performance of humility, not boundary knowledge; produces coached answers
- ~~"What was the hardest part technically?"~~ — same problem; philosophical framing, not specific signal
- ~~A new scenario or constraint~~ — the second anchor is too shallow for a non-generic application transfer
- ~~Coverage of resume sections they never mentioned~~ — the candidate didn't surface it for a reason

---

### Phase 6: Human Close (Turns 14-15)

**Purpose:** End warmly. Let the candidate feel the interview was a real conversation, not a grilling. Collect any remaining qualitative signal without pressure. Leave them with a positive impression of the process regardless of outcome.

**The principle here:** The close should feel like the natural end of a conversation between two people, not the final exam question. It should be something any candidate can answer comfortably, which also means it needs to actually be interesting to answer — not performatively philosophical.

**Turn 14:**
> "Alright, we're almost done — before we finish, is there anything about your work or what you've been building that you wanted to talk about that we didn't get to?"

Why this:
- "Anything you wanted to talk about" — genuinely open invitation, zero pressure
- It catches cases where the candidate has something important they didn't get to show
- A candidate who says "actually yes, I've been working on X" tells you something real
- A candidate who says "no, I think we covered it" also tells you something

**Turn 15:**
> "Last one — what kind of work are you most excited to be doing in the next role? Like what's the thing you really want to get into?"

Why this:
- Low stakes, easy to answer, everyone has a genuine answer
- Reveals motivation and direction — useful signal even if not technical
- Ends the interview on a forward-looking, energized note — the candidate leaves thinking about their own excitement, not about how the exam went
- Closes the loop with warmth: the interview started with who they are, it ends with where they want to go

**What NOT to use here:**
- ~~"What's the hardest unsolved problem you're sitting with right now?"~~ — sounds like one more technical test, kills the warmth of the close
- ~~"Is there something this format didn't let you show?"~~ — implicitly defensive, implies the format was inadequate
- ~~Anything that requires the candidate to self-assess their performance~~ — they can't do this objectively and it creates anxiety

---

## 4. New System Component: Candidate State Tracker

**Where it lives:** `backend/state/candidate_state.py`
**When it runs:** Updated after every turn, in the fast path (not background)
**What it feeds:** orchestrator.py routing decisions, followup_agent.py question selection

```python
@dataclass
class CandidateState:
    disengagement_level: float = 0.0        # 0.0-5.0, drives mode switching
    consecutive_no_content: int = 0          # turns with zero extractable signal
    explicit_skip_count: int = 0             # "skip", "next question", "different topic"
    social_deflection_count: int = 0         # "i'm good", "don't worry", "thank you"
    incoherence_count: int = 0               # circular definitions, non-sequiturs
    communication_mode: str = "normal"       # "normal" | "simplified" | "narrative_only"
    topic_fatigue: dict = field(default_factory=dict)  # {focus_key: question_count}
    topic_fatigue_threshold: int = 4         # max questions per focus_key before forced rotation
    forced_exit_triggered: bool = False
    phase: str = "orientation"               # tracks which interview phase we're in
```

### Disengagement Level Increments

| Signal | Increment | Detection Method |
|--------|-----------|-----------------|
| Explicit skip request ("skip", "next question", "different topic", "move on") | +2.0 | Keyword regex on raw transcript |
| Social deflection ("i'm good", "don't worry", "that's fine") | +1.0 | Keyword regex |
| Zero technical content in response | +0.5 | ConceptAgent returns empty concepts list |
| Incoherent response (circular definition, non-sequitur) | +1.0 | WeaknessAgent detects incoherence pattern |
| Substantive technical answer | -0.5 | ConceptAgent returns non-empty concepts |

### Disengagement Thresholds → Actions

| Level | Action |
|-------|--------|
| 2.0 | Trigger save-face pivot: "Let me try a different angle — which part of this work are you most confident explaining?" |
| 3.0 | Force focus_key rotation — select question from different focus area regardless of map sequence |
| 4.0 | Switch communication_mode to "simplified" — shorten question phrasing, prefer narrative prompts |
| 5.0 | Trigger graceful exit protocol — skip to Phase 6 close immediately |

### Topic Fatigue Check

```python
def check_topic_fatigue(state: CandidateState, current_focus_key: str) -> bool:
    """Returns True if forced rotation should trigger."""
    count = state.topic_fatigue.get(current_focus_key, 0)
    return count >= state.topic_fatigue_threshold

def get_topic_fatigue_ratio(state: CandidateState, current_focus_key: str) -> float:
    """Returns fraction of total questions on this focus_key."""
    total = sum(state.topic_fatigue.values())
    if total == 0:
        return 0.0
    return state.topic_fatigue.get(current_focus_key, 0) / total
```

If `get_topic_fatigue_ratio() > 0.55`, force rotation regardless of disengagement level.

### Communication Mode Detection

Run on turns 1-2 only. If detected patterns exceed threshold, set `communication_mode`:

- **ESL markers**: word repetition ("while while while", "for for that"), mid-sentence restarts, fragmented syntax → `communication_mode = "simplified"`
- **Full shutdown**: single-word or near-empty responses 2+ times → `communication_mode = "narrative_only"`
- **Normal**: coherent sentences, structured thought → `communication_mode = "normal"`

In `simplified` mode, followup_agent receives instruction: "Use maximum one sentence per question. Prefer 'Tell me about X' over mechanism questions. Avoid compound questions."

**Reasoning:** ESL communication difficulty under pressure is not the same as not knowing the answer. Removing linguistic friction surfaces real knowledge. Session 98c80520's early turns were ESL patterning, not ignorance.

**Trade-off:** Risk of false positive — some candidates who are disengaged look like ESL speakers. Mitigation: only set on turns 1-2, and only if 3+ markers detected.

---

## 5. New System Component: Answer Coverage Map

**Where it lives:** Generated per Application Transfer question, stored in session state
**When it's generated:** During Phase 2 (STAR-lite), so it's ready before the application question is asked
**What it feeds:** Phase 4 coverage-guided follow-up logic

### Structure

```python
@dataclass
class CoverageDimension:
    id: str                         # "data_freshness", "cold_start", "model_serving", etc.
    label: str                      # Human-readable
    description: str                # What this dimension is and why it matters
    expected_approaches: list[str]  # A1, A2, A3 — multiple valid implementations
    surfacing_question: str         # The one exploratory prompt if this dimension is missed
    weight: float                   # How important is this dimension (0.0-1.0)

    # Set after evaluation
    coverage_state: str = "not_evaluated"  # "voluntary" | "recovered_deep" | "recovered_surface" | "missed" | "incorrect"
    candidate_response: str = ""
    surfacing_attempted: bool = False  # True once the surfacing question has been asked

@dataclass
class AnswerCoverageMap:
    application_question: str
    implementation_anchor: str          # The specific thing they said in Phase 2 that generated this
    dimensions: list[CoverageDimension]
    total_weight: float
    coverage_score: float = 0.0         # Computed after evaluation
    coverage_confidence: float = 0.0    # How confident we are in our expected-answer lattice
```

### Coverage Scoring

```python
COVERAGE_WEIGHTS = {
    "voluntary":        1.0,   # addressed without prompting
    "recovered_deep":   0.7,   # prompted, explained mechanism — real knowledge
    "recovered_surface": 0.4,  # prompted, named the concept, no mechanism — recognition only
    "missed":           0.0,   # surfaced directly, still nothing
    "incorrect":       -0.2,   # conceptual misunderstanding
}

def compute_coverage_score(coverage_map: AnswerCoverageMap) -> float:
    weighted_sum = 0.0
    for dim in coverage_map.dimensions:
        weight = dim.weight * COVERAGE_WEIGHTS.get(dim.coverage_state, 0.0)
        weighted_sum += weight
    return max(0.0, weighted_sum / coverage_map.total_weight)
```

### Surfacing Question Framing Rules

The surfacing question for each dimension must be **directional but not revealing**:

| Wrong (too leading) | Right (directional) |
|---------------------|---------------------|
| "Don't you think caching is important here?" | "I didn't hear you address what happens when the pipeline falls behind real-time — was that intentional?" |
| "What about cold start users?" | "Your system knows a lot about returning users — what does it do for someone who just installed?" |
| "Shouldn't you use a feature store?" | "How does your real-time signal get to the model — what sits between the event and the prediction?" |

The rule: name the **problem space** (pipeline falling behind, new users, event-to-prediction path), not the **solution** (caching, cold-start fallback, feature store). You're testing whether they recognize the problem, not whether they can repeat a solution you named.

### Coverage Map Generation Prompt

The coverage map is generated by a dedicated LLM call (claude-haiku-4-5 for speed) using:
- `implementation_anchor`: what they specifically said they built
- `target_role`: the job they're applying for
- `application_question`: the transfer question that was asked

Output: 4-6 dimensions with expected_approaches, surfacing_questions, and weights.

**Trade-off:** LLM-generated lattice quality depends on domain coverage in training. Niche proprietary systems (XNCC DSP, custom ML pipelines) may produce thin or inaccurate lattices. Mitigation: add `coverage_confidence` score to the map — if the system doesn't recognize the domain well, flag lower confidence on the evaluation output.

---

## 6. New System Component: Application Transfer Generator

**Where it lives:** New agent — `backend/agents/application_agent.py`
**When it runs:** End of Phase 2 (after turn 4), in background
**What it produces:** The Phase 3 application question + the answer coverage map

### Input

```python
@dataclass
class ApplicationTransferInput:
    implementation_anchor: str      # "I built X using Y approach for Z constraint"
    candidate_domain: str           # Derived from resume focus area
    target_role: str                # From session config
    years_experience: str           # junior / mid / senior — calibrates complexity
    resume_snippets: list[str]      # Relevant resume lines for domain context
```

### Output

```python
@dataclass
class ApplicationTransferOutput:
    question: str                   # The application transfer question
    adjacent_constraint: str        # What's new/different (e.g., "real-time instead of batch")
    anchor_reference: str           # The specific thing from their answer the question references
    coverage_map: AnswerCoverageMap # Pre-built dimension lattice
    complexity_level: str           # "surface" | "mechanism" | "boundary" — calibrated to experience
```

### Generation Rules (injected into prompt)

1. **Must reference the implementation anchor specifically** — if they said "SVD decomposition", the question must mention SVD or the constraint that makes SVD insufficient
2. **Adjacent, not orthogonal** — the new problem must be in the same domain, not a different field entirely
3. **One new constraint** — don't add 5 new requirements. One meaningful shift (batch→real-time, single-user→multi-tenant, controlled→adversarial environment)
4. **Open-ended answer space** — must have multiple correct implementation approaches
5. **Calibrate to experience** — junior: surface-level design; senior: boundary conditions and failure modes

### Failure Modes and Mitigations

| Failure | Mitigation |
|---------|------------|
| Question becomes generic system design (answerable without the candidate's specific knowledge) | Validation step: does the question reference the `implementation_anchor`? If not, regenerate. |
| Question is too hard (requires knowledge the role doesn't demand) | Experience tier calibration. Junior → "how would you approach", Senior → "what breaks first and how do you fix it" |
| Candidate gave no clear implementation anchor in Phase 2 | Fallback: use the broadest resume claim as anchor. Flag lower confidence on evaluation. |

---

## 7. New System Component: Coverage-Guided Follow-up

**Where it lives:** Modified `backend/agents/followup_agent.py` — new route `coverage_surface`
**When it runs:** Phase 4 (turns 6-10)
**What it replaces:** The current `attack_probe` / `clarification_fast` cycle in response to weakness detection

### The One-Prompt Rule (with depth-of-recovery exception)

For each uncovered dimension in the coverage map:
- Ask the surfacing question once
- Evaluate the response
- **If recovered at surface level:** fire one mechanism follow-up (depth-of-recovery step) — then score and move on
- **If recovered at mechanism level or missed entirely:** score immediately and move on

**No dimension receives more than two questions total** (opening surfacing + optional mechanism follow-up). This is a hard cap. The current system asks 4-5 on the same weakness — this doubles down on the weakness and ignores everything else. The new system surfaces one gap, probes depth once if needed, and moves.

### Routing Logic

```python
def select_coverage_route(
    coverage_map: AnswerCoverageMap,
    candidate_state: CandidateState,
    turn_number: int,
    last_dimension_id: str | None = None,
    last_recovery_depth: str | None = None,
) -> str:
    """
    Returns the next question to ask in Phase 4.

    last_dimension_id: dimension we just surfaced (if any)
    last_recovery_depth: "surface" if candidate recovered but couldn't explain mechanism
    """
    # Check candidate state first — override if disengaged
    if candidate_state.disengagement_level >= 3.0:
        return "force_rotation"

    # If last surfacing produced a surface-level recovery, fire depth-of-recovery follow-up
    if last_dimension_id and last_recovery_depth == "surface":
        return f"coverage_depth_probe:{last_dimension_id}"

    # Find uncovered dimensions that haven't been surfaced yet
    unsurfaced = [
        d for d in coverage_map.dimensions
        if d.coverage_state == "not_evaluated" and not d.surfacing_attempted
    ]

    if not unsurfaced:
        # All dimensions surfaced — move to Phase 5
        return "phase_transition_second_domain"

    # Sort by weight — surface highest-weight gaps first
    next_dim = sorted(unsurfaced, key=lambda d: d.weight, reverse=True)[0]
    next_dim.surfacing_attempted = True

    return f"coverage_surface:{next_dim.id}"
```

### Semantic Matching for Coverage Evaluation

When evaluating whether a candidate covered a dimension, use semantic matching — not keyword matching.

The evaluation prompt (in EvaluationAgent or a dedicated coverage evaluator):
> "The expected dimension is [dimension description]. The candidate said: [response]. Did they address this dimension, even using different terminology or a different approach than expected? Score: full / partial / not_covered / incorrect."

This prevents the false-negative where a candidate correctly addresses caching by calling it "buffering" or "data persistence" and the system marks it as uncovered because the keyword "cache" didn't appear.

---

## 8. Evaluation Redesign — Coverage Portrait

### Current Output (Deficit Model)

```json
{
  "overall_score": 2,
  "hire_recommendation": "NO HIRE",
  "confidence_score": 0.5,
  "weaknesses": ["deflection x13", "shallow x1"]
}
```

This output is epistemically misleading. It presents a definitive verdict with 0.5 confidence on 2 of 10 possible areas tested.

### New Output (Coverage Portrait)

```json
{
  "overall_score": 6.2,
  "coverage_score": 0.71,
  "coverage_confidence": 0.82,
  "hire_recommendation": "MAYBE",
  "verdict_basis": "coverage_portrait",

  "domain_coverage": {
    "primary_domain": {
      "label": "Real-time ML pipeline design",
      "voluntary_coverage": ["model serving architecture", "latency constraints"],
      "recovered_coverage": ["monitoring metrics"],
      "missed_coverage": ["online learning / retraining", "data consistency guarantees"],
      "incorrect_coverage": [],
      "domain_score": 0.68
    },
    "secondary_domain": {
      "label": "Analytics event infrastructure",
      "voluntary_coverage": ["session definition"],
      "missed_coverage": ["pipeline failure handling", "schema versioning"],
      "domain_score": 0.31
    }
  },

  "capability_portrait": {
    "systems_thinking": "moderate — identified deployment concern but missed consistency model",
    "application_transfer": "good — extended batch→realtime correctly on serving layer",
    "depth_under_probing": "shallow — recovered on monitoring when surfaced but could not go deeper",
    "communication_quality": "clear, structured, calibrated confidence"
  },

  "claim_credibility": {
    "level": "medium",
    "detail": "Primary implementation claim partially substantiated. Real-time extension showed genuine domain understanding on 2 of 5 dimensions."
  },

  "verdict_confidence_basis": "Coverage was 71% of expected dimensions across 2 domains. Confidence is high (0.82) because gaps were confirmed via surfacing prompts.",

  "untested_dimensions": ["SQL/data modeling depth", "collaboration/process skills"],
  "recommended_followup": "Technical phone screen on data consistency and retraining pipeline before final decision"
}
```

### Verdict Tier System

**2026-05-07 Yash final decision:** The coverage-map verdict tier system is advisory for now, not the final hiring authority. The final `hire_recommendation` and `confidence_score` must come from the LLM evaluator's full transcript context. Coverage score should be passed in as strong evidence and surfaced in `coverage_verdict_advisory`, but it must not override the LLM verdict unless Yash explicitly reopens this decision.

| Verdict | Condition | Meaning |
|---------|-----------|---------|
| `STRONG_HIRE` | Coverage > 75%, domain_score > 0.80 | Clear endorsement |
| `HIRE` | Coverage > 55%, domain_score > 0.65 | Standard endorsement |
| `MAYBE` | Coverage > 35%, domain_score 0.45-0.65 | Human review — describe specific gaps |
| `NO_HIRE` | Coverage > 45%, domain_score < 0.40, confirmed gaps even when prompted | Definitive rejection |
| `CLAIM_RISK_FLAG` | Confirmed discrepancies on core claims | Append to any verdict — flag for HR |
| `INSUFFICIENT_DATA` | Coverage < 35% OR disengagement_triggered_early_exit | Cannot assess — reschedule or different format |

### Confidence Gates Verdict

```python
def resolve_verdict(coverage_score, coverage_confidence, disengagement_triggered):
    if disengagement_triggered:
        return "INSUFFICIENT_DATA"

    if coverage_confidence < 0.50:
        # We don't trust our own coverage map — downgrade
        return "INSUFFICIENT_DATA" if coverage_score < 0.50 else "MAYBE"

    if coverage_score < 0.35:
        return "INSUFFICIENT_DATA"
    elif coverage_score < 0.45:
        return "NO_HIRE"
    elif coverage_score < 0.65:
        return "MAYBE"
    elif coverage_score < 0.80:
        return "HIRE"
    else:
        return "STRONG_HIRE"
```

**Why this matters:** Session e5170a7a had 0.5 confidence and output NO_HIRE. Under this model, it outputs INSUFFICIENT_DATA — an epistemically honest answer that tells the hiring manager "we couldn't assess this candidate, not that we assessed them and they failed."

---

## 9. Implementation Plan — Prioritized

### P0 — Critical UX Fixes (1-3 days, no architecture changes)

| Item | File | Change | Problem Solved |
|------|------|--------|---------------|
| Add explicit skip detection | `orchestrator.py::handle_transcript()` | Regex scan for skip signals before routing. If detected, set `force_focus_rotation=True` | Candidate says "skip" 3 times, gets Veo-3 question anyway |
| Add topic fatigue ratio check | `orchestrator.py` | If focus_key count / total_questions > 0.55, force rotation | 13/15 questions on same project |
| Fix Q1 opening preamble | `followup_agent.py::PERSONA_PROMPTS` | Decouple warmth preamble from route. Only use "ease in" prefix when route is `sprint_seed` or `sprint_opener`, never `attack_probe` | Promise of warmth violated by cold probe |
| Add `INSUFFICIENT_DATA` to evaluation | `evaluation_agent.py` | New verdict tier, triggered by low coverage + disengagement flag | False confidence in NO_HIRE on narrow coverage |

These four changes address the most severe failures in both sessions. They are surgical — no new components, just guards and routing logic.

> **Map generation failures (see Section 12) are also P0 in spirit — they produce broken interviews before the candidate even speaks. Tracked separately below because they live in the map generation pipeline, not the live interview pipeline.**

### P0 — Map Generation Fixes (1-3 days, surgical prompt + logic changes)

| Item | File | Change | Problem Solved |
|------|------|--------|---------------|
| Add role type as first-class generation input | `interview_map.py` | Pass `role_type` (PA / engineer / scientist / etc.) into focus area selection and question generation prompts. Role type determines what "depth" means. | Map generates analytics engineer questions for a product analyst role |
| Fix anchor selection — outcome claims over implementation claims | `interview_map.py::_select_focus_anchor()` | For PA/PM roles: rank quantified outcome claims above implementation language claims. "Retention 25%→42%" outranks "Architected and implemented analytics infrastructure." | Wrong bullet anchored; top 3 outcome bullets demoted to secondary |
| Phase-tag openers — Turn 2 compatible only | `interview_map.py::_generate_opener()` | Openers must be warm + narrative + ownership-establishing. Cannot be mechanism-level. Pattern: "Tell me about [outcome claim] — walk me through that experiment." | Cold mechanism question on Turn 1; candidate feedback: "silly, how would I remember" |
| Promote metric_risk and causal_validity to main flow | `interview_map.py::_generate_dimensions()` | For PA roles: metric definition question and causal validity question are core dimensions, not recovery branches. They fire regardless of candidate fluency. | "How was retention defined" only fires if candidate underperforms — confident wrong answers never get challenged |
| Add signal_weight to each dimension | `interview_map.py` + dimension schema | Each dimension gets `signal_weight` (1.0–3.0) based on role relevance. Orchestrator surfaces highest-weight dimensions first. | Diamonds and garbage weighted identically; good questions become outliers |
| Close the pass_1 repair loop | `interview_map.py::_apply_pass1_repairs()` | New function: takes `repair_instructions` from pass_1 as direct prompt input and re-generates named fields. Sets `repair_applied: true/false` per instruction. Map with unapplied repairs does not ship as `map_status: ready`. | Pass_1 correctly identified compound CV opener; shipped unchanged |
| Rebalance focus area budget by recency + role relevance | `interview_map.py::_allocate_focus_budget()` | Current role: 60%+ budget. Adjacent context (same company, previous title): 20-25%. Academic internship with no continuity: 10% attention-check only (2-3 questions max). | 2-month CV internship given equal billing as current role |

---

### P1 — Candidate State Layer (1-2 weeks)

| Item | File | Change |
|------|------|--------|
| Create `CandidateState` dataclass | `backend/state/candidate_state.py` | New file |
| Integrate with SessionManager | `backend/state/session_manager.py` | Store/retrieve candidate_state alongside session state |
| Add disengagement scoring to orchestrator | `orchestrator.py::handle_transcript()` | After each turn, update disengagement_level |
| Add disengagement action thresholds | `orchestrator.py::_select_next_question()` | Level 2 → save-face pivot, Level 3 → force rotation, Level 5 → graceful exit |
| Build Total Confession pivot | `followup_agent.py` + `orchestrator.py` | New route: `confession_pivot`. "What skill are you most confident in that this role needs?" |
| Add graceful exit protocol | `orchestrator.py::handle_transcript()` | When exit triggered, skip to Phase 6 close questions |
| Add ESL/communication mode detection | `orchestrator.py` | Detect on turns 1-2, set `communication_mode` |
| Pass communication_mode to followup_agent | `followup_agent.py` | Simplified question phrasing when mode != "normal" |

---

### P2 — New Interview Architecture (2-4 weeks)

| Item | File | Change |
|------|------|--------|
| Build Orientation Phase (turns 1-2) | New: `backend/agents/orientation_agent.py` | Generates warm, narrative, ownership-probing turns 1-2. Replaces cold sprint opener. |
| Build STAR-lite extraction | `orchestrator.py` | After turns 3-4, extract `implementation_anchor` from candidate responses |
| Build Application Transfer Generator | New: `backend/agents/application_agent.py` | Takes implementation_anchor, generates adjacent-constraint transfer question + coverage map |
| Build Answer Coverage Map | New: `backend/models/coverage_map.py` | Data structure + generation logic |
| Build Coverage-Guided Follow-up route | `followup_agent.py` | New route `coverage_surface` — one surfacing prompt per uncovered dimension |
| Add semantic matching to coverage evaluation | `evaluation_agent.py` | Check dimension coverage semantically, not by keyword |
| Build Coverage Portrait output | `evaluation_agent.py` | New output format — coverage_score, domain_coverage, capability_portrait |
| Implement Verdict Tier System | `evaluation_agent.py` | Replace binary HIRE/NO_HIRE with 6-tier system |
| Update report rendering | `app/report/[session_id]/page.tsx` | Display coverage portrait, capability portrait, not just deficit list |

---

### P3 — Polish and Calibration (ongoing)

| Item | Notes |
|------|-------|
| Coverage map confidence scoring | Flag domains where the expected-answer lattice may be thin or inaccurate |
| Application question validation gate | After generation, check that the question references the implementation_anchor — regenerate if not |
| Experience-tier calibration | Junior → surface-level design questions; Senior → boundary conditions, failure modes |
| Second domain quick-pass templating | Abbreviated STAR + one "redo" question |
| Graceful close turn generation | Orientation-agent-style for Phase 6 |
| Evaluation output dashboard update | /sessions endpoint + dashboard unpacking of new coverage_portrait JSONB |
| Candidate name extraction | Pull from resume parsing and display in report header |
| Secure /admin/redis-dump | Add auth or remove entirely |

---

## 10. Trade-off Table

| Decision | Benefit | Cost | Mitigation |
|----------|---------|------|------------|
| Application transfer over claim drilling | Tests real capability, harder to fake | Scoring is subjective — no single right answer | Coverage map with expected lattice + semantic scoring |
| One surfacing prompt per gap | Prevents tunneling, respects candidate | May miss depth on genuinely important gaps | Weight high-importance dimensions, move them to Phase 5 second domain if needed |
| Candidate state disengagement detection | Prevents sessions like e5170a7a Q12-Q15 | False positives — confident blunt candidates may look disengaged | Calibrate thresholds carefully; social deflection alone doesn't trigger — needs consecutive no-content |
| INSUFFICIENT_DATA verdict tier | Epistemically honest | Hiring manager gets less signal | Report explains exactly what was and wasn't tested, with recommendation to reschedule |
| Coverage portrait over deficit list | Richer, more actionable output | Harder to generate reliably | Multiple coverage_state options, semantic matching, confidence flagging |
| Orientation phase (turns 1-2) | Real warmth, baseline speech data | Costs 2 turns of probing time | More efficient probing in turns 3-10 compensates — better anchoring means fewer wasted probes |
| ESL/simplified mode | Tests knowledge through accessible language | May reduce bar for communication skill | Only affects phrasing, not scoring. Communication score still evaluated separately. |
| Topic fatigue ratio (55% cap) | Prevents 13/15 on same topic | Might cut off a genuinely deep line of questioning | 55% is generous. 8 of 15 questions on one topic is already excessive. |

---

## 11. What the Current System Keeps

These are strong and should not be touched:

- **Two-track architecture** (fast path + background pipeline) — keeps UX snappy
- **Interview map two-pass generation with self-critique** — the dimension and recovery generation quality is genuinely good; the two-pass loop itself needs to close (see Section 12, Failure 6)
- **Background agent pipeline** (ConceptAgent, WeaknessAgent, DiscrepancyAgent, ReasoningBehaviorAgent) — these still run during candidate speech, their output feeds the coverage portrait
- **Discrepancy detection** — moves from being the *driver* of the interview to being a *background signal* that annotates the coverage portrait and can trigger CLAIM_RISK_FLAG
- **Sprint structure** (3 sprints, 3 personas) — the persona progression from curious_lead → socratic_mentor → senior_peer maps naturally to Orientation → STAR-lite → Application Transfer
- **Challenge budget and anti-tunneling** — kept but augmented by the topic fatigue ratio check
- **ProvenHire handoff integration** — unchanged
- **Redis session management** — unchanged
- **Evaluation agent dimensions** (reasoning, technical_depth, communication, adaptability) — kept as sub-scores under the capability_portrait

---

## Summary: What Changes, What Stays, What's New

```
CHANGES (modify existing):
  orchestrator.py          → candidate state integration, disengagement routing, skip detection
  followup_agent.py        → coverage_surface route, confession_pivot route, communication_mode phrasing
  evaluation_agent.py      → coverage portrait output, verdict tier system, semantic matching
  interview_map.py         → role-aware anchor selection, phase-tagged openers,
                             question signal weighting, pass_1 repair loop closure,
                             focus area budget allocation by recency/relevance

NEW (build from scratch):
  candidate_state.py       → CandidateState dataclass + scoring logic
  orientation_agent.py     → Turns 1-2 warm narrative questions
  application_agent.py     → Application transfer question generator
  coverage_map.py          → Answer lattice data structure + generation

KEEPS (untouched):
  Two-track architecture, background pipeline agents, map generation quality,
  sprint/persona structure, ProvenHire integration, Redis session management
```

---

---

## 12. Interview Map Generation — Diagnosed Failures

> **Source:** Two production sessions (e5170a7a, 98c80520) + GPT interview benchmark analysis + direct candidate feedback from S V S Apparao (session 98c80520, Product Analyst role). Every failure below is mechanically traced — each has a root cause, a downstream cascade, and a specific fix target.

### The Cascade: One Root Cause, Six Downstream Failures

Almost every problem in the Apparao map traces back to a single failure in anchor selection. Fix the anchor and roughly 80% of what's broken self-corrects.

```
Wrong anchor selection  (bullet 4 chosen over bullets 1-2-3)
  ↓
Wrong focus area label  ("Daily Mantra Analytics Infrastructure" not "Retention & Experimentation")
  ↓
Wrong question tree     (implementation-depth framing, not analytical-reasoning framing)
  ↓
Wrong opener            (mechanism question cold on Turn 1)
  ↓
Core questions demoted  (metric_risk, causal_validity buried in recovery branches)
  ↓
Critical bullet omitted (trial-to-subscription never became a primary dimension)
  ↓
Uniform weighting       (good questions indistinguishable from bad ones)
```

---

### Failure 1: Anchor Selection Optimizes for Technical Language, Not Role-Relevant Signal

**What happened:**
The map selected bullet 4 as the primary anchor for Apparao's Daily Mantra experience:
> *"Architected and implemented core analytics event tracking for Daily Mantra zero-to-one product, defining critical product events enabling real-time insights and experimentation."*

**What should have been selected** (direct candidate feedback — Apparao's own priority ordering):

| Bullet | Claim | Why it's the right anchor |
|--------|-------|--------------------------|
| 1 | Retention 25%→42% via A/B testing (Video, Today, AI Guruji) | Primary outcome + primary skill demonstration. Involves hypothesis, experiment design, variant attribution, causal interpretation. |
| 2 | Trial-to-subscription 27%→42% by reducing trial 7→1 day | Counterintuitive product decision with measurable outcome. Rich analytical reasoning signal. |
| 3 | Mantra Track End completion 27.5%→55.5% | Funnel optimization with hard numbers — testable on denominator, cohort, causality. |
| **4** | **Architected analytics event tracking** | **This is the scaffolding that enabled 1-3. It's the mechanism, not the achievement.** |

**Why the system picked bullet 4:** It contains the strongest technical claim language — "Architected and implemented," "zero-to-one product," "real-time insights." These phrases produce the richest implementation question tree. The system optimized for question-tree richness, not for role relevance.

**The anchor rule that was missing:**
For PA/PM roles, outcome claims with numbers rank above implementation language claims. The anchor should be the highest-impact outcome that involves the most analytical reasoning — not the most technically-sounding verb phrase.

---

### Failure 2: Role Type Is Not a First-Class Generation Input

The map generation pipeline produces structurally identical interviews regardless of what job is being filled. Same surface→mechanism→boundary ladder. Same implementation-depth framing. Same recovery structure. Applied identically whether the role is Product Analyst, Analytics Engineer, or Data Scientist.

**What "depth" means by role type:**

| Role | Depth means | Primary signals |
|------|------------|-----------------|
| Product Analyst | Analytical reasoning, metric validity, experiment design, product judgment | Hypothesis formation, causal attribution, denominator definition, decision from data |
| Analytics / Data Engineer | Build quality, pipeline reliability, implementation ownership | Schema design, tooling choices, failure modes, scaling behavior |
| Data Scientist | Model understanding, statistical rigor, evaluation integrity | Algorithm selection rationale, metric trade-offs, out-of-sample thinking |

Apparao's map generated analytics engineer questions for a product analyst role. Every dimension probed build quality: event schema consistency, naming convention enforcement, API field joins at ad-set granularity. The hiring question for a PA role is not "did you build it correctly" — it's "did you think correctly with it."

**The GPT comparison confirms the target mismatch:**

| Question type | GPT covers | Antigravity map covers |
|---|---|---|
| Business reasoning ("why would shorter trial increase conversion?") | ✓ | ✗ |
| Causal validity ("how do you know the change caused the improvement?") | ✓ | ✗ — recovery only |
| Metric definition ("what exactly do you mean by retention?") | ✓ | ✗ — recovery only |
| Revenue impact ("roughly, what's the business impact?") | ✓ | ✗ |
| Prioritization ("10 ideas, 2 can ship — how do you decide?") | ✓ | ✗ |
| Implementation fidelity ("what did you build?") | ✗ weak | ✓ strong |
| Experiment contamination ("simultaneous AB test attribution") | ✗ | ✓ |
| Technical boundary probing | ✗ | ✓ strong |

For a Product Analyst, the top five rows are the primary signal. Antigravity covers none in the main flow. The GPT interview felt more relevant to Apparao because it was aiming at the right target, even with unanchored, generic questions. Antigravity has better question quality but wrong question direction.

The ideal is Antigravity's precision applied to GPT's target layer: causal validity / metric definition / business reasoning questions, anchored to Apparao's specific experiments and numbers.

---

### Failure 3: The Opener Fires at the Wrong Interview Phase

**The opener selected:**
> *"For Daily Mantra's session flow events, what was the first event you defined and why that one first?"*

**Direct candidate feedback from Apparao:**
> *"That is a really silly question. How would I even remember the first event I defined? That is extremely irrelevant. That is a really bad way of asking questions."*

**Three compounding problems in one question:**

**A — Chronological memory test, not a knowledge test.**
"What was the *first* event" demands temporal recall of a specific moment that doesn't meaningfully exist in anyone's memory. Nobody remembers what they built first in an implementation context — they remember *why* they prioritized one thing over another. "What was the first event" tests memory. "How did you decide what to instrument first" tests judgment. Only the second has signal.

**B — Phase mismatch.**
This is a Turn 4a question (mechanism probe, after the candidate has narrated the system in their own words) delivered as Turn 1 (cold, before any context is established). In the redesign:
- Turn 1: warm intro — who you are, what you've been up to
- Turn 2: narrative — tell me more about that work, what were you building
- Turn 3: surface + ownership — walk me through how it worked, what was your part
- Turn 4a: mechanism — what did you actually write to make that work

The opener lands in Turn 4 territory. The candidate hasn't narrated anything yet. Delivered cold, it sounds like an interrogation, not a conversation.

**C — Direct consequence of wrong anchor.**
If the anchor had been the retention experiment, the opener would be: *"Walk me through the A/B test you ran for the Video feature — what were you actually testing and what was your hypothesis?"* — warm, narrative, phase-appropriate, and aimed at the right signal. The infrastructure anchor produced an infrastructure opener.

---

### Failure 4: The Most Important Bullets Never Became Primary Questions

**The trial-to-subscription bullet never surfaced as a primary probe.**

Bullet 2: *"Optimized trial-to-subscription conversion rate from 27% to 42% by reducing trial period from 7 days to 1 day, significantly reducing cancellation rates and accelerating user commitment."*

Apparao confirmed this never appeared as a primary dimension. It exists in the map as one sub-dimension of `trial_conversion_instrumentation`, framed as: *"Which events did you track to measure conversion from trial start to paid subscription?"* — an instrumentation question.

What's actually rich about this claim:
- **The business reasoning**: why would a *shorter* trial increase conversion? That's counterintuitive — it implies the hypothesis was "urgency drives commitment, not access." That reasoning is testable.
- **The measurement problem**: the trial window itself changed (7 days → 1 day). Measuring conversion rate when the denominator's time window changes requires cohort redefinition — a non-trivial analytical problem.
- **The causal question**: was this a clean A/B test? You can't A/B test trial duration without running two simultaneous product variants — how was causality established?

The map buried this in instrumentation framing. The real questions were never asked.

**The retention metric_risk question was buried in recovery.**

> *"That retention number — 25% to 42% — how was retention defined, over what time window, and what was the denominator you measured against?"*

This is the most important question for a PA role. It lives in the `recovery` overlay, which only fires when the candidate underperforms on other dimensions. Confident wrong answers — a candidate who gives fluent implementation answers while never questioning their metric definition — never trigger it.

For a PA role, metric definition is a core question, not a contingency. It should fire regardless of candidate fluency. The distinction between "I measured Day-7 retention on new installs who completed at least one session in the first 24 hours" and "I just looked at the Mixpanel retention chart" is exactly what this question surfaces — and it should always be asked.

---

### Failure 5: Uniform Question Weighting — Good Questions Become Outliers

No question in the map carries a `signal_weight`. All five dimensions per focus area are enumerated identically. The orchestrator pulls from this flat list with no priority mechanism.

**The problem in practice:** Several genuinely strong questions were generated:
- *"If a user qualified for both the Video and Today experiments simultaneously, how did your infrastructure handle variant assignment and attribution?"* — requires genuine A/B engineering knowledge, can't be faked
- *"When the trial period changed from 7 to 1 day, how did you handle cohort definitions so early-trial and late-trial users weren't mixed in the same conversion window?"* — requires having actually instrumented this specific change

These questions are 10x more signal-rich than *"How did you categorize events across session flow, engagement, and conversion in Daily Mantra's schema?"* — which any Mixpanel tutorial reader can answer. But the system treats them identically.

**The result:** When the majority of questions are the wrong type (implementation-depth for an analytical-reasoning role), the few genuinely good questions become statistical outliers swamped by volume. The diamonds exist in the map — they are invisible because nothing marks them as diamonds.

---

### Failure 6: Pass_1 Review Is a Dead Loop — Critique Without Repair

**What pass_1 correctly identified:**
1. CV opener is compound — lets weak candidates deflect to the easier half. Provided exact fix: *"On your 400-frame highway dataset, which of the three methods produced the most ID-switch errors — and what in the footage caused that?"*
2. AppsFlyer opener too generic. Provided exact fix: anchor it to the three-team collision risk.
3. Daily Mantra has 5 dimensions, 3-4 would suffice — provided merge instruction.
4. CV metric_risk too vague — provided specific replacement.

**What the final map contained:**
CV opener: *"When you benchmarked blob tracking against optical flow on the 400 highway frames, which method produced higher error rates and why?"* — still compound. Identical to what was flagged.

Zero of four repair instructions were applied.

**The mechanism of the failure:** `repair_instructions` are stored as JSON commentary in the map output. Nothing reads them back as generative input. The second pass generates critique and repair guidance — but there is no third step that takes those instructions, re-prompts the model on the specific flagged fields, and writes corrected output back. The loop is open.

**Required fix:** After pass_1 generates `repair_instructions`, a targeted repair step re-generates only the named fields using the repair instruction as a direct prompt addition. Each instruction gets a `repair_applied: bool` flag. A map with `repair_applied: false` on any instruction does not ship with `map_status: "ready"`.

---

### Failure 7: Focus Area Budget Misallocated — CV Gets Equal Billing as Current Role

Three focus areas, five dimensions each, equal question budget:

| Focus Area | Actual experience | Budget received |
|------------|------------------|-----------------|
| Daily Mantra Analytics Infrastructure | Current role, 5 months, primary claims, current employer | 5 dimensions |
| AppsFlyer Stack | Previous title at same company, 6 months | 5 dimensions |
| Computer Vision Benchmarking | 2-month summer internship, academic paper, zero continuity to current role | 5 dimensions |

A 2-month summer internship that produced one paper at CoMSO 2024 (a small niche conference) receives identical question depth as the candidate's current job. A real interviewer gives the CV internship 2-3 questions as an attention check — enough to confirm the work was real, not enough to spend interview time on someone's summer project from a career they've already moved away from.

**The correct budget allocation:**
- Current role (Daily Mantra): 60%+ of question budget
- Adjacent context, same employer (AppsFlyer): 20-25% — worth verifying but not the focus
- Academic internship with no career continuity (Computer Vision): 10-15% attention check, 2-3 questions maximum

**The bridge direction is also backward.** The map bridges from AppsFlyer → Computer Vision, moving backward in time and relevance. The correct sequence: Daily Mantra (primary) → AppsFlyer (brief adjacent context, same company) → Computer Vision only if time remains.

---

### Direct Candidate Feedback — Apparao (Session 98c80520)

These are the candidate's own words, captured from post-session discussion:

> *"That is a really silly question. How would I even remember the first event I defined? That is extremely irrelevant. That is a really bad way of asking questions."*
> — On the opener: "For Daily Mantra's session flow events, what was the first event you defined and why that one first?"

> *"Questions regarding retention would have had more importance. The trial-to-subscription point and the Mantra Track End point — those three were the most important three points."*
> — On which bullets deserved primary focus (bullets 1, 2, 3)

> *"It captured the fourth point [analytics infrastructure] and even if you look at the anchor — it was the wrong kind of anchor."*
> — On anchor selection failure

> *"When you choose the wrong anchor, you tend to split a lot of questions based on that anchor. So the anchor itself was wrong."*
> — On the cascade from wrong anchor

> *"[Trial-to-subscription bullet] never got introduced."*
> — On the missing bullet — the second most important claim on the resume never appeared as a primary question

> The interview did not feel like a real interview.

---

### Correct Anchor Logic — What Should Happen

```
Step 1:  Extract all quantified outcome claims from the resume
         (claims with numbers, percentages, measurable results)

Step 2:  Filter by role relevance
         PA/PM roles:  A/B testing outcomes, retention/conversion/funnel metrics → highest priority
         Engineering:  implementation claims, system design, scalability claims → highest priority
         Data Science: model evaluation, statistical results, research outcomes → highest priority

Step 3:  Score each claim by analytical reasoning surface area
         Not: how impressive is the number?
         Yes: how many decisions, hypotheses, validations, and reasoning steps does this claim imply?
         High score: "retention improved via multi-feature A/B testing" (hypothesis, experiment design,
                      variant attribution, causal interpretation, business impact)
         Low score:  "architected analytics event tracking" (one thing — did you build it?)

Step 4:  Primary anchor = highest-scoring outcome claim
         Implementation claims become sub-branches of the outcome anchor, not the center

Step 5:  All downstream generation derives from the anchor
         Opener: warm + narrative, anchored to the outcome ("walk me through that experiment")
         Core dimensions: probe the analytical reasoning behind the outcome
         metric_risk and causal_validity: main flow, not recovery
         Infrastructure claim: sub-branch of experiment dimensions, not a focus area
```

---

### What the Map Generation Layer Needs

These are the specific intervention points, mapped to implementation targets:

| Fix | Target | Description |
|-----|--------|-------------|
| Role-type input | `interview_map.py` generation prompt | `role_type` as first-class param; changes what "depth" means in all downstream generation |
| Anchor selection rewrite | `_select_focus_anchor()` | PA/PM: outcome claims ranked above implementation claims; score by analytical reasoning surface area |
| Outcome-to-question mapping | `_generate_dimensions()` | For PA roles: generates causal validity, metric definition, business reasoning questions as core dimensions |
| Phase-tagged openers | `_generate_opener()` | Openers are Turn-2-compatible (warm, narrative, ownership-establishing); mechanism questions cannot be openers |
| Metric_risk promotion | `_generate_dimensions()` | For any role with metric claims: metric_definition and causal_validity are core dimensions, not recovery |
| signal_weight per dimension | Dimension schema + orchestrator | Each dimension rated 1.0–3.0; orchestrator surfaces highest-weight first; report marks signal tier |
| Pass_1 repair closure | `_apply_pass1_repairs()` | New function: re-generates flagged fields using repair_instructions as direct prompt input; sets `repair_applied` per instruction; blocks `map_status: ready` if repairs unapplied |
| Focus budget allocation | `_allocate_focus_budget()` | Current role ≥60%; same-employer previous title 20-25%; discontinued domain/short internship ≤15% attention-check |
| Bridge direction fix | `recovery.bridge` generation | Bridge moves forward in time and role relevance, never backward toward older/less relevant experience |

---

---

## 13. Surgical Implementation Guide — Code-Level Findings

> **Source:** Full read of `orchestrator.py` (3273 lines), `interview_map.py` (3221 lines), `followup_agent.py` (982 lines), `evaluation_agent.py` (304 lines), `session_manager.py` (30 lines).
> Every change below specifies the exact file, function, line range, and diff. Nothing is speculative.

---

### What the System Actually Is (Architecture Facts)

**Two-track architecture:**
- `handle_transcript()` — **fast path**, returns in 300–500ms. Serves from pre-staged answers: prepped_next_question → speculative_cache → sprint fallback template. No LLM calls on the critical path.
- `_run_background_pipeline()` — **full reasoning pipeline**, runs during the candidate's answer. Runs all agents in parallel (ConceptAgent, WeaknessAgent, DiscrepancyAgent, ReasoningBehaviorAgent), then runs FollowUpAgent to generate the next question. Output is staged in `prepped_next_*` fields, consumed at the START of the next `handle_transcript()` call.

**State dict in Redis (flat JSON):**
All session state is a single flat dict stored in Redis via `SessionManager.save_state()`. There is no schema validation — fields are added by convention. `CandidateState` slots in as a nested dict under key `"candidate_state"`.

**Route types (what drives question selection):**
```
attack_probe          → followup_agent.generate() — adversarial, highest severity weakness
clarification_fast    → followup_agent.generate_clarification() — ambiguous answers
discrepancy_challenge → followup_agent.generate_discrepancy_challenge() — confirmed conflict
bank_followup_fast    → followup_agent.adapt_followup() — pre-queued follow-up from packet
sprint_seed           → followup_agent.generate_sprint_question() — general topic advance
trajectory_map_*      → select_from_trajectory_map_detailed() — map-prepped question
speculative_fast      → generate_speculative() — partial-transcript entity trigger
```

**How the interview map feeds into questions:**
`select_from_trajectory_map_detailed()` (called from both fast path and background pipeline) consults the trajectory map for the current `focus_key` and returns a map-prepped question if one fits. The map questions have priority over generic sprint_seed questions but not over discrepancy/clarification routes.

**Sprint structure:**
```
Sprint 1: "Project Defense"   — persona: curious_lead
Sprint 2: "Foundations"       — persona: socratic_mentor
Sprint 3: "System Design"     — persona: senior_peer
5 questions per sprint. QUESTIONS_PER_SPRINT = 5.
```

---

### Critical Finding: `target_role` Is Never Passed to Map Generation

`target_role` is stored in session state (line 771) and passed to: `WeaknessAgent`, `EvaluationAgent`, `ResumeAgent`.

It is **NOT** passed to `generate_interview_map()`. The call at line 2811-2814:
```python
interview_map = await asyncio.wait_for(
    generate_interview_map(
        resume=resume,
        session_id=session_id,    # ← target_role missing here
    ),
    ...
)
```
`generate_interview_map()` signature (line 2327-2330) accepts only `resume` and `session_id`. Role type is available in session state at call time — it just isn't threaded through. This is the single root cause of role-blindness in map generation.

---

### Critical Finding: The Repair Loop Only Fires When Score < 7.0

The two-pass repair loop (line 2370):
```python
if not _review_is_ready(pass_one_review):
    # regenerate tracks with critic_feedback injected
```

`_review_is_ready()` returns True when `overall_score >= _MAP_MIN_READY_SCORE` (= 7.0) OR `review["ready"] == True`.

The Apparao map: `overall_score: 7.6`, `ready: true`. Result: repair path skipped entirely. The four repair_instructions were stored as JSON commentary, never fed back as generation input.

**When the repair path DOES run:** `_generate_priority_tracks_for_candidate()` (called in repair) passes `critic_feedback=pass_one_review` to each track generation. `_critic_guidance_for_focus()` (line 2150) extracts `repair_instructions` + focus-specific `issues` from the review and injects them as `repair_guidance` into `_TRACK_USER_TEMPLATE`. So the repair mechanism works correctly when triggered — it's only the trigger threshold that's wrong.

---

### Critical Finding: Opener Rules Prohibit the Right Pattern

`_TRACK_SYSTEM` (line 197-202):
```
Opener rules:
- Reference the single most specific artifact or technology named in the resume snippets
- Pick one end of the problem as a starting hypothesis — do not ask about everything at once
- Must be consistent with dimensions[0]: the opener enters that dimension
- Max 24 words. No "walk me through" or "tell me about" — those invite monologue
```

"No walk me through" is the rule that produces cold mechanism questions. The redesign wants warm, narrative-inviting openers for Phase 1. The current rule explicitly prohibits the pattern we want.

Additionally, "what was the first event you defined" is the direct result of the "specific artifact/technology" + "one end of the problem as starting hypothesis" rule applied to an infrastructure anchor. The rule is working as designed — the design is wrong for a PA role.

---

### Critical Finding: Anti-Tunneling Is Too Narrow

Current topic guard (lines 2387-2396):
```python
repeated_focus = (
    same_focus_recent >= 2      # last 3 turns on same topic
    and not discrepancy_conflict
    and isinstance(weakness, dict)
    and weakness.get("severity") == "high"
    and not substantive_recovery
)
```

This only fires when: 2 of last 3 turns on same topic AND high severity weakness AND no recovery. Requiring high severity means topic tunneling doesn't fire on weaker but persistent probing. The 13/15 Veo-3 questions could easily pass this check if the weakness severity varied.

There is **no total ratio check** — `same_focus_history / total_history > 0.55` doesn't exist anywhere in the codebase.

---

### Critical Finding: Skip Detection Doesn't Exist

`_ADMISSION_SIGNALS` regex (lines 83-90) detects honest gaps ("I don't know", "I didn't build"). There is no regex for meta-language skip requests ("skip", "next question", "move on", "different topic").

In session e5170a7a: candidate said "skip" and "move on" 6 times. None of these triggered any routing change because they were processed as technical answers, scored as deflections, and the deflection budget was exhausted after 2 per topic.

---

### Critical Finding: Q1 Warmth Is Real, Q2 Can Be Cold

`SPRINT_OPENERS[1]` (line 534):
```python
"Welcome to the interview — I'm really glad you're here. To start on a lighter note, let's ease in with something you know really well."
```
The first utterance IS warm. This is not the bug.

The bug: the background pipeline processes the candidate's first answer and can route to `attack_probe` if a high-severity weakness is detected (line 2451-2458). There is no turn_number guard. Turn 2 (the response to the candidate's first answer) can be an adversarial mechanism probe. This is the preamble/route mismatch.

---

### Critical Finding: EvaluationAgent Already Has INSUFFICIENT_DATA

`FULL_INTERVIEW_PROMPT` (line 29-81) already includes:
- `INSUFFICIENT_DATA` as a verdict option ✓
- `untested_dimensions` field ✓
- `claim_credibility_risk` with separate scoring ✓
- `coverage_note` injected when weakness types are homogeneous ✓

The evaluation layer is closer to the redesign than expected. What's missing: Coverage Portrait format and `CandidateState` feeding disengagement signals into the verdict.

---

## Exact Surgical Changes

### Group A — Map Generation (P0, `interview_map.py`)

---

**A1. Pass `target_role` through the entire map generation stack**

All three prompts need `target_role` threaded through.

**File: `backend/services/orchestrator.py`**
**Line: 2811–2814**

```python
# BEFORE
generate_interview_map(
    resume=resume,
    session_id=session_id,
)

# AFTER
generate_interview_map(
    resume=resume,
    session_id=session_id,
    target_role=state.get("target_role", ""),
)
```

**File: `backend/services/interview_map.py`**
**Line: 2327–2330** — add `target_role` parameter:
```python
# BEFORE
async def generate_interview_map(
    *,
    resume: str,
    session_id: str = "",
) -> dict:

# AFTER
async def generate_interview_map(
    *,
    resume: str,
    session_id: str = "",
    target_role: str = "",
) -> dict:
```

Thread `target_role` through to `_generate_focus_area_plan()` and `_generate_priority_tracks_for_candidate()`.

**Risk:** Zero. `target_role` defaults to `""`. Existing behavior unchanged when empty.

---

**A2. Role-type anchor selection in `_focus_plan_user_prompt()`**

**File: `backend/services/interview_map.py`**
**Function: `_focus_plan_user_prompt()`** (line 988)
**Change:** Add `target_role: str = ""` parameter. Inject a role-conditional ranking block into the rules section.

```python
def _focus_plan_user_prompt(*, resume: str, dedup_hint: str = "", target_role: str = "") -> str:
    lines = [
        "Resume (full text):",
        resume,
        "",
    ]

    # Role-type anchor override — injected before core ranking rules
    role_lower = target_role.lower()
    is_analyst_role = any(t in role_lower for t in (
        "product analyst", "product manager", "growth analyst",
        "data analyst", "analytics", "pm ", "apm",
    ))
    if is_analyst_role:
        lines.extend([
            f"ROLE CONTEXT: This is a {target_role} role.",
            "ANCHOR SELECTION OVERRIDE FOR ANALYTICS/PM ROLES:",
            "- The highest-priority anchor is the OUTCOME claim with the richest experimental and analytical reasoning surface area.",
            "- A bullet claiming '25% → 42% retention via A/B testing' OUTRANKS 'architected analytics infrastructure'",
            "  because the outcome claim implies: hypothesis formation, experiment design, causal attribution, and measurement validity.",
            "- Implementation and infrastructure claims become sub-dimensions of the outcome they enabled — not separate focus areas.",
            "- Quantified outcome claims with A/B testing, conversion optimization, or funnel analysis are always anchor[0].",
            "",
        ])

    lines.extend([
        "Return ONLY JSON with this schema:",
        # ... rest of schema
    ])
    # ... rest of function
```

**Risk:** Only fires when `target_role` contains analyst/PM keywords. All other role types use existing behavior. Add test for edge case where `target_role = ""`.

---

**A3. Role-type depth instruction in `_TRACK_SYSTEM` and `_TRACK_USER_TEMPLATE`**

The track system prompt is a module-level constant. It needs to become a function that conditionally injects depth instructions.

**File: `backend/services/interview_map.py`**
**Lines: 188–265** — convert `_TRACK_SYSTEM` from a constant to a function:

```python
def _track_system_prompt(role_type: str = "") -> str:
    role_lower = role_type.lower()
    is_analyst_role = any(t in role_lower for t in (
        "product analyst", "product manager", "growth analyst",
        "data analyst", "analytics",
    ))

    base = """You are an expert technical interviewer designing a precision interview track for one specific resume focus area.

Your goal: write questions that find where a candidate's knowledge actually ends — not what vocabulary they know, but what they can explain from genuine hands-on experience."""

    if is_analyst_role:
        depth_instruction = """

ROLE-TYPE OVERRIDE — PRODUCT ANALYST / PM ROLE:
For this role, "depth" means analytical reasoning quality, not implementation fidelity.

Opener rules (OVERRIDE for analyst roles):
- Opener must be warm, narrative-inviting, anchored to the outcome claim.
- Pattern: "Walk me through [the experiment / the analysis] — what were you actually testing and why?"
- Avoid questions asking what was built first, what events were defined first, or implementation chronology.
- The opener should invite the candidate to narrate the work in their own words.

Mandatory dimensions for analyst roles — include at least one of each:
1. METRIC VALIDITY dimension: probe how the key metric was defined, what the denominator was, over what time window, what cohort. Example boundary: "That 25→42% retention — Day-7 on new installs, or something else? What was in the denominator?"
2. CAUSAL REASONING dimension: probe whether the candidate understands why the result happened, not just that it did. Example boundary: "How do you know the trial change caused the conversion improvement — what rules out organic growth or seasonality?"
3. EXPERIMENT DESIGN dimension (if A/B testing claimed): probe variant assignment, contamination, and result interpretation. Example boundary: "If a user qualified for both the Video and Today experiments simultaneously, what happened to variant attribution?"

Boundary probe definition for analyst roles:
- NOT "what breaks at scale" — that's an engineering question
- YES "what would make this result wrong, unmeasurable, or uninterpretable" — that's an analyst question
"""
    else:
        depth_instruction = """

Opener rules:
- Reference the single most specific artifact or technology named in the resume snippets
- Pick one end of the problem as a starting hypothesis — do not ask about everything at once
- Must be consistent with dimensions[0]: the opener enters that dimension
- Max 24 words. No "walk me through" or "tell me about" — those invite monologue
- The answer should be answerable at different depths: shallowness reveals itself quickly
"""

    remainder = """
Dimension rules (generate 4–6, each grounded in actual resume evidence):
- surface: confirms the concept exists in their experience
- mechanism: tests whether they understand WHY it works
- boundary: designed to be unanswerable if they only read documentation or didn't personally own this
...
[rest of existing _TRACK_SYSTEM content]
"""
    return base + depth_instruction + remainder
```

**Usage:** Anywhere `_TRACK_SYSTEM` is currently referenced, replace with `_track_system_prompt(role_type=target_role)`.

**Risk:** Medium. Need to carefully thread `target_role` through `_generate_focus_track()` → `_TRACK_USER_TEMPLATE` call chain. The constant being used in two LLM calls — check both. Add `role_type: str = ""` to `_generate_focus_track()`.

---

**A4. Fix the repair loop trigger — fire on explicit opener issues even when score ≥ 7.0**

**File: `backend/services/interview_map.py`**
**Lines: 2370** — add helper and change gate:

```python
def _has_targeted_repairs(review: dict | None) -> bool:
    """True when the critic identified specific fixable issues, even if overall score is ready."""
    if not isinstance(review, dict):
        return False
    # 2+ repair instructions = targeted problems worth fixing
    if len(review.get("repair_instructions") or []) >= 2:
        return True
    # Any focus area has an explicit opener_issue
    for fr in (review.get("focus_reviews") or []):
        if isinstance(fr, dict) and fr.get("opener_issue"):
            return True
    return False

# Line 2370 — change from:
if not _review_is_ready(pass_one_review):

# To:
if not _review_is_ready(pass_one_review) or _has_targeted_repairs(pass_one_review):
```

**Why this is safe:** The repair path regenerates tracks WITH the critic feedback as guidance. If the repaired tracks score lower, the original is kept (line 2408: `if _review_score(repaired_review) >= _review_score(pass_one_review)`). So this is a no-regression change — worst case it re-generates and keeps the original.

**Risk:** Low. Adds one extra LLM generation call when `_has_targeted_repairs()` is True. Slightly increases map prep latency for maps with explicit repair needs. This is intentional.

---

**A5. Focus area budget allocation — add to `_FOCUS_PLAN_SYSTEM`**

**File: `backend/services/interview_map.py`**
**Lines: 896–925** — append to `_FOCUS_PLAN_SYSTEM`:

```python
_FOCUS_PLAN_SYSTEM = """...(existing content)...

BUDGET ALLOCATION SIGNALS (used by question routing, not your output):
- area[0] will receive approximately 60% of interview time — select the single most analytically rich experience
- area[1] receives approximately 20-25%
- area[2]+ receive attention-check level coverage — 2-3 questions each
- If the resume contains an academic internship of ≤3 months with no continuity to current career path, include it as area[2] at most — do not elevate it above current-role work
- A 2-month summer internship should NOT share equal slot weight with a 12-month current role

JSON only, no markdown, no commentary."""
```

**Risk:** Zero. This adds documentation-level context to the prompt. It changes what the LLM is told about downstream use, which shapes selection priorities without changing the JSON schema.

---

**A6. Add `signal_weight` to dimension schema**

**File: `backend/services/interview_map.py`**
**Lines: 235–256 (`_TRACK_USER_TEMPLATE` dimension schema)**

Add `signal_weight` field to dimension output schema:
```python
    {{
      "id": "snake_case_dimension_id",
      "label": "short dimension label",
      "resume_anchor": "exact or near-exact resume claim this dimension probes",
      "surface": "question confirming basic familiarity",
      "mechanism": "question requiring genuine implementation understanding",
      "boundary": "question unanswerable without real hands-on ownership",
      "signal_weight": 1.0
    }}
```

Add to `_TRACK_SYSTEM` dimension rules:
```
- signal_weight: float 1.0–3.0. Rate each dimension by how much it reveals about role fitness.
  For analyst roles: metric_validity = 3.0, causal_reasoning = 3.0, experiment_design = 2.5, implementation_details = 1.5
  For engineering roles: boundary probes on core claimed system = 3.0, secondary tools = 1.5
```

**In `select_from_trajectory_map_detailed()`**: add weight-based sorting so highest signal_weight dimensions surface first when multiple dimensions are available for a focus area.

**Risk:** Medium. `signal_weight` is a new field — need to handle missing values gracefully in `_coerce_llm_track()` with a default of `1.0`. The selection function changes affect ordering but not correctness.

---

### Group B — Orchestrator (P0, `orchestrator.py`)

---

**B1. Add skip signal detection in fast path**

**File: `backend/services/orchestrator.py`**
**Insert after line 90** (after `_ADMISSION_SIGNALS`):

```python
_SKIP_SIGNALS = re.compile(
    r"\b(skip|next question|move on|move to something|different topic|"
    r"another topic|something else|can we move|let'?s move|"
    r"change the topic|switch topics|i'?m good|don'?t worry about)\b",
    re.IGNORECASE,
)

def _looks_like_skip_request(text: str) -> bool:
    return bool(_SKIP_SIGNALS.search(text))
```

**File: `backend/services/orchestrator.py`**
**In `handle_transcript()`, after the echo guard (line ~1301):**

```python
# Skip signal detection — update candidate_state before consuming staged analysis
if _looks_like_skip_request(text):
    candidate_state = state.get("candidate_state", {})
    candidate_state["explicit_skip_count"] = candidate_state.get("explicit_skip_count", 0) + 1
    candidate_state["disengagement_level"] = candidate_state.get("disengagement_level", 0.0) + 2.0
    state["candidate_state"] = candidate_state
    # Force topic rotation for the prepped question
    state["_force_focus_rotation"] = True
```

**In `_run_background_pipeline()`, after force_sprint_question flags (line ~2396):**
```python
if state.get("_force_focus_rotation"):
    force_sprint_question = True
    pivoting = True
    state.pop("_force_focus_rotation", None)  # consume the flag
```

**Risk:** Low. The regex is conservative — "i'm good" is context-dependent, but combined with the `+2.0` disengagement rather than immediate route change, false positives are recoverable. Tune the regex based on live session data.

---

**B2. Add topic fatigue ratio check**

**File: `backend/services/orchestrator.py`**
**In `_run_background_pipeline()`, after line 2352** (after `same_focus_history` is computed):

```python
# Topic fatigue ratio — prevents cumulative tunneling that bypasses recent-turn check
total_history_turns = len(history)
focus_ratio = (
    len(same_focus_history) / total_history_turns
    if total_history_turns >= 5 else 0.0
)
topic_ratio_exceeded = focus_ratio > 0.55
if topic_ratio_exceeded:
    force_sprint_question = True
    pivoting = True
    await self._trace(
        session_id, "topic_fatigue_ratio_exceeded",
        turn_id=turn_id,
        focus_key=current_focus_key,
        focus_ratio=round(focus_ratio, 2),
        total_turns=total_history_turns,
    )
```

**Risk:** Low. Only fires when focus_ratio > 0.55 with ≥5 turns on record. Does not affect early sessions. The `force_sprint_question = True` path already exists and is well-tested — this is just a new trigger for an existing mechanism.

---

**B3. Warm guard — no attack_probe on turns 0 or 1**

**File: `backend/services/orchestrator.py`**
**In `_run_background_pipeline()`, change the `aggressive_probe` condition** (line ~2410):

```python
# BEFORE
aggressive_probe = (
    isinstance(weakness, dict)
    and weakness.get("severity") == "high"
    and weakness.get("attack_strategy") not in ("clarification", "ownership_probe")
)

# AFTER
aggressive_probe = (
    isinstance(weakness, dict)
    and weakness.get("severity") == "high"
    and weakness.get("attack_strategy") not in ("clarification", "ownership_probe")
    and turn_number >= 2   # no adversarial probing on the first two turns
)
```

**Risk:** Low. Only affects `turn_number < 2`. Sprint 1 question 1 (Turn 0) and Turn 1 are now protected from attack_probe. Both will fall through to `sprint_seed` → `generate_sprint_question()` instead — which is the correct behavior (warm, narrative).

---

**B4. Add `candidate_state` to `_build_initial_state()`**

**File: `backend/services/orchestrator.py`**
**In `_build_initial_state()` return dict** (line ~755), add:

```python
"candidate_state": {
    "disengagement_level": 0.0,
    "consecutive_no_content": 0,
    "explicit_skip_count": 0,
    "social_deflection_count": 0,
    "incoherence_count": 0,
    "communication_mode": "normal",   # "normal" | "simplified" | "narrative_only"
    "topic_fatigue": {},               # {focus_key: question_count}
    "forced_exit_triggered": False,
    "phase": "orientation",
},
```

**Risk:** Zero. New field in the state dict. Existing code doesn't read `candidate_state` so there are no regressions.

---

### Group C — FollowUpAgent (P1, `followup_agent.py`)

---

**C1. No PERSONA_PROMPTS changes needed for P0**

The three personas (`curious_lead`, `socratic_mentor`, `senior_peer`) are correctly warm and non-adversarial in their phrasing. The warmth problem is in the route selection (B3), not in the persona prompts themselves.

What IS needed for P1: add `communication_mode` support. When `state["candidate_state"]["communication_mode"] == "simplified"`, pass a prompt addition to all `generate_*` calls: "Use maximum one sentence per question. Prefer 'Tell me about X' framing. Avoid compound questions."

**C2. Sprint goal alignment for analyst roles (P1)**

`SPRINT_GOALS` (line 329) are hardcoded engineering goals. For analyst roles, Sprint 1 should be about outcomes and experiments, not "most significant project — the problem it solved." Add role-type conditioning analogous to A2/A3.

---

### Group D — EvaluationAgent (P1, `evaluation_agent.py`)

---

**D1. `INSUFFICIENT_DATA` already exists** — no change needed on the verdict tier.

**D2. Add Coverage Portrait to `FULL_INTERVIEW_PROMPT`**

`FULL_INTERVIEW_PROMPT` (line 29) currently returns a dict without a `coverage_portrait` field. After `CandidateState` and `AnswerCoverageMap` are built (P2), extend the prompt to include coverage_score and domain_coverage as additional output fields.

**D3. Per-answer scoring for analyst roles (P1)**

`PER_ANSWER_PROMPT` (line 5) scores on: problem_framing, logical_reasoning, technical_correctness, production_awareness. For analyst roles, replace `technical_correctness` with `measurement_validity` (does the metric definition hold up?) and `production_awareness` with `business_impact_awareness`. These are the same positions in the rubric — just re-labeled and re-defined for the role.

---

### Group E — `SessionManager` (P1, `session_manager.py`)

No changes needed. The flat Redis dict is sufficient for `candidate_state` as a nested dict. The 30-line SessionManager is clean and correct.

---

### Change Dependency Graph

```
A1 (pass target_role to map) → A2 (role-aware anchor) → A3 (role-aware track depth)
A4 (repair loop fix) — independent of A1-A3, can ship alone
A5 (budget allocation) — independent, can ship alone
A6 (signal_weight) — depends on A3 (track generation must emit it)

B1 (skip detection) — independent
B2 (fatigue ratio) — independent
B3 (warm guard) — independent
B4 (candidate_state in state) → B1 (skip detection writes to it) → future P1 disengagement thresholds

A1 is the prerequisite for A2 and A3.
B4 is the prerequisite for all CandidateState work in P1.
Everything else is independent and can ship in any order.
```

**Safe shipping order for P0:**
1. B3 (warm guard) — 2 lines, zero risk, immediate improvement
2. B1 + B2 + B4 (skip + fatigue + candidate_state init) — one coherent diff, minimal risk
3. A4 (repair loop fix) — standalone, low risk
4. A1 + A2 + A5 (target_role threading + anchor override + budget) — one map-generation PR
5. A3 + A6 (track system prompt + signal_weight) — depends on A1 being merged

---

### What Does NOT Need to Change for P0

| Component | Current state | Verdict |
|-----------|--------------|---------|
| Two-track architecture | Working correctly | Keep |
| `select_from_trajectory_map_detailed()` | Works correctly | Keep — add weight ordering in P1 |
| Discrepancy detection | Working signal | Keep as background signal |
| Sprint/persona structure | Well-designed | Keep |
| `PERSONA_PROMPTS` content | Correctly warm | Keep for P0 |
| `EvaluationAgent.score_full_interview()` | Already has INSUFFICIENT_DATA, untested_dimensions, coverage_note | Keep, extend in P2 |
| `SessionManager` | Clean | No changes |
| Redis session management | Working | No changes |
| ProvenHire integration | Untouched by all changes | No changes |
| `SPRINT_OPENERS[1]` | Already warm | Keep |

---

*This document is the development contract. Every P0-P3 item maps to a specific problem identified in the session data or a specific design decision made in the boardroom discussion. Nothing here is speculative — every change is grounded in observed failure or reasoned trade-off.*

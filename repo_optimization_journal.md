# Repo Optimization Journal

Date started: 2026-04-17

This file is the long-form companion to `bug audit.md`.

`bug audit.md` is the defect register.
This journal is the deeper mentor-style walkthrough: what each agent/component is trying to do, how the code translates into behavior, what it is doing well, what it is getting wrong, and what its best version should look like.

## Review Method

For each agent or subsystem, we will keep the same lens:

1. Mission: what job this code is supposed to do in the live product.
2. Line-by-line walkthrough: what each block of code translates to functionally and architecturally.
3. Strengths: what is already good and worth preserving.
4. Failure modes: where it breaks, drifts, or leaves capability on the table.
5. Optimality path: how to evolve it into the best version of itself without breaking adjacent systems.
6. Cross-agent fit: how it cooperates with the other agents and the orchestrator.

---

## Agent 1: `WeaknessAgent`

Primary file:
- `backend/agents/weakness_agent.py`

Main integration points:
- `backend/services/orchestrator.py:1531-1778`
- `backend/agents/followup_agent.py:332-437`
- `backend/models/llm_router.py:1-58`

### Mission

`WeaknessAgent` is the system's "diagnosis" agent.
Its real job is not merely to say "this answer is weak." Its job is to convert a candidate answer into the most useful next adversarial move.

That means it is doing three things at once:

- classifying the main gap in the answer
- estimating how severe that gap is for the current sprint and candidate level
- suggesting the best probing route for the next turn

Architecturally, this means `WeaknessAgent` is not the whole interrogation brain.
It is a compact judgment module whose output is later merged with:

- `DiscrepancyAgent` for resume/claim conflicts
- `ReasoningBehaviorAgent` for adaptability / honesty signals
- `FollowUpAgent` for turning diagnosis into the next question
- `Orchestrator` for final route arbitration, breadth control, and pivoting

The important mental model is:

`WeaknessAgent` decides "what is wrong here?"
`Orchestrator` decides "do we press this now or pivot?"
`FollowUpAgent` decides "what exact question should that become?"

### Full File Walkthrough

#### `backend/agents/weakness_agent.py:1`

`from backend.models.llm_router import LLMRouter`

Functional meaning:
- The agent does not talk to the model provider directly.
- It delegates model selection and JSON parsing behavior to the shared router.

Architectural meaning:
- This keeps model choice centralized and lets the agent stay focused on judgment logic.
- It also means the agent inherits the router's strengths and weaknesses, especially its loose `dict | str` output contract.

#### `backend/agents/weakness_agent.py:4-48`

This prompt defines the agent's ontology.

Functional meaning:
- It teaches the model the allowed weakness categories.
- It teaches the allowed attack strategies.
- It explains severity levels.
- It explicitly protects intellectual honesty from being punished.
- It asks for strict JSON output.

Architectural meaning:
- This is where most of the agent's behavior actually lives.
- The Python code is thin; the prompt is the real policy layer.
- The rest of the system assumes this ontology is stable and meaningful.

What is good here:
- The weakness taxonomy is small and usable.
- `ambiguous_but_promising` is especially strong because it creates a "clarify before attack" lane instead of forcing false certainty.
- The prompt explicitly encodes role/experience calibration and ownership sensitivity.
- The honesty rule is a strong product choice. It pushes the interview toward truth-seeking instead of cheap gotchas.

What is fragile here:
- The prompt text contains visible mojibake characters like `鈥?` and `鈥攄o`, which means some instructions are partially corrupted before they ever reach the model.
- The schema is described in prose only. There is no enforced validator here.
- The attack-strategy list is doing double duty as both diagnosis and execution policy, which makes the agent partly responsible for downstream follow-up style.

#### `backend/agents/weakness_agent.py:51-56`

Class docstring:

- Calls this the most important agent in the system.
- Says it uses sprint plus previous weaknesses to avoid redundant probing.

Functional meaning:
- The design intent is correct: this agent is supposed to find the precise fault line.

Architectural meaning:
- The docstring slightly overstates autonomy.
- In the live system, the most important behavior is shared between this file and `orchestrator.py`.

Important nuance:
- The "avoid redundant probing" claim is only partially true in implementation.
- The agent sees recent weakness types and severities, but not a rich structured memory of what exact angle was already exhausted.

#### `backend/agents/weakness_agent.py:58-59`

`self.llm = LLMRouter(tier="medium")`

Functional meaning:
- This uses the medium model tier for diagnosis.

Architectural meaning:
- This is a good latency/capability tradeoff.
- Weakness detection matters a lot, but it happens every turn, so using the large tier would likely hurt responsiveness.

What this gets right:
- The agent is important enough to deserve more than the cheap tier.
- It is still cheap enough to run in parallel with discrepancy and reasoning analysis.

#### `backend/agents/weakness_agent.py:61-71`

`detect(...)` signature:

- `question`
- `answer`
- `sprint`
- `prior_weaknesses`
- `memory_context`
- `parsed_resume`
- `target_role`
- `years_experience`

Functional meaning:
- The agent gets the full local context it needs to judge the current answer.

Architectural meaning:
- This is where a hidden truth shows up: the agent is not pure "JSON in, JSON out."
- It directly consumes raw question/answer text plus a stringified memory summary.

Why that matters:
- This is effective for speed and simplicity.
- It also means the implementation has drifted from the documented ideal in `AGENTS.md` that agents should only consume structured outputs from prior agents.

#### `backend/agents/weakness_agent.py:72-78`

Method docstring describes sprint-specific severity calibration.

Functional meaning:
- Sprint 1 is ownership/vagueness.
- Sprint 2 is fundamentals/mechanics.
- Sprint 3 is trade-offs/scale/failure modes.

Architectural meaning:
- This is the correct high-level contract.
- It keeps one weakness taxonomy while letting severity depend on interview phase.

#### `backend/agents/weakness_agent.py:79-83`

`sprint_focus` map.

Functional meaning:
- Converts sprint number into a short instruction string for the model.

Architectural meaning:
- This is a very cheap but effective way to give phase-sensitive judgment without separate prompts.

Limitation:
- The sprint distinctions are broad.
- There is no explicit per-role/per-domain focus map, so the model must infer a lot from free text.

#### `backend/agents/weakness_agent.py:85-90`

`prior_context` uses the last three weaknesses and reduces them to `type(severity)`.

Functional meaning:
- Tells the model what categories were recently probed so it avoids obvious repetition.

Architectural meaning:
- This is a lightweight anti-loop safeguard.

What it does well:
- Cheap token usage.
- Prevents the worst "same label forever" repetition.

What it misses:
- It does not preserve the actual content of the prior probe.
- Two weaknesses can share the same type but target different concepts.
- Two semantically repetitive probes can still look different at the label level and slip through.

#### `backend/agents/weakness_agent.py:91`

`memory_section` wraps the free-form `memory_context`.

Functional meaning:
- Feeds prior facts, prior probes, and recent claims into the prompt.

Architectural meaning:
- This is the main way the agent becomes context-aware across turns.

Risk:
- `memory_context` is unstructured prose assembled upstream, so the agent depends on prompt comprehension rather than deterministic fields.

#### `backend/agents/weakness_agent.py:92-111`

Resume and calibration extraction:

- default empty resume object
- read `experience_tier`
- read top three projects and top two experiences
- compress them into ownership strings
- build `calibration_context`

Functional meaning:
- This is the fairness layer.
- It gives the model signals about whether the candidate claimed leadership, contribution, internship-level ownership, and what role/YOE bar to use.

Architectural meaning:
- This is one of the strongest ideas in the file.
- It turns resume parsing into operational calibration instead of just interview personalization.

What it does well:
- It pushes the model away from punishing junior candidates for not sounding like staff engineers.
- It creates a specific path for `ownership_probe`, which is important in Sprint 1.

What it leaves on the table:
- The structure is flattened into short strings, so nuance is lost.
- Only a small subset of projects/experiences is included.
- The quality of this section depends heavily on `ResumeAgent` having parsed ownership correctly upstream.
- If `parsed_resume` is sparse or wrong, the calibration silently degrades.

#### `backend/agents/weakness_agent.py:113-118`

User prompt assembly.

Functional meaning:
- Joins sprint focus, prior weakness context, memory summary, calibration info, the current question, and the current answer into one prompt payload.

Architectural meaning:
- The agent is effectively doing late fusion of all available human-context signals in one shot.

Strength:
- Simple and fast.

Risk:
- Everything becomes one long prompt blob.
- There is no structured separation between "facts," "claims," "previously probed topic," and "current answer span."
- This reduces inspectability and makes systematic improvements harder.

#### `backend/agents/weakness_agent.py:120-123`

Router call and fallback.

Functional meaning:
- If the router returns a parsed `dict`, it is trusted and returned directly.
- Otherwise the result is downgraded into a default low-severity vague clarification.

Architectural meaning:
- This is a resilience choice: never crash the turn because the model returned bad JSON.

What it does well:
- Keeps the interview alive under malformed output.
- Biases failure toward "ask a clarification question" rather than "launch a bad attack."

What is weak:
- There is no schema validation even when the router returns a `dict`.
- A malformed dictionary can still leak bad enum values or missing keys downstream.
- The string fallback hides systemic model-formatting failures instead of surfacing them clearly.

### What `WeaknessAgent` Is Doing Well

1. It has a crisp job.
   - The file is small because its purpose is narrow: diagnose the next best probe.

2. It encodes one of the best product instincts in the repo.
   - The explicit "do not punish honesty" rule is excellent and aligns with a strong interviewer philosophy.

3. It calibrates to candidate context instead of using one universal bar.
   - Role, experience, and ownership signals are all in play.

4. It gives the rest of the system a usable routing contract.
   - `type`, `severity`, and `attack_strategy` are exactly the fields the orchestrator needs to steer the next move.

5. It is cheap enough to run every turn.
   - The medium-tier routing is appropriate for a real-time interview loop.

### Where `WeaknessAgent` Is Messing Up

1. It is too prompt-dependent and too validator-light.
   - The file trusts prompt compliance more than enforced output structure.
   - Best case: occasional drift.
   - Worst case: silent routing degradation.

2. It gives a diagnosis without evidence.
   - There is no `evidence`, `quoted_span`, or `why_this_gap` field.
   - That makes it harder to audit whether the judgment was fair.

3. It cannot truly remember what was already explored.
   - The anti-redundancy memory is label-level, not topic-level or argument-level.

4. Its calibration inputs are meaningful but lossy.
   - Ownership and resume context arrive as flattened strings, not stable structured features.

5. The live prompt text is partially corrupted.
   - Mojibake in prompt instructions is a real quality problem because prompt clarity is the core behavior surface of this agent.

6. It is pretending to be more final than it really is.
   - In practice, the orchestrator soft-caps, remaps, pivots, and sometimes overrides its output.
   - That is not bad, but it means this agent is a recommender, not the sole judge.

### Cross-Agent Reality Check

#### Relationship with `Orchestrator`

Key code:
- `backend/services/orchestrator.py:1531-1545`
- `backend/services/orchestrator.py:1609-1700`
- `backend/services/orchestrator.py:1702-1739`

What happens:
- `WeaknessAgent` runs in parallel with discrepancy and reasoning analysis.
- The orchestrator catches agent failure and applies a safe fallback.
- The orchestrator reduces high severity to medium when the reasoning agent says the candidate honestly admitted a gap.
- The orchestrator enforces breadth control and anti-tunneling rules.
- The orchestrator forces `ambiguous_but_promising` into a clarification lane.
- The orchestrator decides whether the next move is:
  - discrepancy challenge
  - clarification
  - aggressive weakness probe
  - bank follow-up adaptation
  - sprint-seed pivot

Architectural conclusion:
- `WeaknessAgent` is an adviser with strong influence, not an unchecked authority.

#### Relationship with `FollowUpAgent`

Key code:
- `backend/agents/followup_agent.py:332-373`
- `backend/agents/followup_agent.py:375-437`

What happens:
- `attack_strategy` is converted into an actual question-generation style.
- `generate()` handles aggressive, high-severity probing.
- `generate_clarification()` handles ambiguity and ownership clarification.

Why this matters:
- The downstream quality of `WeaknessAgent` is only as good as the semantic alignment of:
  - weakness type
  - attack strategy
  - follow-up prompt instructions

Current issue:
- The two files are semantically coupled, but that coupling is informal.
- There is no shared typed schema or contract test that proves every weakness strategy is understood the same way on both sides.

#### Relationship with `ReasoningBehaviorAgent`

Key code:
- `backend/services/orchestrator.py:1609-1613`

What happens:
- The reasoning agent can protect intellectually honest candidates from being over-punished.

Why this is good:
- It creates a two-agent balance:
  - `WeaknessAgent` pushes toward pressure.
  - `ReasoningBehaviorAgent` pushes toward fairness.

Why it is incomplete:
- The fairness correction happens after the fact.
- `WeaknessAgent` itself still cannot emit a first-class "honest-but-incomplete" structured state beyond severity lowering instructions in the prompt.

#### Relationship with `DiscrepancyAgent`

Key code:
- `backend/services/orchestrator.py:1676-1721`

What happens:
- Confirmed discrepancy can outrank weakness-based probing and take over the next turn.

Why this is right:
- Resume contradiction and reasoning weakness are different failure surfaces.
- The system should not blur them together.

Open design tension:
- Sometimes the best probe is a blended one: "your mechanism is vague, and it also conflicts with your stated ownership."
- The current system resolves that by priority order rather than by a richer combined diagnosis.

#### Relationship with `ResumeAgent`

What happens:
- `WeaknessAgent` relies on `parsed_resume` fields like `experience_tier`, `projects`, and `experiences`.

Why this matters:
- If resume parsing is weak, `WeaknessAgent` can miscalibrate severity or ask the wrong ownership bar question.

Architectural lesson:
- A large part of `WeaknessAgent` quality is upstream data quality, not just prompt quality.

### Best Version of `WeaknessAgent`

The best version of this agent is not "bigger" or "more aggressive."
It is "more precise, more inspectable, and more cooperative with the rest of the system."

#### Stage 1: Hardening

1. Add strict output normalization after the router call.
   - Clamp `type`, `severity`, and `attack_strategy` to known enums.
   - Fill missing keys deterministically.

2. Clean the prompt encoding.
   - Remove mojibake so the model sees the intended instructions cleanly.

3. Emit evidence.
   - Add fields like `evidence` or `answer_span` so we can see what in the answer triggered the diagnosis.

4. Add telemetry when fallback/parsing repair happens.
   - A "safe clarification fallback" is good behavior, but we should know when it happened.

#### Stage 2: Better Diagnosis

1. Add a first-class `confidence` field.
   - Not every diagnosis deserves the same downstream weight.

2. Add a first-class `probe_target` or `focus_key`.
   - The orchestrator is already doing topic/breadth control.
   - The agent should help by naming the exact conceptual target.

3. Split "what is wrong" from "what to do next."
   - Example:
     - `diagnosis_type`
     - `severity`
     - `recommended_route`
     - `reason`

4. Feed it cleaner structured memory.
   - Instead of a blob of prose, send explicit fields for prior established facts, prior probed topics, and recent claims.

#### Stage 3: System-Level Optimization

1. Give it concept support without over-coupling.
   - It does not necessarily need full concept-agent output every turn, but it would benefit from a small structured notion of the main entities or concepts under discussion.

2. Add contract tests against `FollowUpAgent`.
   - Every supported `attack_strategy` should have a tested downstream execution path.

3. Add fairness/pressure coordination with reasoning output.
   - Not full fusion inside the agent.
   - But enough structure that honest admission, ambiguity, and ownership uncertainty are represented more explicitly.

### Mentor Verdict

`WeaknessAgent` has a very good soul.
It understands that the purpose of the interview is not generic scoring or generic helpfulness. It is trying to find the most revealing next pressure point while still respecting honesty and candidate level.

That is exactly the right core instinct.

Its biggest problem is not that it is "bad at detecting weakness."
Its biggest problem is that too much of its intelligence lives in fragile prompt text and informal downstream assumptions.

So the path to optimality is not to make it louder or smarter in the abstract.
It is to make it:

- more structured
- more evidence-backed
- more contract-safe
- more explicit about uncertainty
- easier for the orchestrator and follow-up layer to trust

### Next Recommended Deep Dive

`FollowUpAgent` should be next.

Reason:
- `WeaknessAgent` decides the diagnosis.
- `FollowUpAgent` decides whether that diagnosis becomes a sharp, fair, human-sounding question or a clumsy one.
- If we want the system to "feel" brilliant in live interviews, the handoff between these two agents is the highest-leverage next seam to inspect.

---

## Agent 2: `FollowUpAgent`

Primary file:
- `backend/agents/followup_agent.py`

Main integration points:
- `backend/services/orchestrator.py:1090`
- `backend/services/orchestrator.py:1717-1754`
- `backend/services/orchestrator.py:1997`
- `backend/services/orchestrator.py:2111`
- `backend/services/orchestrator.py:2218`
- `backend/rag/question_bank.py:27-34`
- `backend/models/llm_router.py:1-58`

### Mission

`FollowUpAgent` is the interviewer's voice engine.

If `WeaknessAgent` decides what should be tested next, `FollowUpAgent` decides how that becomes an actual spoken question that sounds:

- specific
- continuous with the prior turn
- appropriate to the current persona
- fair in tone
- fast enough for the live product

This makes it one of the most product-visible agents in the repo.
Candidates do not experience "weakness severity" directly.
They experience the question this agent writes.

Architecturally, this agent is doing more than its name suggests.
It is not just a "follow-up generator."
It is currently responsible for:

- targeted weakness probes
- clarification probes
- discrepancy challenges
- sprint-seed question generation
- bank-template adaptation
- sprint-transition openers
- turn-1 seed generation
- speculative partial-transcript questions
- output cleanup and fallback repair

That means this file is both:

- a language/styling layer
- a tactical question-rendering layer

### Full File Walkthrough

#### `backend/agents/followup_agent.py:1-4`

Imports:
- `json`
- `re`
- `LLMRouter`
- `question_bank`

Functional meaning:
- This agent relies on both LLM generation and retrieval-based structural seeds.

Architectural meaning:
- It sits at the intersection of prompting and retrieval.
- That is a strong design instinct because good interview questions need both live adaptation and structural scaffolding.

#### `backend/agents/followup_agent.py:7-36`

`_extract_question_from_serialized_payload(...)`

Functional meaning:
- If the model returns serialized JSON or a list payload instead of a plain question string, this helper tries to recover the actual question text.

Architectural meaning:
- This is a repair layer for model noncompliance.
- It acknowledges a real-world truth: "Output only the question" is not reliable enough on its own.

What is good here:
- It salvages useful outputs without throwing away the whole generation.
- It supports several likely key names such as `question`, `followup`, `response`, and `text`.

What this reveals:
- The agent already knows its raw model contract is not strict enough.

#### `backend/agents/followup_agent.py:39-111`

`_clean_question_output(...)`

Functional meaning:
- Strips meta-commentary, headers, quoted wrappers, extra markdown, and multi-sentence noise.
- Tries to reduce model output down to a usable single question.

Architectural meaning:
- This is one of the most important practical utilities in the file.
- The codebase has already learned that question quality is not just about prompt quality; it is also about post-processing discipline.

What it does well:
- It is defensive in exactly the right place: before bad text escapes the agent layer into the interview.
- It handles serialized payloads, reasoning preambles, quoted questions, and formatting artifacts.

Where it is fragile:
- Like several other prompts in the repo, some regex delimiter text contains mojibake such as `鈥揮`, which means the intended punctuation matching is partly corrupted.
- The cleaner is heuristic, not contract-backed, so it can still over-clean or under-clean edge cases.

#### `backend/agents/followup_agent.py:114-139`

`_is_viable_question_output(...)` and `_finalize_question_output(...)`

Functional meaning:
- Decide whether cleaned text is acceptable.
- If not, fall back to a safer deterministic question.

Architectural meaning:
- This is the final quality gate before the question leaves the agent layer.

What it gets right:
- Bad outputs degrade into usable questions instead of surfacing raw prompt garbage.

What it misses:
- It does not enforce an actual upper length bound, even though many prompts ask for very short questions.
- It does not record whether cleanup or fallback was needed, so this critical repair behavior is mostly invisible.

#### `backend/agents/followup_agent.py:142-169`

Deterministic fallback question helpers.

Functional meaning:
- Provide route-specific backups for:
  - weakness strategies
  - sprint questions
  - sprint openers
  - discrepancy questions

Architectural meaning:
- These are reliability anchors.
- They keep the interview moving even when the model or retrieval path is weak.

Strength:
- The fallbacks are decent, not placeholder trash.

Risk:
- Because they are generic by design, heavy fallback usage will make the interview feel flatter and less personalized.

#### `backend/agents/followup_agent.py:177-223`

`PERSONA_PROMPTS`

Functional meaning:
- Defines the interviewer voice:
  - `curious_lead`
  - `socratic_mentor`
  - `senior_peer`

Architectural meaning:
- This is the main "human feel" layer of the system.
- The same tactical route can feel probing, collaborative, or instructive depending on this prompt.

What is good here:
- The persona prompts are thoughtful and mostly product-aligned.
- They preserve intellectual honesty as something to reward, not punish.
- They make the interview feel like a real engineering conversation instead of a benchmark script.

What is risky:
- Tone and tactic are mixed together here.
- Persona wording can partially override the tactical route chosen upstream.
- The prompt text also contains mojibake, which is especially damaging in a file whose main job is linguistic quality.

#### `backend/agents/followup_agent.py:231-260`

`ATTACK_STRATEGY_INSTRUCTIONS`

Functional meaning:
- Converts `WeaknessAgent`'s abstract strategy labels into concrete execution guidance for question writing.

Architectural meaning:
- This map is the semantic bridge between diagnosis and question rendering.

This is extremely important:
- `WeaknessAgent` says "use `ownership_probe`."
- `FollowUpAgent` decides what `ownership_probe` actually sounds like.

What is strong:
- The strategy descriptions are clear and operational.
- They prevent `FollowUpAgent.generate()` from becoming a vague generic prompt.

What is fragile:
- The contract is informal.
- There is no typed schema or contract test proving that strategy meanings stay aligned across both files over time.

#### `backend/agents/followup_agent.py:262-266`

`SPRINT_GOALS`

Functional meaning:
- Defines the narrative job of each sprint.

Architectural meaning:
- This gives the agent a high-level interview arc:
  - Sprint 1: project / ownership
  - Sprint 2: concepts / reasoning
  - Sprint 3: trade-offs / scale

This is good:
- It keeps "fresh question generation" from becoming random topic hopping.

#### `backend/agents/followup_agent.py:269-314`

`_build_resume_context(...)`

Functional meaning:
- Builds a structured grounding string from parsed resume content:
  - skills
  - tools
  - experience
  - roles
  - projects
  - claims

Architectural meaning:
- This is the grounding core of the agent.
- It is what keeps the questions tied to the actual candidate instead of drifting into stock interview prompts.

What it does well:
- It is richer than a raw resume blob.
- It preserves ownership and contribution hints.
- It is shared by many generation routes.

What it gets wrong:
- It is often much larger than the fast-generation paths really need.
- The same resume context shape is fed to very different tasks, even though seed generation, discrepancy challenge, and sprint opener do not need the same grounding density.

#### `backend/agents/followup_agent.py:317-330`

Class definition and router setup.

Functional meaning:
- Uses `medium` for richer generation.
- Uses `small` for fast or speculative generation.

Architectural meaning:
- This is a smart latency design.
- The agent already understands that not every question-generation path deserves the same cost.

This is one of the better design choices in the file.

#### `backend/agents/followup_agent.py:332-373`

`generate(...)`

Functional meaning:
- Used for high-severity, non-clarification weakness probes.
- Takes the previous question, candidate answer, weakness object, persona, and resume context, then writes one targeted adversarial probe.

Architectural meaning:
- This is the main execution path for aggressive weakness pressure.

What it does well:
- It explicitly carries through `attack_strategy`.
- It grounds the question in both resume and current answer.

What it misses:
- It returns only a string, so downstream code loses visibility into why a specific question was chosen or how strongly it was grounded.

#### `backend/agents/followup_agent.py:375-437`

`generate_clarification(...)`

Functional meaning:
- Used for ambiguity and ownership uncertainty.
- Lighter, faster, and less confrontational than `generate()`.

Architectural meaning:
- This is one of the best lanes in the whole interviewing system.
- It gives the architecture a "clarify before attack" mode instead of forcing binary gentle-vs-aggressive behavior.

What is strong:
- Uses the cheaper model tier.
- Narrows the task to one precise clarifying question.
- Separates clarification from contradiction.

What is weak:
- The shortness constraint is prompt-only and partially corrupted by mojibake (`鈮?0 words`), so brevity is more aspirational than enforced.

#### `backend/agents/followup_agent.py:439-473`

`generate_discrepancy_challenge(...)`

Functional meaning:
- Turns discrepancy findings into a direct but non-accusatory reconciliation question.

Architectural meaning:
- This is how the system gives candidates a fair chance to resolve resume/answer tension.

What is good:
- The prompt explicitly avoids "gotcha" energy.

What is missing:
- Like the other methods, it has no structured output or explanation field.
- If it falls back often, the discrepancy route becomes repetitive fast.

#### `backend/agents/followup_agent.py:475-558`

`generate_sprint_question(...)`

Functional meaning:
- Generates fresh non-attack questions for normal progression.
- Pulls structural seeds from the question bank.
- Uses transition memory, topic anchor, weakness hints, and covered-question history.
- Returns both the new question and any seed follow-ups from the chosen bank item.

Architectural meaning:
- This is not just question generation.
- This is lightweight planning.
- It decides how the interview opens up new territory while staying continuous.

What it does well:
- Uses retrieval as scaffolding, not as rigid script text.
- Keeps continuity with `transition_brief`.
- Tries to avoid generic prompts and repeated topics.

What is fragile:
- If the question bank is unavailable, `question_bank.retrieve()` silently returns `[]` and this route quietly degrades to pure LLM generation or generic fallbacks.
- The fallback may use the top bank seed verbatim even though the main instruction says not to copy seeds verbatim.
- Coverage memory is only the last six questions, which helps but is not a full semantic deduplication system.

Relevant supporting context:
- `backend/main.py:51-58` loads the bank on a best-effort basis.
- `backend/rag/question_bank.py:27-34` silently returns `[]` when not loaded.
- `backend/rag/faiss_store.py:20-22` and `backend/rag/faiss_store.py:51-52` rebuild the embedding model at search time, which makes this retrieval path weaker and less predictable than the high-level design suggests.

#### `backend/agents/followup_agent.py:560-600`

`adapt_followup(...)`

Functional meaning:
- Takes a raw template follow-up from the bank and adapts it to the candidate's specific answer.

Architectural meaning:
- This is a critical fast-path method.
- The orchestrator calls it when deterministic bank follow-ups should be served quickly without a full new planning pass.

What it does well:
- Preserves structural intent while making the wording feel locally grounded.
- Uses the fast model tier, which is appropriate for live responsiveness.

What it leaves on the table:
- It only sees a truncated answer and truncated resume context.
- That is good for latency, but it means adaptation quality can collapse when the anchor detail sits outside the truncation window.

#### `backend/agents/followup_agent.py:602-678`

`generate_sprint_opener(...)`

Functional meaning:
- Writes transition questions between sprints so the conversation feels continuous instead of reset.

Architectural meaning:
- This method is a direct answer to a major product complaint: cold sprint transitions.

What it does well:
- Uses recent Q/A history.
- Uses transition memory and avoid-topics guidance.
- Treats the new sprint as a bridge, not a hard scene cut.

What is still fragile:
- It still depends on prompt obedience rather than a stronger notion of transition target or topic handoff.

#### `backend/agents/followup_agent.py:680-711`

`generate_seed_question(...)`

Functional meaning:
- Generates a Turn 1 pre-seeded follow-up before the candidate has answered.

Architectural meaning:
- This exists to remove the old "generic first follow-up" problem from the fast lane.

What is good:
- Strong product instinct.
- It gives the first post-answer question a chance to feel grounded immediately.

What is inherently limited:
- Before the candidate answers, this agent can only make a resume-grounded guess.
- That means mismatch is unavoidable sometimes.
- The orchestrator's seed-relevancy guard is what keeps this method from causing more harm than good.

#### `backend/agents/followup_agent.py:713-765`

`generate_speculative(...)`

Functional meaning:
- Writes speculative deepening questions while the candidate is still speaking.
- Uses partial transcript text, detected entities, and honesty signals.

Architectural meaning:
- This is the question-writing half of the speculative fast-response system.

What is strong:
- It has a dedicated honesty-aware branch, which matches the system's broader philosophy.
- It uses the fast model tier and limited context to stay cheap.

What is fragile:
- Partial transcript speculation is inherently noisy.
- The quality of this method depends heavily on the orchestrator's staleness, versioning, and promotion rules.

#### `backend/agents/followup_agent.py:767-794`

`prefetch(...)`

Functional meaning:
- Generates two speculative follow-up questions from concept hints.

Architectural meaning:
- This looks like an older speculative-generation path that predates the current partial-transcript flow.

Important note:
- I found no live orchestrator call site for `prefetch()` in the repo.
- That makes it appear to be effectively dead code right now.

### What `FollowUpAgent` Is Doing Well

1. It has strong interviewer taste.
   - The questions are being generated through a philosophy that values continuity, specificity, fairness, and conversational realism.

2. It understands that different routes need different question styles.
   - Clarification, discrepancy, sprint opener, and aggressive weakness probes are not all treated as the same problem.

3. It contains a real repair layer, not blind optimism.
   - The cleanup and fallback helpers are practical and product-minded.

4. It uses model tiers intelligently.
   - Fast adaptation and speculation go through the small model.
   - Richer question writing goes through the medium model.

5. It is deeply integrated with continuity.
   - `adapt_followup`, `generate_sprint_opener`, `generate_seed_question`, and `generate_sprint_question` all try to make the interview feel like one coherent conversation.

### Where `FollowUpAgent` Is Messing Up

1. It is carrying too many responsibilities.
   - This one class currently owns question cleaning, route rendering, sprint planning, continuity bridging, speculative generation, and seed generation.
   - That makes it harder to reason about, harder to test, and easier for one change to destabilize several behaviors at once.

2. Its prompt surface is partially corrupted.
   - Mojibake appears throughout the persona prompts, strategy instructions, and length limits.
   - In a question-writing agent, prompt clarity is not cosmetic. It is the behavior surface.

3. Too much quality control is reactive.
   - The file is good at cleaning up bad outputs after the fact, but that also tells us the core generation contract is still too loose.

4. It returns only strings.
   - Downstream systems cannot see whether a question came from:
     - raw model output
     - cleaned output
     - fallback
     - retrieval seed adaptation
     - speculative generation

5. It degrades silently when retrieval is weak or unavailable.
   - Because `question_bank.retrieve()` quietly returns `[]`, the interview can become more generic without any explicit product signal that grounding quality has dropped.

6. It has at least one dead or drifting path.
   - `prefetch()` appears unused, which means the file contains speculative logic that the live system no longer relies on.

7. It relies on prompt requests for brevity instead of actual enforcement.
   - Several methods ask for very short questions, but there is no strong post-generation length control.

### Cross-Agent Reality Check

#### Relationship with `WeaknessAgent`

What happens:
- `WeaknessAgent` provides the tactical hint.
- `FollowUpAgent` turns that hint into wording.

Why this matters:
- If these two agents drift semantically, the interview can diagnose one thing and ask about another.

Architectural truth:
- `WeaknessAgent` is the diagnosis engine.
- `FollowUpAgent` is the execution engine.

#### Relationship with `DiscrepancyAgent`

What happens:
- `DiscrepancyAgent` identifies the conflict.
- `FollowUpAgent.generate_discrepancy_challenge()` authors the fair confrontation.

Why this matters:
- This agent is the difference between "credible pressure" and "cheap accusation."

#### Relationship with `ReasoningBehaviorAgent`

What happens:
- The reasoning agent influences the follow-up path indirectly through orchestrator decisions and speculative honesty handling.

Why this matters:
- `FollowUpAgent` already contains honesty-respecting language.
- But it still receives honesty mostly as route context, not as a richer structured control signal.

#### Relationship with `Orchestrator`

Key live routes:
- `backend/services/orchestrator.py:1090`
- `backend/services/orchestrator.py:1717-1754`
- `backend/services/orchestrator.py:1997`
- `backend/services/orchestrator.py:2111`
- `backend/services/orchestrator.py:2218`

What happens:
- The orchestrator uses this agent on both the fast lane and the background lane.
- `adapt_followup()` serves bank follow-ups quickly.
- `generate()` / `generate_clarification()` / `generate_discrepancy_challenge()` serve route-specific next questions.
- `generate_sprint_question()` and `generate_sprint_opener()` handle broader progression.
- `generate_seed_question()` and `generate_speculative()` support latency masking.

Architectural conclusion:
- `FollowUpAgent` is not a side utility.
- It is woven into nearly every moment where the system decides what the interviewer will actually say next.

#### Relationship with the Question Bank

Relevant files:
- `backend/rag/question_bank.py`
- `backend/rag/faiss_store.py`
- `backend/main.py`

What happens:
- The question bank is supposed to provide structural seeds and follow-up templates.
- This agent uses those seeds for both sprint questioning and deterministic deepening.

Why this matters:
- When the bank is healthy, `FollowUpAgent` can feel more grounded and less generic.
- When the bank is weak, absent, or slow, the agent quietly shifts toward pure prompt generation.

Architectural lesson:
- A meaningful chunk of `FollowUpAgent` quality is really question-bank/runtime health, not just prompt craft.

#### Relationship with `LLMRouter`

What happens:
- `LLMRouter` returns `dict | str`.
- `FollowUpAgent` individually handles and cleans the result in almost every method.

Why this matters:
- The loose router contract pushes output-validation complexity into this agent.
- That is one reason the file has accumulated so much cleanup logic.

### Best Version of `FollowUpAgent`

The best version of this agent should still feel human and flexible.
But it should stop being one monolithic "question everything" class.

#### Stage 1: Hardening

1. Clean the prompt text encoding.
   - Remove mojibake everywhere.

2. Centralize call-and-normalize behavior.
   - One helper should handle:
     - router call
     - raw extraction
     - cleanup
     - viability check
     - fallback selection
     - telemetry of fallback/repair usage

3. Add actual brevity enforcement.
   - If the product wants short questions, trim or score for length after generation rather than only asking politely in the prompt.

4. Emit lightweight metadata.
   - Example:
     - `question`
     - `source_method`
     - `fallback_used`
     - `seed_used`
     - `cleaned`

#### Stage 2: Decomposition

1. Split the class by responsibility.
   - Example slices:
     - `QuestionCleaner`
     - `QuestionRenderer`
     - `SprintPlanner`
     - `SpeculativeQuestioner`

2. Keep persona control separate from tactical route control.
   - Tone should be composable with route, not fused into every prompt string ad hoc.

3. Remove or revive dead paths deliberately.
   - If `prefetch()` is obsolete, delete it.
   - If it still matters, wire it into the current speculative architecture intentionally.

#### Stage 3: Better System Cooperation

1. Give the orchestrator more visibility.
   - Return more than a bare string so downstream logic can understand what question it is serving.

2. Strengthen the `WeaknessAgent` contract.
   - Treat strategy names as a tested interface, not an informal shared vocabulary.

3. Make retrieval health explicit.
   - If the question bank is unavailable, log it and treat it as a degraded mode, not a silent invisible shift.

4. Use more targeted grounding slices.
   - Different methods should get the minimum useful resume/history context instead of always reusing the same broad context pattern.

### Mentor Verdict

`FollowUpAgent` has very good instincts.
It is one of the main reasons this project can feel like an actual interviewer instead of a raw orchestration demo.

The file understands something important:
great interview behavior is not just about catching errors, it is about asking the next question in a way that feels intelligent, fair, and naturally connected to what was just said.

That is excellent.

Its biggest problem is role sprawl.
This file is trying to be:

- a style engine
- a route executor
- a sprint planner
- a speculative generator
- a cleanup layer
- a fallback layer

That is too much gravity in one class.

So the path to optimality is not to make it more clever in one giant prompt.
It is to make it:

- more modular
- more observable
- more contract-safe
- more explicit about degraded modes
- still just as human in tone

### Next Recommended Deep Dive

`DiscrepancyAgent` should be next.

Reason:
- We now understand the main diagnosis path (`WeaknessAgent`) and the main rendering path (`FollowUpAgent`).
- The next competing route that can hijack the interview is discrepancy detection.
- If we want to understand when the system should press, clarify, or confront, that is the next clean seam to inspect.

---

## Agent 3: `DiscrepancyAgent`

Primary file:
- `backend/agents/discrepancy_agent.py`

Main integration points:
- `backend/services/orchestrator.py:1513-1528`
- `backend/services/orchestrator.py:1547-1554`
- `backend/services/orchestrator.py:1675-1721`
- `backend/services/orchestrator.py:1791-1794`
- `backend/agents/followup_agent.py:439-473`
- `backend/agents/resume_agent.py:66-210`

### Mission

`DiscrepancyAgent` is the system's trust-calibration agent.

Its job is not to measure how deep the candidate's reasoning is.
Its job is to answer a different question:

"Does what this person is saying line up with what they have claimed elsewhere?"

In product terms, this is the agent that protects the interview from two opposite failures:

- being too naive and letting inflated claims slide
- being too accusatory and treating normal partial explanations like dishonesty

Architecturally, this means `DiscrepancyAgent` is not about depth.
It is about consistency.

That makes it one of the few agents that can reroute the interview away from normal weakness probing and into a direct reconciliation question.

### Full File Walkthrough

#### `backend/agents/discrepancy_agent.py:1`

`from backend.models.llm_router import LLMRouter`

Functional meaning:
- Like the other agents, it relies on the shared router for model selection and output parsing.

Architectural meaning:
- It inherits the same loose `dict | str` contract as the rest of the system.

#### `backend/agents/discrepancy_agent.py:4-27`

Prompt definition.

Functional meaning:
- Compares resume claims with the candidate explanation.
- Tells the model not to re-flag claims already established as true.
- Introduces a three-level conflict ontology:
  - `none`
  - `suspected`
  - `confirmed`
- Requests JSON with:
  - `conflict_level`
  - `description`
  - `severity`

Architectural meaning:
- This prompt is the entire policy layer of the agent.
- The Python implementation is extremely thin.

What is good here:
- The distinction between `suspected` and `confirmed` is smart.
- The instruction not to re-flag already established truths is important.
- The prompt is concise and easier to reason about than a giant tangled policy block.

What is missing:
- `severity` is requested but not actually defined.
- The prompt never says what the `description` should contain when `conflict_level="none"`.
- It asks the model to compare against prior confirmed facts and earlier claims, but it does not define a structured way to represent them.

#### `backend/agents/discrepancy_agent.py:30-35`

Class docstring.

Functional meaning:
- Describes the agent as cross-verifying resume claims and guarding against bluffing and inflation.

Architectural meaning:
- This is accurate, but the implementation is narrower than the description implies.
- The code does not really do a structured cross-verification pipeline; it performs a single prompt-based judgment over raw text.

#### `backend/agents/discrepancy_agent.py:37-38`

`self.llm = LLMRouter(tier="medium")`

Functional meaning:
- Uses the medium tier for discrepancy analysis.

Architectural meaning:
- This is a sensible choice.
- Discrepancy detection is important enough that the small tier would likely be too brittle, but it still needs to run every turn in parallel.

#### `backend/agents/discrepancy_agent.py:40-50`

`check(resume, answer, memory_context="")`

Functional meaning:
- Accepts the raw resume text, the candidate's answer, and optional memory context.
- Appends memory context directly into the prompt payload.
- Calls the router and trusts the parsed dict if it gets one.
- Supports an older boolean `conflict` output by converting it into `conflict_level`.
- Falls back to `conflict_level="none"` if the model returns a string.

Architectural meaning:
- This is a very small interface for a very sensitive job.
- It does not take:
  - parsed resume claims
  - a structured prior-claims list
  - the current question
  - claim IDs
  - quoted evidence spans

That matters because discrepancy judgment is extremely context-sensitive.

### What `DiscrepancyAgent` Is Doing Well

1. It has a clean conceptual job.
   - This agent is not trying to do weakness detection, reasoning scoring, or follow-up writing. It is trying to detect consistency problems.

2. The `suspected` versus `confirmed` split is the right instinct.
   - Real interviews often need an intermediate "this feels off, but we do not have enough to accuse" state.

3. It tries to preserve memory.
   - The prompt explicitly asks the model not to re-flag claims that prior turns already established as credible.

4. It is cheap enough to run in parallel every turn.
   - That makes trust checking a live feature instead of a delayed post-hoc report feature.

### Where `DiscrepancyAgent` Is Messing Up

1. It is under-structured for a high-trust job.
   - The entire input is basically:
     - raw resume blob
     - raw answer blob
     - free-form memory string
   - That is too fuzzy for something that can trigger confrontation.

2. `suspected` exists in the ontology, but the live route barely uses it.
   - In `orchestrator.py:1676-1680`, only `confirmed` plus `medium/high` severity wins the discrepancy route.
   - That means `suspected` is mostly a dead middle state with no first-class interview behavior.

3. There is no fairness correction for honest self-correction.
   - `ReasoningBehaviorAgent` can soften weakness severity in `orchestrator.py:1609-1613`.
   - There is no equivalent softening for discrepancy.
   - So a candidate honestly correcting an earlier overclaim can still be routed into confrontation instead of resolution.

4. The agent can silently pollute the memory model.
   - In `orchestrator.py:1791-1794`, if discrepancy returns `conflict_level="none"` and a non-empty `description`, that description is stored as an established fact.
   - But the prompt never clearly defines what `description` should mean in the `none` case.
   - If the router falls back to a raw string like "No conflict detected", that can become a bogus established fact on later turns.

5. `severity` is underdefined.
   - The prompt asks for it, but it never explains what low/medium/high mean for a discrepancy.
   - Since the orchestrator uses severity to decide whether confirmed conflict gets a dedicated challenge route, this ambiguity matters in production.

6. It does not see the current question.
   - That is a real limitation.
   - A candidate may answer only one narrow slice of a project because that was the question, not because they are contradicting the resume.
   - Without question context, the agent can misread incompleteness as inconsistency.

7. It does not use the structured resume parse directly.
   - `ResumeAgent` already extracts projects, claims, ownership, and contribution type in `resume_agent.py:66-210`.
   - `DiscrepancyAgent` still operates on the raw resume string instead of that structured representation.

### Cross-Agent Reality Check

#### Relationship with `Orchestrator`

Key code:
- `backend/services/orchestrator.py:1513-1528`
- `backend/services/orchestrator.py:1547-1554`
- `backend/services/orchestrator.py:1675-1721`
- `backend/services/orchestrator.py:1791-1794`

What happens:
- The orchestrator builds `memory_context` from:
  - `established_facts`
  - `probed_weaknesses`
  - recent Q/A claim summaries
- `DiscrepancyAgent` runs in parallel with weakness and reasoning analysis.
- If it emits `confirmed` with `medium/high` severity, it outranks the weakness route and triggers `generate_discrepancy_challenge()`.
- If it emits `none` with a `description`, the orchestrator may promote that description into `candidate_model.established_facts`.

Architectural conclusion:
- `DiscrepancyAgent` is not just a detector.
- It is part of the system's long-term memory formation and route arbitration.

#### Relationship with `FollowUpAgent`

Key code:
- `backend/agents/followup_agent.py:439-473`

What happens:
- `FollowUpAgent.generate_discrepancy_challenge()` converts conflict output into a fair reconciliation question.

Why this matters:
- `DiscrepancyAgent` decides whether tension exists.
- `FollowUpAgent` decides whether that tension feels like a professional clarification or an accusation.

Important limitation:
- The follow-up prompt only receives:
  - description
  - conflict level
  - resume context
  - previous answer
- It does not receive structured evidence or claim IDs, because `DiscrepancyAgent` does not emit them.

#### Relationship with `ResumeAgent`

Key code:
- `backend/agents/resume_agent.py:66-210`

What happens:
- `ResumeAgent` already extracts projects, claims, experiences, ownership level, and contribution type.
- Those are exactly the kinds of normalized units discrepancy detection would benefit from.

Architectural lesson:
- `DiscrepancyAgent` is currently leaving a lot of upstream structure unused.
- It is comparing against a raw resume blob when the system already has a partial claim graph.

#### Relationship with `ReasoningBehaviorAgent`

What happens:
- The reasoning agent protects weakness routing from punishing intellectual honesty.
- There is no corresponding discrepancy-resolution concept.

Why this matters:
- "I overstated that on my resume" should probably not be treated the same as evasive bluffing.
- The system currently has no first-class state for:
  - honest correction
  - resolved discrepancy
  - clarified discrepancy

#### Relationship with Candidate Memory

What happens:
- The prompt explicitly depends on "Already established as true."
- But those facts are just prior descriptions stored as free-form strings.

Why this matters:
- Memory is helping, but it is not precise.
- There is no stable notion of:
  - which claim was confirmed
  - what evidence confirmed it
  - which contradiction was resolved

### Best Version of `DiscrepancyAgent`

The best version of this agent should not be more aggressive.
It should be more evidence-based, more fair, and more structured.

#### Stage 1: Hardening

1. Normalize the output strictly.
   - Clamp `conflict_level` and `severity` to known enums.
   - Fill missing keys deterministically.

2. Define `description` semantics.
   - Especially for `conflict_level="none"`.
   - If it is going to feed established facts, it must mean something precise like:
     - "candidate consistently described claim X as Y"
   - Otherwise do not store it as memory.

3. Add telemetry when fallback or compatibility conversion happens.
   - The old `conflict` boolean compatibility path and raw-string fallback should be observable.

4. Stop using raw fallback strings as established facts.
   - Only structured, evidence-backed confirmations should enter `candidate_model.established_facts`.

#### Stage 2: Better Diagnosis

1. Feed the agent structured inputs.
   - Use parsed resume claims, ownership hints, and recent prior claims as explicit fields instead of one big blob.

2. Give it question context.
   - Discrepancy judgment should know what the candidate was actually asked.

3. Add evidence fields.
   - Example:
     - `resume_claim`
     - `candidate_claim`
     - `evidence`
     - `claim_id`
     - `resolution_state`

4. Distinguish suspicious vagueness from actual contradiction.
   - `suspected` should not just be a softer `confirmed`.
   - It should represent a different kind of uncertainty with a different downstream route.

#### Stage 3: System-Level Optimization

1. Add a first-class route for `suspected`.
   - Not full confrontation.
   - Something like a targeted clarification or ownership check.

2. Add a first-class route for honest correction.
   - If the candidate transparently resolves the mismatch, the system should mark the discrepancy as clarified instead of endlessly circling it.

3. Convert memory from prose into claim-level state.
   - The agent should know which claims are:
     - asserted
     - confirmed
     - disputed
     - resolved

4. Align discrepancy with focus/budget logic more explicitly.
   - Right now the orchestrator only budgets repeated `confirmed` conflicts on the same focus.
   - A more structured discrepancy state would make repetition control safer and more interpretable.

### Mentor Verdict

`DiscrepancyAgent` has the right instinct but too little scaffolding.

It understands a crucial truth:
an interview is not just about whether the answer sounds smart.
It is also about whether the candidate's story stays coherent across resume, prior turns, and present explanation.

That is important.

But this is one of the most dangerous places in the system to stay fuzzy.
If this agent is too weak, bluffing slides through.
If it is too loose or overconfident, the AI starts accusing people for normal interview behavior.

So the path to optimality is not "make it harsher."
It is:

- make it more structured
- make it more evidence-backed
- make it more honest-correction-aware
- make it use the upstream resume structure we already have
- make its middle states actually matter downstream

### Next Recommended Deep Dive

`ResumeAgent` should be next.

Reason:
- `DiscrepancyAgent` is only as good as the claim surface it compares against.
- The repo already has a structured resume parse path, but discrepancy is underusing it.
- If we want confrontation to be fair and precise, the next best place to lock in is the upstream agent that defines what the system thinks the candidate actually claimed.

---

## Agent 4: `ResumeAgent`

Primary file:
- `backend/agents/resume_agent.py`

Main integration points:
- `backend/api/routes.py:15-19`
- `backend/services/orchestrator.py:97-137`
- `backend/services/orchestrator.py:547-663`
- `backend/agents/weakness_agent.py:92-111`
- `backend/agents/followup_agent.py:269-314`
- `backend/agents/evaluation_agent.py:84-129`
- `backend/agents/discrepancy_agent.py:40-45`

### Mission

`ResumeAgent` is the system's claim-ingestion and calibration agent.

Its job is not just "parse the resume."
Its real job is to create the structured candidate model that the rest of the interview uses to decide:

- what the candidate seems to have built
- how much ownership they likely had
- how senior the system should assume they are
- which projects, companies, and claims deserve attention

Architecturally, this makes `ResumeAgent` the upstream contract for almost every other agent we have reviewed so far.

If this parse is good:
- `WeaknessAgent` can calibrate pressure fairly.
- `FollowUpAgent` can ask grounded questions.
- `DiscrepancyAgent` can compare against real claims instead of mush.
- `EvaluationAgent` can judge tested claims with the right bar.

If this parse is bad:
- the whole interview starts from a distorted map of the candidate.

### Full File Walkthrough

#### `backend/agents/resume_agent.py:1-2`

Imports:
- `LLMRouter`
- `re`

Functional meaning:
- This agent mixes LLM parsing with regex-heavy heuristic fallback.

Architectural meaning:
- That is the right high-level pattern for a session-start parser.
- You want best-effort structure, but you also need deterministic fallback when the model output is thin or malformed.

#### `backend/agents/resume_agent.py:5-63`

Prompt definition.

Functional meaning:
- Requests a structured parse containing:
  - skills
  - tools
  - projects
  - experiences
  - claims
  - per-domain experience
  - experience tier
- It also emphasizes ownership and contribution signals, not just technologies.

Architectural meaning:
- This is one of the best prompt intents in the repo.
- It understands that fair interviewing depends on ownership and level calibration, not just keyword extraction.

What is good here:
- The requested schema is directly aligned with live product needs.
- `ownership_level` and `contribution_type` are especially valuable.
- The prompt is explicit that calibration fairness matters.

What is weak:
- Some requested fields are not equally supported downstream.
- `experience` is asked for, but it has little live behavioral weight.
- The prompt does not define confidence or evidence, which would help distinguish inferred structure from clear structure.

#### `backend/agents/resume_agent.py:66-73`

Class definition and model selection.

Functional meaning:
- Uses the `small` model tier for resume parsing.

Architectural meaning:
- This is a sensible cost/latency choice because parsing happens at session start, not every turn.
- But it also means the parser has to lean on fallback logic more than a richer model would.

#### `backend/agents/resume_agent.py:75-179`

`_heuristic_parse(...)`

Functional meaning:
- Builds a fallback parse from raw resume text line by line.
- Extracts:
  - `skills`
  - `tools`
  - `experiences`
  - `projects`
  - `claims`
  - `experience_tier`

Architectural meaning:
- This is the resilience core of the agent.
- If the LLM returns bad JSON or sparse structure, the system still gets a usable candidate profile.

This method is doing several distinct jobs:

1. Skill extraction
   - `resume_agent.py:97-107`
   - Looks for `skills:` style lines and tokenizes them.

2. Tool extraction
   - `resume_agent.py:109-112`
   - Picks up infra/dev-tool keywords like AWS, Docker, Linux, GCP, Git, deployment.

3. Experience/project detection
   - `resume_agent.py:114-139`
   - Detects roles by heuristics like `@`, `intern`, `research assistant`, `engineer`.
   - Creates both an `experience` entry and a corresponding `project` shell.

4. Claim extraction from bullets
   - `resume_agent.py:141-160`
   - Treats bullet lines as claims tied to the current project.
   - Infers strength from visible quantitative markers.
   - Infers technologies from capitalization and a short allowlist.

5. Tier inference
   - `resume_agent.py:162-169`
   - Guesses `experience_tier` from the provided years-of-experience string and internship hints.

What it does well:
- It is not pretending resumes are cleanly structured.
- It creates useful ownership and contribution defaults.
- It gives the system something coherent even when the LLM path fails.

What it gets wrong:
- It contains mojibake in bullet handling like `("鈥?, "-", "*")`, which makes one of its most important branch conditions fragile.
- The role heuristic is very coarse: anything with `engineer` becomes `built`, anything with `assistant` becomes `assisted`, otherwise `contributed`.
- It auto-creates projects from experiences, which is often helpful, but can also blur companies, roles, and actual shipped projects into one bucket.
- The `experience` field is hardcoded to zeroes in fallback output, even though the prompt asks for meaningful per-domain years.

#### `backend/agents/resume_agent.py:181-191`

`_merge_with_fallback(...)`

Functional meaning:
- Merges the LLM result with the heuristic fallback.
- If the model leaves a list/dict field empty, the fallback fills it.

Architectural meaning:
- This is a pragmatic "best-of-both-worlds" layer.

What is good:
- It avoids throwing away useful heuristic structure when the model output is sparse.

What is risky:
- It is a shallow merge.
- It cannot reconcile partial-but-conflicting structures inside lists.
- If the model gives one low-quality project entry, the fallback's richer project list may be discarded entirely because the list is technically non-empty.

#### `backend/agents/resume_agent.py:193-210`

`parse(...)`

Functional meaning:
- Sends `target_role` and `years_experience` into the parser prompt along with the resume text.
- Builds the heuristic fallback.
- If the LLM output is not a dict, returns fallback only.
- Otherwise merges model and fallback output.

Architectural meaning:
- This is where product calibration enters at session start.
- The frontend explicitly requires `target_role` and `years_experience` in `app/page.tsx:16-20`, so this is a real user-facing contract, not optional decoration.

What it does well:
- Lets role/YOE influence the initial parse.
- Never blocks session start on perfect model output.

What it leaves on the table:
- There is no schema validation after the router call.
- There is no telemetry about whether the LLM parse succeeded cleanly, partially, or fell back heavily.

### How `ResumeAgent` Becomes Product Behavior

#### Session start contract

Relevant code:
- `backend/api/routes.py:15-19`
- `backend/api/routes.py:56-64`
- `backend/services/orchestrator.py:547-663`

What happens:
- The frontend collects:
  - resume text
  - optional GitHub links
  - target role
  - years of experience
- `start_session()` calls `resume_agent.parse()` before creating session state.
- The parsed output is stored in `state["parsed_resume"]`.

Important architectural note:
- `github_links` are collected and stored, but `ResumeAgent` does not currently use them at all.
- So the candidate model is still resume-only, even though the product collects richer raw input.

#### Focus and topic tracking

Relevant code:
- `backend/services/orchestrator.py:97-137`
- `backend/services/orchestrator.py:140-199`

What happens:
- `parsed_resume.projects`, `experiences`, and `claims` feed `_resume_focus_candidates()`.
- That, in turn, feeds `_infer_focus()` and `_seed_relevant_to_answer()`.

Why this matters:
- `ResumeAgent` is not only used for grounding prompts.
- It also shapes the system's internal topic map:
  - what counts as the same focus
  - whether a Turn 1 seed is relevant
  - when breadth guards think the interview is circling the same project or claim

This is a bigger responsibility than "parser" usually implies.

#### Weakness calibration

Relevant code:
- `backend/agents/weakness_agent.py:92-111`

What happens:
- `WeaknessAgent` uses `experience_tier`, projects, and experiences to calibrate severity and ownership pressure.

Why this matters:
- If `ResumeAgent` overstates ownership, `WeaknessAgent` will over-press.
- If `ResumeAgent` understates ownership, the interview can become too gentle.

#### Question grounding

Relevant code:
- `backend/agents/followup_agent.py:269-314`

What happens:
- `FollowUpAgent` turns `skills`, `tools`, `experience`, `experience_tier`, `experiences`, `projects`, and `claims` into a prompt grounding block.

Why this matters:
- `ResumeAgent` quality is directly visible in question specificity.
- Better parse means more grounded, more personal follow-ups.

#### Discrepancy checking

Relevant code:
- `backend/agents/discrepancy_agent.py:40-45`

What happens:
- Ironically, `DiscrepancyAgent` still compares against the raw resume blob, not the structured parse.

Why this matters:
- One of the highest-value consumers is currently underusing the parser.

#### Final evaluation

Relevant code:
- `backend/agents/evaluation_agent.py:84-129`
- `backend/services/orchestrator.py:717-727`

What happens:
- `EvaluationAgent` uses parsed claims, ownership signals, and `experience_tier` to calibrate the final judgment.

Why this matters:
- `ResumeAgent` influences not only the live interview, but also the final report.

### What `ResumeAgent` Is Doing Well

1. It has the right philosophy.
   - The parser is trying to capture ownership and level, not just extract buzzwords.

2. It has a sensible resilience pattern.
   - LLM parse plus heuristic fallback is the right architecture for session-start parsing.

3. It already feeds real live behavior.
   - Focus inference, question grounding, weakness calibration, and final evaluation all depend on it.

4. It uses the user-provided calibration inputs.
   - `target_role` and `years_experience` are not dead fields; they meaningfully enter the parsing path.

### Where `ResumeAgent` Is Messing Up

1. Parts of its schema are much more real than others.
   - `projects`, `claims`, `experiences`, and `experience_tier` matter a lot.
   - `experience` is mostly aspirational and lightly used.

2. The heuristic parser is brittle in exactly the places it must be stable.
   - Bullet detection and bullet stripping rely on mojibake-corrupted character handling.

3. The merge strategy is shallow.
   - One weak non-empty LLM list can suppress a stronger fallback list.

4. It has no confidence model.
   - The rest of the system cannot tell whether a claim/project/ownership signal came from a strong parse or a best-effort guess.

5. It ignores GitHub links entirely.
   - The product collects them, stores them, and then leaves them unused in the parsing path.

6. It collapses too many concepts together.
   - company
   - role
   - project
   - bullet claim
   can blur into one another in fallback mode.

7. There is no post-parse validation or repair beyond basic merge behavior.
   - Enum values can drift.
   - Lists can be semantically low quality while still looking structurally valid.

### Cross-Agent Reality Check

#### Relationship with `WeaknessAgent`

What happens:
- Ownership and seniority signals from `ResumeAgent` determine how hard Sprint 1 and later turns should push.

Architectural lesson:
- `ResumeAgent` sets the fairness bar for weakness detection.

#### Relationship with `FollowUpAgent`

What happens:
- Parsed resume structure becomes prompt grounding for almost every question-writing route.

Architectural lesson:
- `ResumeAgent` is part of the interviewer's memory and vocabulary, not just an onboarding step.

#### Relationship with `DiscrepancyAgent`

What happens:
- `ResumeAgent` should be the natural source of structured claims for discrepancy checking.
- Right now that connection is only partial.

Architectural lesson:
- The repo already has claim structure, but one of the most important trust-checking routes is not consuming it properly.

#### Relationship with `EvaluationAgent`

What happens:
- Final scoring uses parsed claims, project ownership, and inferred experience tier.

Architectural lesson:
- Bad parse quality can distort both the live interview and the final report.

#### Relationship with `Orchestrator`

What happens:
- `parsed_resume` is stored once at session start and then reused everywhere.
- It also drives focus-key inference and seed relevance checks in the orchestrator.

Architectural lesson:
- `ResumeAgent` is part parser, part topology builder for the interview state machine.

### Best Version of `ResumeAgent`

The best version of this agent should become the trustworthy candidate-claim substrate for the whole system.

#### Stage 1: Hardening

1. Clean the heuristic parser text handling.
   - Fix mojibake-sensitive bullet detection and stripping.

2. Add strict schema normalization.
   - Clamp enums like:
     - `ownership_level`
     - `contribution_type`
     - `experience_tier`

3. Add parse telemetry.
   - Record whether:
     - the LLM parse succeeded
     - fallback filled key fields
     - normalization repaired values

4. Make merge behavior smarter.
   - Merge lists by quality and completeness, not just "non-empty wins."

#### Stage 2: Better Candidate Modeling

1. Add confidence per section.
   - Example:
     - `claims_confidence`
     - `ownership_confidence`
     - `tier_confidence`

2. Separate roles from projects more explicitly.
   - A company, a title, and a project should not be conflated when fallback parsing is active.

3. Turn claims into better units.
   - Each claim should ideally carry:
     - stable ID
     - linked project
     - ownership hint
     - confidence

4. Make per-domain experience real or remove it.
   - Right now `experience` is mostly placeholder structure.

#### Stage 3: System-Level Optimization

1. Feed structured claims directly into `DiscrepancyAgent`.
   - That is the most obvious unlocked value.

2. Let focus inference consume stronger typed entities.
   - The orchestrator currently builds topic focus from string tokens and claim text.
   - A better candidate graph would make focus tracking more accurate.

3. Consider using GitHub links as optional enrichment.
   - Even lightweight repo-name extraction or project-title matching could strengthen grounding without going full crawler mode.

4. Expose parse quality downstream.
   - Agents should know when they are grounding against high-confidence structure versus fallback guesses.

### Mentor Verdict

`ResumeAgent` has one of the best design intentions in the codebase.

It understands that a fair adversarial interview cannot start from a naive resume keyword dump.
It needs an estimate of:

- what the candidate actually claimed
- how much they likely owned
- how senior a bar is fair

That is exactly right.

Its biggest problem is that it is acting like a strong canonical parser before it is fully earning that status.
Some fields are robust and heavily used.
Some are rough guesses.
Some are requested but barely real downstream.

So the path to optimality is not just "improve extraction accuracy."
It is:

- make the parse more trustworthy
- make uncertainty visible
- make downstream agents consume the structure more deliberately
- turn this from a convenient parse blob into an explicit candidate-claim model

### Next Recommended Deep Dive

`ReasoningBehaviorAgent` should be next.

Reason:
- We have now reviewed the main claim-ingestion path and the three major live routing influences around it.
- The remaining big fairness/control seam is the agent that decides whether the candidate is being adaptive, brittle, evasive, or honestly self-correcting.
- That agent quietly moderates how hard the whole interview should press, so it is the next high-leverage piece to lock in.

---

## Agent 5: `ReasoningBehaviorAgent`

Primary file:
- `backend/agents/reasoning_behavior_agent.py`

Main integration points:
- `backend/services/orchestrator.py:40-43`
- `backend/services/orchestrator.py:212-229`
- `backend/services/orchestrator.py:1506-1563`
- `backend/services/orchestrator.py:1609-1613`
- `backend/services/orchestrator.py:1857-1860`
- `backend/services/orchestrator.py:2243-2255`
- `backend/agents/evaluation_agent.py:203-219`

### Mission

`ReasoningBehaviorAgent` is the interview loop's meta-cognition and fairness sensor.

Its job is not to decide whether the candidate is technically right.
Its job is to decide how the candidate is behaving cognitively under pressure.

In product terms, it tries to answer questions like:

- Are they structured or rambling?
- Do they ask for constraints before designing?
- Do they adapt when challenged?
- Are they honestly admitting limits, or just deflecting?
- Are they calibrated or overconfident?

Architecturally, this makes it a quiet but very high-leverage agent.
It does not usually choose the next question directly.
Instead, it modifies how hard the rest of the system should press and how the final evaluation should interpret the transcript.

### Full File Walkthrough

#### `backend/agents/reasoning_behavior_agent.py:1`

`from backend.models.llm_router import LLMRouter`

Functional meaning:
- The agent uses the shared router and inherits the same `dict | str` looseness as the rest of the LLM-backed agents.

Architectural meaning:
- The file stays very small, but its output safety depends heavily on downstream guards.

#### `backend/agents/reasoning_behavior_agent.py:4-28`

Prompt definition.

Functional meaning:
- Explicitly says:
  - do not evaluate technical accuracy
  - evaluate how the candidate thinks and communicates
- Requests:
  - `structure_score`
  - `clarification_behavior`
  - `adaptability`
  - `confidence_calibration`
  - `notes`

Architectural meaning:
- This is the policy layer of the agent.
- The entire notion of "intellectual honesty" in this file lives here, especially via `adaptability="admitted_gap"`.

What is good here:
- The separation from technical correctness is exactly right.
- `admitted_gap` is a strong category. It gives the system a principled way to treat self-correction as honest rather than weak.
- `clarification_behavior` is a nice idea because good engineers often ask for constraints before answering.

What is weak:
- The prompt asks the model to infer clarification behavior without giving it the actual question context in the input.
- `structure_score` is defined as `0-3`, but the rest of the system is not consistently aligned to that scale.
- There is no explicit confidence field, even though this is a judgment about behavior that can be noisy.

#### `backend/agents/reasoning_behavior_agent.py:31-36`

Class docstring.

Functional meaning:
- Describes the agent as a parallel meta-cognition evaluator that feeds the final hire recommendation.

Architectural meaning:
- Accurate, but slightly understated.
- In practice this agent also affects live routing and even interview termination, not just final evaluation.

#### `backend/agents/reasoning_behavior_agent.py:38-39`

`self.llm = LLMRouter(tier="medium")`

Functional meaning:
- Uses the medium tier.

Architectural meaning:
- This is a reasonable tradeoff.
- Behavioral judgment under pressure is subtle enough that the small tier would likely be flimsy, but it still needs to run every turn in parallel.

#### `backend/agents/reasoning_behavior_agent.py:41-43`

`evaluate(answer, was_challenged=False)`

Functional meaning:
- The model sees only:
  - the answer text
  - a boolean saying whether the candidate was challenged

Architectural meaning:
- This is the file's biggest limitation.
- It is trying to infer:
  - clarification behavior
  - adaptability
  - confidence calibration
from very little context.

Why that matters:
- Without the question, the agent cannot reliably know whether the candidate asked clarifying questions appropriately.
- Without richer challenge context, `was_challenged=True/False` is a very coarse signal for adaptability.
- Without prior answer context, it cannot cleanly distinguish correction from contradiction.

### How `ReasoningBehaviorAgent` Becomes Product Behavior

#### Parallel background analysis

Relevant code:
- `backend/services/orchestrator.py:1506-1563`

What happens:
- The orchestrator derives `was_challenged` from whether the prior weakness had `severity="high"`.
- `ReasoningBehaviorAgent` runs in parallel with:
  - `WeaknessAgent`
  - `DiscrepancyAgent`
  - `ConceptAgent` when needed

Architectural meaning:
- This is a sidecar judgment agent, not the main route chooser.
- But because it runs every turn, it becomes a persistent moderation signal across the interview.

#### Honest-admission soft cap

Relevant code:
- `backend/services/orchestrator.py:1609-1613`

What happens:
- If reasoning output says `adaptability == "admitted_gap"` and weakness severity is `high`, the orchestrator downgrades weakness severity to `medium`.

Architectural meaning:
- This is one of the most ethically important pieces of logic in the system.
- It is the mechanism that turns "reward honesty" from prompt philosophy into actual runtime behavior.

This is excellent design intent.

#### Topic dead-end detection

Relevant code:
- `backend/services/orchestrator.py:212-229`

What happens:
- `_collect_overprobed_topics()` treats topics with `adaptability="admitted_gap"` and `structure_score <= 1` as terminal dead-ends and pushes them to the avoid list.

Architectural meaning:
- This agent is helping the system know when a topic is exhausted for legitimate reasons, not just because it has been probed a lot.

#### Final staged analysis

Relevant code:
- `backend/services/orchestrator.py:1857-1860`
- `backend/services/orchestrator.py:1912`

What happens:
- `reasoning_behavior` is stored into staged analysis and then attached to canonical turn history.

Architectural meaning:
- This turns one-turn behavioral judgment into durable interview memory and final-evaluation input.

#### Terminal admission ending

Relevant code:
- `backend/services/orchestrator.py:2243-2255`

What happens:
- If the last two turns both show:
  - `adaptability == "admitted_gap"`
  - `structure_score <= 1`
  the interview ends early.

Architectural meaning:
- This is a very strong product decision.
- It says the system should stop pressing once the candidate has clearly and repeatedly said they cannot answer.

That is humane and sensible.

#### Final evaluation summary

Relevant code:
- `backend/agents/evaluation_agent.py:203-219`

What happens:
- Final evaluation aggregates:
  - average `structure_score`
  - dominant `adaptability`
  - `clarification_behavior` from the first reasoning signal only

Architectural meaning:
- `ReasoningBehaviorAgent` is one of the main sources of the report's adaptability judgment.

Important limitation:
- `clarification_behavior` is not really aggregated; the evaluation currently grabs it from the first signal only.

### What `ReasoningBehaviorAgent` Is Doing Well

1. It is judging the right thing.
   - Separating meta-cognition from technical correctness is a strong architectural choice.

2. It encodes one of the best fairness concepts in the repo.
   - `admitted_gap` is exactly the right way to represent honest self-correction as something distinct from evasion.

3. It has real live influence.
   - This is not report-only garnish. It affects weakness severity, topic avoidance, interview termination, and final evaluation.

4. It is intentionally small.
   - The file is easy to reason about, which is valuable for a system-level fairness component.

### Where `ReasoningBehaviorAgent` Is Messing Up

1. It is under-contextualized.
   - It sees only the answer and a boolean `was_challenged`.
   - That is too little information for some of the judgments it is being asked to make.

2. `clarification_behavior` is especially under-grounded.
   - Whether someone asked for constraints before designing is hard to judge without the actual prompt/question context.

3. There is no output normalization.
   - The file returns `await self.llm.call(...)` directly.
   - If the router returns a string or malformed dict, there is no local repair layer.

4. The fallback contract is inconsistent with the prompt schema.
   - `_REASONING_FALLBACK` in `orchestrator.py:43` sets `structure_score` to `5`, even though the prompt defines a `0-3` scale.
   - That is a small but real contract bug.

5. It has no explicit notion of uncertainty.
   - The system treats `adaptability` labels as clean truth even though these are often fuzzy interpretive judgments.

6. It is only partially integrated with fairness.
   - Weakness routing gets honesty softening.
   - Discrepancy routing does not.
   - So the fairness signal is not applied uniformly across the interview loop.

7. Its downstream aggregation is lossy.
   - Final evaluation uses average structure and dominant adaptability, but clarification behavior is effectively sampled from one turn instead of aggregated.

### Cross-Agent Reality Check

#### Relationship with `WeaknessAgent`

What happens:
- `WeaknessAgent` identifies technical/reasoning gaps.
- `ReasoningBehaviorAgent` decides whether the candidate's stance toward those gaps is honest, rigid, defensive, or adaptive.

Architectural lesson:
- These two agents create the system's pressure-versus-fairness balance.

#### Relationship with `DiscrepancyAgent`

What happens:
- `DiscrepancyAgent` can still escalate contradiction routes even when the reasoning signal suggests honest self-correction.

Architectural lesson:
- Fairness moderation is currently asymmetric across routes.

#### Relationship with `FollowUpAgent`

What happens:
- `FollowUpAgent` has honesty-respecting prompt language, but the direct operational softening comes from the orchestrator using `ReasoningBehaviorAgent`.

Architectural lesson:
- The agent is less about wording and more about route pressure.

#### Relationship with `EvaluationAgent`

Relevant code:
- `backend/agents/evaluation_agent.py:203-219`

What happens:
- Final evaluation summarizes average structure and dominant adaptability from these signals.

Why this matters:
- This agent has lasting report-level impact, not just live-loop influence.

Current issue:
- The aggregation is simple and only partially expressive.

#### Relationship with `Orchestrator`

Relevant code:
- `backend/services/orchestrator.py:1506-1563`
- `backend/services/orchestrator.py:1609-1613`
- `backend/services/orchestrator.py:2243-2255`

What happens:
- The orchestrator is where this agent becomes consequential:
  - it influences severity softening
  - it helps mark topics as exhausted
  - it can end the interview

Architectural conclusion:
- `ReasoningBehaviorAgent` is not the main planner, but it is a live moderation layer for the whole interview state machine.

### Best Version of `ReasoningBehaviorAgent`

The best version of this agent should stay small, but become more informed, more normalized, and more evenly integrated.

#### Stage 1: Hardening

1. Normalize outputs locally.
   - Clamp:
     - `structure_score`
     - `clarification_behavior`
     - `adaptability`
     - `confidence_calibration`

2. Fix the fallback contract.
   - Align `_REASONING_FALLBACK` with the real `0-3` `structure_score` scale.

3. Add a minimal repair layer.
   - If the router returns a string, convert it into a safe structured fallback instead of relying entirely on orchestrator defaults.

4. Add telemetry when fallback/repair happens.
   - This is too important a fairness component to fail silently.

#### Stage 2: Better Judgment

1. Give it the current question.
   - This especially improves `clarification_behavior`.

2. Give it the previous challenged context, not just a boolean.
   - A small challenge summary would help it tell adaptation from contradiction more reliably.

3. Add confidence or certainty.
   - Not every behavioral judgment deserves equal downstream force.

4. Distinguish honest correction from terminal inability more explicitly.
   - Right now both can map through `admitted_gap`, and the system uses `structure_score <= 1` to separate them.
   - That is clever, but a more explicit representation would be cleaner.

#### Stage 3: System-Level Optimization

1. Apply fairness moderation across more routes.
   - Honest self-correction should influence discrepancy handling too, not only weakness severity.

2. Aggregate behavioral signals better in final evaluation.
   - Especially for `clarification_behavior`, which is currently underused.

3. Consider richer behavioral state in history.
   - Example:
     - `adaptation_after_challenge`
     - `clarifying_before_answer`
     - `honesty_signal`
     - `pressure_response`

4. Keep it separate from technical grading.
   - This separation is good and should be preserved even if the schema gets richer.

### Mentor Verdict

`ReasoningBehaviorAgent` is one of the smallest files in the repo, but it has one of the best moral instincts.

It understands that a strong interview should not just punish wrong answers.
It should distinguish:

- wrong but honest
- wrong and rigid
- vague but curious
- evasive
- calibrating in real time

That is excellent.

Its biggest problem is not intent. It is context and contract quality.
The system asks this agent to make subtle behavioral judgments from very limited inputs, then uses those judgments in surprisingly consequential ways.

So the path to optimality is:

- keep the agent small
- give it slightly better context
- normalize its outputs properly
- apply its fairness signal more consistently across the system

### Next Recommended Deep Dive

`EvaluationAgent` should be next.

Reason:
- We have now reviewed the main upstream claim model and the live-loop fairness/governance layer.
- `EvaluationAgent` is where these signals ultimately converge into the final product judgment.
- If we want to understand how the system turns all of this runtime behavior into a report and hire recommendation, that is the next high-leverage seam.

---

## Agent 6: `EvaluationAgent`

Primary file:
- `backend/agents/evaluation_agent.py`

Main integration points:
- `backend/services/orchestrator.py:516-535`
- `backend/services/orchestrator.py:705-755`
- `backend/services/orchestrator.py:760-785`
- `backend/api/routes.py:147-170`
- `backend/api/routes.py:351-383`
- `app/report/[session_id]/page.tsx:5-278`
- `backend/db/postgres.py:84-114`

### Mission

`EvaluationAgent` is the system's judgment synthesizer.

All the other agents help the interview decide:

- what to ask
- how hard to press
- what signals to store
- what claims to doubt

`EvaluationAgent` is where those signals are supposed to become a coherent final answer to:

- what was actually tested
- how strong the candidate looked on that tested evidence
- how broad or narrow the evidence base was
- whether claim credibility concerns are local or systemic
- what recommendation the product should show

Architecturally, this agent is really two related subsystems:

1. Per-answer scoring during the interview
2. Final full-interview evaluation at session end

That split matters, because the two paths do not currently have the same richness or the same calibration inputs.

### Full File Walkthrough

#### `backend/agents/evaluation_agent.py:5-26`

`PER_ANSWER_PROMPT`

Functional meaning:
- Scores one answer on:
  - problem framing
  - logical reasoning
  - technical correctness
  - production awareness
- Returns:
  - score
  - breakdown
  - confidence

Architectural meaning:
- This is a lightweight scoring rubric for live accumulation, not a full candidate judgment.

What is good here:
- It explicitly says to score relative to target role and experience.
- It also says not to punish modest claims unfairly.

What is limited:
- It does not receive parsed resume context directly, only role/YOE text.
- It has no direct access to the behavioral signals from `ReasoningBehaviorAgent`.
- It is trying to "reward honest clarification" without actually seeing the structured honesty signal.

#### `backend/agents/evaluation_agent.py:29-81`

`FULL_INTERVIEW_PROMPT`

Functional meaning:
- Requests:
  - overall score
  - dimension breakdown
  - failure surface
  - hire recommendation
  - confidence
  - summary
  - risk flags
  - strengths
  - claim credibility risk
  - untested dimensions

Architectural meaning:
- This prompt is not just "score the interview."
- It is also the report schema for the entire product.

What is strong here:
- It explicitly distinguishes claim credibility from overall engineering judgment.
- It explicitly instructs the model to respect narrow coverage and mark untested dimensions as inconclusive.
- `INSUFFICIENT_DATA` is an excellent category. It prevents fake precision.

What is weak:
- The prompt surface contains mojibake in several crucial instructions, which is risky in a schema-defining prompt.
- The schema is rich, but there is no local normalization or validation after the model returns.

#### `backend/agents/evaluation_agent.py:84-129`

`_build_calibration_context(...)`

Functional meaning:
- Builds a compact context string from:
  - target role
  - years of experience
  - experience tier
  - parsed claims
  - project ownership summaries

Architectural meaning:
- This is the calibration bridge between `ResumeAgent` and evaluation.

What it does well:
- It uses the strongest parts of the parsed resume schema.
- It keeps claim credibility and ownership visible to the evaluator.

What it misses:
- The per-answer scoring path calls `_build_calibration_context()` without passing `parsed_resume`, so full evaluation is better calibrated than live per-answer scoring.

#### `backend/agents/evaluation_agent.py:132-141`

Class docstring and constructor.

Functional meaning:
- Documents the two-mode design.
- Uses `LLMRouter(tier="large")`.

Architectural meaning:
- Using the large tier here makes sense.
- This is where the system is allowed to spend more latency and cost for better synthesis.

#### `backend/agents/evaluation_agent.py:143-168`

`score_answer(...)`

Functional meaning:
- Runs `_score_once()` three times in parallel.
- Averages the top-level score and confidence.
- Returns the breakdown from only the first valid result.

Architectural meaning:
- This is a classic anti-variance trick: multi-pass averaging.

What it does well:
- It acknowledges that one LLM judgment is noisy.

What it gets wrong:
- It averages only the top-level score, not the breakdown categories.
- So the returned breakdown is not actually the averaged judgment; it is just one sample.
- That creates a hidden mismatch between the reported per-answer score and the detailed sub-scores attached to it.

#### `backend/agents/evaluation_agent.py:170-281`

`score_full_interview(...)`

Functional meaning:
- Builds:
  - transcript text from full history
  - weakness summary
  - reasoning summary
  - per-answer score summary
  - coverage note
  - calibration context
- Then asks the large model for the final structured evaluation.

Architectural meaning:
- This is the true report compiler for the product.

Breaking down the important sub-blocks:

1. Transcript assembly
   - `evaluation_agent.py:187-196`
   - Converts history into one transcript blob with sprint/persona context.

2. Weakness summary
   - `evaluation_agent.py:198-201`
   - Compresses weaknesses into a concise list.

3. Reasoning behavior aggregation
   - `evaluation_agent.py:203-219`
   - Uses average structure and dominant adaptability.
   - Uses only the first turn's `clarification_behavior`.

4. Per-answer score summary
   - `evaluation_agent.py:221-225`
   - Reduces per-answer scores to one overall average.

5. Coverage note
   - `evaluation_agent.py:227-245`
   - Warns the model when the weakness evidence base is narrow.

6. Final call + fallback
   - `evaluation_agent.py:267-281`
   - Returns raw dict if parse succeeded, otherwise emits a minimal `INSUFFICIENT_DATA`-style fallback.

What it does well:
- It is explicitly trying to prevent overconfident broad judgment from narrow evidence.
- It combines multiple signal sources instead of trusting only transcript text.
- It preserves the separation between local claim-risk issues and overall recommendation.

What is weak:
- Most of the summarization is lossy.
- `clarification_behavior` is not truly aggregated.
- Per-answer scoring contributes only an average, not a trend or distribution.
- There is no schema repair if the LLM returns partially malformed structured data.

#### `backend/agents/evaluation_agent.py:283-300`

`_score_once(...)`

Functional meaning:
- Calls the per-answer prompt with question, answer, and lightweight calibration context.

Architectural meaning:
- This is the primitive scoring unit used three times by `score_answer()`.

Important limitation:
- It does not receive `parsed_resume`.
- So live per-answer scoring is calibrated by role/YOE text only, while full evaluation is calibrated by richer structured resume context.

### How `EvaluationAgent` Becomes Product Behavior

#### Live per-answer scoring

Relevant code:
- `backend/services/orchestrator.py:760-785`

What happens:
- The background pipeline fires `_score_answer_async()` without blocking the response path.
- Scores are stored in `self._per_answer_scores[session_id]`.

Architectural meaning:
- This path is best thought of as supporting evidence for final evaluation, not as a live UX feature.

#### Session-end evaluation

Relevant code:
- `backend/services/orchestrator.py:705-730`

What happens:
- On `end_session()`, the orchestrator gathers:
  - history
  - weaknesses
  - reasoning signals
  - per-answer scores
  - coverage ratio
  - role/YOE
  - parsed resume
- Then calls `score_full_interview()`.

Architectural meaning:
- This is the true convergence point of the interview loop.

#### API contract

Relevant code:
- `backend/api/routes.py:147-170`
- `backend/api/routes.py:351-383`

What happens:
- `/end_interview/{session_id}` exposes a small summary.
- `/report/{session_id}` exposes most of `final_evaluation` directly plus weakness summaries/raw weaknesses.

Architectural meaning:
- `EvaluationAgent` is effectively defining the public report schema.

#### Frontend report rendering

Relevant code:
- `app/report/[session_id]/page.tsx:5-278`

What happens:
- The report page renders:
  - recommendation
  - confidence
  - summary
  - claim credibility risk
  - score breakdown
  - untested dimensions
  - failure surface
  - strengths
  - risk flags
  - raw weakness log

Architectural meaning:
- The frontend mostly trusts the backend evaluation contract.
- So any schema drift, inconsistency, or low-quality judgment in `EvaluationAgent` shows up almost directly to the user.

#### Persistence

Relevant code:
- `backend/db/postgres.py:84-114`
- `backend/services/orchestrator.py:744-754`

What happens:
- Only a reduced summary is persisted:
  - hire recommendation
  - overall score
  - sprint reached
  - duration
  - resume snippet

Architectural meaning:
- The rich evaluation remains in Redis/session state, while Postgres stores only a dashboard-facing summary.

### What `EvaluationAgent` Is Doing Well

1. It has the right product philosophy.
   - It explicitly separates claim credibility from overall engineering judgment.

2. It takes coverage seriously.
   - `INSUFFICIENT_DATA` and `untested_dimensions` are strong design choices.

3. It synthesizes multiple signal streams.
   - Transcript, weaknesses, reasoning behavior, per-answer scores, and calibration context all contribute.

4. It uses the expensive model tier in the right place.
   - Final evaluation is exactly where spending more quality budget makes sense.

5. It powers a rich user-facing report.
   - The output schema is meaningfully better than a simple score/verdict pair.

### Where `EvaluationAgent` Is Messing Up

1. The two evaluation modes are unevenly calibrated.
   - Full evaluation gets `parsed_resume`.
   - Per-answer scoring does not.

2. Multi-pass averaging is only half-done.
   - `score_answer()` averages the scalar score but reuses just the first breakdown sample.

3. Output validation is too trusting.
   - If the model returns a dict, it is accepted as-is.
- There is no normalization of:
  - breakdown keys
  - enum values
  - confidence bounds
  - failure surface numeric ranges

4. Some important summaries are lossy.
   - Clarification behavior is effectively sampled from the first reasoning signal only.
   - Per-answer scores are reduced to one average without showing spread or trend.

5. The coverage heuristic is narrow.
   - Coverage is inferred from weakness-type diversity, which is useful but incomplete.
   - A broad interview could still have repetitive weakness labels.
   - A narrow interview could still look diverse at the weakness-label level.

6. The prompt surface is a core contract but contains corrupted characters.
   - This matters more here than almost anywhere else because the file is defining the final report schema.

7. It mixes raw transcript evaluation with summarized side-channel signals in one big prompt blob.
   - That works, but it is not especially inspectable or robust.

### Cross-Agent Reality Check

#### Relationship with `ResumeAgent`

What happens:
- `EvaluationAgent` uses parsed claims, ownership signals, and experience tier for calibration.

Architectural lesson:
- Final judgment quality depends meaningfully on upstream claim parsing quality.

#### Relationship with `WeaknessAgent`

What happens:
- Weakness history is summarized into one weakness list and partially used as a coverage proxy.

Architectural lesson:
- `EvaluationAgent` is inheriting not just the candidate's performance, but also the interview's probing behavior.

#### Relationship with `ReasoningBehaviorAgent`

What happens:
- Adaptability and structure signals feed directly into the final summary.

Architectural lesson:
- This is one of the main places where the system's fairness layer cashes out in the final report.

#### Relationship with `DiscrepancyAgent`

What happens:
- There is no separate structured discrepancy summary fed in directly.
- Claim credibility concerns are expected to emerge through transcript/weakness history/report synthesis rather than through a richer dedicated discrepancy channel.

Architectural lesson:
- The final evaluator is underusing one of the system's most important trust signals.

#### Relationship with the Frontend Report

What happens:
- The report page mostly renders the evaluation payload directly.

Architectural lesson:
- `EvaluationAgent` is not just an internal scorer; it is effectively the author of the user-facing report narrative.

### Best Version of `EvaluationAgent`

The best version of this agent should stay synthesis-focused, but become more consistent, more normalized, and more explicit about evidence quality.

#### Stage 1: Hardening

1. Normalize all returned fields.
   - Clamp:
     - scores
     - confidence
     - failure surface values
     - recommendation enums
     - claim-risk enums

2. Fix per-answer multi-pass averaging.
   - Average the breakdown categories too, not just the scalar score.

3. Use consistent calibration inputs across both modes.
   - Per-answer scoring should be able to consume `parsed_resume` too.

4. Clean prompt encoding.
   - This file defines a report contract; corrupted prompt text is high-risk.

#### Stage 2: Better Synthesis

1. Improve behavioral aggregation.
   - Aggregate `clarification_behavior` meaningfully instead of sampling the first turn.

2. Improve coverage modeling.
   - Use more than weakness-type diversity as the evidence-breadth signal.

3. Feed structured discrepancy signal explicitly.
   - Claim credibility risk should not rely only on transcript osmosis.

4. Consider per-answer score trends.
   - Growth, collapse under pressure, and recovery are all more informative than a single average.

#### Stage 3: System-Level Optimization

1. Separate evidence pack from prompt prose.
   - Build a more explicit structured evaluation input instead of a long concatenated blob.

2. Make degraded mode explicit in the report.
   - If final evaluation fell back or key evidence streams were missing, surface that clearly.

3. Consider partial persistence of richer report data.
   - Right now Postgres stores only a thin summary, which limits downstream dashboard/reporting quality.

4. Keep the distinction between claim credibility and engineering strength.
   - This is one of the best design choices here and should remain central.

### Mentor Verdict

`EvaluationAgent` has the right ambition.

It is not trying to compress the interview into one dumb score.
It is trying to answer a harder and more honest question:

- what was actually tested
- what did the candidate actually demonstrate
- how broad was the evidence
- how much of the risk is local to a claim versus broad to the engineer

That is excellent.

Its biggest problem is not philosophical. It is contract discipline.
The product depends on this file as both:

- the final judge
- the report schema

That means loose normalization, lossy summaries, and uneven calibration matter a lot more here than they would in an internal helper.

So the path to optimality is:

- make both modes more consistent
- validate and normalize aggressively
- preserve evidence quality explicitly
- keep the report honest about uncertainty and coverage

### Next Recommended Deep Dive

`ConceptAgent` should be next.

Reason:
- We have now reviewed the full judgment path from claim ingestion to final report synthesis.
- `ConceptAgent` is the last core agent in the live loop that we have not locked in at this same level.
- After that, the natural next step is the orchestrator itself as the cross-agent runtime brain.

---

## Agent 7: `ConceptAgent`

Primary file:
- `backend/agents/concept_agent.py`

Main integration points:
- `backend/api/routes.py:123-130`
- `backend/services/orchestrator.py:795-871`
- `backend/services/orchestrator.py:916-923`
- `backend/services/orchestrator.py:1565-1583`
- `backend/services/orchestrator.py:1327-1334`
- `lib/audio.ts:250-279`
- `lib/audio.ts:489-523`

### Mission

`ConceptAgent` is the system's concept-surface extractor.

At a high level, its job is simple:

- look at the candidate's answer
- pull out the important technical concepts

In the original architecture, that would have made it a key upstream signal for follow-up generation and reasoning pressure.

In the current architecture, its role has shifted.
The live system now prefers frontend-supplied entities from Deepgram and partial-transcript accumulation.
So `ConceptAgent` has become mostly a backend fallback for concept/entity extraction when those upstream signals are absent.

That makes this deep dive less about "how good is the agent prompt?" and more about "how load-bearing is this agent now, and what role should it still play?"

### Full File Walkthrough

#### `backend/agents/concept_agent.py:1`

`from backend.models.llm_router import LLMRouter`

Functional meaning:
- Uses the shared router and inherits its loose `dict | str` return behavior.

Architectural meaning:
- Because the file itself is tiny, almost all of its robustness depends on how callers guard it.

#### `backend/agents/concept_agent.py:4-11`

Prompt definition.

Functional meaning:
- Ask for a list of key technical concepts from the candidate answer.
- Ignore filler.
- Return JSON of the form `{"concepts": [...]}`.

Architectural meaning:
- This is intentionally minimal.
- The agent is trying to be a fast label extractor, not a semantic analyzer.

What is good here:
- The prompt is short and easy to reason about.
- It keeps the task narrow, which is appropriate for a fast extraction agent.

What is weak:
- "technical concepts" is underspecified.
- It does not distinguish:
  - named entities
  - tools
  - algorithms
  - architectural components
  - buzzwords
- There is no schema guidance for deduplication, normalization, or granularity.

#### `backend/agents/concept_agent.py:14-19`

Class docstring.

Functional meaning:
- Describes the agent as running in parallel every turn with a low-latency target.

Architectural meaning:
- This reflects the older or more general design intent.
- In the current live path, that statement is only conditionally true because the agent is skipped whenever entities are already present.

#### `backend/agents/concept_agent.py:21-22`

`self.llm = LLMRouter(tier="small")`

Functional meaning:
- Uses the cheapest/fastest model tier.

Architectural meaning:
- This is exactly the right tier for a lightweight extraction fallback.

#### `backend/agents/concept_agent.py:24-32`

`extract(answer)`

Functional meaning:
- Call the LLM and return `result.get("concepts", [])`.

Architectural meaning:
- This is the file's biggest weakness.
- It assumes the router returned a dict.
- If the router returns a string, this method throws.

Important runtime nuance:
- The orchestrator wraps this call in `_safe_concepts()` and catches exceptions, so the system usually degrades to `[]`.
- That means the agent's fragility is partially hidden by caller-side resilience.

### How `ConceptAgent` Becomes Product Behavior

#### Frontend-first entity flow

Relevant code:
- `lib/audio.ts:250-279`
- `lib/audio.ts:489-523`
- `backend/api/routes.py:123-130`
- `backend/services/orchestrator.py:795-871`
- `backend/services/orchestrator.py:916-923`

What happens:
- Deepgram browser-side transcription provides entity data on final transcript blocks.
- The frontend accumulates those entities in `entityBuffer`.
- It sends them through:
  - `/partial_transcript`
  - `/process_turn`
- The orchestrator accumulates them in `_partial_entities`.
- On committed turn handling, those accumulated entities are merged into the canonical turn payload.

Architectural meaning:
- In the modern live path, concept/entity extraction is frontend-first, not `ConceptAgent`-first.

This is the most important truth about the agent today.

#### Backend fallback extraction

Relevant code:
- `backend/services/orchestrator.py:1565-1583`

What happens:
- If `entities` are already present, the orchestrator does:
  - `concepts = entities`
  - `concepts_ms = 0.0`
- Only when entities are absent does `_safe_concepts()` call `self.concept_agent.extract(text)`.

Architectural meaning:
- `ConceptAgent` is now a fallback path, not the primary concept source.

#### Speculative generation relationship

Relevant code:
- `backend/services/orchestrator.py:851-871`
- `backend/services/orchestrator.py:2051-2146`

What happens:
- Speculative follow-up generation during partial transcripts is triggered by:
  - new entities
  - admission signals
  - longer rolling transcript snapshots
- It does not use `ConceptAgent`.

Architectural meaning:
- Another major product path that might once have depended on concept extraction now bypasses the agent entirely.

#### History storage

Relevant code:
- `backend/services/orchestrator.py:1327-1334`
- `backend/services/orchestrator.py:1857-1858`

What happens:
- Extracted `concepts` are stored into staged analysis and then canonical history.

Architectural meaning:
- Even though the agent does not currently drive much routing, it still contributes to the historical record.

Important limitation:
- I did not find strong downstream logic that meaningfully uses stored `concepts` later.
- They appear to be more of a captured artifact than a decisive control signal in the current architecture.

### What `ConceptAgent` Is Doing Well

1. It is appropriately simple for its job.
   - The file is tiny, the prompt is narrow, and the chosen model tier is sensible.

2. It is cheap enough to keep as a fallback.
   - If upstream entities are missing, the system still has a way to recover some concept surface.

3. It reveals a healthy architectural evolution.
   - The system moved from backend LLM extraction toward faster frontend-provided entity signals where possible.

### Where `ConceptAgent` Is Messing Up

1. Its local contract is too fragile.
   - `extract()` assumes a dict and will throw on raw string output.

2. The concept ontology is too vague.
   - "technical concepts" can mean many things, and the output does not clearly distinguish them.

3. It is barely load-bearing in the current runtime.
   - Most live paths now prefer frontend/Deepgram entities instead.

4. Its downstream impact is weak.
   - Concepts are stored in history, but they do not currently appear to meaningfully influence many later decisions.

5. The repo documentation and code intent have drifted a bit.
   - The class docstring implies it runs every turn in parallel, but the actual orchestrator now skips it whenever entities are available.

### Cross-Agent Reality Check

#### Relationship with the Frontend Audio Layer

What happens:
- `lib/audio.ts` extracts and buffers entity signals from Deepgram NER and sends them eagerly to the backend.

Architectural lesson:
- The frontend audio layer has effectively taken over most of the concept-surface job for live runtime behavior.

#### Relationship with `FollowUpAgent`

What happens:
- `FollowUpAgent.prefetch()` can generate speculative questions from `concepts`, but I did not find a live orchestrator call path using that method.

Architectural lesson:
- There is a likely legacy seam here:
  - old concept-driven speculative path
  - newer entity/admission/rolling-transcript speculative path

#### Relationship with `WeaknessAgent` / `DiscrepancyAgent` / `ReasoningBehaviorAgent`

What happens:
- Those agents do not currently consume `ConceptAgent` output directly in the current live branch.

Architectural lesson:
- `ConceptAgent` is not one of the main control-plane agents anymore.

#### Relationship with `Orchestrator`

Relevant code:
- `backend/services/orchestrator.py:1565-1583`

What happens:
- The orchestrator decides whether concepts come from:
  - frontend entities
  - or `ConceptAgent` fallback

Architectural conclusion:
- The orchestrator has already demoted `ConceptAgent` from primary extractor to backup extractor.

### Best Version of `ConceptAgent`

The best version of this agent should either become a clearly defined fallback utility or be promoted back into a more purposeful semantic role.

Right now it sits in an awkward middle state.

#### Stage 1: Hardening

1. Normalize output locally.
   - If the router returns a string or malformed dict, return `[]` safely instead of throwing.

2. Clarify the extraction contract.
   - Decide whether output should represent:
     - entities
     - concepts
     - technologies
     - architectural components
     - or a normalized mix

3. Add lightweight deduping/normalization.
   - Lowercasing, trimming, and duplicate removal would make the output more stable.

#### Stage 2: Architectural Decision

1. Decide whether this is still needed as an agent.
   - If frontend entities are reliable enough, keep it as a fallback helper and document that clearly.

2. Or give it a richer semantic job.
   - For example:
     - map raw entities into normalized concept families
     - detect jargon clusters
     - bridge noisy ASR entities into more useful conceptual labels

3. Remove stale/legacy concept-driven paths if they are truly dead.
   - Especially if `FollowUpAgent.prefetch()` is no longer part of the active runtime.

#### Stage 3: Better System Cooperation

1. If kept, connect stored concepts to something meaningful.
   - topic continuity
   - report surfacing
   - failure-surface evidence
   - question-bank alignment

2. If not, simplify the architecture.
   - A fallback utility might be enough; it does not necessarily need to remain framed as a major agent.

### Mentor Verdict

`ConceptAgent` is not bad.
It is just no longer central in the way the rest of the architecture evolved.

That is actually okay.

Sometimes the healthiest thing in a codebase is not to make every component more sophisticated.
Sometimes it is to recognize that a once-important component has become:

- a safety net
- a compatibility layer
- or a candidate for removal/refactoring

That is what this looks like.

So the path to optimality is not "make concept extraction smarter" by default.
It is:

- decide whether this is a real control-plane agent or just a fallback extractor
- harden it accordingly
- align the docs and runtime reality
- either promote its semantic value or simplify it

### Next Recommended Deep Dive

`backend/services/orchestrator.py` should be next.

Reason:
- We have now reviewed the full core-agent surface.
- The orchestrator is where these agents are actually fused into one runtime brain.
- That is the natural next step if we want to move from per-agent mentoring into system-level architectural mentoring.

## System 8: `Orchestrator`

### Mission

`Orchestrator` is the real runtime brain of the product.

This file now owns five different jobs at once:

1. session startup and readiness
2. committed-turn fast response selection
3. background full-agent analysis and staging
4. speculative partial-transcript preparation
5. sprint progression and interview termination

Architecturally, this means the orchestrator is no longer just a router.

It is the place where the product's actual interview philosophy gets turned into execution policy:
- what gets asked now
- what gets staged for later
- what gets ignored
- what counts as a revision
- when to stay on-thread
- when to pivot
- when to end

That makes it the most strategically important file in the backend.

### Full File Walkthrough

#### `backend/services/orchestrator.py:1-52`

What lives here:
- imports
- trajectory-map helpers from `backend/services/interview_map.py`
- telemetry wiring
- local fallback payloads

Architectural meaning:
- the orchestrator now depends directly on the new interview-map layer, not just the classic agents.
- this is an explicit shift from "purely reactive live follow-up generation" toward a hybrid of:
  - reactive live agents
  - deterministic packet scheduling
  - resume-grounded fallback map retrieval

Important bug signal:
- `_REASONING_FALLBACK` uses `structure_score: 5` even though the reasoning contract is `0-3`.
- Relevant code:
  - `backend/services/orchestrator.py:72-75`
  - `backend/agents/reasoning_behavior_agent.py:22-24`

#### `backend/services/orchestrator.py:53-243`

This block defines the transcript/focus primitives:
- admission detection
- transcript normalization
- echo filtering
- resume-focus candidate extraction
- focus inference

What it translates to functionally:
- the orchestrator tries to infer "what project/thread are we actually talking about?" from lightweight lexical overlap, not from a heavyweight memory graph.

Architectural meaning:
- focus tracking is pragmatic and cheap.
- that is a good instinct for a real-time voice system.
- the downside is that downstream quality becomes highly sensitive to whether focus metadata is preserved correctly later.

#### `backend/services/orchestrator.py:246-497`

This helper block handles:
- seed relevance checks
- substantive-answer thresholding
- over-probed topic collection
- continuity brief generation
- bank-follow-up priority rules
- short-answer rescue eligibility
- question-packet construction/cloning
- sprint opener fallback text

This is the orchestrator's local scheduler language.

Architectural meaning:
- the file is trying to treat each question as a packet with memory:
  - text
  - route kind
  - focus
  - follow-up budget
  - pivot state

That is a strong architectural move.

It gives the runtime something more durable than raw strings.

#### `backend/services/orchestrator.py:531-602`

This section adds version helpers and `_upsert_turn_skeleton()`.

What it does:
- every committed answer can now get:
  - `turn_id`
  - `answer_version`
  - a pending history skeleton

Why that matters:
- continuity no longer has to wait for the slow pipeline.
- the conversation gets immediate memory, even before full weakness/discrepancy/reasoning analysis returns.

This is one of the best design decisions in the file.

#### `backend/services/orchestrator.py:665-801`

This is `start_session()`.

What it does:
- parses the resume
- builds the initial Redis session state
- saves the opening packet
- then awaits both:
  - `_seed_first_question()`
  - `_build_interview_map()`
- then re-reads Redis and refuses to start if the interview map has no focus areas

Important clarification from the current live code:
- the startup contract now really does block on map creation.
- older prose elsewhere in the repo said this still happened in background via `asyncio.create_task(...)`.
- that is stale now.

Architectural meaning:
- the product has intentionally traded some startup latency for higher Turn-1 correctness.
- that is consistent with the user's product direction.

#### `backend/services/orchestrator.py:803-924`

This block handles:
- `end_session()`
- queued analysis flush
- final evaluation
- fire-and-forget Postgres persistence
- per-answer scoring helper

What it means functionally:
- end-of-interview correctness depends on whatever staged analysis actually made it into Redis before completion.

Architectural pressure point:
- this whole section assumes staged analysis is trustworthy and complete.
- any bug in the staging pipeline propagates directly into the final report.

#### `backend/services/orchestrator.py:929-1009`

This is the live partial-transcript path.

What it does:
- rejects stale snapshots by sequence
- accumulates partial entities
- detects admissions
- triggers speculative generation on:
  - new entities
  - admission signals
  - sufficiently long rolling transcript snapshots

Architectural meaning:
- the orchestrator now treats partial speech as speculative planning input, not canonical truth.
- that is the right contract.

#### `backend/services/orchestrator.py:1011-1785`

This is the fast path, and it is the most important runtime block in the repo.

What happens in order:

1. load session state and guard against completed interviews
2. detect same-turn revision via `turn_id`
3. merge partial entities into the committed answer
4. reject question-echo garbage
5. consume staged analysis from prior turns
6. infer current focus and write immediate turn skeleton
7. choose the next spoken question from a priority ladder:
   - active packet follow-up
   - staged prepped question
   - trajectory-map promotion over generic staged fallback
   - speculative question
   - trajectory-map retrieval
   - short-answer rescue
   - generic sprint fallback
8. maybe advance the sprint
9. save current-answer state
10. spawn the full background pipeline

Architectural meaning:
- this is not just a function.
- this is effectively a state machine compressed into one method.

Good news:
- the control flow is much more intentional than a naive "always call the LLM again" loop.

Bad news:
- the correctness of the whole interview now depends on a large number of state-shape invariants all staying aligned:
  - `history`
  - `current_answer_*`
  - `prepped_turn_queue`
  - `prepped_next_*`
  - `active_question_packet`
  - `speculative_cache`
  - `latest_turn_versions`
  - `interview_trajectory_map`

That is a lot of moving parts for one file to keep coherent.

#### `backend/services/orchestrator.py:1787-1865`

This is `_apply_staged_analysis()`.

What it does:
- merges completed background analysis into canonical history
- appends weakness ledger entries
- updates candidate memory
- restores follow-up sequencing metadata

Architectural meaning:
- this is the canonical-state mutation gate.
- if this function receives duplicate or malformed staged payloads, the interview's remembered truth changes.

That makes it one of the most dangerous write points in the repo.

#### `backend/services/orchestrator.py:1870-2477`

This is the slow path background pipeline.

What it does:
- inflight guards
- parallel agent execution:
  - weakness
  - discrepancy
  - reasoning
  - concepts fallback when needed
- honesty soft-cap
- focus/breadth guard logic
- route selection for next question
- candidate-model updates
- staging queue write
- next-question staging
- TTS pre-generation dispatch

Architectural meaning:
- this is where the orchestrator interprets the agents, not merely calls them.

That distinction matters.

The agents emit signals.
The orchestrator decides what those signals are allowed to mean in runtime policy.

This is why the orchestrator is the true owner of interview behavior.

#### `backend/services/orchestrator.py:2483-2745`

This block contains:
- `_seed_first_question()`
- `_build_interview_map()`
- `_run_speculative_generation()`

What it means:
- startup prep and live speculative prep now coexist in the same orchestration layer.
- the file is trying to create a two-timescale system:
  - session-start structure
  - turn-by-turn structure
  - sub-turn speculative refinement

That is ambitious and mostly directionally correct.

#### `backend/services/orchestrator.py:2750-2859`

This is sprint advancement and completion logic.

What it does:
- resets sprint-local counters/guardrails
- synthesizes a partial prior-turn record if needed
- generates sprint openers
- ends the interview on:
  - sprint exhaustion
  - 30-minute limit
  - repeated terminal honest admissions

Architectural meaning:
- this file is also the owner of interview pacing and closure, not just immediate question selection.

### How `Orchestrator` Becomes Product Behavior

#### Startup readiness

Relevant code:
- `backend/services/orchestrator.py:665-801`
- `backend/api/routes.py:56-101`
- `app/interview/[session_id]/page.tsx:718-732`

What happens:
- backend startup now blocks until both the first seed and the interview trajectory map are ready.
- `/api/start_interview` returns a preview of trajectory focus areas.
- the interview page now treats a missing map as a startup error.

Architectural meaning:
- "ready" now means structurally ready, not "session row exists in Redis."

#### Real-time question scheduling

Relevant code:
- `backend/services/orchestrator.py:1158-1771`

What happens:
- committed answers are resolved through a layered priority system that mixes:
  - deterministic packet follow-ups
  - staged analysis output
  - speculative partial-STT prep
  - trajectory-map retrieval
  - emergency generic fallback

Architectural meaning:
- the product no longer has one question-generation mechanism.
- it has a scheduler that arbitrates among several mechanisms.

That is powerful, but it means scheduler bugs are now product bugs.

#### Focus continuity and topic steering

Relevant code:
- `backend/services/orchestrator.py:1170-1177`
- `backend/services/orchestrator.py:2088-2175`
- `backend/services/interview_map.py:561-824`

What happens:
- focus is inferred from the live question/answer pair.
- that focus selects prompt context, over-probed topics, breadth guards, and trajectory-map branches.

Architectural meaning:
- focus metadata is now one of the most load-bearing concepts in the whole system.

#### Same-turn revision handling

Relevant code:
- `backend/services/orchestrator.py:1044-1053`
- `backend/services/orchestrator.py:1890-1943`
- `backend/services/orchestrator.py:2321-2340`

What happens:
- revisions increment `answer_version`.
- older staged analyses are supposed to self-discard.

Architectural meaning:
- this is the system's attempt at making fragmented STT behave like one human answer.

This is the right problem to solve.

The current implementation is close, but not correct yet.

### What `Orchestrator` Is Doing Well

1. It has real product intent.
   - This is not a random async blob. The file clearly encodes policies about continuity, honesty, breadth, speed, and fallback quality.

2. The packet model is a major improvement over raw question strings.
   - `active_question_packet` and `prepped_next_packet` are the beginnings of a real interview scheduler abstraction.

3. The fast-path versus slow-path split is directionally excellent.
   - It keeps latency low without throwing away deeper analysis.

4. The startup contract is stronger now.
   - Blocking on trajectory-map readiness is a better product contract than racing Turn 1 against background prep.

5. The file increasingly thinks in terms of explicit state transitions.
   - turn skeletons, answer versions, speculative cache versions, and packet focus are all signs of a system maturing beyond ad hoc prompt calls.

### Where `Orchestrator` Is Messing Up

1. The legacy staging shadow still exists, and it is now actively dangerous.
   - Relevant code:
     - `backend/services/orchestrator.py:1104-1113`
     - `backend/services/orchestrator.py:1787-1819`
     - `backend/services/orchestrator.py:2350-2429`
   - The background pipeline writes both:
     - `prepped_turn_queue`
     - `prepped_turn_analysis` / `prepped_next_metadata`
   - On the next turn, `handle_transcript()` appends the legacy staged payload back into the queue.
   - `_apply_staged_analysis()` then applies both.
   - The queue payload includes `focus_key` and `focus_label`.
   - The legacy payload does not.
   - Result: the second apply can overwrite a fully enriched turn with empty focus metadata.

2. Same-turn revision suppression can leave the newest answer with no full analysis at all.
   - Relevant code:
     - `backend/services/orchestrator.py:1747-1756`
     - `backend/services/orchestrator.py:1921-1939`
     - `backend/services/orchestrator.py:2321-2340`
   - If v1 of a turn is already in the background pipeline, v2 is skipped by `_turn_pipeline_running`.
   - Then when v1 finishes, it sees a newer `latest_turn_versions` entry and discards itself as stale.
   - No replacement pipeline is scheduled for the newest revision.
   - That means the final revised answer can be left with only a pending skeleton and no completed weakness/discrepancy/reasoning analysis.

3. The trajectory-map fast path loses its own metadata before state is saved.
   - Relevant code:
     - `backend/services/orchestrator.py:1586-1648`
   - In the trajectory-map branch, `active_packet` is first built with:
     - the correct focus overrides
     - bridge pivot state
   - Then it is rebuilt unconditionally a few lines later without those overrides.
   - That can erase:
     - exact focus identity
     - bridge/pivot intent
   - So the route is selected correctly, but the packet metadata that downstream logic relies on gets flattened.

4. The reasoning fallback is contract-invalid.
   - Relevant code:
     - `backend/services/orchestrator.py:72-75`
     - `backend/agents/reasoning_behavior_agent.py:22-24`
   - `structure_score: 5` is outside the agent's own declared range.
   - That makes fallback-path reasoning incomparable to real reasoning output.

5. This file still carries too many overlapping state shapes.
   - canonical turn history
   - skeleton turns
   - staged queue items
   - legacy staged shadow
   - prepped next question
   - question packets
   - speculative cache
   - trajectory map
   - current-answer state
   - latest-turn version map

Architecturally, that is the core maintainability risk.

### Cross-Agent Reality Check

#### Relationship with `FollowUpAgent`

What happens:
- `FollowUpAgent` no longer "owns the next question."
- the orchestrator decides when live generation is allowed to win versus when packet memory or trajectory retrieval should win.

Architectural lesson:
- `FollowUpAgent` is now a specialized generator living inside a larger scheduler.

#### Relationship with `WeaknessAgent`, `DiscrepancyAgent`, and `ReasoningBehaviorAgent`

What happens:
- those agents provide important signals, but the orchestrator applies the guardrails:
  - honesty soft-cap
  - contradiction budget
  - deflection budget
  - breadth forcing
  - Sprint 3 strategy remap

Architectural lesson:
- agent quality matters, but orchestration policy matters more.

#### Relationship with `ResumeAgent` and `interview_map`

What happens:
- startup now builds a resume-grounded trajectory map.
- focus prompt packs pull exact resume snippets into many follow-up generation paths.

Architectural lesson:
- the orchestrator is now the integration point between:
  - parsed candidate model
  - raw resume grounding
  - live turn routing

#### Relationship with the Frontend Audio Layer

What happens:
- the frontend now co-owns turn integrity:
  - `turn_id`
  - partial snapshots
  - entity accumulation
  - final commit timing

Architectural lesson:
- the orchestrator is no longer a purely backend concern.
- it is tightly coupled to frontend turn semantics.

#### Relationship with `SessionManager`

What happens:
- nearly every important orchestrator action is a read-modify-write of one Redis JSON blob.

Architectural lesson:
- even a well-designed scheduler becomes fragile if its state store is too coarse-grained.

### Best Version of `Orchestrator`

This file does not need a cosmetic cleanup first.

It needs a correctness-first consolidation.

#### Stage 1: Fix the dangerous state bugs

1. Remove or fully deduplicate the legacy staging shadow.
   - Pick one staging representation.
   - Do not keep both queue and legacy payloads alive.

2. Guarantee that the newest same-turn revision gets a completed background analysis.
   - Either:
     - cancel and replace the old pipeline
     - or queue the newest revision to run immediately after the in-flight one ends

3. Preserve trajectory-map packet metadata.
   - Do not rebuild a trajectory-selected packet without carrying forward focus overrides and pivot flags.

4. Fix invalid fallback schemas.
   - especially `_REASONING_FALLBACK`

#### Stage 2: Split policy from storage mutation

1. Extract a dedicated fast-path scheduler object.
2. Extract a dedicated background-route planner.
3. Extract canonical-state application into a narrower reducer-style module.

Right now one file is doing all three jobs.

#### Stage 3: Add scenario-level tests around the real product risks

The most valuable tests are not unit tests of tiny helpers.

They are scenario tests for:
- same-turn revision while background pipeline is in flight
- trajectory-map bridge serving and packet preservation
- startup with map present versus missing
- duplicate staged payload handling
- short-answer rescue followed by substantive recovery
- sprint transition after a trajectory-selected fast response

### Mentor Verdict

`Orchestrator` is the strongest and riskiest file in the repo at the same time.

It contains some of the smartest product thinking in the backend:
- packetized follow-up scheduling
- speculative sub-turn prep
- resume-grounded fallback structure
- honesty-aware pressure control

But it is also carrying too much state responsibility by itself.

The file does not mainly suffer from "bad ideas."
It suffers from "too many good ideas stacked into one place without enough structural separation."

That is why the next step is not to simplify the interview logic.
It is to protect the logic from state-shape drift.

### Next Recommended Deep Dive

`backend/services/interview_map.py` should be next.

Reason:
- the orchestrator now depends on it in the startup path, fast path, speculative path, and sprint transition path.
- it is no longer an optional sidecar; it is part of the live control plane.
- after that, `backend/state/session_manager.py` is the next high-leverage systems pass because the orchestrator's concurrency story depends on it.

## System 9: `Interview Map`

### Mission

`backend/services/interview_map.py` is the repo's attempt to give the interview a precomputed spine.

Its job is not to replace the live agents.

Its job is to stop the system from becoming generic or directionless when the live path is:
- under-informed
- too slow
- too vague
- or pointed at the wrong thread

Architecturally, that means this module now owns four things:

1. focus-area extraction from the raw resume
2. per-focus question-track generation across all three sprints
3. retrieval/ranking of those tracks at runtime
4. prompt-grounding packs used by other generators

That is a lot more responsibility than a normal fallback helper.

### Full File Walkthrough

#### `backend/services/interview_map.py:1-153`

This opening block defines the module's real contract:
- valid branches
- sprint keys
- route kinds
- the full generation prompt for focus-track creation

What this means functionally:
- the map is not just "a list of questions."
- it is a structured branching object that tries to anticipate answer states:
  - strong answer
  - vague answer
  - honest gap
  - claim conflict
  - short answer
  - bridge to the next focus

Architectural meaning:
- this file is trying to externalize interview policy into a reusable substrate.
- that is a strong design instinct.

#### `backend/services/interview_map.py:155-217`

This section defines:
- generic-phrase rejection helpers
- token stopwords
- focus-key normalization
- resume line normalization

What it translates to:
- the module is trying to stay attached to the literal resume text, not just parsed abstractions.

Important observation:
- the module's real retrieval language is still token overlap, not semantic retrieval.
- that makes it fast and dependency-light, but also more brittle than the product framing might suggest.

#### `backend/services/interview_map.py:220-355`

This block handles:
- noise filtering
- snippet extraction
- fallback seed extraction from raw resume lines
- LLM seed extraction

What it means:
- the file deliberately keeps two seed sources alive:
  - LLM-readable focus extraction
  - deterministic raw-resume fallback

That is good resilience design.

But it also creates a subtle bar:
- if a seed cannot later be grounded back into exact resume snippets, it gets dropped.

That matters because startup now depends on this module succeeding.

#### `backend/services/interview_map.py:358-484`

This block is the heart of map generation:
- deterministic per-focus fallback track
- generic/off-focus rejection
- response parsing
- `_generate_focus_track()`

Architectural meaning:
- each focus area gets its own generated branch object instead of one giant monolithic JSON response.
- that is one of the best ideas in the file.

It reduces blast radius.

If one focus track fails, the whole map does not necessarily die.

#### `backend/services/interview_map.py:487-558`

This is `generate_interview_map()`.

What it does:
- extracts 3-5 focus seeds
- enriches each with exact resume snippets
- generates all focus tracks in parallel
- returns `focus_areas`

Important runtime fact:
- this is now part of the startup critical path because `start_session()` awaits it.

That changes how we should judge it.

When this was background-only, "pretty good fallback generation" was enough.
Now it needs startup-grade reliability.

#### `backend/services/interview_map.py:561-625`

This is `get_focus_area_context()`.

What it does:
- resolve the best focus area from:
  - current focus key
  - last substantive focus
  - query-token overlap
- return a compact prompt pack:
  - focus key
  - label
  - anchor context
  - exact resume snippets
  - prompt-ready context string

Architectural meaning:
- this function is how the interview map stops being isolated storage and starts influencing the other generators.

It is now a prompt-grounding service, not just a retrieval helper.

#### `backend/services/interview_map.py:628-824`

This block handles branch priority and runtime question selection.

What it does:
- chooses which branch to favor for the current answer state
- ranks search groups:
  - current focus
  - last substantive focus
  - other matching areas by overlap
- prevents immediate repeat questions
- returns:
  - question
  - route kind
  - focus identity
  - chosen branch

Architectural meaning:
- this is the module's runtime retrieval brain.

It decides whether the map behaves like:
- a same-thread deepener
- an honesty-aware rescue
- a discrepancy challenge
- a bridge
- or nothing at all

### How `Interview Map` Becomes Product Behavior

#### Startup readiness

Relevant code:
- `backend/services/interview_map.py:487-558`
- `backend/services/orchestrator.py:782-801`
- `backend/api/routes.py:56-101`

What happens:
- the map is built before `/api/start_interview` returns.
- startup now fails loudly if the map has no focus areas.

Architectural meaning:
- this module is now a required subsystem, not an optional enhancement.

#### Fast-path rescue and fallback selection

Relevant code:
- `backend/services/interview_map.py:718-824`
- `backend/services/orchestrator.py:1217-1253`
- `backend/services/orchestrator.py:1266-1467`
- `backend/services/orchestrator.py:1586-1621`

What happens:
- the orchestrator consults the map for:
  - Turn-1 seed replacement
  - honesty probes
  - short-answer rescue
  - generic-fallback replacement
  - bridge questions

Architectural meaning:
- this is no longer "backup content."
- it is a real competitor in the fast-path scheduler.

#### Prompt grounding for live generators

Relevant code:
- `backend/services/interview_map.py:561-625`
- `backend/services/orchestrator.py:29-51`
- `backend/services/orchestrator.py:1170-1177`
- `backend/services/orchestrator.py:2094-2100`

What happens:
- the orchestrator turns focus resolution into prompt context packs and passes them into:
  - speculative generation
  - clarification
  - discrepancy challenge
  - attack probes
  - adapted bank follow-ups
  - sprint openers

Architectural meaning:
- the map now influences not only what deterministic question gets picked, but also how the LLM generators speak about the current thread.

#### Manual simulation path

Relevant code:
- `backend/test_trajectory_map.py:1-230`

What happens:
- there is a scenario runner covering:
  - vague short answers
  - honest admissions
  - topic switches
  - short-but-specific answers
  - delayed Turn 1

Architectural meaning:
- the team clearly understands the right product scenarios.

Important limitation:
- this is still a smoke script, not a real assertive automated test suite.

### What `Interview Map` Is Doing Well

1. It encodes a better failure mode than generic fallback templates.
   - When live generation is weak, the system now has a more resume-aware fallback spine than "What would you do differently?"

2. The per-focus generation structure is smart.
   - Splitting the map by focus area is much more robust than asking one model call to synthesize the whole interview trajectory.

3. The exact-snippet grounding is directionally right.
   - Using raw resume snippets as source-of-truth is better than trusting parsed labels alone.

4. It is genuinely integrated.
   - The map now affects startup, fast-path retrieval, speculative refinement context, and sprint generation hints.

### Where `Interview Map` Is Messing Up

1. It is now startup-critical, but still built like an expensive best-effort generator.
   - Relevant code:
     - `backend/services/interview_map.py:451-484`
     - `backend/services/interview_map.py:487-558`
     - `backend/models/llm_router.py:9-25`
     - `backend/services/orchestrator.py:782-801`
   - The map build runs 3-5 parallel `tier="large"` generations.
   - `large` currently routes to `deepseek/deepseek-r1`.
   - `start_session()` now blocks on this.
   - That means a subsystem designed as a fallback spine is now sitting directly on the startup critical path with heavyweight model calls.

2. Seed enrichment is brittle in a startup-critical context.
   - Relevant code:
     - `backend/services/interview_map.py:231-260`
     - `backend/services/interview_map.py:503-523`
   - Any seed with no snippet overlap is silently dropped.
   - If all seeds are dropped, the map returns `{}`.
   - The orchestrator then fails session startup.
   - That is a harsh failure mode for what is still fundamentally a heuristic grounding pipeline.

3. Retrieval and prompt-grounding are related, but not fully unified.
   - `get_focus_area_context()` and `select_from_trajectory_map_detailed()` use overlapping but not identical resolution behavior.
   - That means:
     - the map can choose one focus for deterministic retrieval
     - while the prompt pack for an LLM generator may resolve slightly differently
   - Not always a bug, but definitely a coherence risk.

4. The test surface is still observational, not assertive.
   - `backend/test_trajectory_map.py` is useful for manual checking, but it does not fail CI or enforce invariants automatically.

### Cross-Agent Reality Check

#### Relationship with `ResumeAgent`

What happens:
- `ResumeAgent` gives the broader parsed candidate model.
- `Interview Map` goes back to raw resume text and reconstructs focus areas/snippets directly.

Architectural lesson:
- this module is the system's corrective force against parser blur.

#### Relationship with `FollowUpAgent`

What happens:
- `FollowUpAgent` now receives map-derived focus prompt packs and trajectory hints.

Architectural lesson:
- the map is becoming upstream scaffolding for the live generator, not just a fallback competitor.

#### Relationship with `Orchestrator`

What happens:
- the orchestrator decides when the map is allowed to win.

Architectural lesson:
- `Interview Map` is important, but it is still subordinate to orchestration policy.

#### Relationship with `LLMRouter`

What happens:
- seed extraction uses `small`
- track generation uses `large`

Architectural lesson:
- the map is trying to be cheap in extraction and expensive in authoring.

That is a reasonable idea, but now that startup blocks on it, the cost/latency tradeoff needs to be revisited.

### Best Version of `Interview Map`

#### Stage 1: Make startup-safe behavior explicit

1. Put explicit latency/timeout bounds around per-focus generation.
2. Decide what "acceptable degraded map" means before session start fails.
3. Preserve a deterministic minimum map even when snippet enrichment is weak.

#### Stage 2: Unify focus resolution

1. Use one shared focus-resolution policy for:
   - deterministic question retrieval
   - prompt grounding packs
   - runtime bridge selection

2. Log chosen focus area + branch more explicitly so debugging map behavior is easier.

#### Stage 3: Turn the smoke script into real tests

1. Assert route kinds.
2. Assert startup returns a non-empty map.
3. Assert no generic fallback appears in the covered scenarios.
4. Assert bridge questions preserve the intended focus shift.

### Mentor Verdict

`Interview Map` is a strong strategic addition.

It solves a real product weakness:
- live agents alone are too fragile to be the only source of interview direction

But the module has crossed a line.

It is no longer just a clever fallback bank.
It is now part of the session-start contract.

That means it needs to be judged less like a prompt experiment and more like infrastructure.

That is the main lesson from this pass.

### Next Recommended Deep Dive

`backend/state/session_manager.py` should be next.

Reason:
- the orchestrator and interview-map layers now depend on many concurrent read-modify-write cycles against one Redis JSON blob.
- if the state layer is weak, even good orchestration and retrieval logic will continue to lose fights against concurrency.

## System 10: `SessionManager`

### Mission

`backend/state/session_manager.py` is tiny, but it is one of the most consequential files in the repo.

Its job is not to make interview decisions.
Its job is to decide whether the rest of the system's decisions survive contact with concurrency.

In this codebase, `SessionManager` is effectively responsible for:

1. active interview state storage
2. cross-request continuity
3. cross-task coordination
4. session lifetime and expiry
5. report availability for completed sessions

That is a lot of responsibility for a four-method class.

### Full File Walkthrough

#### `backend/state/session_manager.py:1-4`

Imports only:
- `json`
- `os`
- `redis.asyncio`

Architectural meaning:
- this file intentionally stays extremely thin.

That simplicity is attractive, but it also means almost all correctness guarantees have to come from caller discipline instead of the storage layer itself.

#### `backend/state/session_manager.py:6-16`

`__init__()` does three things:
- resolve a Redis URL from `KV_URL`, `REDIS_URL`, or `STORAGE_URL`
- construct a single async Redis client
- set a fixed TTL of 3600 seconds

What this means functionally:
- every session key expires after one hour
- every save refreshes that TTL because the write path uses `setex`

Architectural meaning:
- session lifetime is not just a cache detail here.
- it is part of the product contract, whether the product intended that or not.

#### `backend/state/session_manager.py:18-19`

`save_state()` does:
- `json.dumps(state)`
- `redis.setex(session_id, ttl, serialized_state)`

This is the most important line in the file.

Why:
- the entire session is stored as one JSON blob.
- every save overwrites the entire prior state atomically as a single value.

That gives us one guarantee:
- each individual write is all-or-nothing

But it does **not** give us the guarantee the system actually needs:
- safe composition of concurrent read-modify-write cycles

#### `backend/state/session_manager.py:21-25`

`get_state()`:
- fetches the full blob
- raises `KeyError` if absent
- `json.loads()` the whole thing

Architectural meaning:
- reads are full-state reads
- callers always work on detached in-memory copies

That is exactly why the orchestrator can have lost-update races even though Redis writes are atomic.

#### `backend/state/session_manager.py:27-28`

`delete_session()` just deletes the key.

Important note:
- I did not see this as a major live control point in the runtime we just audited.

### How `SessionManager` Becomes Product Behavior

#### Every major orchestrator step depends on it

Relevant code:
- `backend/services/orchestrator.py:770`
- `backend/services/orchestrator.py:1029`
- `backend/services/orchestrator.py:1721`
- `backend/services/orchestrator.py:1946`
- `backend/services/orchestrator.py:2316`
- `backend/services/orchestrator.py:2691`

What happens:
- startup
- fast-path turn handling
- background staging
- speculative generation
- session completion

all round-trip through this class.

Architectural meaning:
- the orchestrator's sophistication is limited by the storage model here.

#### Public state and report access depend on it

Relevant code:
- `backend/api/routes.py:362-375`
- `app/report/[session_id]/page.tsx:25-31`

What happens:
- `/state/{session_id}` reads directly from Redis-backed session state
- `/report/{session_id}` also reads directly from Redis-backed session state
- the report page depends on that endpoint

Architectural meaning:
- Redis is not just ephemeral working memory.
- it is still the source of truth for completed full reports.

That is the key product consequence of this file.

#### Dashboard persistence only stores a summary

Relevant code:
- `backend/db/postgres.py:71-79`
- `backend/db/postgres.py:84-114`
- `backend/db/postgres.py:121-134`

What happens:
- Postgres stores:
  - session id
  - created_at
  - resume snippet
  - hire recommendation
  - overall score
  - sprint reached
  - duration
- it does **not** store the full interview report payload

Architectural meaning:
- completed sessions are split across two durability models:
  - summary in Postgres
  - detailed report in Redis TTL state

That split is the source of one of the biggest state bugs in the repo.

### What `SessionManager` Is Doing Well

1. It is very easy to understand.
   - There is no hidden magic here.

2. It keeps the rest of the code async-friendly.
   - No sync Redis misuse showed up in this file.

3. It centralizes environment resolution cleanly enough.
   - The rest of the backend does not have to care which Redis URL variable is set.

4. The TTL does protect against abandoned-session buildup.
   - For truly ephemeral active-session state, that is a reasonable instinct.

### Where `SessionManager` Is Messing Up

1. It treats a highly concurrent interview state machine like one replaceable JSON document.
   - Relevant code:
     - `backend/state/session_manager.py:18-25`
     - `backend/services/orchestrator.py:1029-1721`
     - `backend/services/orchestrator.py:1946-2431`
     - `backend/services/orchestrator.py:2632-2734`
   - Fast path, background pipeline, speculative path, seed generation, and interview-map startup all do independent read-modify-write cycles against the same blob.
   - This is the root cause under the race condition already logged in `bug audit.md`.

2. Completed reports are still TTL-bound.
   - Relevant code:
     - `backend/state/session_manager.py:16-19`
     - `backend/api/routes.py:370-389`
     - `app/report/[session_id]/page.tsx:25-31`
     - `backend/db/postgres.py:71-79`
   - After one hour, the Redis state expires.
   - The dashboard summary can still exist in Postgres.
   - But the full report page will 404 because `/report/{session_id}` still reads Redis state, not durable report storage.

3. The storage layer offers no native help with conflict detection.
   - There is:
     - no version stamp
     - no compare-and-swap
     - no patch/merge primitive
     - no per-field atomic operations
   - All callers have to "be careful," which is not a strong concurrency model.

4. Session keys are raw `session_id`s with no namespacing.
   - That is not the biggest risk today, but it is weak hygiene for shared Redis infrastructure.

### Cross-Agent Reality Check

#### Relationship with `Orchestrator`

What happens:
- the orchestrator assumes it can coordinate a sophisticated multi-track state machine on top of simple whole-blob reads and writes.

Architectural lesson:
- most of the orchestrator bugs we found are not just orchestration bugs.
- they are orchestration-plus-storage bugs.

#### Relationship with the Report Layer

What happens:
- the report page still needs the Redis session to exist.

Architectural lesson:
- the current product has "durable summary, ephemeral full report."
- that is almost certainly not the intended user experience.

#### Relationship with Postgres

What happens:
- Postgres only gets a stripped-down completed-session summary.

Architectural lesson:
- the system currently has no durable canonical home for the full finished interview artifact.

### Best Version of `SessionManager`

#### Stage 1: Fix durability mismatches

1. Persist full completed reports somewhere durable.
2. Stop making report retrieval depend on TTL-bound Redis state.

#### Stage 2: Add concurrency primitives

1. Add optimistic versioning or CAS semantics.
2. Split hot mutable fields into hashes/keys instead of one giant JSON blob.
3. Separate:
   - canonical history
   - speculative cache
   - staging queue
   - session metadata

#### Stage 3: Improve storage hygiene

1. Namespace keys.
2. Make TTL policy explicit by state type.
3. Add instrumentation around state size and overwrite frequency.

### Mentor Verdict

`SessionManager` is not a bad file.
It is an underspecified file.

It looks harmless because it is short.
But in this architecture, short does not mean low-risk.

This class is acting like:
- a cache
- a session store
- a coordination store
- a report backing store

all at once.

That is too many jobs for a blind whole-document replace API.

### Next Recommended Deep Dive

`backend/api/routes.py` should be next.

Reason:
- the route layer is where these backend subsystems become public runtime contracts.
- after reviewing orchestration, interview-map behavior, and state durability, the next best step is to inspect exactly how those contracts are exposed to the frontend and deployment surface.

## System 11: `API Routes`

### Mission

`backend/api/routes.py` is the backend's contract surface.

This file decides how the rest of the system is allowed to exist from the outside.

That means it owns:

1. request/response shape
2. error semantics
3. public exposure of internal subsystems
4. telemetry at the HTTP boundary
5. the translation between backend state and frontend expectations

Architecturally, route files often look boring.

But this one is not boring because the product is very contract-sensitive:
- live voice turn-taking
- startup readiness
- report retrieval
- TTS source selection
- completed-session behavior

So if the route layer is sloppy, the product can feel broken even when the internal services are mostly correct.

### Full File Walkthrough

#### `backend/api/routes.py:1-25`

This opening block does three things:
- imports FastAPI primitives
- constructs a global `TTSService`
- constructs a global `Orchestrator`

Architectural meaning:
- the route module is not a pure dependency-injection layer.
- it owns long-lived singletons at import time.

That is simple and practical for now, but it means route import is also service initialization.

#### `backend/api/routes.py:15-49`

These request models define the live HTTP contract:
- `StartInterviewRequest`
- `TTSRequest`
- `TurnRequest`
- `PartialRequest`
- `TelemetryEventRequest`

What this means functionally:
- the backend contract is now explicit enough for:
  - startup calibration
  - partial-STT snapshots
  - same-turn version protection through `turn_id`
  - arbitrary frontend telemetry events

Architectural meaning:
- these models are the thin seam where frontend floor-state logic meets backend orchestration logic.

#### `backend/api/routes.py:56-101`

`/start_interview`:
- calls `orchestrator.start_session()`
- translates startup `RuntimeError` into `503`
- re-reads session state
- returns:
  - `session_id`
  - opening question
  - sprint info
  - trajectory map preview
- logs telemetry

Architectural meaning:
- this route is now the public face of the stronger startup contract.
- it is the place where "map-ready or fail" becomes an HTTP behavior.

#### `backend/api/routes.py:104-108`

`/deepgram_token`:
- returns the raw Deepgram API key from environment

Architectural meaning:
- the route explicitly supports the "client-side Deepgram SDK" architecture decision.
- this is intentionally not a production-hardened token-exchange flow.

#### `backend/api/routes.py:111-163`

`/partial_transcript` and `/process_turn`:
- `/partial_transcript` forwards speculative snapshots and logs them
- `/process_turn` calls the committed-turn fast path and logs the selected route kind

Architectural meaning:
- this pair is the live conversational boundary:
  - unstable sub-turn context
  - stable committed turn

That distinction is one of the healthiest contracts in the repo.

#### `backend/api/routes.py:166-190`

`/end_interview/{session_id}`:
- calls `orchestrator.end_session()`
- returns a summary
- logs end-of-interview telemetry

Architectural meaning:
- this route *looks* like the one place that finalizes an interview.
- but in the current system, it is not.
- the orchestrator can also finalize an interview internally during `handle_transcript()`.

That mismatch matters a lot.

#### `backend/api/routes.py:197-343`

This block covers:
- `/tts_filler`
- `/tts_health`
- `/telemetry`
- `/telemetry/{session_id}`
- `/tts`

What it means:
- the route layer also owns the real-time media interface.

Good aspect:
- `/tts` exposes whether audio came from:
  - prepped cache
  - live synthesis

That makes the frontend and telemetry layer much more diagnosable.

#### `backend/api/routes.py:350-402`

This final block covers:
- `/sessions`
- `/state/{session_id}`
- `/report/{session_id}`

Architectural meaning:
- this is where the repo's storage split becomes user-visible:
  - dashboard summaries from Postgres
  - full reports from Redis-backed session state

This is also the clearest place where contract drift has already happened.

### How `API Routes` Become Product Behavior

#### Startup experience

Relevant code:
- `backend/api/routes.py:56-101`
- `app/page.tsx:23-47`
- `app/interview/[session_id]/page.tsx:718-732`

What happens:
- the landing page posts calibration data to `/start_interview`
- the interview page later verifies map presence through `/state/{session_id}`

Architectural meaning:
- startup correctness is now split across:
  - one route that creates
  - one route that verifies

#### Live turn loop

Relevant code:
- `backend/api/routes.py:111-163`
- `lib/audio.ts:489-562`

What happens:
- frontend sends partial snapshots to `/partial_transcript`
- committed answers go to `/process_turn`
- frontend trusts the returned `route_kind`, `complete`, and question payload

Architectural meaning:
- these routes are not generic JSON endpoints.
- they are timing-sensitive control-plane APIs.

#### Completion and report navigation

Relevant code:
- `backend/api/routes.py:166-190`
- `backend/services/orchestrator.py:1723-1742`
- `app/interview/[session_id]/page.tsx:377-386`
- `app/interview/[session_id]/page.tsx:781-792`

What happens:
- on natural completion, `handle_transcript()` already calls `end_session()`
- then the frontend still calls `/end_interview/{session_id}`
- manual end also calls `/end_interview/{session_id}`

Architectural meaning:
- the route contract says "call this to end the interview."
- the orchestration contract says "the interview may already be ended before the route is called."

That is a real semantic mismatch, not just messy layering.

#### Report retrieval

Relevant code:
- `backend/api/routes.py:370-402`
- `app/report/[session_id]/page.tsx:25-31`
- `backend/db/postgres.py:71-79`

What happens:
- the report page expects `/report/{session_id}` to work as the durable source of truth
- but the route still pulls from Redis session state
- Postgres only stores the summary row

Architectural meaning:
- the frontend experience promises a durable report page
- the route layer is still serving an ephemeral backing store

### What `API Routes` Are Doing Well

1. The file is thin where it should be thin.
   - Most handlers delegate cleanly to orchestrator or service methods.

2. The partial-vs-committed transcript contract is explicit.
   - That is one of the strongest product contracts in the backend.

3. TTS observability is good.
   - Headers plus telemetry make cache/live/provider behavior inspectable.

4. Startup surfaces useful diagnostic context.
   - returning trajectory preview helps both smoke testing and operator sanity checks.

### Where `API Routes` Are Messing Up

1. Natural interview completion is effectively finalized twice.
   - Relevant code:
     - `backend/api/routes.py:166-190`
     - `backend/services/orchestrator.py:1723-1742`
     - `backend/services/orchestrator.py:850`
     - `app/interview/[session_id]/page.tsx:377-386`
   - On a natural completion turn:
     - `handle_transcript()` already calls `end_session()`
     - which pops `self._per_answer_scores`
   - Then the frontend calls `/end_interview/{session_id}` again
   - which triggers a second `end_session()` and a second full evaluation pass after those per-answer scores are already consumed
   - That makes the final report path unnecessarily expensive and potentially nondeterministic.

2. `/process_turn` still has inconsistent missing-session semantics.
   - Relevant code:
     - `backend/api/routes.py:142-163`
     - `backend/api/routes.py:362-375`
   - Neighboring state/report/end routes translate `KeyError` to `404`.
   - `/process_turn` still lets missing sessions fall through as server errors.

3. `/sessions` still exposes the contract drift directly.
   - Relevant code:
     - `backend/api/routes.py:350-359`
     - `app/dashboard/page.tsx`
   - The route returns raw DB rows, while the dashboard expects report-shaped fields.
   - This was already logged as a bug, and the route layer is where that mismatch is concretely visible.

4. The file still exposes internal-tool assumptions directly at the HTTP boundary.
   - `deepgram_token` exposes a raw key
   - telemetry is unauthenticated
   - `/tts_health` is used as a warm-up ping

These are not all immediate bugs, but they are important boundary assumptions.

### Cross-System Reality Check

#### Relationship with `Orchestrator`

What happens:
- routes mostly present orchestrator behavior to the outside world
- but `/end_interview` currently conflicts with orchestration semantics

Architectural lesson:
- the route layer should not invent a second completion model.

#### Relationship with the Frontend Audio Layer

What happens:
- the frontend depends on these handlers for:
  - session existence
  - process-turn result shape
  - TTS media source
  - end-of-session navigation

Architectural lesson:
- route contracts here are UX contracts.

#### Relationship with Storage

What happens:
- `/sessions` and `/report` expose the Redis/Postgres split directly

Architectural lesson:
- the route layer is where storage architecture becomes product behavior.

### Best Version of `API Routes`

#### Stage 1: Fix semantic mismatches

1. Make completion idempotent.
   - Either:
     - stop calling `/end_interview` after a natural `complete` turn
     - or make `end_session()` explicitly no-op/idempotent once final evaluation exists

2. Normalize missing-session behavior.
   - `/process_turn` should return a clean `404` like the adjacent session routes.

3. Decide what `/report/{session_id}` really promises.
   - If it is durable, back it with durable storage.

#### Stage 2: Tighten route contracts

1. Separate internal diagnostics from product-facing APIs more clearly.
2. Make health/warm-up semantics explicit instead of piggybacking on `/tts_health`.
3. Reduce accidental exposure of internal assumptions.

### Mentor Verdict

`backend/api/routes.py` is mostly doing the right kind of work.

It is not overcomplicated.
It is not pretending to be smarter than the orchestrator.

But it does have one classic boundary-layer problem:

it sometimes tells a cleaner story to the outside world than the internals can actually guarantee.

That is exactly what happened with:
- `/end_interview`
- `/report`
- `/sessions`

So the path to optimality here is not to add more logic.
It is to make the route semantics match the real system semantics more honestly.

### Next Recommended Deep Dive

`backend/main.py` should be next.

Reason:
- after routes, the next backend boundary is application boot and deployment behavior.
- that is where env loading, startup warmup, schema init, and degraded-mode masking all come together.

## System 12: `backend/main.py`

### Mission

`backend/main.py` is the application's boot contract.

It decides:
- how environment config enters the process
- what work must happen before the app is considered ready
- what startup failures are tolerated
- what origins are allowed to talk to the backend
- which router becomes the live API surface

Architecturally, this file defines what "successful startup" means for the whole product.

That is why it matters.

### Full File Walkthrough

#### `backend/main.py:1-29`

This block loads environment configuration from the project root:
- `.env` as base
- `.env.local` as override
- inherited environment if no files exist

What it means:
- config precedence is now explicit and better than earlier repo states.

Architectural meaning:
- this file is the source of truth for local runtime config ordering.
- that is good.

Important caveat:
- it still executes at import time, which means boot side effects happen as soon as `backend.main` is imported.

#### `backend/main.py:31-35`

This block imports:
- FastAPI
- CORS middleware
- the route router
- the shared `tts_service`

Architectural meaning:
- app boot and route import are tightly coupled.

#### `backend/main.py:37-61`

This is the lifespan hook.

What it does before startup completes:

1. warm filler TTS cache
2. initialize Postgres schema
3. load the RAG question bank in an executor

Each one is wrapped in a broad `try/except` and treated as best-effort.

Architectural meaning:
- the app is designed to prefer degraded startup over failed startup.

That is a deliberate philosophy.

But it has consequences:
- "booted" does not necessarily mean:
  - filler TTS is warm
  - Postgres is available
  - question bank is loaded

#### `backend/main.py:64-83`

This final block:
- creates the FastAPI app
- applies localhost-only CORS
- mounts the API router under `/api`

Architectural meaning:
- the backend assumes:
  - local dev origins
  - or same-origin deployment behind rewrites

That is consistent with the current Vercel-style deployment shape.

### How `backend/main.py` Becomes Product Behavior

#### Config resolution

Relevant code:
- `backend/main.py:4-29`
- `backend/config/env_runtime.py:1-25`

What happens:
- local key/model/provider overrides are established before service modules read environment

Architectural meaning:
- this file makes the rest of the backend's config story coherent.

#### Startup readiness

Relevant code:
- `backend/main.py:37-61`
- `backend/services/tts_service.py`
- `backend/db/postgres.py`
- `backend/rag/question_bank`

What happens:
- the backend warms subsystems opportunistically, then declares startup success even if those warmups fail

Architectural meaning:
- startup is availability-first, not truth-first.

That can be the right call, but only if degraded mode is visible and intentional.

#### Deployment entrypoint relationship

Relevant code:
- `backend/main.py:64-83`
- `api/index.py:1-42`
- `vercel.json:1-9`

What happens:
- `api/index.py` imports this module as the real app
- Vercel rewrites `/api/*` to that ASGI entrypoint

Architectural meaning:
- `backend/main.py` is not just for local `uvicorn`.
- it is the real app object for deployment too.

### What `backend/main.py` Is Doing Well

1. The dotenv precedence is finally sane.
   - Base defaults from `.env`, runtime overrides from `.env.local`, inherited env if needed.

2. Boot responsibilities are centralized.
   - filler warmup, schema init, and question-bank load all have one obvious home.

3. The file stays small.
   - for a startup file, that is generally a virtue.

4. The CORS setup matches the current local-dev and same-origin story reasonably well.

### Where `backend/main.py` Is Messing Up

1. Startup success is too forgiving to be self-describing.
   - Relevant code:
     - `backend/main.py:39-59`
   - The app can boot with:
     - no warm filler cache
     - no Postgres schema/init
     - no question bank
   - and still look healthy unless you already know to go inspect deeper telemetry or behavior.

2. The lifespan has no teardown phase.
   - Relevant code:
     - `backend/main.py:37-61`
     - `backend/db/postgres.py:57-61`
   - There is no cleanup after `yield`.
   - `close_pool()` exists in the Postgres module but is not used.
   - Combined with the already-logged TTS client shutdown gap, this means resource lifecycle is only half-implemented.

3. Startup warmups have no explicit timeout budget.
   - They are best-effort in terms of exception handling, but not bounded in terms of time.
   - If a dependency stalls instead of erroring, boot can still stall.

### Cross-System Reality Check

#### Relationship with `API Routes`

What happens:
- routes assume orchestrator and TTS singletons are ready because this module imported them and attached them to the app.

Architectural lesson:
- app boot and route availability are tightly coupled.

#### Relationship with `SessionManager` / Storage

What happens:
- boot does not verify Redis availability here.

Architectural lesson:
- the most important live-state dependency is not explicitly startup-checked in this file.

#### Relationship with Deployment

What happens:
- this file is the real app object whether the backend is run locally or imported through the ASGI fallback entrypoint.

Architectural lesson:
- any ambiguity here becomes deployment ambiguity immediately.

### Best Version of `backend/main.py`

#### Stage 1: Make degraded startup explicit

1. Emit structured startup status for:
   - filler cache warm
   - Postgres init success
   - question-bank load success

2. Distinguish:
   - boot failed
   - boot succeeded in degraded mode

#### Stage 2: Add teardown symmetry

1. Close Postgres pool on shutdown.
2. Close shared TTS client on shutdown.

#### Stage 3: Add bounded startup timing

1. Put timeouts around warmup operations.
2. Decide which dependencies are optional versus required by environment.

### Mentor Verdict

`backend/main.py` is disciplined, but overly polite.

It does not crash recklessly.
That is good.

But it also does not speak clearly enough when major subsystems fail to come up.

So the issue here is not architectural chaos.
It is that the file currently defines "healthy boot" too loosely.

### Next Recommended Deep Dive

`api/index.py` should be next.

Reason:
- after reading the real FastAPI app boot file, the next logical step is the serverless/ASGI fallback boundary that imports it.
- that file is tiny, but it is the last layer between deployment failure and user-visible error payloads.

## System 13: `api/index.py`

### Mission

`api/index.py` is the emergency deployment bridge.

Its purpose is very narrow:
- make sure Vercel can import *something*
- patch `sys.path`
- delegate to `backend.main.app`
- if that fails, still return a valid ASGI response

Architecturally, this file is not the application.
It is the crash boundary.

### Full File Walkthrough

#### `api/index.py:1-5`

Imports:
- `sys`
- `os`
- `traceback`
- `json`

Architectural meaning:
- this file is intentionally dependency-light so it can survive import failure deeper in the stack.

#### `api/index.py:6-19`

This is the happy path:
- compute the repo root relative to `api/`
- insert it into `sys.path` if missing
- import `backend.main.app` as `master_app`
- delegate the ASGI request

What this means:
- the serverless entrypoint is effectively a thin bootstrap shim around the real app object.

That is a reasonable pattern.

#### `api/index.py:21-41`

This is the fallback failure path:
- catch any exception during import or delegation
- build a JSON 500 manually
- include:
  - error label
  - exception string
  - traceback lines
  - `sys.path`
- send the response without depending on FastAPI/Starlette

Architectural meaning:
- this file values survivability very highly.

That is good.

But it values diagnosability over secrecy.

That is where the risk lives.

### How `api/index.py` Becomes Product Behavior

#### Deployment handoff

Relevant code:
- `api/index.py:9-19`
- `vercel.json:4-8`

What happens:
- all `/api/*` traffic is rewritten to this file
- this file then tries to import the real backend app

Architectural meaning:
- if this shim fails or lies about failure, the whole deployment surface lies with it.

#### Failure payload surface

Relevant code:
- `api/index.py:21-41`

What happens:
- boot/import failures are surfaced directly to HTTP clients as structured JSON

Architectural meaning:
- this is not just a logging decision.
- it is an externally visible error contract.

### What `api/index.py` Is Doing Well

1. It is extremely robust to import-time dependency failure.
   - That is the exact reason this file exists.

2. It stays intentionally tiny.
   - Good for a deployment shim.

3. The pure-ASGI fallback path is real.
   - It does not depend on FastAPI already being healthy in order to report failure.

### Where `api/index.py` Is Messing Up

1. It exposes too much internal failure detail to clients.
   - Relevant code:
     - `api/index.py:21-28`
   - This is the issue already logged in `bug audit.md`.
   - `traceback` plus `sys_path` is excellent for debugging and bad for production exposure.

2. It mutates `sys.path` dynamically at request time.
   - That is understandable in a deployment shim, but it is still global interpreter state mutation.

3. It has no distinction between:
   - safe client-facing error
   - detailed operator-facing diagnostics

### Cross-System Reality Check

#### Relationship with `backend/main.py`

What happens:
- this file is only useful because `backend/main.py` is the real app object.

Architectural lesson:
- this is a boundary shim, not an alternate backend.

#### Relationship with Deployment

What happens:
- `vercel.json` points all API traffic here.

Architectural lesson:
- even a tiny file can be production-critical if the deployment config routes everything through it.

### Best Version of `api/index.py`

#### Stage 1: Split diagnostics from client response

1. Keep the pure-ASGI fallback.
2. Log detailed traceback internally.
3. Return a minimal generic 500 body to the client.

#### Stage 2: Keep the shim minimal

1. Preserve the dependency-light bootstrap philosophy.
2. Avoid letting this file become a second app entrypoint with its own behavior.

### Mentor Verdict

`api/index.py` is doing the right job.

It is not over-engineered.
It is not architecturally confused.

It just makes one production-hostile trade:
- too much crash detail is sent back to the caller

That means the fix here is small and clear.

### Next Recommended Deep Dive

`backend/models/llm_router.py` should be next at the systems level.

Reason:
- we have already touched it repeatedly while auditing agents, interview-map startup, and route behavior.
- it now influences startup latency, agent output normalization, and cross-model contract stability across the whole backend.

## System 14: `backend/models/llm_router.py`

### Mission

`LLMRouter` is the backend's model-policy gateway.

Its job is not just "make an API call."

It decides:
- which model family each subsystem actually runs on
- how much token budget that subsystem gets
- how much malformed model output the backend tries to recover from
- what parts of provider/model weirdness are hidden from the rest of the codebase

Architecturally, that makes this file much more important than its size suggests.

It is the shared translation layer between:
- agent intent
- runtime config
- provider transport
- downstream JSON contracts

### Full File Walkthrough

#### `backend/models/llm_router.py:1-4`

Imports:
- `os`
- `json`
- `AsyncOpenAI`
- `model_tier`

Architectural meaning:
- this file is intentionally thin, but it already owns provider transport plus config indirection.

#### `backend/models/llm_router.py:7-18`

This block defines the tier system:
- `small` -> `anthropic/claude-haiku-4-5`
- `medium` -> `anthropic/claude-sonnet-4-5`
- `large` -> `deepseek/deepseek-r1`

Then `MODEL_TIERS` resolves env overrides through `model_tier(...)`.

Architectural meaning:
- this is the real source of truth for model routing now, not the older "Haiku / Sonnet / Opus" story still present in docs and coordination files.
- the tier map is computed at import time, so the live app boot path needs env loading to happen before this module is imported.

That boot ordering is currently safe in the real app path because `backend/main.py` loads dotenv before importing routes and agents.

So this is not a live boot bug right now.

But it is still an architectural detail worth respecting:
- direct script imports do not get the same safety guarantee automatically.

#### `backend/models/llm_router.py:20-25`

This block sets default token budgets:
- `small`: `256`
- `medium`: `768`
- `large`: `2500`

Architectural meaning:
- these are not neutral defaults.
- they are product decisions about how much "thinking room" each subsystem is allowed to consume.

That matters because:
- `ResumeAgent`
- `WeaknessAgent`
- `FollowUpAgent`
- `ReasoningBehaviorAgent`
- `EvaluationAgent`
- `Interview Map`

all inherit their effective response budget from here unless they override it explicitly.

#### `backend/models/llm_router.py:33-51`

`LLMRouter.__init__()`:
- validates the tier
- binds `self.model`
- creates an `AsyncOpenAI` client immediately

Architectural meaning:
- the router currently owns both model selection and transport lifetime.
- every router instance is also a fresh HTTP client owner.

That is fine when the router is effectively process-scoped.

It is less fine when callsites instantiate routers dynamically inside request/startup paths, which now happens in the interview-map generator.

#### `backend/models/llm_router.py:53-90`

`call()` is the whole operational contract:
- pick default `max_tokens` if none provided
- send a chat completion request with one system message and one user message
- read the returned text
- strip `<think>...</think>`
- try to parse JSON directly
- if that fails, try fenced JSON
- if that fails, try the first `{ ... }` object
- otherwise return raw text

Architectural meaning:
- this is a "best effort structured-output shim," not a true typed boundary.
- the router protects agents from some provider noise, but it still allows type instability to cross the boundary.

That is the most important truth in this file.

### How `LLMRouter` Becomes Product Behavior

#### Shared agent runtime

Relevant callsites:
- `backend/agents/concept_agent.py:25`
- `backend/agents/resume_agent.py:73`
- `backend/agents/weakness_agent.py:59`
- `backend/agents/followup_agent.py:392-393`
- `backend/agents/discrepancy_agent.py:38`
- `backend/agents/reasoning_behavior_agent.py:39`
- `backend/agents/evaluation_agent.py:141`

What happens:
- almost every meaningful agent in the backend inherits its provider behavior from this one file.

Architectural meaning:
- agent prompt quality matters, but the shared reliability floor is defined here.

If this file has a weak contract, every agent inherits that weakness.

#### Interview-map startup path

Relevant callsites:
- `backend/services/interview_map.py:322`
- `backend/services/interview_map.py:458`
- `backend/services/interview_map.py:498`
- `backend/services/orchestrator.py:2568`

What happens:
- startup-critical seed extraction uses `small`
- startup-critical per-focus track generation uses `large`
- `start_session()` now blocks on the map

Architectural meaning:
- `LLMRouter` is no longer just "per-turn inference plumbing."
- it is now part of the session-readiness contract.

That is a major promotion in architectural importance.

#### Model-specific cleanup layer

Relevant code:
- `backend/models/llm_router.py:67-69`

What happens:
- `<think>` blocks are stripped because the current `large` tier is `deepseek/deepseek-r1`, not the older Opus assumption.

Architectural meaning:
- this file is already absorbing provider/model-specific behavior drift on behalf of the rest of the codebase.

That is the right place for that responsibility.

But once a file starts doing that, it is no longer a trivial wrapper.

### What `LLMRouter` Is Doing Well

1. It centralizes model policy cleanly.
   - The rest of the backend does not need to know provider base URLs or model IDs.

2. It keeps the tier idea simple.
   - `small`, `medium`, and `large` are easy architectural handles.

3. It already includes pragmatic recovery for common malformed outputs.
   - Direct JSON parse.
   - Fenced JSON parse.
   - `<think>` stripping for reasoning-model output.

4. It integrates with runtime config aliasing cleanly.
   - `backend/config/env_runtime.py` keeps the env contract from fragmenting further.

5. It is still small enough to reason about fully.
   - That matters for a central boundary file.

### Where `LLMRouter` Is Messing Up

1. Its output contract is still unstable by design.
   - Relevant code:
     - `backend/models/llm_router.py:53-90`
   - It returns `dict | str`, not a stable structured shape.
   - This is the underlying systems reason the repo keeps needing per-agent cleanup and fallback logic.

2. Its recovery logic is object-centric, but one startup-critical caller is array-centric.
   - Relevant code:
     - `backend/models/llm_router.py:83-89`
     - `backend/services/interview_map.py:317-355`
   - The router's last-resort extraction only searches for `{ ... }`, not `[ ... ]`.
   - But `_extract_focus_seeds_llm()` explicitly asks for a JSON array.
   - So if the model returns something like commentary plus an unfenced array, the router cannot rescue it the same way it rescues object-shaped outputs.
   - The result is that interview-map seed extraction can quietly fall back to deterministic resume parsing even when the model was mostly correct.

3. It creates transport clients too eagerly and too locally.
   - Relevant code:
     - `backend/models/llm_router.py:48-51`
     - `backend/services/interview_map.py:322`
     - `backend/services/interview_map.py:458`
   - Every router instance owns a fresh `AsyncOpenAI` client.
   - Agent-owned routers are mostly long-lived, which is acceptable.
   - But interview-map generation creates fresh routers inside the session-start path, including several parallel `large` routers, and this file exposes no shared lifecycle or shutdown path.

4. It has no router-owned timeout, retry, or telemetry policy.
   - Relevant code:
     - `backend/models/llm_router.py:56`
   - That means:
     - transient provider issues are handled inconsistently by whichever caller happens to catch them
     - latency observability lives outside the shared boundary
     - startup-critical calls inherit the provider's raw behavior instead of a deliberate product policy

5. The code and the team's stated architecture have drifted apart.
   - Relevant references:
     - `backend/models/llm_router.py:9-18`
     - `README.md`
     - `AGENTS.md`
   - The live `large` tier is now DeepSeek R1, while the project narrative still repeatedly says "Opus."
   - That is not a runtime crash bug.
   - But it is a real team-contract bug: expectations about behavior, cost, verbosity, and structured-output quirks can drift if the docs keep describing a different system than the code runs.

### Cross-System Reality Check

#### Relationship with Agent Design

What happens:
- the repo keeps describing each agent as if its prompt is the main boundary.

Architectural lesson:
- that is only half true.
- the router is the upstream contract layer every agent shares.

So when agent behavior feels inconsistent, the right question is often:
- "is this really a prompt problem?"
- or
- "did the shared router boundary already hand the agent unstable input/output semantics?"

#### Relationship with Startup

What happens:
- the interview map now blocks session start
- the interview map depends directly on `LLMRouter`

Architectural lesson:
- this file now participates in startup correctness, not just runtime latency.

That is why router weaknesses matter more now than they did when it was just serving per-turn agent calls.

#### Relationship with Deployment and Config

What happens:
- env aliasing is centralized nicely in `env_runtime`
- but the router snapshots tier choices at import time

Architectural lesson:
- the live backend boot path is currently disciplined enough to make this safe.
- still, this is a subtle invariant, not an obvious one.

### Best Version of `backend/models/llm_router.py`

#### Stage 1: Split structured and unstructured call modes

1. Add explicit interfaces such as:
   - `call_json_object(...)`
   - `call_json_array(...)`
   - `call_text(...)`
2. Stop making every caller rediscover whether it received a `dict`, `list`, or `str`.
3. Move stable fallback-shape responsibility into the agent or router boundary explicitly.

#### Stage 2: Make parsing symmetrical

1. Add last-resort array extraction, not just object extraction.
2. Record which parse path succeeded:
   - direct JSON
   - fenced JSON
   - object rescue
   - array rescue
   - raw text fallback

That would make the interview-map seed path much less brittle immediately.

#### Stage 3: Centralize transport lifecycle

1. Reuse a shared OpenRouter client per process or per tier.
2. Add a clean shutdown path.
3. Stop creating multiple startup-path clients when one shared client would do.

#### Stage 4: Make cross-cutting provider policy explicit

1. Add router-level timeout defaults.
2. Add bounded retry for clearly transient provider failures.
3. Emit telemetry for:
   - tier
   - concrete model
   - latency
   - parse mode
   - fallback mode

#### Stage 5: Realign the repo narrative with runtime truth

1. Update docs and coordination files to reflect the actual current large-tier model.
2. Decide whether the product wants:
   - "abstract tier names only"
   - or
   - "concrete current model IDs documented everywhere"

Either choice is fine.
The current half-and-half state is not.

### Mentor Verdict

`LLMRouter` is disciplined, but under-scoped.

It was designed like a thin helper.
The architecture now uses it like a control boundary.

That mismatch is the key insight.

The file is good enough to keep the system moving.
It is not yet strong enough to be the stable shared contract the rest of the backend now assumes it is.

### Next Recommended Deep Dive

`backend/services/tts_service.py` should be next.

Reason:
- it is the other shared provider boundary that turns internal decisions into user-visible latency and failure behavior.
- we have already seen it in startup, route-layer, and shutdown-risk discussions, but it deserves its own full systems pass the same way `LLMRouter` did.

## System 15: `backend/services/tts_service.py`

### Mission

`TTSService` is the voice-delivery control boundary.

Its real job is larger than "turn text into audio."

It is responsible for:
- enforcing provider policy
- masking latency with filler and pre-generation
- deciding when emergency provider fallback is acceptable
- caching enough audio to make the interview feel conversational
- exposing just enough runtime state that failures are diagnosable

Architecturally, this file sits exactly where:
- backend scheduling
- frontend playback
- user-perceived latency

all meet.

That makes it one of the most product-visible infrastructure files in the repo.

### Full File Walkthrough

#### `backend/services/tts_service.py:1-28`

Imports plus constants:
- ElevenLabs SDK setup
- Cartesia HTTP fallback config
- filler phrase list

Architectural meaning:
- this file already encodes provider strategy, not just provider mechanics.

The tiny filler list is also important:
- it defines the audible personality of the latency mask.

#### `backend/services/tts_service.py:31-89`

`TTSService.__init__()` does five things:
- reads provider env config
- enforces project policy toward ElevenLabs
- builds the provider clients
- creates caches
- initializes lightweight runtime-health state

Important design choice:
- even if `TTS_PROVIDER=cartesia`, the code explicitly ignores it and prefers ElevenLabs.

Architectural meaning:
- this file is enforcing product policy in code, not just reflecting configuration.

That is fine.

But once a service starts overruling config intentionally, it is acting as a policy boundary and needs to be judged like one.

#### `backend/services/tts_service.py:91-111`

This is the operator-facing status surface:
- provider
- media type
- provider-config flags
- filler cache size
- prepped-audio count
- last provider used
- last error

Architectural meaning:
- `status_snapshot()` is the small but important bridge between invisible runtime state and debuggability.

#### `backend/services/tts_service.py:113-177`

Provider-specific byte generation:
- ElevenLabs streaming generator
- ElevenLabs bytes aggregation
- Cartesia bytes fetch
- narrow logic for deciding when ElevenLabs failure should fall back to Cartesia

Architectural meaning:
- fallback policy is intentionally selective, not universal.

That is good when you want to avoid silently switching providers for every minor issue.

But it also means some "provider unavailable" conditions still bubble out as hard failure.

#### `backend/services/tts_service.py:179-205`

`synthesize()` is the main contract:
- try ElevenLabs unless runtime configuration already landed on Cartesia
- on certain ElevenLabs failures, fall back to Cartesia
- return `(audio_bytes, media_type, provider_used)`

Architectural meaning:
- this is the exact moment "voice policy" becomes user-facing behavior.

The fact that the method returns the actual provider used is good design.

It acknowledges that configured provider and effective provider are not always the same thing.

#### `backend/services/tts_service.py:207-231`

Compatibility helpers:
- `stream()`
- `get_filler_audio()`
- `get_filler_payload()`
- `stream_with_filler()`

Architectural meaning:
- this block shows the system still conceptually believes in filler-first latency masking.

That matters, because one of the main cross-file findings is that the normal interview path no longer actually uses that contract.

#### `backend/services/tts_service.py:233-292`

This is the most operationally important block:
- `pre_generate(session_id, text)`
- `get_prepped(session_id, text)`

What it is trying to do:
- synthesize the next likely question while the candidate is still talking
- cache it
- let `/tts` serve it instantly on the next turn

Architectural meaning:
- this is the heart of the low-latency illusion.

If this block is robust, the interview feels sharp.
If it is race-prone, the interview feels randomly sluggish even when the backend "did the work already."

#### `backend/services/tts_service.py:294-305`

Startup filler warming:
- pre-build audio for all filler phrases

Architectural meaning:
- startup work here is small, bounded, and easy to reason about.
- this is one of the cleaner parts of the file.

### How `TTSService` Becomes Product Behavior

#### Startup behavior

Relevant code:
- `backend/main.py:41`
- `backend/services/tts_service.py:294-305`

What happens:
- filler phrases are warmed during app startup on a best-effort basis.

Architectural meaning:
- the service influences perceived responsiveness before a session even begins.

#### Main `/tts` runtime path

Relevant code:
- `backend/api/routes.py:249-343`
- `backend/services/tts_service.py:271-292`

What happens:
- `/tts` first checks for pre-generated audio
- if cache misses, it does live synthesis
- telemetry records whether the response was `prepped` or `live`

Architectural meaning:
- this is where the backend either cashes in on earlier scheduling work or admits it must do the expensive thing now.

#### Background orchestration path

Relevant code:
- `backend/services/orchestrator.py:2446-2457`
- `backend/services/tts_service.py:233-258`

What happens:
- whenever the background pipeline stages a next question, it dispatches `pre_generate(...)` as a fire-and-forget task

Architectural meaning:
- TTS latency is not independent.
- it depends directly on orchestrator staging discipline and version hygiene.

#### Frontend playback path

Relevant code:
- `lib/audio.ts:567-606`
- `lib/audio.ts:643-719`
- `app/interview/[session_id]/page.tsx:233-381`

What happens:
- frontend waits for `processTurn(...)`
- then calls `/tts`
- then plays the returned audio

Architectural meaning:
- the frontend is not just a passive player.
- its sequencing choices decide whether the service's latency-hiding features are actually used.

#### Filler path in the current codebase

Relevant code:
- `backend/api/routes.py:197-224`
- `lib/audio.ts:609-640`
- `app/interview/[session_id]/page.tsx:643-657`

What happens:
- filler audio is currently used for silence nudges
- not for the normal committed-turn response path

Architectural meaning:
- this is the biggest cross-file truth from this audit pass.
- the repo still contains filler-first machinery, but the main interview loop is no longer actually filler-first.

### What `TTSService` Is Doing Well

1. It makes provider policy explicit.
   - ElevenLabs is clearly the preferred path.
   - Cartesia is clearly positioned as emergency backup.

2. It returns the actual provider used, not just the configured one.
   - That is operationally honest.

3. It exposes a useful runtime-health surface.
   - `/tts_health` is simple and valuable.

4. The filler cache is small and bounded.
   - Good startup design.

5. Pre-generation is architecturally the right idea.
   - It is exactly the kind of latency work this product needs.

6. The route layer preserves source/provider metadata to the frontend.
   - Good observability handshake.

### Where `TTSService` Is Messing Up

1. The normal interview path is no longer filler-first.
   - Relevant code:
     - `app/interview/[session_id]/page.tsx:455-503`
     - `lib/audio.ts:567-606`
     - `app/interview/[session_id]/page.tsx:643-657`
     - `backend/services/tts_service.py:227-230`
   - The main turn path does:
     - `processTurn(...)`
     - then `/tts`
     - then playback
   - `prefetchFillerAudio()` is only used for silence nudges.
   - `stream_with_filler()` exists but has no live caller.
   - So the product's latency mask on normal answers now depends entirely on:
     - fast `processTurn`
     - or
     - a lucky pre-generated-audio hit
   - When those miss, the user hears dead air directly.

2. The pre-generated audio cache is race-prone.
   - Relevant code:
     - `backend/services/tts_service.py:233-243`
     - `backend/services/tts_service.py:271-292`
     - `backend/services/orchestrator.py:2457`
   - `_prepped_audio` is a single slot per `session_id`.
   - `pre_generate(...)` writes to that slot unconditionally.
   - background pre-generation is dispatched with `asyncio.create_task(...)`, so multiple stale/new tasks can overlap.
   - A slower older task can finish last and overwrite a newer correct question's audio.
   - `/tts` will then miss cache on the real question text and fall back to live synthesis.

3. Stale pre-generated audio has no cleanup path except exact consumption.
   - Relevant code:
     - `backend/services/tts_service.py:243`
     - `backend/services/tts_service.py:276-279`
   - If a pre-generated entry is overwritten, never requested, or no longer text-matched, it just stays there.
   - There is no explicit purge on session completion or abandonment.

4. Session-level filler telemetry is weaker than it should be.
   - Relevant code:
     - `backend/api/routes.py:207-215`
     - `lib/audio.ts:617`
     - `lib/audio.ts:625`
   - filler fetch/play events are logged under `"system"` rather than the actual interview session.
   - That means one class of voice-latency behavior is underrepresented in per-session traces.

5. The file still contains traces of an older contract that the live path no longer honors fully.
   - `stream_with_filler()` is the clearest sign.
   - The design intent is still audible in the service.
   - The runtime sequencing has drifted elsewhere.

### Cross-System Reality Check

#### Relationship with the Orchestrator

What happens:
- the orchestrator decides *when* the next question is probably stable enough to synthesize
- this service decides whether that work pays off at playback time

Architectural lesson:
- TTS latency is not a standalone subsystem.
- it is downstream of staging correctness.

#### Relationship with the Frontend Interview Loop

What happens:
- the frontend currently treats TTS as:
  - "once we have the answer text, fetch the audio"
- not:
  - "mask the waiting period immediately and bridge into the real response"

Architectural lesson:
- the product's conversational feel is being determined as much by UI sequencing as by provider speed.

#### Relationship with Product Policy

What happens:
- the repo still talks like filler-first latency masking is a live convention
- the code only uses filler for silence nudges

Architectural lesson:
- this is not a small naming mismatch.
- it is a behavioral contract drift.

### Best Version of `backend/services/tts_service.py`

#### Stage 1: Restore or formally retire filler-first

1. Decide explicitly whether the main interview path should still be filler-first.
2. If yes:
   - reintroduce filler in the normal turn-response path
   - make it revocable when real audio is ready
3. If no:
   - remove dead filler-first abstractions and update the repo narrative honestly

The worst state is the current in-between.

#### Stage 2: Version pre-generated audio

1. Key pre-generated audio by more than `session_id`.
2. Include:
   - question text hash
   - or turn/version metadata
3. Reject stale writes instead of letting late tasks overwrite newer audio.

#### Stage 3: Add cleanup symmetry

1. Clear pre-generated audio on session completion.
2. Consider TTL or bounded-size cleanup for abandoned sessions.
3. Pair that with the existing client shutdown fix already noted in the bug register.

#### Stage 4: Improve traceability

1. Tie filler fetch/play telemetry to the session when used inside a live interview.
2. Record:
   - cache hit/miss reason
   - whether pre-generated audio was stale-superseded
   - whether playback used real provider audio or browser fallback

### Mentor Verdict

`TTSService` has the right instincts.

It understands:
- provider policy
- cacheable latency
- emergency fallback
- operator visibility

But the surrounding architecture has drifted away from the contract this file was built to serve.

So the main issue here is not that the service is incompetent.
It is that:
- the service still thinks in filler-first / staged-audio terms
- while the live interview loop only partially cashes that design in

That is why this subsystem feels more inconsistent than it should.

### Next Recommended Deep Dive

`app/interview/[session_id]/page.tsx` should be next.

Reason:
- the biggest TTS findings in this pass are no longer isolated backend issues.
- they now live at the frontend orchestration boundary where turn commit, hold/revoke logic, TTS fetch timing, and playback sequencing all decide whether the conversation feels sharp or dead.

## Frontend 1: `app/interview/[session_id]/page.tsx`

### Mission

This file is the frontend interview conductor.

It is not "just the page."

It owns:
- session boot and resume
- transcript rendering
- answer accumulation
- same-turn revision handling
- stale-response invalidation
- TTS playback timing
- completion/navigation behavior

Architecturally, this file is where the product stops being a backend system and starts being an actual interview experience.

If the orchestrator is the backend brain, this page is the frontend nervous system.

### Full File Walkthrough

#### `app/interview/[session_id]/page.tsx:1-90`

This block defines:
- UI-level message/session types
- sprint/persona labels
- the settle-window and TTS-hold constants
- `buildMessagesFromHistory(...)`

Architectural meaning:
- this file is not rendering raw backend state directly.
- it is maintaining its own interpreted UI transcript model.

That means consistency with backend state is something this file has to actively preserve.

#### `app/interview/[session_id]/page.tsx:92-178`

State and refs:
- visible UI state
- boot state
- active `InterviewSession`
- current turn id
- optimistic answer draft
- silence-confirmation refs

Architectural meaning:
- the page is keeping two worlds alive at once:
  - React-rendered UI state
  - mutable real-time control state

That is necessary for low-latency voice UX.
It is also where subtle consistency bugs tend to live.

#### `app/interview/[session_id]/page.tsx:180-226`

Snapshot loading and teardown:
- fetch current session state
- redirect bad session ids
- reset UI when route/session changes
- stop live audio session on cleanup

Architectural meaning:
- this page treats session re-entry seriously.
- that is one of its strongest architectural traits.

#### `app/interview/[session_id]/page.tsx:233-388`

`handleFollowup(...)` is the post-answer handoff:
- stale-turn guards
- silence-confirmation hold
- revoke-on-user-resume behavior
- UI commit of pivot/sprint/AI message
- playback
- completion behavior

Architectural meaning:
- this is the single most important user-experience block in the file.

It decides whether the interview feels:
- smooth
- interruptible
- revocable
- coherent

or not.

#### `app/interview/[session_id]/page.tsx:390-524`

`commitAnswerDraft(...)` is the answer-commit pipeline:
- merge buffered chunks
- optimistically write candidate text into UI
- mark floor as `AI_THINKING`
- call `processTurn(...)`
- fetch audio
- guard against same-turn staleness
- hand off to `handleFollowup(...)`

Architectural meaning:
- this is where local speech becomes canonical interview progress.

That makes it the most state-sensitive block on the page.

#### `app/interview/[session_id]/page.tsx:526-577`

`queueAnswerChunk(...)` is the same-turn merge layer:
- keeps a stable `turnId`
- accumulates partial chunks into one draft
- preserves entities
- supports re-opened same-turn revisions
- defers commit with `ANSWER_SETTLE_MS`

Architectural meaning:
- this is the frontend counterpart to the backend same-turn revision work.

This file is doing real state-machine work here, not cosmetic transcript accumulation.

#### `app/interview/[session_id]/page.tsx:579-716`

`bootInterview(...)` wires the live session:
- restore transcript on resume
- prefetch opening audio
- create `InterviewSession`
- wire floor callbacks
- wire barge-in invalidation
- wire silence nudges
- start mic/Deepgram
- play opening prompt

Architectural meaning:
- boot, resume, live audio, and TTS are all fused here.

That is why this file now deserves systems-level review rather than "frontend page" review.

#### `app/interview/[session_id]/page.tsx:718-793`

Session lifecycle actions:
- start new
- resume existing
- start fresh
- end interview

Architectural meaning:
- this block is the public lifecycle contract of the frontend.
- the backend routes matter, but this is where the product decides what users are allowed to do and when.

#### `app/interview/[session_id]/page.tsx:795-1080`

Rendering:
- start gate
- resume/completed-session gate
- transcript
- live partial
- completion banner
- action bar

Architectural meaning:
- the UI is simple, but it is reflecting a surprisingly complex control model underneath.

### How This Page Becomes Product Behavior

#### Session safety gate

Relevant code:
- `app/interview/[session_id]/page.tsx:723-730`
- `app/interview/[session_id]/page.tsx:930-973`

What happens:
- the page refuses to auto-overwrite a session that already has progress
- completed sessions route the user toward report or fresh run

Architectural meaning:
- this page is protecting session integrity, not just rendering a screen.

#### Live answer merge and revision control

Relevant code:
- `app/interview/[session_id]/page.tsx:390-524`
- `app/interview/[session_id]/page.tsx:526-577`

What happens:
- multiple ASR chunks can still become one answer turn
- resumed same-turn speech can revise the turn before the AI answer is allowed to land

Architectural meaning:
- this file is a major part of why the split-answer bug got better.

#### Frontend TTS sequencing

Relevant code:
- `app/interview/[session_id]/page.tsx:455-503`
- `app/interview/[session_id]/page.tsx:649-657`
- `app/interview/[session_id]/page.tsx:695-700`

What happens:
- normal turns wait for the real response audio
- silence nudges use filler audio
- opening playback happens before the first candidate turn begins

Architectural meaning:
- the page is the actual owner of whether the TTS system feels filler-first, not just the TTS service itself.

#### Completion behavior

Relevant code:
- `app/interview/[session_id]/page.tsx:377-386`
- `app/interview/[session_id]/page.tsx:781-792`

What happens:
- completion can happen automatically after a backend `complete` response
- manual end also exists

Architectural meaning:
- this page participates directly in session finalization semantics, which is why the double-finalization bug was not merely a backend issue.

### What This Page Is Doing Well

1. It has strong stale-turn discipline.
   - `currentTurnIdRef` checks are everywhere they need to be.

2. The same-turn draft model is thoughtful.
   - This is one of the best pieces of frontend logic in the repo.

3. It delays AI-message UI commit until the silence-hold/revoke window is resolved.
   - That prevents some very ugly phantom-question behavior.

4. It protects existing/completed sessions from accidental overwrite.
   - Good product hygiene.

5. Cleanup is taken seriously.
   - session teardown, camera stop, visualizer stop, and abort invalidation are all handled consciously.

### Where This Page Is Messing Up

1. The main answer path is no longer truly filler-first.
   - Relevant code:
     - `app/interview/[session_id]/page.tsx:455-503`
     - `app/interview/[session_id]/page.tsx:649-657`
   - This is the frontend half of the TTS finding already logged in `bug audit.md`.
   - The silence-nudge path still uses filler.
   - The main interview answer path does not.

2. Natural completion still triggers a second finalization request.
   - Relevant code:
     - `app/interview/[session_id]/page.tsx:377-381`
   - This is the frontend half of the already-logged double-finalization bug.

3. Candidate answers are committed optimistically with no reconciliation on `processTurn` failure.
   - Relevant code:
     - `app/interview/[session_id]/page.tsx:416-428`
     - `app/interview/[session_id]/page.tsx:503-509`
   - The UI transcript adds the candidate's answer before the backend acknowledges it.
   - If `processTurn(...)` fails, the page keeps that answer in local UI, shows an error, and returns to listening.
   - There is no rollback, pending marker, or refetch of canonical session state.
   - That means the local transcript can claim an answer was recorded even when the backend never accepted it.

4. Fresh-run startup still drops calibration data.
   - Relevant code:
     - `app/interview/[session_id]/page.tsx:763-769`
   - This is the frontend half of the already-logged role/YOE drift bug.

5. Boot still serializes some work that could be overlapped.
   - Relevant code:
     - `app/interview/[session_id]/page.tsx:612`
     - `app/interview/[session_id]/page.tsx:681-700`
   - Opening TTS fetch happens before `session.start()`.
   - That is not a correctness failure.
   - But it is a reminder that this file still treats several latency-sensitive steps sequentially.

### Cross-System Reality Check

#### Relationship with `lib/audio.ts`

What happens:
- this page depends on `InterviewSession` for floor state, barge-in, and ASR flush timing
- but it makes the higher-level decisions about when a turn is committed and when AI playback is allowed

Architectural lesson:
- `lib/audio.ts` is the sensor/control substrate.
- this page is the conversation policy layer on top of it.

#### Relationship with the Orchestrator

What happens:
- the backend can do a lot of careful versioning work
- but this page still decides whether local UI and backend canonical state stay in sync when requests fail

Architectural lesson:
- backend correctness alone does not guarantee interview correctness.

#### Relationship with TTS

What happens:
- the TTS service can pre-generate audio and cache filler
- this page decides whether that capability is actually used in a conversationally effective way

Architectural lesson:
- conversational latency is an end-to-end behavior, not a service property.

### Best Version of `app/interview/[session_id]/page.tsx`

#### Stage 1: Reconcile optimistic local state with canonical backend state

1. Mark candidate answers as pending until `processTurn(...)` succeeds.
2. On failure:
   - roll back
   - or refetch session state
   - or clearly mark the answer as unsent

Right now the UI is too trusting.

#### Stage 2: Decide the true turn-response contract

1. Either restore filler-first on normal turns.
2. Or explicitly embrace "wait for real audio" and optimize around that honestly.

Again, the current hybrid state is the confusing one.

#### Stage 3: Reduce lifecycle duplication

1. Make natural completion and manual completion converge on one idempotent frontend path.
2. Keep the page from sending redundant finalization requests after a backend-complete response.

#### Stage 4: Preserve calibration on fresh runs

1. Carry forward `target_role`
2. Carry forward `years_experience`

This page should not silently change the meaning of a rerun.

### Mentor Verdict

This file is much better than a typical "big frontend page."

It is doing real systems work:
- revision handling
- stale invalidation
- revoke windows
- session lifecycle protection

That is the good news.

The risk is that it now behaves like a control plane while still carrying a few optimistic UI assumptions that belong in a much simpler app.

The biggest of those assumptions is:
- "if we rendered it locally, it probably happened canonically"

For a voice interview system, that assumption is too weak.

### Next Recommended Deep Dive

`lib/audio.ts` should be next.

Reason:
- this page depends heavily on `InterviewSession`, and the next remaining question is how much of the turn-boundary behavior is really decided in the page versus in the browser audio/Deepgram layer underneath it.

## System 16: Memory Handling and Data Highway

### Mission

This is the system that decides:
- what data counts as canonical truth
- what data is only speculative
- what data is allowed to stay local and ephemeral
- how evidence moves from browser speech into agent judgment, then back out as the next question

This matters because Antigravity is no longer a simple request/response app.

It is now a layered runtime with:
- browser-local speech memory
- frontend UI control memory
- Redis session memory
- backend process-local sidecar memory
- model-generated structured memory

If those layers are cleanly separated, the interview feels coherent.
If they blur together, the system becomes hard to reason about, hard to scale, and easy to desynchronize.

### Memory Inventory

#### Canonical durable memory: `backend/state/session_manager.py:6-28`

This is the official persistent session store.

What it actually is:
- one Redis key per session
- full JSON blob overwrite on every save
- full blob read on every get

Architectural meaning:
- the system has a very simple durability model
- but also a coarse one

There is no field-level merge, compare-and-swap, or versioned write protocol here.

So "Redis is the source of truth" is only true at blob granularity.

#### Backend process-local sidecars: `backend/services/orchestrator.py:644-656`

This block is extremely important.

It stores:
- `_pipeline_inflight`
- `_turn_pipeline_running`
- `_per_answer_scores`
- `_partial_entities`
- `_partial_snapshot_meta`
- `_speculative_locks`

Architectural meaning:
- the backend has already grown a second memory system beside Redis

Some of this is fine as pure optimization.

Some of it is not pure optimization anymore:
- `_per_answer_scores` affects final evaluation
- `_partial_entities` and `_partial_snapshot_meta` affect committed-turn merge
- `_pipeline_inflight` and `_turn_pipeline_running` affect whether background work happens at all
- `_speculative_locks` affect same-session speculative concurrency

That means these sidecars are operationally load-bearing.

#### TTS process-local sidecars: `backend/services/tts_service.py:81-89`

This service keeps:
- `_filler_cache`
- `_prepped_audio`

Architectural meaning:
- voice latency also depends on process-local memory, not just Redis session state

`_filler_cache` is mostly harmless as a warm cache.

`_prepped_audio` is more serious:
- it directly determines whether `/tts` serves fast cached audio or has to synthesize live

#### Frontend UI control memory: `app/interview/[session_id]/page.tsx:111-123`

This page keeps its own high-stakes local refs:
- `currentTurnIdRef`
- `answerDraftRef`
- `silenceConfirmedRef`
- `commitTimeRef`

Architectural meaning:
- the UI is not just rendering Redis state
- it is running a temporary local control plane while the backend catches up

That is why the frontend can be locally "ahead" of canonical backend truth for a moment.

#### Browser audio/session memory: `lib/audio.ts:91-112`

`InterviewSession` carries:
- `utteranceBuffer`
- `entityBuffer`
- `lastPartialSnapshotSentAt`
- `lastPartialSnapshotText`
- `partialSnapshotSeq`
- `activeTurnId`
- floor state
- AI echo memory

Architectural meaning:
- the first memory layer in the whole product is in the browser, before the backend even sees a token of transcript

### The Working Highway

#### Startup highway

Relevant code:
- `app/page.tsx:16-45`
- `backend/api/routes.py:56-101`
- `backend/services/orchestrator.py:665-801`
- `backend/services/interview_map.py:317-355`
- `backend/services/interview_map.py:451-558`

What happens:
- landing page warms `GET /tts_health`
- user submits `POST /start_interview`
- backend parses the resume
- backend seeds the first follow-up
- backend builds the interview map before startup returns
- interview page later loads `GET /state/{session_id}`

LLM budget at startup:
- `ResumeAgent.parse()` = 1 small call
- `_seed_first_question()` = 1 small call
- `_extract_focus_seeds_llm()` = 1 small call
- `_generate_focus_track()` = 3-5 large parallel calls

So the real startup budget is roughly 5-7 LLM calls before session start completes.

Architectural meaning:
- startup is no longer a lightweight boot step
- it is a full planning phase

That is defensible if the product wants a high-quality ready state.

But it means startup latency must be treated as a first-class system budget, not an implementation detail.

#### Partial transcript highway

Relevant code:
- `lib/audio.ts:197-309`
- `lib/audio.ts:489-523`
- `backend/api/routes.py:111-139`
- `backend/services/orchestrator.py:929-1010`
- `backend/services/orchestrator.py:2625-2734`

What happens:
- Deepgram emits interim and final fragments
- browser accumulates text and entities locally
- throttled snapshots go to `POST /partial_transcript`
- backend updates local partial-entity memory and snapshot metadata
- speculative follow-up generation may fire
- canonical interview history is not changed yet

This is one of the better contracts in the repo.

Why:
- speculative text is allowed to help preparation
- but not allowed to become official interview history

That is the right conceptual split for a real-time voice system.

#### Committed-turn highway

Relevant code:
- `lib/audio.ts:311-433`
- `app/interview/[session_id]/page.tsx:390-520`
- `backend/api/routes.py:142-163`
- `backend/services/orchestrator.py:1011-1761`

What happens:
- Deepgram `UtteranceEnd` or safety timeout flushes the utterance
- UI merges draft fragments into one answer
- UI sends `POST /process_turn`
- backend merges locally accumulated partial entities into the committed turn
- backend consumes prior staged analysis
- backend serves a fast response
- backend launches the heavy background pipeline for the next turn

Architectural meaning:
- the committed-turn path is really a handoff between three schedulers:
  - browser ASR/floor logic
  - frontend draft/revision logic
  - backend fast-path orchestration

That is why seemingly small changes in `lib/audio.ts` can change product behavior far beyond audio.

#### Background reasoning highway

Relevant code:
- `backend/services/orchestrator.py:1889-2457`
- `backend/agents/evaluation_agent.py:143-168`

What happens:
- backend rebuilds a compact `memory_context`
- weakness, discrepancy, and reasoning agents run in parallel
- concept extraction runs too if frontend entities were absent
- per-answer scoring fires asynchronously
- one follow-up generation route is chosen
- staged analysis and staged next question are written back
- TTS pre-generation is dispatched

Hot-path LLM budget per committed turn:
- `WeaknessAgent.detect()` = 1 medium
- `DiscrepancyAgent.check()` = 1 medium
- `ReasoningBehaviorAgent.evaluate()` = 1 medium
- `ConceptAgent.extract()` = 0 or 1 small
- follow-up generation = 1 model call
- `EvaluationAgent.score_answer()` = 3 large calls

So the background path is roughly 7-8 LLM calls per committed turn.

Architectural meaning:
- the system is not cheap or simple per answer
- it is running a dense diagnostic fan-out on every real turn

That can be worth it.

But only if the system is very deliberate about:
- what context each call gets
- what work is truly necessary
- how much duplicate prompt payload is being paid for

#### TTS highway

Relevant code:
- `backend/services/orchestrator.py:2446-2457`
- `backend/api/routes.py:197-343`
- `lib/audio.ts:567-719`
- `app/interview/[session_id]/page.tsx:455-502`

What happens:
- background pipeline may pre-generate audio
- frontend later calls `/tts`
- backend either serves prepped audio or synthesizes live
- frontend plays the object URL or falls back to browser speech

Architectural meaning:
- voice delivery is downstream of almost every earlier memory decision

If earlier memory/versioning is stale, the TTS path pays for it immediately.

#### End-session and report highway

Relevant code:
- `backend/api/routes.py:166-190`
- `backend/api/routes.py:362-402`
- `backend/services/orchestrator.py:803-870`
- `backend/agents/evaluation_agent.py:170-286`

What happens:
- `/end_interview` calls `end_session()`
- backend flushes staged analysis
- per-answer scores are popped from process-local memory
- final evaluation runs once
- report endpoints read the Redis state

Architectural meaning:
- the final report is only as complete as the memory layers that survived until the end

That makes the process-local `_per_answer_scores` store more important than it first looks.

### API Call Surface

#### Per interview start

Observed frontend/API path:
- `GET /tts_health`
- `POST /start_interview`
- `GET /state/{session_id}`
- `GET /deepgram_token` once audio starts

#### During each active answer

Observed hot path:
- repeated `POST /partial_transcript`
- one `POST /process_turn`
- one `POST /tts`
- many `POST /telemetry`

From `rg -c "trackInterviewEvent\\("`:
- `lib/audio.ts` has 20 call sites
- `app/interview/[session_id]/page.tsx` has 20 call sites

That does not mean 40 telemetry requests per turn every time.

But it does mean observability is now materially part of the runtime traffic pattern.

### Prompt Efficiency and Cross-Agent Sharing

The prompt surfaces are not equally heavy.

Lean prompt surfaces:
- `concept_agent.py`
- `reasoning_behavior_agent.py`
- `weakness_agent.py`
- `discrepancy_agent.py`
- `resume_agent.py`

Heavier prompt surfaces:
- `followup_agent.py`
- `evaluation_agent.py`
- `interview_map.py`

Most important systems insight here:
- the hot path duplicates context more than the repo narrative suggests

`AGENTS.md:176-182` still describes a strict chain-isolated architecture where agents receive JSON from the preceding agent and state lives in Redis only.

The real runtime does not work that way anymore.

In `backend/services/orchestrator.py:1986-2055`, multiple agents are given:
- raw `text`
- raw `resume`
- `memory_context`
- `parsed_resume`

in parallel.

Architectural meaning:
- the system is now a shared-context fan-out architecture, not a strict agent-chain architecture

That is not automatically wrong.

But it has consequences:
- more token duplication
- more opportunities for inconsistent interpretation between agents
- weaker architectural truthfulness between docs and runtime

### What This System Is Doing Well

1. It has a real speculative-vs-canonical split.
   - That is one of the strongest architectural choices in the repo.

2. It has strong stale/version discipline in the backend.
   - `snapshot_seq`
   - `turn_id`
   - `answer_version`
   - staged queue replacement rules

3. It treats fast response and full reasoning as separate workloads.
   - That is the only reason the interview can feel conversational at all.

4. The data highway is observable.
   - There is enough telemetry now that we can actually reason about bottlenecks.

5. The system has already moved away from naive "one answer, one synchronous giant model call."
   - That is a meaningful architectural maturity step.

### Where This System Is Messing Up

1. The canonical memory story is no longer honest.
   - The codebase says Redis is the state store.
   - The runtime also depends on multiple process-local sidecars.

2. The design now assumes sticky single-process execution in more places than it admits.
   - That is a big production reality gap.

3. The prompt/data fan-out is more redundant than it should be.
   - Several parallel calls rebuild overlapping context from scratch.

4. The call budget is expensive and mostly implicit.
   - startup: roughly 5-7 LLM calls
   - per committed turn: roughly 7-8 LLM calls

5. Observability has become part of the hot path, but still behaves like debug instrumentation.
   - lots of tiny telemetry posts
   - not much batching
   - some session attribution gaps

### Best Version of the Memory and Data Highway

#### Stage 1: Make the memory classes explicit

Define four official categories:
- canonical durable
- speculative shared
- performance cache
- browser-local ephemeral

Right now those categories exist in practice, but not as an explicit architecture.

#### Stage 2: Stop letting load-bearing state live only in one Python process

At minimum, move or persist:
- per-answer scores
- partial entity accumulation
- partial snapshot sequence metadata
- speculative coordination metadata
- pre-generated TTS identity/version metadata

#### Stage 3: Compress the agent fan-out contract

Instead of sending each agent a mostly reassembled view of the same raw evidence:
- normalize one compact turn-diagnosis pack
- pass that forward deliberately

That would reduce:
- prompt duplication
- drift between agents
- hidden token cost

#### Stage 4: Give the system a written budget

This project now needs explicit budgets for:
- startup LLM calls
- per-turn LLM calls
- per-turn frontend API calls
- telemetry volume

Without that, "fast enough" will always be anecdotal.

### Mentor Verdict

The memory and data highway is smarter than a typical startup prototype.

It has already discovered several correct ideas:
- speculative preparation should not equal canonical commitment
- stale/version hygiene matters
- fast response and deep analysis must be decoupled

That is the good news.

The bad news is that the runtime has outgrown its own story.

The code still talks like:
- Redis is the state store
- agents form a clean JSON chain

But the real system is now:
- a mixed-memory control plane
- with shared-context fan-out
- and process-local sidecars that matter to correctness

That does not mean the architecture is bad.

It means the architecture is now powerful enough that it must be described and stabilized honestly.

## System 17: `lib/audio.ts`

### Mission

`lib/audio.ts` is not just an audio helper.

It is the browser-side sensor and handoff substrate for the entire interview loop.

Its real responsibilities are:
- connect browser audio to Deepgram
- decide when the user is speaking versus the AI
- accumulate and flush utterances
- suppress echo and handle barge-in
- send speculative partial snapshots
- hand committed turns to the backend
- fetch and play TTS

Architecturally:
- `app/interview/[session_id]/page.tsx` is the policy layer
- `lib/audio.ts` is the lower-level control substrate underneath it

If this file is wrong, the whole repo can look like an "agent problem" when it is really a turn-boundary problem.

### Full File Walkthrough

#### `lib/audio.ts:1-29`

`trackInterviewEvent(...)` is the client telemetry transport.

Architectural meaning:
- observability is built directly into the browser hot path

This is useful.

It also means telemetry traffic is not free anymore.

#### `lib/audio.ts:34-55`

`FloorState` and `FLOOR_CONFIG` define the entire conversational physics of the browser layer:
- barge-in thresholds
- echo cooldown
- silence threshold
- interim snapshot throttling
- safety timeout
- multimodal weights

Architectural meaning:
- these constants are product behavior
- not just implementation tuning knobs

#### `lib/audio.ts:57-75`

Text normalization plus `isLikelyEchoSnippet(...)`.

Architectural meaning:
- this file uses lexical overlap as a cheap acoustic-memory proxy

That is clever.

It is also a place where a heuristic can silently delete real user speech.

#### `lib/audio.ts:77-168`

`InterviewSession` state and `transition(...)`.

This block is doing real control-plane work:
- storing floor state
- storing AI echo memory
- storing the active turn id
- buffering user speech
- buffering Deepgram entities
- clearing buffers on AI state transitions

The buffer-clearing behavior on `AI_SPEAKING` and `AI_THINKING` is especially important.

Architectural meaning:
- this file is actively protecting the rest of the stack from TTS bleed and stale user fragments

#### `lib/audio.ts:170-348`

`start()` is the entire browser ASR boot pipeline:
- fetch Deepgram token
- open live transcription socket
- set Deepgram options
- attach transcript handler
- attach utterance-end handler
- open mic
- start shipping PCM frames

This is the most important line block in the file.

Why:
- it turns browser speech into the actual runtime event stream that powers the backend

#### `lib/audio.ts:197-309`

Transcript handler behavior:
- early echo suppression
- silence tracking
- barge-in detection while AI is speaking
- final-fragment accumulation
- entity extraction
- interim partial display
- throttled speculative snapshot emission
- vision-score inspection without meaning commit

Architectural meaning:
- one event handler here is feeding three different consumers:
  - UI partial text
  - backend speculative prep
  - future committed-turn flush

That is why this file deserves systems scrutiny, not just frontend scrutiny.

#### `lib/audio.ts:311-433`

Utterance commit path:
- `UtteranceEnd`
- `_flushUtterance(...)`
- empty-flush silence signaling

Architectural meaning:
- this is the exact seam between "candidate is still talking" and "backend may now reason canonically"

That seam is one of the highest-risk boundaries in the repo.

#### `lib/audio.ts:435-523`

Cleanup and partial snapshot API path:
- stop/teardown
- partial snapshot throttling
- partial transcript POST

Architectural meaning:
- this block controls whether speculative backend prep stays cheap or turns into transcript spam

#### `lib/audio.ts:528-562`

`processTurn(...)` is intentionally small.

That is good.

Architectural meaning:
- the file is correctly not pretending that committed-turn logic belongs here
- it hands that job to the backend orchestrator

#### `lib/audio.ts:567-719`

TTS utilities:
- `prefetchAudio(...)`
- `prefetchFillerAudio(...)`
- `playAudioUrl(...)`
- `speakText(...)`

Architectural meaning:
- this is where backend voice infrastructure becomes actual browser playback timing

#### `lib/audio.ts:722-781`

Browser fallback speech synthesis.

Architectural meaning:
- this file explicitly carries the "voice must still happen even if the preferred provider fails" policy on the client side too

### How `lib/audio.ts` Fits the Larger Highway

#### Relationship with the interview page

Relevant code:
- `app/interview/[session_id]/page.tsx:131-140`
- `app/interview/[session_id]/page.tsx:233-388`
- `app/interview/[session_id]/page.tsx:390-520`

What happens:
- the page decides when a new turn starts
- `InterviewSession` enforces the lower-level floor and ASR mechanics

Architectural meaning:
- the page is the policy layer
- `lib/audio.ts` is the transport/control layer

#### Relationship with the backend orchestrator

Relevant code:
- `lib/audio.ts:489-562`
- `backend/api/routes.py:111-163`
- `backend/services/orchestrator.py:929-1061`

What happens:
- this file sends speculative and committed transcript events with:
  - `turn_id`
  - `snapshot_seq`
  - `is_final`
  - entities

Architectural meaning:
- backend version safety depends directly on this file sending the right identifiers at the right moments

#### Relationship with TTS and product latency

Relevant code:
- `lib/audio.ts:567-719`
- `backend/api/routes.py:197-343`
- `backend/services/tts_service.py:233-292`

What happens:
- the browser is the last mile for the low-latency illusion

Architectural meaning:
- even perfect backend staging still has to survive this file's playback sequencing and fallback behavior

### What `lib/audio.ts` Is Doing Well

1. The floor model is thoughtful.
   - `USER_SPEAKING`
   - `AI_THINKING`
   - `AI_SPEAKING`
   - explicit transition side effects

2. Barge-in protection is much better than the average voice prototype.
   - lock window
   - min-char threshold
   - sustained VAD duration

3. It correctly refuses to let vision directly commit meaning.
   - that is a mature correction after the earlier split-answer bug class

4. Partial snapshot traffic is meaningfully throttled.
   - the backend gets live context without getting every transient token

5. Playback now waits for audio readiness and has a real fallback path.
   - that makes the browser TTS path much less brittle

### Where `lib/audio.ts` Is Messing Up

1. Telemetry is too coupled to the hot path.
   - `trackInterviewEvent()` does one POST per event.
   - this file alone has 20 call sites.
   - the interview page has 20 more.
   - that is a lot of side traffic on the same path already handling Deepgram, partial snapshots, committed turns, and TTS.

2. Playback telemetry is not session-scoped where it matters most.
   - `playAudioUrl(...)` logs to `"system"` instead of the live session id.
   - same for filler playback events.
   - that weakens exactly the session-level playback diagnosis we now care about.

3. Echo suppression is broad enough to plausibly eat legitimate answer openings.
   - the transcript handler drops any text that looks like recent AI speech
   - `recentAiTextNorm` persists for `aiEchoCooldownMs`
   - lexical overlap is enough to trigger suppression
   - candidates often begin by repeating the noun phrase or technology from the question

4. Stale-turn invalidation does not cancel network work.
   - the page can ignore stale responses later
   - but `fetch(...)` calls for partials and committed turns still run
   - that is wasted backend/API work on a path we already know can revise itself

5. The audio capture path is still built on `ScriptProcessorNode`.
   - it works
   - but it is older browser technology and should be treated as technical debt

### Best Version of `lib/audio.ts`

#### Stage 1: Make telemetry session-aware and less chatty

1. Batch client telemetry per turn or short time window.
2. Thread the real `sessionId` into playback helpers.
3. Keep the session trace as the primary unit of diagnosis.

#### Stage 2: Narrow echo suppression to avoid clipping real answers

1. Use stronger evidence than generic word overlap during the post-playback cooldown.
2. Prefer matching longer n-grams or timing-aware acoustic evidence.
3. Be especially careful right after `beginUserTurn(...)`, when real candidate speech is expected immediately.

#### Stage 3: Make network work abortable where turn revisions already exist

1. Give committed-turn fetches and maybe partial-snapshot sends turn-scoped cancellation where safe.
2. Stop treating stale local UI drops as the only cleanup layer.

#### Stage 4: Treat this file as infrastructure

1. Migrate from deprecated browser audio primitives when practical.
2. Keep the file small in API shape, but explicit in system responsibility.

### Mentor Verdict

This file is one of the strongest pieces of engineering in the repo.

It has already absorbed several hard-learned lessons:
- direct CV commit was unsafe
- barge-in needs more than one heuristic
- speculative text and canonical commit must stay separate
- browser playback needs real readiness handling

That is the good news.

The risk is that `lib/audio.ts` is now important enough to create systemic problems when its heuristics are only "pretty good."

The clearest example is echo suppression:
- it is protecting the system from real speaker bleed
- but it may also be a little too willing to mistrust the candidate's first words

So the right mentor judgment is:
- this is not a messy helper
- this is a high-value infrastructure file
- and it now deserves the same care we give the orchestrator

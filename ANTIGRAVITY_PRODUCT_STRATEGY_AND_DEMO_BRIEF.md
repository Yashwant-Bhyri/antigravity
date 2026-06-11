# Antigravity Product Strategy And Demo Brief

Date: 2026-06-09  
Audience: consulting strategist, investor-facing advisor, HR/buyer strategist, technical demo planner  
Purpose: provide enough product, business, UX, and engineering context to design Antigravity's pitch deck, investor demo, HR demo, candidate walkthrough, and technical demo direction without reading the full codebase.

---

## 1. Executive Brief

Antigravity is an AI-observed technical assessment platform. It is built to answer a high-stakes hiring question:

> What did this candidate actually prove under realistic pressure?

The product is not a quiz engine, not a resume parser, and not a generic AI chatbot. It is a live assessment room that converts resume claims, role context, conversation, real-time reasoning behavior, and eventually hands-on engineering work into a defensible hiring evidence package.

Antigravity currently has two related product surfaces:

1. **Voice Interview Engine**  
   A real-time AI interviewer that reads the candidate's resume and target role, prepares a role-specific interview map, asks live spoken questions, adapts to answers, tracks reasoning behavior, and produces an evidence-first report.

2. **Engineering Simulation Workbench**  
   A realistic task environment where candidates inspect a problem, edit real code, run tests, explain decisions, and generate observable evidence of engineering judgment.

The strategic promise is bigger than "AI interviews." Antigravity is building an **evidence engine for hiring**. It aims to replace weak signals such as polished resumes, generic behavioral answers, trivia interviews, and shallow coding tests with live, role-specific proof of judgment.

For a pitch or demo, the strongest framing is:

> Hiring teams do not need more interview content. They need better evidence. Antigravity turns the interview itself into a structured evidence-producing system.

The key output is not a transcript. The key output is a **decision package**: what was tested, what was proven, what held up under follow-up, what remained uncertain, and what a human interviewer should clarify next.

---

## 2. Product Thesis

### Core Belief

Modern hiring relies on signals that are too easy to polish and too hard to defend.

Resumes overstate ownership. Human interviews vary by interviewer. Coding exercises often measure rehearsed patterns. AI interview tools often feel robotic, opaque, or shallow. At the end, hiring teams are left with scattered notes and subjective impressions rather than a clear evidence trail.

Antigravity's thesis:

> The best hiring signal comes from observing how a candidate reasons, adapts, clarifies, validates, recovers, and communicates under realistic role pressure.

This shifts the assessment question from:

> "Can the candidate answer this question?"

to:

> "How does the candidate behave when their claim is explored, stressed, transferred, and turned into a decision?"

### Philosophical Shift

The product originally began as a strongly adversarial cognitive interrogation engine: probe claims, find weak spots, challenge inconsistencies.

That evolved into a better philosophy:

> Measure substance, not guilt.

Bad candidates usually reveal weak signal naturally. Good candidates should be allowed to show strength naturally. The product should be rigorous, but not hostile. Adversarial probing is a tool, not the brand identity.

The current philosophy is:

- Start with the candidate's actual evidence.
- Ask grounded, human, plain-English questions.
- Clarify before applying pressure.
- Test application transfer after enough context exists.
- Move on once enough signal is gathered.
- Report uncertainty honestly.
- Never confuse pressure with evidence.

This matters for positioning. Antigravity should not be sold as "an AI that attacks candidates." It should be sold as:

> A system that creates fair, structured, defensible evidence from live assessment.

---

## 3. Problem Landscape

### 3.1 Resume Over-Trust

Resumes are optimized documents, not evidence records. Candidates often write:

- "owned launch analytics"
- "scaled infrastructure"
- "improved retention"
- "built ML pipeline"
- "led product dashboarding"

Those claims may be true, partly true, inflated, inherited from a team, or misunderstood by the candidate. A recruiter or interviewer must determine:

- What did the candidate personally do?
- What was the actual mechanism?
- What tradeoffs did they understand?
- What metrics did they influence?
- What would they do if the situation changed?

Most interview processes do not systematically resolve this.

### 3.2 Inconsistent Human Interviews

Human interview quality varies sharply:

- Different interviewers probe different things.
- Some over-index on charisma.
- Some over-index on trivia.
- Some drill one topic too long.
- Some fail to follow up when an answer is vague.
- Some do not produce useful written feedback.

This creates inconsistent candidate evaluation and weak hiring committee evidence.

### 3.3 Weak Decision Packages

After an interview, hiring teams often have:

- transcript fragments,
- interviewer impressions,
- scattered scorecards,
- a few quotes,
- broad "strong/weak" labels,
- and unclear reasoning behind the final recommendation.

Antigravity's report layer exists because the core buyer pain is not only interview execution. It is decision defensibility.

The hiring team needs to know:

- What was actually tested?
- What held up?
- What did not?
- What was never tested?
- Which resume claims were supported, weakened, or left uncertain?
- What follow-up would a human interviewer still need?

### 3.4 AI Interview Distrust

Candidates are skeptical of AI interviews because they can feel:

- opaque,
- surveillant,
- unfair,
- robotic,
- unable to understand nuance,
- and hard to interrupt or correct.

The UI and voice interaction therefore matter as much as the backend. The candidate must know:

- whose turn it is,
- whether the system heard them,
- whether the question is anchored,
- whether the transcript is live or committed,
- how to pause,
- how to repeat,
- how to correct a term,
- and how the session ends.

### 3.5 Static Technical Tests Miss Real Work

Traditional coding tests often measure:

- syntax recall,
- isolated algorithms,
- rehearsed patterns,
- one-shot correctness.

Real engineering requires:

- debugging,
- ambiguity handling,
- testing,
- validation,
- observability,
- tradeoff communication,
- and recovery from partial failure.

This is why Antigravity includes an Engineering Simulation Workbench, not only a voice interviewer.

---

## 4. What Antigravity Does

### 4.1 Voice Interview Engine

The Voice Interview Engine conducts live spoken interviews from resume and role context.

Core flow:

1. Candidate submits resume and role context.
2. Backend parses resume claims and extracts work surfaces.
3. System builds a role-specific interview map.
4. Candidate enters the live room.
5. AI interviewer asks an anchored question.
6. Candidate answers by speaking.
7. Browser streams speech through Deepgram.
8. Backend agents analyze the answer.
9. System asks a grounded follow-up.
10. Interview continues through multiple turns.
11. Final report synthesizes evidence.

What makes this different:

- Questions are not generic.
- Follow-ups are not random.
- The system tracks what the candidate has already shown.
- The report is evidence-first, not transcript-first.

### 4.2 Resume-Grounded Interview Map

Before the live room starts, Antigravity prepares a candidate-specific map.

The map identifies:

- resume claims,
- role-relevant focus areas,
- testable sub-surfaces,
- opener questions,
- clarification paths,
- pressure paths,
- application-transfer opportunities,
- recovery paths,
- and coverage needs.

This is a core moat. It transforms the resume from a static document into an assessment plan.

Example:

Instead of asking:

> Tell me about a project you worked on.

The system can ask:

> You mentioned owning launch analytics for a product rollout. Walk me through how you separated a real conversion drop from instrumentation noise.

The difference is specificity. The second question is anchored to the candidate's claim and tests decision reasoning.

### 4.3 Turn-Aware Live Room

The live room is designed around clarity:

- AI interviewer presence is represented through an abstract Aura.
- Current question remains anchored.
- Candidate answer live transcription appears separately below the question.
- Turn ownership is explicit: AI corner vs candidate corner.
- Candidate camera and history live in a side panel.
- Candidate controls remain accessible.

The UI goal is not "cool visualizer." The goal is:

> A premium assessment room where the candidate never has to guess what is happening.

### 4.4 Multi-Agent Reasoning Pipeline

During the interview, multiple agents analyze evidence:

- **ResumeAgent** parses claims, roles, metrics, projects, and evidence anchors.
- **ConceptAgent** extracts concrete concepts from answers.
- **WeaknessAgent** detects vagueness, unsupported claims, shallow reasoning, and gaps.
- **DiscrepancyAgent** compares answers against resume claims and prior statements.
- **ReasoningBehaviorAgent** tracks clarity, calibration, adaptability, and reasoning structure.
- **FollowUpAgent** generates next questions and recovery moves.
- **ApplicationAgent** creates role-relevant transfer scenarios.
- **EvaluationAgent** synthesizes final evidence into Report V2.

Important positioning:

> These agents are not there to create complexity. They are there to turn conversation into structured evidence.

### 4.5 Two-Track Low-Latency Architecture

The system separates fast candidate-facing response from slower deeper analysis.

Fast path:

- candidate commits answer,
- system applies already staged analysis,
- next question is served quickly,
- user-facing flow continues.

Slow path:

- background agents analyze answer,
- future question packets are prepared,
- deeper report evidence is staged.

Business value:

- reduces awkward dead air,
- keeps conversation feeling live,
- preserves deeper reasoning quality,
- supports natural turn-taking.

### 4.6 Report Layer

The report is the buyer-facing product artifact.

Report V2 is intended to include:

- role fit,
- strongest signal,
- interview quality,
- resume claim calibration,
- tested strengths,
- scoped tested risks,
- knowledge coverage,
- recommended follow-ups,
- confidence limitations.

Strategic framing:

> The report should tell the hiring team what the interview actually proved, not merely what was said.

### 4.7 Engineering Simulation Workbench

The simulation track places candidates inside realistic engineering work.

Implemented examples:

- Payment retry safety: fix an idempotency hole that can double-charge users.
- Flash sale inventory race: reason about oversell during concurrent reservations.

Candidate actions include:

- reading an incident,
- planning a fix,
- editing code,
- running tests,
- observing failures,
- improving the solution,
- defending tradeoffs,
- reflecting on what remains unproven.

Strategic role:

> The voice interview tests claimed experience and reasoning depth. The simulation workbench tests applied judgment under real work conditions.

---

## 5. Candidate Experience

### 5.1 Candidate-Facing Design Goal

The candidate experience should feel:

- serious,
- calm,
- responsive,
- fair,
- clear,
- premium,
- and human-respecting.

It should not feel:

- like a surveillance dashboard,
- like an interrogation chamber,
- like a chatbot,
- like a visualizer demo,
- like a deposition transcript,
- or like a generic video call.

### 5.2 Live Room Philosophy

The live room should always answer three questions:

1. What is the current question?
2. Whose turn is it?
3. What context has been retained?

Everything else is secondary.

### 5.3 Key UI Components

**AI Interviewer Presence**

- Abstract Aura.
- Shows state without pretending to be human.
- Avoids uncanny face/avatar.
- Signals listening, asking, reviewing, closing.

**Current Question**

- Highest-priority object.
- Anchored centrally.
- Pitch-black card for readability.
- Does not get pushed around by transcript.

**Turn Rail**

- AI corner / Turn / Candidate corner.
- Active side glows subtly.
- Makes floor ownership explicit.

**Candidate Answer Live Transcription**

- Current utterance only.
- Separate from committed history.
- Can be shown or hidden.
- Should not dominate the screen.

**Turn History**

- Committed prior Q/A turns.
- Secondary memory system.
- Latest first.
- Full transcript opens on demand.

**Camera**

- Candidate camera belongs in the right rail.
- Preview can be hidden without stopping capture.
- During candidate turn, camera zone can light subtly.

**Controls**

- Repeat question.
- Need a moment.
- Fix last term.
- Hide stream.
- Full transcript.
- End interview.

### 5.4 Psychological Safety

Candidates need control, not false comfort.

The UI should give candidates practical agency:

- repeat the question,
- pause briefly,
- correct speech recognition,
- see live transcription,
- hide their preview,
- understand when the AI is thinking,
- and exit cleanly.

The system should not show live scoring, weakness labels, hidden evaluator state, or "risk detected" language during the live interview.

### 5.5 Candidate-Facing Onboarding

The candidate prep/onboarding demo should explain:

- how the room works,
- how turn-taking works,
- where the question appears,
- where their live answer appears,
- what controls exist,
- what the camera/history rail does,
- and how to start the live interview.

It should not mention:

- adversarial probes,
- weakness detection,
- policy handlers,
- score internals,
- hidden report risk labels,
- or backend map machinery.

Candidate copy should sound like:

> You will be asked about your experience, then follow-up questions will explore how you reason through details and apply judgment. The room will show whose turn it is, keep the current question visible, and give you controls if you need a moment.

---

## 6. Hiring Team And Buyer Experience

### 6.1 Buyer Persona

Primary buyer/users may include:

- HR leaders,
- technical recruiters,
- hiring managers,
- engineering managers,
- talent assessment teams,
- technical interview ops,
- internal evaluation teams,
- staffing platforms,
- recruiting marketplaces.

Each cares about different things:

- HR cares about consistency, fairness, process quality, candidate experience.
- Hiring managers care about signal quality and decision confidence.
- Recruiters care about throughput and explainable recommendations.
- Technical leads care about whether the candidate's reasoning actually holds up.
- Investors care about category, moat, scalability, market pull, defensibility.

### 6.2 Buyer Outcome

The buyer should not receive a raw transcript and a score. They should receive a decision package.

The report should help answer:

- Is this candidate plausibly fit for the role?
- What was their strongest demonstrated signal?
- What claims were supported?
- What claims were only partially tested?
- What risks remain?
- What would a human interviewer ask next?
- How confident should we be in this result?

### 6.3 Why The Report Is More Valuable Than A Transcript

A transcript says what happened. A report explains what it means.

The report should:

- compress the interview into decision-relevant evidence,
- distinguish proof from uncertainty,
- avoid overclaiming,
- surface coverage gaps,
- connect answers to resume claims,
- and support defensible next steps.

### 6.4 HR/Buyer Demo Message

The HR/buyer demo should not over-index on technical agent names. It should show:

- resume claim enters,
- role-specific assessment map is prepared,
- live room tests reasoning,
- candidate receives clear experience,
- hiring team receives evidence package,
- report explains fit and uncertainty.

The emotional takeaway:

> This makes hiring decisions more defensible without turning candidates into data points.

---

## 7. Engineering Architecture

### 7.1 Frontend

Main frontend stack:

- Next.js App Router.
- Candidate landing page.
- Live interview routes.
- Report routes.
- Recruiter/dashboard prototypes.
- Simulation pages.
- Visualizer/demo prototypes.
- Shared design components.
- Browser-side Deepgram integration through `lib/audio.ts`.

Important route surfaces:

- `/interview/[session_id]`: original live voice interview workspace.
- `/interview-room/[session_id]`: newer live candidate room route using the locked-room visual shell.
- `/report/[session_id]`: report display.
- `/simulation`: payment retry simulation.
- `/simulation/inventory`: inventory race simulation.
- `/simulation/report/[session_id]`: simulation report.
- `/visualizer-livekit-room-floor-locked`: locked visual reference for the live room.
- `/visualizer-map-prep-cinematic`: cinematic map-prep/onboarding prototype.
- `/visualizer-map-prep-internal`: internal/buyer-facing prototype.
- `/visualizer-map-prep-candidate`: candidate-facing walkthrough prototype.
- `/visualizer-interview-demo-flash`: experimental full-interview demo direction.

### 7.2 Backend

Main backend stack:

- FastAPI.
- Redis session state.
- OpenRouter model routing.
- Deepgram browser ASR.
- Cartesia-first TTS.
- ElevenLabs fallback TTS.
- Multi-agent orchestration.
- Simulation services.
- Report generation.

Key backend components:

- `backend/api/routes.py`: API endpoints.
- `backend/services/orchestrator.py`: live interview brain.
- `backend/services/interview_map.py`: resume-grounded map prep.
- `backend/services/tts_service.py`: Cartesia-first synthesis.
- `backend/models/llm_router.py`: model routing and JSON recovery.
- `backend/state/session_manager.py`: Redis-backed session state.
- `backend/agents/*`: assessment agents.

### 7.3 Core Runtime Loop

Simplified:

```text
Candidate speaks
  -> Deepgram streams transcript
  -> frontend commits final answer
  -> backend applies staged analysis
  -> next question is selected
  -> TTS speaks question
  -> background agents prepare future moves
  -> final report synthesizes evidence
```

### 7.4 Important Architecture Principle

Canonical state should mutate at clean turn boundaries. Background agents should stage future analysis, not corrupt the current user-visible turn.

Business translation:

> The system can feel fast without losing the integrity of the assessment record.

### 7.5 Realtime Interaction Contract

The product needs to distinguish:

- counted assessment turns,
- non-counting interaction moves.

Assessment turns include:

- mechanism probe,
- boundary probe,
- application transfer,
- coverage pivot,
- synthesis close.

Interaction moves include:

- repeat,
- rephrase,
- slow down,
- pause,
- resume,
- bad-audio repair,
- continuation invite.

This distinction is crucial. A candidate asking "can you repeat that?" should not consume an interview question or affect assessment coverage.

---

## 8. Moat

### 8.1 Resume-Grounded Map

Many interview products can ask questions. Antigravity builds a candidate-specific map from resume evidence and role context.

Moat:

- specificity,
- role relevance,
- branch planning,
- coverage tracking,
- and claim calibration.

### 8.2 Multi-Agent Evidence Generation

The system does not rely on one monolithic chat response. Different agents analyze different evidence dimensions.

Moat:

- weakness detection,
- discrepancy tracking,
- reasoning behavior,
- application transfer,
- coverage evaluation,
- final evidence synthesis.

### 8.3 Low-Latency Voice Orchestration

The two-track architecture exists because voice UX collapses if response timing feels dead.

Moat:

- staged next questions,
- partial transcript speculation,
- background analysis,
- filler/TTS readiness,
- turn-boundary integrity.

### 8.4 Candidate Trust UI

Most AI interview tools feel like forms, bots, or surveillance products. Antigravity's visual direction aims to create a premium assessment room.

Moat:

- turn ownership,
- anchored question,
- separate live transcript vs committed history,
- candidate controls,
- abstract AI presence,
- calm room design.

### 8.5 Evidence-First Report Contract

The report is not a scorecard wrapper. It is the decision artifact.

Moat:

- what was tested,
- what was proven,
- what remained uncertain,
- what to follow up,
- how resume claims calibrated against live evidence.

### 8.6 Engineering Simulation Workbench

The simulation product expands the category beyond voice interviewing.

Moat:

- real code,
- real tests,
- realistic incidents,
- behavior evidence,
- validation reasoning,
- evidence ledger.

### 8.7 Testing And Harness Discipline

The project includes simulation harnesses, map gates, replay tests, policy checks, and browser tests. This matters because interview systems can look good in isolated demos but fail under real runtime conditions.

Moat:

> Antigravity is being tested as a system of assessment behavior, not just as a UI.

---

## 9. Demo Strategy

### 9.1 Demo Principle

The demo should feel like using the product, not reading a pitch deck inside a browser.

The best demos from companies like Claude, Gemini, Base44, Suno, ElevenLabs, and modern AI product launches tend to do three things:

1. Make the product action visible.
2. Explain the problem through interaction, not paragraphs.
3. End with a clear artifact that proves value.

Antigravity should follow that structure:

```text
Weak hiring evidence
  -> role/resume context enters
  -> interview room forms
  -> live turn movement is shown
  -> candidate answer becomes evidence
  -> report becomes decision package
```

### 9.2 90-Second Cinematic Product Ad

Audience:

- investors,
- website visitors,
- executive buyers.

Goal:

- establish category and product feel quickly.

Suggested sequence:

1. Start with one centered object: "Start interview simulation."
2. Cursor selects it.
3. Three evidence cards appear:
   - Resume claim.
   - Live test.
   - Decision evidence.
4. Cursor glides across cards; each card raises as it becomes active.
5. Product shows how a resume claim becomes live testing.
6. Live room forms.
7. Turn ownership moves between AI and candidate.
8. Answer becomes report evidence.
9. Final report appears: "Scoped yes, with follow-ups."

Emotional takeaway:

> This is what an AI-native interview should feel like.

Avoid:

- technical agent names,
- dense architecture,
- too much text,
- raw dashboard grids,
- busy internal labels.

### 9.3 5-Minute Investor Demo

Audience:

- seed/pre-seed investors,
- strategic advisors,
- technical angels.

Goal:

- show market pain, product mechanism, moat, and credible progress.

Suggested flow:

1. Problem: hiring still relies on weak evidence.
2. Product: Antigravity creates a live assessment room.
3. Mechanism: resume evidence becomes interview map.
4. Live room: show turn ownership and anchored question.
5. Candidate answer: show live transcription and follow-up.
6. Report: show decision package.
7. Simulation: show future/second product surface with real code and tests.
8. Moat: map + agents + report + simulation + UI trust layer.

Investor takeaway:

> This is not another AI screening bot. It is a new assessment infrastructure layer.

### 9.4 HR / Buyer Demo

Audience:

- HR leaders,
- recruiting teams,
- hiring managers.

Goal:

- show how Antigravity improves consistency and decision quality.

Suggested flow:

1. Upload resume and role.
2. Show evidence packet:
   - role,
   - problem,
   - measurement basis,
   - fit for job,
   - room goal.
3. Show live room from candidate perspective.
4. Show how candidate controls preserve fairness.
5. Show report:
   - role fit,
   - strongest signal,
   - tested strengths,
   - scoped risks,
   - follow-ups.

Buyer takeaway:

> Better evidence, clearer reports, fairer candidate experience.

Avoid:

- "adversarial" branding,
- hidden weakness labels,
- complex backend diagrams,
- model/provider specifics unless asked.

### 9.5 Technical Architecture Demo

Audience:

- CTO,
- technical cofounder,
- engineering evaluator,
- technical investor.

Goal:

- prove the system is not a wrapper around a chatbot.

Suggested flow:

1. Resume and role enter.
2. Interview map prep creates launch-ready tracks.
3. Live room starts.
4. Candidate answer triggers parallel agents.
5. Next question arrives via fast path.
6. Background pipeline stages future packet.
7. Report V2 synthesizes evidence.
8. Optional simulation workbench shows real code execution.

Technical takeaway:

> The architecture is designed around turn integrity, latency, evidence, and assessment quality.

### 9.6 Candidate-Facing Demo

Audience:

- candidates waiting for map prep,
- candidates before live room entry.

Goal:

- reduce anxiety and explain controls.

Suggested flow:

1. Confirm details.
2. Explain what to expect.
3. Show room layout.
4. Show turn rail.
5. Show question and live answer.
6. Show controls.
7. Show camera/history.
8. End with "Engage interview."

Candidate takeaway:

> I know how the room works, and I know what to do if I need help.

Avoid:

- internal map logic,
- scoring,
- weakness detection,
- report risk labels.

---

## 10. Pitch Deck Direction

### Suggested Slide Arc

1. **Hiring evidence is broken**  
   Resumes, interviews, and static tests are too weak to support confident decisions.

2. **Existing tools miss live reasoning**  
   Automation screens candidates faster, but does not necessarily observe judgment better.

3. **Antigravity creates an assessment room**  
   A live AI interviewer plus structured environment for role-specific evidence.

4. **Resume evidence becomes an interview map**  
   Candidate claims become testable surfaces, not generic questions.

5. **The room observes reasoning under pressure**  
   Turn-taking, follow-ups, application transfer, recovery, and clarification.

6. **The report becomes a decision package**  
   Hiring teams receive calibrated evidence, not a transcript dump.

7. **Simulation extends this into real work**  
   Candidates solve realistic incidents, run tests, and defend decisions.

8. **Why now**  
   AI changes both engineering work and assessment expectations. Hiring needs new evidence infrastructure.

9. **Moat**  
   Resume-grounded maps, multi-agent assessment, low-latency orchestration, report contract, simulation workbench, trust UI.

10. **Product readiness**  
   Show working live loop, locked room UI, report layer, simulation prototypes, test harnesses, and honest caveats.

11. **Roadmap**  
   From prototype and internal pilots to robust customer workflows, persistence, dashboarding, more simulation domains, and enterprise integrations.

12. **Ask / next step**  
   Funding, pilots, design partners, HR buyer validation, technical diligence, or investor intros.

### Alternative Short Pitch

> Antigravity turns hiring interviews into structured evidence. It reads the resume, builds a role-specific interview map, runs a live AI assessment room, observes how candidates reason and recover, and produces a decision package that tells hiring teams what was actually proven.

---

## 11. What To Highlight

### Highest-Signal Product Points

- The product evaluates live reasoning, not static answers.
- The resume becomes a structured interview map.
- The live room is designed for candidate clarity and trust.
- The system separates live transcription from committed history.
- The report is a decision package, not a transcript.
- The simulation workbench tests applied judgment with real code/tests.
- The architecture is built for low-latency spoken interaction.
- The product has an explicit philosophy: substance over intimidation.

### Highest-Signal Demo Moments

- A resume claim transforms into a targeted live question.
- Turn ownership visibly moves from AI to candidate.
- A candidate answer produces a meaningful follow-up.
- Live transcription appears without moving the question.
- A final report identifies strongest signal and scoped risks.
- A simulation shows code/test evidence rather than answer-only grading.

### Highest-Signal Strategic Claims

- Antigravity creates defensible hiring evidence.
- It makes AI interviews feel legible and controlled.
- It combines conversation, reasoning, and work simulation.
- It can become an assessment infrastructure layer, not merely a point tool.

---

## 12. What To Avoid

### Avoid In Investor / HR Pitch

- Overusing "adversarial" as the product identity.
- Showing hidden evaluator internals.
- Showing raw weakness labels.
- Making the product seem punitive.
- Overexplaining model routing.
- Presenting this as a chatbot.
- Showing too many technical components at once.
- Showing cluttered UI prototypes that feel like internal tools.
- Claiming production maturity where caveats remain.

### Avoid In Candidate Demo

- Weakness detection.
- Risk scoring.
- Policy handlers.
- Internal map names.
- Hidden evaluator state.
- "Probe/break/attack" language.
- Any suggestion that the system is trying to trap the candidate.

### Avoid In Technical Demo

- Hiding known caveats.
- Showing only a happy path without explaining turn integrity.
- Claiming generic AI magic instead of concrete architecture.
- Letting visual polish substitute for system behavior.

---

## 13. Current Readiness And Caveats

### Working / Strong

- End-to-end live interview loop exists.
- Resume-grounded map prep exists.
- Multi-agent orchestration exists.
- Two-track fast/slow design exists.
- Deepgram browser ASR path exists.
- Cartesia-first TTS path exists.
- Locked live-room visual reference exists.
- Live backend integration route exists.
- Report V2 direction exists.
- Payment simulation exists.
- Inventory simulation exists.
- Simulation e2e coverage exists.
- Internal and candidate onboarding prototypes exist.

### Still Needs Care

- Map prep latency can still be high.
- Some generated questions can be too long or overpacked.
- Late-stage routing is structurally safe but still needs senior-human polish.
- Dashboard/Postgres persistence is not fully complete for all production workflows.
- Candidate-facing voice and Realtime behavior require continued turn-integrity validation.
- UI demo routes are still prototypes and should be curated carefully before investor use.
- Report should be shown as a product direction and working artifact, but not oversold as final enterprise-grade scoring.

### How To Phrase This Honestly

Good:

> We have a working end-to-end assessment engine and several polished prototype surfaces. The next step is turning this into a focused buyer-facing demo and pilot-ready workflow.

Bad:

> The product is fully production-ready across all enterprise hiring workflows.

---

## 14. Recommended Demo Narrative For The Next Iteration

The next internal/investor demo should revolve around the **whole interview**, not only map prep.

Recommended narrative:

1. **Hook**  
   Hiring still relies on weak evidence.

2. **Input**  
   A resume claim enters: "owned launch analytics."

3. **Live Test**  
   The system does not trust the claim blindly. It creates a role-specific live test.

4. **Room**  
   Candidate enters a clear interview room with turn ownership, question anchoring, camera, transcript, and controls.

5. **Reasoning Moment**  
   Candidate answers under ambiguity.

6. **Follow-Up**  
   The AI asks the next question from what was actually said.

7. **Decision Package**  
   The report explains what held up, what did not, and what to clarify.

8. **Extension**  
   Simulation workbench shows where this goes next: real work, real tests, real evidence.

This is stronger than a technical dump because it lets the viewer feel the product loop.

---

## 15. Consultant Assignment

Please use this document to recommend:

1. **Best investor story**
   - What is the sharpest category framing?
   - Is this "AI interviews," "hiring evidence infrastructure," "assessment OS," or something else?

2. **Best HR/buyer story**
   - Which pain should be led with: consistency, defensibility, speed, candidate experience, quality of signal, or cost?

3. **Best demo sequence**
   - What should be shown in 90 seconds?
   - What should be shown in 5 minutes?
   - What should be held back?

4. **Best proof points**
   - Which claims need numbers before fundraising?
   - Which proof points can be qualitative for now?
   - What pilot metrics would matter most?

5. **What to cut**
   - Which product details confuse the story?
   - Which UI elements feel internal?
   - Which claims risk overpromising?

6. **Competitive positioning**
   - How should Antigravity position against:
     - generic AI interviewers,
     - coding test platforms,
     - recruiter automation tools,
     - assessment vendors,
     - AI coding-agent evaluation tools?

7. **Demo craft**
   - How much should be cinematic?
   - How much should be actual product?
   - What is the strongest opening moment?
   - What is the strongest ending moment?

8. **Buyer objections**
   - Candidate fairness.
   - AI bias.
   - Accuracy and false negatives.
   - Legal/compliance concerns.
   - Integration with existing ATS.
   - Candidate anxiety.
   - Human interviewer replacement fears.

9. **Fundraising lens**
   - What is the wedge?
   - What is the expansion path?
   - What makes the company venture-scale?
   - What proof would investors need in the next 90 days?

---

## 16. Suggested Positioning Options

### Option A: Hiring Evidence Infrastructure

> Antigravity turns interviews and simulations into defensible hiring evidence.

Best for:

- investors,
- enterprise buyers,
- strategic HR leaders.

Strength:

- broader than AI interviews.

Risk:

- may sound abstract unless demo makes it concrete.

### Option B: AI-Native Technical Assessment Room

> Antigravity is a live AI assessment room for engineering and product talent.

Best for:

- product demo,
- website hero,
- candidate experience.

Strength:

- concrete and visual.

Risk:

- may underplay report/data moat.

### Option C: The Interview That Produces A Decision Package

> Instead of interview notes, hiring teams get a decision package showing what was tested, proven, and left uncertain.

Best for:

- HR buyers,
- hiring managers,
- consulting-style deck.

Strength:

- directly tied to buyer pain.

Risk:

- report must look very strong.

### Option D: AI-Observed Engineering Simulation Platform

> Antigravity observes candidates doing realistic work, not just answering questions.

Best for:

- long-term vision,
- technical investors,
- engineering leadership.

Strength:

- differentiates strongly from interview bots.

Risk:

- may make the current voice product seem secondary.

Recommended combined position:

> Antigravity is an AI-native assessment room that turns live interviews and realistic simulations into defensible hiring evidence.

---

## 17. Product Glossary

**Assessment Room**  
The live candidate-facing environment where the AI interviewer, question, transcription, camera, controls, and history are organized.

**Interview Map**  
A role-specific plan generated from the candidate's resume and target role. It defines testable surfaces and question trajectories.

**Question Packet**  
A prepared interviewer move containing question text, route intent, focus metadata, and supporting context.

**Application Transfer**  
A question that asks the candidate to apply demonstrated reasoning to an adjacent role-relevant scenario.

**Coverage**  
The degree to which important role-relevant surfaces have been tested.

**Turn Ownership**  
The explicit UI and runtime state showing whether the AI interviewer or candidate owns the conversational floor.

**Live Transcription**  
The candidate's current utterance as it is being captured. It is not the same as committed history.

**Turn History**  
Committed prior Q/A turns.

**Decision Package**  
The final report artifact that converts the interview into hiring evidence.

**Simulation Workbench**  
A realistic environment where candidates work through engineering incidents and produce observable execution evidence.

---

## 18. Claude Codebase Reading Map For UI And Demo Copy

This section is for Claude or another writing-focused agent that needs to turn the product strategy into exact on-screen copy, component labels, demo stage text, pitch narration, or UI microcopy. The goal is to let the writing agent use real implementation context instead of inventing generic AI interview language.

Claude should read this brief first, then inspect the code paths below. The assignment is not to rewrite the product. The assignment is to mine the real UI, runtime architecture, report model, and simulation surfaces so the displayed text inside the demos feels precise, trustworthy, and Antigravity-native.

### What Claude Should Produce From This Context

Claude should produce a copy and demo-content package with:

- Stage-by-stage display text for the internal demo.
- Stage-by-stage display text for the candidate demo.
- Component-level labels for the live room preview.
- Short pitch narration for investor, HR/buyer, and technical audiences.
- Alternatives for hero lines, card titles, button labels, progress text, and report preview text.
- A list of UI components that need copy but are currently under-explained.
- A list of copy that should be removed because it leaks internals, feels generic, or weakens the product story.

The output should distinguish:

- **Internal / investor / HR copy:** can mention map builder, evidence packet, report contract, coverage, calibration, simulation workbench, and decision package.
- **Candidate-facing copy:** should mention clarity, turn-taking, question, answer transcription, controls, camera, history, and readiness. It must not mention scoring internals, weakness detection, adversarial probes, policy handlers, hidden evaluator logic, or risk labels.

### Priority Reading Order

Claude should inspect these files in this order.

1. Strategy and state documents:
   - `/Users/yash/antigravity/ANTIGRAVITY_PRODUCT_STRATEGY_AND_DEMO_BRIEF.md`
   - `/Users/yash/antigravity/README.md`
   - `/Users/yash/antigravity/PROJECT_STATE.md`
   - `/Users/yash/antigravity/COLLAB.md`
   - `/Users/yash/antigravity/ANTIGRAVITY_INTERVIEW_SYSTEM_TECHNICAL_README.md`
   - `/Users/yash/antigravity/ANTIGRAVITY_UI_RESEARCH_PRD.md`
   - `/Users/yash/antigravity/SIMULATION_PRD.md`
   - `/Users/yash/antigravity/REALTIME_INTERACTION_ACTION_DECK_CONTRACT.md`

2. Demo routes and stage machines:
   - `/Users/yash/antigravity/app/visualizer-interview-demo-flash/page.tsx`
   - `/Users/yash/antigravity/app/visualizer-map-prep-internal/page.tsx`
   - `/Users/yash/antigravity/app/visualizer-map-prep-candidate/page.tsx`
   - `/Users/yash/antigravity/app/visualizer-map-prep-cinematic/page.tsx`
   - `/Users/yash/antigravity/app/visualizer-livekit-room-floor-locked/page.tsx`

3. Live interview room implementation:
   - `/Users/yash/antigravity/app/interview-room/[session_id]/page.tsx`
   - `/Users/yash/antigravity/components/interview-room/InterviewRoomFloor.tsx`
   - `/Users/yash/antigravity/lib/audio.ts`
   - `/Users/yash/antigravity/components/agents-ui/agent-audio-visualizer-aura.tsx`
   - `/Users/yash/antigravity/components/Waveform.tsx`

4. Report model and report UI:
   - `/Users/yash/antigravity/app/report/[session_id]/page.tsx`
   - `/Users/yash/antigravity/backend/models/final_report.py`
   - `/Users/yash/antigravity/backend/agents/evaluation_agent.py`

5. Backend interview intelligence:
   - `/Users/yash/antigravity/backend/api/routes.py`
   - `/Users/yash/antigravity/backend/services/orchestrator.py`
   - `/Users/yash/antigravity/backend/services/interview_map.py`
   - `/Users/yash/antigravity/backend/services/question_quality.py`
   - `/Users/yash/antigravity/backend/data/question_quality_guide.json`

6. Engineering simulation workbench:
   - `/Users/yash/antigravity/app/simulation/page.tsx`
   - `/Users/yash/antigravity/app/simulation/inventory/page.tsx`
   - `/Users/yash/antigravity/app/simulation/report/[session_id]/page.tsx`
   - `/Users/yash/antigravity/backend/services/simulation_service.py`
   - `/Users/yash/antigravity/backend/services/inventory_simulation_service.py`

7. Verification and behavior contracts:
   - `/Users/yash/antigravity/tests/interview-room.e2e.spec.ts`
   - `/Users/yash/antigravity/tests/interview-room-live-smoke.e2e.spec.ts`
   - `/Users/yash/antigravity/tests/simulation.e2e.spec.ts`
   - `/Users/yash/antigravity/backend/test_robust_interview_simulation_suite.py`
   - `/Users/yash/antigravity/backend/test_interview_ripper_contract.py`
   - `/Users/yash/antigravity/backend/test_saved_map_replay_suite.py`

### Code Components To Mine For UI Language

| Product area | Files to inspect | What to extract |
|---|---|---|
| Internal cinematic demo | `app/visualizer-interview-demo-flash/page.tsx`, `app/visualizer-map-prep-internal/page.tsx` | Stage titles, stage rhythm, card language, cursor-led simulation moments, report preview wording, and the problem-to-output arc. |
| Candidate onboarding demo | `app/visualizer-map-prep-candidate/page.tsx` | Candidate-safe expectation setting, control explanations, room walkthrough copy, and what the candidate should feel before entering the live room. |
| Cinematic choreography baseline | `app/visualizer-map-prep-cinematic/page.tsx` | The strongest existing motion language: seed, toggle, builder card, building state, stepper, room reveal, and final ready state. |
| Locked room reference | `app/visualizer-livekit-room-floor-locked/page.tsx`, `components/interview-room/InterviewRoomFloor.tsx` | Final room component names and meanings: AI interviewer, Aura, turn rail, interviewer question, candidate answer live transcription, camera, hide stream, turn history, full transcript, repeat question, need a moment, fix last term, end interview. |
| Live runtime | `app/interview-room/[session_id]/page.tsx`, `lib/audio.ts` | Real interaction constraints: media permission, camera preview, Deepgram live ASR, partial transcript, barge-in, stale turn protection, TTS response, backend state hydration, report handoff. |
| Backend interview engine | `backend/api/routes.py`, `backend/services/orchestrator.py`, `backend/services/interview_map.py` | What is real in the product: start interview, prepare map, process turn, partial transcript, map status, follow-up selection, application transfer, coverage, second anchor, synthesis, report generation. |
| Report layer | `app/report/[session_id]/page.tsx`, `backend/models/final_report.py`, `backend/agents/evaluation_agent.py` | Exact report vocabulary: role fit, strongest signal, interview quality, resume claim calibration, tested strengths, scoped tested risks, knowledge coverage, recommended follow-ups, confidence limits. |
| Simulation workbench | `app/simulation/*`, `backend/services/*simulation*` | How to describe realistic job-task assessment: incidents, artifacts, tests, actions, evidence ledger, final recommendation, what was proved and not proved. |
| Question quality | `backend/services/question_quality.py`, `backend/data/question_quality_guide.json` | How Antigravity avoids weak questions: no generic recall, no unsupported hidden-internal traps, no self-rating prompts, no busy multi-part overload. Translate this into "higher-quality live evidence." |

### Existing Copy Fragments Worth Reusing Or Refining

These phrases already exist in prototypes and should be treated as raw material, not final copy:

- "Hiring still relies on weak evidence."
- "Antigravity turns the interview itself into the product."
- "The interview starts with role context, not generic questions."
- "The floor moves visibly between interviewer and candidate."
- "The live room makes the interview legible."
- "The output is a decision package."
- "Interviewer’s question"
- "Candidate answer live transcription"
- "Repeat question"
- "Need a moment"
- "Fix last term"
- "Hide stream"
- "Full transcript"
- "AI interviewer"
- "Candidate corner"
- "AI corner"
- "Turn"
- "Role fit"
- "Strongest signal"
- "Resume claim calibration"
- "Scoped tested risks"
- "Recommended follow-ups"

Claude should improve these for exact audience and stage. For example, "The output is a decision package" is strong for an internal pitch, but the candidate version should say something calmer like "Your interview is saved and ready for review."

### Translation Map From Code To Demo Story

Use this map to turn implementation into buyer-facing or candidate-facing language.

| Code reality | Better demo language | Audience |
|---|---|---|
| `interview_map.py` generates resume-grounded tracks and question ladders | "The system turns resume claims and role requirements into a live interview path." | Internal / buyer |
| `orchestrator.py` chooses follow-ups from the latest answer and agenda state | "The next question comes from what the candidate just said, not a static script." | Internal / buyer |
| `routes.py` exposes `partial_transcript`, `process_turn`, `tts`, `state`, and `report` | "Speech, state, response, and report handoff are part of one live loop." | Technical / internal |
| `lib/audio.ts` handles Deepgram ASR, TTS playback, filler, and turn flow | "The room listens, shows live capture, and answers without making the user guess what happened." | Candidate / technical |
| `InterviewRoomFloor.tsx` separates question, live transcription, camera, and history | "The question stays anchored while the answer and history remain available but secondary." | Candidate / buyer |
| Report V2 model | "The transcript is converted into a decision package: fit, signal, risk, calibration, and follow-ups." | Buyer / investor |
| Simulation services | "For engineering roles, Antigravity can observe real task behavior, not only spoken answers." | Investor / technical buyer |
| Question quality contracts | "The system is designed to avoid low-signal questions and test job-relevant judgment." | Buyer / investor |

### Copy Boundaries Claude Must Respect

Do not expose secrets or implementation-sensitive details:

- Do not read or quote `.env`.
- Do not include API keys, provider keys, tokens, private URLs, or local secret values.
- Do not turn internal route names, policy handlers, weakness labels, hidden evaluator logic, or raw scoring internals into candidate-facing UI copy.
- Do not use "adversarial" language in candidate-facing copy.
- Do not make the product sound like a generic chatbot, generic quiz engine, or generic AI interviewer.
- Do not overload the UI with every technical mechanism. The demo should show a few decisive moments clearly.

### Recommended Claude Deliverable Format

Ask Claude for a structured deliverable like this:

```text
1. Internal demo copy matrix
   - Stage
   - Viewer takeaway
   - On-screen title
   - Subtitle
   - Component/card labels
   - Motion/narrative cue
   - What to avoid

2. Candidate demo copy matrix
   - Stage
   - Candidate reassurance goal
   - On-screen title
   - Subtitle
   - Component labels
   - Safety/control copy
   - What not to reveal

3. Live room component copy
   - Component
   - Current label
   - Proposed label
   - Reason

4. Report preview copy
   - Buyer-facing version
   - Investor-facing version
   - Short demo version

5. Pitch narration
   - 90-second version
   - 5-minute version
   - Technical appendix version
```

### Suggested Prompt To Give Claude

```text
You are helping write the displayed UI copy and narrative for Antigravity, an AI interview and simulation platform that produces defensible hiring evidence.

Read `/Users/yash/antigravity/ANTIGRAVITY_PRODUCT_STRATEGY_AND_DEMO_BRIEF.md` first. Then inspect the code paths in section 18, especially the demo routes, live interview room, report UI, backend orchestrator, interview map generator, and simulation services.

Your job is not to invent a new product. Your job is to turn the real product architecture into excellent on-screen copy and demo narration.

Please produce:
- an internal/investor demo copy matrix,
- a candidate-facing onboarding copy matrix,
- live room component copy recommendations,
- report preview copy,
- a 90-second product demo narration,
- and a list of UI copy that should be removed or rewritten.

Use precise product language. Keep candidate-facing copy reassuring and non-technical. Keep investor/buyer copy focused on decision evidence, not model hype. Do not expose hidden scoring internals, weakness labels, adversarial language, API details, or secrets.
```

---

## 19. Reference Artifacts

Core docs:

- `/Users/yash/antigravity/README.md`
- `/Users/yash/antigravity/PROJECT_STATE.md`
- `/Users/yash/antigravity/COLLAB.md`
- `/Users/yash/antigravity/ANTIGRAVITY_UI_RESEARCH_PRD.md`
- `/Users/yash/antigravity/ANTIGRAVITY_INTERVIEW_SYSTEM_TECHNICAL_README.md`
- `/Users/yash/antigravity/SIMULATION_PRD.md`
- `/Users/yash/antigravity/REALTIME_INTERACTION_ACTION_DECK_CONTRACT.md`
- `/Users/yash/antigravity/ai_observed_engineering_simulation_platform_thesis_document.md`

Useful routes/prototypes:

- `/visualizer-map-prep-cinematic`
- `/visualizer-map-prep-internal`
- `/visualizer-map-prep-candidate`
- `/visualizer-interview-demo-flash`
- `/visualizer-livekit-room-floor-locked`
- `/interview-room/[session_id]`
- `/simulation`
- `/simulation/inventory`
- `/simulation/report/[session_id]`

---

## 20. Final Consultant Takeaway

Antigravity should not be pitched as "AI replacing interviewers."

It should be pitched as:

> A new evidence layer for hiring, built for a world where resumes are polished, interviews are inconsistent, engineering work is changing, and teams need defensible proof of judgment.

The strongest demo will not explain every internal component. It will make the viewer feel one complete loop:

```text
claim
  -> live test
  -> candidate reasoning
  -> adaptive follow-up
  -> decision evidence
```

The strongest deck will show that Antigravity is not just improving interviews. It is redefining what hiring evidence can look like in the AI-native era.

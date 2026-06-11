# Antigravity Live Interview UI Research Assignment

Date: 2026-05-30  
Audience: UI research engineer / interaction design researcher  
Purpose: Give enough product, system, and interaction context for the researcher to independently decide how the live interview UI should be structured.

## 0. Read This First

This is not a design proposal to copy.

This is a research brief and context dossier. The goal is to help you, the UI researcher/designer, understand the product deeply enough to make your own research-backed decisions about:

- how the page should be segmented
- what should be visible at each moment
- what should be hidden
- how transcript should behave
- how turn-taking should be communicated
- how the AI presence should feel
- how candidate trust should be built
- how to avoid making the interface feel gimmicky, creepy, stressful, or generic

Please do not treat the current prototype as final. Treat it as a visual exploration and a source of raw material.

Your job is to apply your own research, design judgment, and interaction-model thinking to propose the right UI architecture.

## 1. What Antigravity Is

Antigravity is an AI-observed technical assessment platform.

The product is not a quiz app and not a normal chatbot. It is meant to evaluate engineering candidates through live reasoning under pressure.

The live interview product works like this:

1. A candidate provides resume and role context.
2. The backend prepares a resume-grounded interview plan.
3. The candidate enters a live voice interview.
4. The AI interviewer asks a question.
5. The candidate answers by speaking.
6. The system transcribes the answer in real time.
7. Backend agents analyze the answer.
8. The AI immediately asks a relevant follow-up.
9. The interview continues for multiple turns.
10. At the end, the system produces an assessment report.

The product promise is:

> We measure how candidates reason, defend claims, handle ambiguity, correct themselves, and transfer ideas into new situations.

The UI problem is:

> How do we make a live AI interview feel clear, intimate, trustworthy, and serious when there is no human interviewer in the room?

## 2. What You Are Being Asked To Decide

Please decide, or propose ways to decide, the following:

### Page Architecture

- Should this be laid out like a chat, a cockpit, a live room, a stage, a console, or something else?
- What are the major regions of the page?
- Which region owns the user's attention during each state?
- Should the AI visual presence be a side element, a central element, a background layer, or something that moves by state?
- Should candidate metadata sit at the top, side, or be minimized after start?

### Information Hierarchy

- What is the most important thing on screen during AI speech?
- What is the most important thing on screen during candidate speech?
- What should happen to the previous question when the candidate answers?
- What should happen to the previous answer when the AI asks the next question?
- How much prior context should remain visible?

### Transcript Strategy

- Should the transcript be central, side-mounted, bottom-mounted, collapsible, or hidden by default?
- Should live ASR text be shown as the candidate speaks?
- How should provisional transcript differ visually from committed transcript?
- Should the candidate be able to correct ASR?
- If yes, when and how without breaking interview flow?
- How do we avoid a deposition/surveillance feeling?

### Turn-Taking

- How does the candidate know it is their turn?
- How does the candidate know the AI is listening?
- How does the candidate know the AI is thinking?
- How does the candidate know the AI is speaking and they should listen?
- How should barge-in be represented?
- How should latency be made understandable without exposing backend machinery?

### AI Presence

- What visual metaphor should represent the AI interviewer?
- Should it be an orb, Aura, waveform, face-like avatar, light field, stage lighting, or something else?
- Should it react to candidate audio?
- Should it react to AI speech?
- Should colors map to states?
- How much motion is useful before it becomes distracting?

### Candidate Trust

- What proof does the candidate need that the AI heard them?
- What proof does the candidate need that the AI used their answer?
- Should the next question show a small anchor from the prior answer?
- How much should the AI reveal about why it asked the next question?
- How can the UI feel challenging without feeling hostile?

### Candidate Controls

- What controls should always be visible?
- Repeat question?
- Pause / need a moment?
- Fix transcript?
- Stop interview?
- Mic test?
- Camera toggle?
- Should candidate have any control over transcript visibility?

### Ending

- What should happen visually when the interview ends?
- How should the UI transition from live interview to report preparation?
- Should it summarize what was covered?
- Should it simply say report is being generated?
- What ending feels premium and complete without feeling theatrical?

## 3. Current Prototype Inventory

These are existing artifacts you can inspect. They are not final designs.

### Real Interview Route

`/interview/[session_id]`

This is the actual production interview page. It includes:

- real microphone/camera startup
- Deepgram live transcription
- AI TTS playback
- phase state: idle, listening, thinking, speaking
- transcript messages
- partial transcript
- sprint/persona/internal assessment labels
- report transition at completion

This route contains real logic but not necessarily the desired final UI.

### Candidate-Facing LiveKit Prototype

`/visualizer-livekit-candidate`

This is the current candidate-facing visual exploration. It includes:

- candidate name, experience, role
- official LiveKit Aura visualizer
- current question area
- response area
- microphone test
- phase simulation buttons
- Claim / Gap / Next Probe simulator blocks
- Run Conversation simulation
- state-based Aura colors
- deep-ocean diagonal caustic background

This is probably the best current visual reference, but it is still a prototype.

### Full Neural Prototype

`/visualizer-livekit-neural`

This is a more intense experimental version. It includes:

- stronger neural/Gemini-style visual field
- official LiveKit Aura
- phase controls
- voice command experiments
- transcript/probe panels
- palette controls
- hue ripples on state changes

This may be too internal/operator-like for candidates, but useful for exploring energy and motion.

### Standalone HTML Prototypes

- `antigravity-neural-interview-preview.html`
- `antigravity-neural-visualizer-preview.html`

These are backend-free mockups for experimenting with interaction and visualizer ideas.

## 4. Current Backend And Frontend Capabilities

This section lists what the system can currently know or do. You can decide whether each item should affect the UI.

### Audio / Speech

- Browser captures candidate microphone.
- Browser connects directly to Deepgram.
- Deepgram emits interim transcript text.
- Deepgram emits final transcript segments.
- Deepgram can extract named entities.
- Frontend tracks microphone energy.
- Frontend can detect likely barge-in while AI is speaking.
- Frontend can abort TTS playback if the candidate interrupts.
- Frontend can show partial transcript while the candidate speaks.

### Turn State

The system has a floor state model:

| Technical state | Plain meaning |
|---|---|
| `IDLE` | Interview is not actively exchanging speech |
| `USER_SPEAKING` | Candidate owns the floor |
| `AI_THINKING` | Candidate answer is committed; AI is preparing next move |
| `AI_SPEAKING` | AI owns the floor and is asking/responding |

The prototypes use friendlier labels:

| Prototype label | Meaning |
|---|---|
| Idle | interview ready |
| Listening | candidate speaking |
| Reviewing | AI thinking |
| Question | AI speaking |
| Closing | interview complete / report prep |

### Backend Question Selection

The backend is not simply chatting. It has a structured interview engine:

- resume parsing
- interview map preparation
- focus areas from resume
- question packets
- prepped next question
- speculative question generation from partial transcript
- short-answer rescue
- discrepancy detection
- weakness detection
- reasoning behavior analysis
- application-transfer question
- coverage tracking
- final evaluation

Most of this is internal. The UI can use it indirectly, but probably should not expose raw internal labels to candidates.

### Fast/Slow Pipeline

The backend is designed so that the next question can be ready quickly:

1. While candidate speaks, backend receives partial transcript snapshots.
2. Backend may prepare speculative follow-up options.
3. When the final answer arrives, backend picks the next question quickly.
4. Full deeper analysis continues in the background.

This matters for UI because "thinking" should usually be brief. If it is not brief, the UI must make the wait feel intentional and safe.

### TTS

- Cartesia is primary TTS.
- ElevenLabs is fallback only.
- Filler audio can play quickly to reduce dead air.
- AI spoken response and visible question text must stay aligned enough to avoid confusion.

### Session / Report

- Session state lives in Redis.
- Interview history is stored.
- At completion, report finalization can run in background.
- UI may need a report-preparing state.

## 5. Candidate-Facing Data Inventory

Below is an exhaustive list of possible things that could appear in the candidate-facing UI. Your task is to decide which should appear, where, when, and how.

### Identity / Setup

- candidate name
- target role
- years of experience
- resume summary
- interview readiness
- mic permission status
- camera permission status
- connection status
- estimated interview length
- privacy/recording notice

### Live AI Presence

- Aura/orb/waveform/avatar
- AI state label
- audio-reactive motion
- AI speaking animation
- thinking animation
- listening animation
- completion animation
- background state hue
- transition ripple
- visual pulse on turn change

### Current Question

- current AI question text
- question type
- question count
- progress through interview
- time since question asked
- repeat question action
- "why this question" explanation
- prior answer anchor
- current focus area

### Candidate Speech

- live transcript
- partial/provisional transcript
- committed answer
- ASR confidence hint
- entity highlights
- filler words / pauses
- silence indicator
- mic energy
- "still listening" indicator
- "answer received" indicator
- transcript correction affordance

### Conversation Memory

- previous AI questions
- previous candidate answers
- last 2-3 turns
- full transcript
- timeline
- expandable details
- search after interview
- export after interview
- current answer vs historical answers

### Assessment-Derived Signals

These exist internally. You must decide if they should be shown, translated, or hidden.

- claim being tested
- gap in answer
- next probe
- weakness severity
- discrepancy level
- application-transfer phase
- coverage map
- focus area
- route kind
- candidate communication mode
- questions remaining
- final score

### Candidate Controls

- start
- stop
- pause
- need a moment
- repeat question
- skip / ask to rephrase
- fix transcript
- mute microphone
- camera toggle
- end interview
- return to dashboard
- accessibility/reduced motion
- transcript visibility toggle

### Error / Recovery

- mic unavailable
- Deepgram disconnected
- AI audio failed
- transcript unclear
- backend failed to produce question
- report still generating
- session expired
- user accidentally interrupted AI
- AI accidentally captured its own echo

## 6. Candidate vs Recruiter vs Internal Visibility

Please evaluate this matrix and decide what belongs where.

| Information | Candidate live UI | Candidate post-interview | Recruiter report | Internal debug |
|---|---|---|---|---|
| Current question | likely yes | yes | yes | yes |
| Candidate live transcript | maybe | maybe | no | yes |
| Committed transcript | maybe | yes | yes | yes |
| AI state | likely yes | no | no | yes |
| Mic energy | likely yes | no | no | yes |
| Question count | maybe | yes | yes | yes |
| Weakness severity | likely no | maybe no | yes | yes |
| Discrepancy | likely no | maybe no | yes | yes |
| Claim/gap/next probe | maybe translated | maybe | yes | yes |
| Route kind | no | no | no | yes |
| Final score | no | maybe | yes | yes |
| Coverage map | no | maybe summarized | yes | yes |
| Report readiness | yes | yes | yes | yes |

This table is not a decision. It is a prompt for your judgment.

## 7. Important Interaction Scenarios

The final UI should handle all of these.

### Scenario A: Normal Fluent Candidate

1. AI asks a question.
2. Candidate gives a strong answer.
3. Live transcript appears.
4. Answer commits.
5. AI briefly reviews.
6. Follow-up question appears, clearly connected to prior answer.

Research issue: how to make the follow-up feel adaptive without exposing backend scoring.

### Scenario B: Terse Candidate

1. AI asks a question.
2. Candidate says "mostly cost" or gives a 1-line answer.
3. Backend uses short-answer rescue or trajectory map.
4. AI asks a grounded follow-up.

Research issue: how to avoid making the UI feel punitive or broken when the answer is short.

### Scenario C: Candidate Interrupts AI

1. AI is speaking.
2. Candidate starts talking.
3. Frontend confirms barge-in.
4. AI TTS stops.
5. Candidate gets the floor.

Research issue: how to show this gracefully and not make interruption feel like an error.

### Scenario D: ASR Error

1. Candidate says something technical.
2. Transcript mishears jargon.
3. Candidate notices.

Research issue: whether/how to offer correction without turning the interview into text editing.

### Scenario E: Backend Latency

1. Candidate answer commits.
2. Next question takes longer than expected.

Research issue: how to make waiting feel like thoughtful review rather than a system stall.

### Scenario F: Interview Closing

1. Final question is answered.
2. AI wraps.
3. Report generation begins.

Research issue: how to make the ending feel complete, premium, and calm.

## 8. Current UI Tensions

Please think deeply about these tensions.

### Transcript vs Presence

The transcript creates transparency, but too much transcript makes the interview feel like surveillance.

Question: where is the balance?

### Immersion vs Seriousness

Gemini-style aura, caustics, and glowing motion can create a premium AI feeling. Too much can feel like a disco or toy.

Question: what is the correct visual intensity for a serious candidate assessment?

### Challenge vs Psychological Safety

The system is adversarial in the sense that it probes weak reasoning. But the candidate-facing UI should not feel hostile.

Question: how do we communicate rigor without aggression?

### AI Transparency vs Anxiety

Showing "why this question" could build trust. Showing "weakness detected" could create anxiety.

Question: what level of explanation is useful during the live interview?

### Human-Like vs Honest Machine

We want intimacy, but we should not fake a human interviewer.

Question: what non-human interaction pattern can still feel warm and attentive?

### Current Turn vs Interview Memory

The current turn needs focus. But candidates also need enough memory to understand continuity.

Question: how should prior turns be represented?

## 9. Research-Backed Areas To Investigate

Please use external research and your own expertise. Useful domains:

- conversation design
- voice UI turn-taking
- human-AI interaction guidelines
- trust in AI systems
- cognitive load during high-pressure tasks
- transcript/caption UX
- video interview UX
- assessment/test-taking UX
- accessibility for voice interfaces
- motion design for state feedback
- explainability in AI products

Starting references:

- Google Conversation Design: https://developers.google.com/assistant/conversation-design/learn-about-conversation
- Microsoft Human-AI Interaction Guidelines: https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/
- Nielsen Norman Group Usability Heuristics: https://www.nngroup.com/articles/ten-usability-heuristics/
- Apple Human Interface Guidelines, Feedback: https://developer.apple.com/design/human-interface-guidelines/feedback
- Apple Human Interface Guidelines, Siri: https://developer.apple.com/design/human-interface-guidelines/siri/

Please do not limit yourself to these.

## 10. Deliverables Requested From The Researcher

Please provide a research-backed UI plan that includes:

1. Recommended page segmentation.
2. Desktop layout.
3. Mobile layout.
4. Candidate-facing information hierarchy.
5. Transcript strategy.
6. Turn-taking model.
7. AI presence / Aura behavior model.
8. Motion and color policy.
9. Candidate controls policy.
10. Error and recovery UI policy.
11. Ending / report handoff experience.
12. What to show live vs post-interview vs recruiter-only.
13. Copy and terminology guidelines.
14. Accessibility considerations.
15. Risks and anti-patterns.
16. Prototype recommendations.
17. Open questions that need user testing.

If possible, include:

- wireframes
- annotated state diagrams
- interaction storyboard
- specific component inventory
- examples of good reference products
- rationale for each major decision

## 11. Specific Questions We Need Answered

### Page Segmentation

- What should be the main visual object during the interview?
- Should the current question be full-stage, card-like, or transcript-like?
- Should the AI presence occupy persistent side real estate?
- Should the candidate answer sit below the question or replace it during speech?
- Should memory live in a right rail, bottom drawer, or modal?

### Transcript

- Should live transcript appear while speaking?
- Should the transcript auto-collapse after a turn?
- Should previous turns be shown as cards, timeline, bubbles, or something else?
- Should transcript correction be allowed before the answer is submitted?
- Should transcript correction be allowed after submission?

### Turn-Taking

- What combination of text, color, motion, and audio should signal the floor?
- Is a state label like "Your turn" enough?
- Should AI speech and candidate speech occupy different visual zones?
- How should barge-in feel?
- How should silence be represented?

### AI Presence

- Is the Aura enough as an interviewer presence?
- Should the Aura be larger, smaller, central, or peripheral?
- Should it be audio-reactive?
- Should it change shape by state?
- Should it have a "personality" or remain abstract?

### Candidate Trust

- What visible proof of listening is required?
- Should next questions include "I heard X, so I am asking Y"?
- Should the system show "answer received"?
- Should it show "preparing follow-up"?
- Should it show how many questions remain?

### Candidate Stress

- Which UI elements increase pressure productively?
- Which UI elements create unhelpful anxiety?
- Does showing transcript increase or reduce stress?
- Does showing progress reduce or increase stress?
- Does showing the AI "thinking" make the system feel smarter or judgmental?

### Visual Style

- What visual intensity is appropriate for a serious AI assessment?
- How should Gemini/LiveKit-inspired effects be restrained?
- What color/state mapping is most intuitive?
- What should be animated and what should stay stable?

### Ending

- What should the last 10 seconds feel like?
- Should the UI summarize the conversation?
- Should it show report generation progress?
- Should there be a final Aura bloom / state transition?
- How should the candidate leave the room?

## 12. Constraints

### Product Constraints

- The system is real-time voice-first.
- It must feel serious enough for hiring.
- It must feel premium enough to differentiate.
- It must not look like a generic chatbot.
- It must not reveal internal scoring live.
- It must support candidates who are fluent, terse, nervous, or interrupted.

### Technical Constraints

- Next.js frontend.
- Browser-side Deepgram SDK.
- LiveKit Aura component is available.
- Backend returns next question and state metadata.
- Some deeper analysis is asynchronous.
- TTS playback and visible question text need to stay coherent.
- Reduced-motion support is required.
- Mobile should not be an afterthought.

### Ethical / Trust Constraints

- Do not over-humanize the AI deceptively.
- Do not show hidden assessment labels to candidates.
- Do not make candidates feel surveilled unnecessarily.
- Do not obscure when audio is being captured.
- Provide clear recovery for mic/transcription failures.

## 13. What We Do Not Want

- A generic chat app with an orb.
- A dashboard full of internal metrics.
- A decorative AI light show that distracts from the interview.
- A transcript wall that feels like legal testimony.
- A fake human avatar that creates uncanny expectations.
- Hidden system state that makes candidates wonder if the app is broken.
- Too many controls that make it feel like an operator console.

## 14. What We Might Want

These are not decisions. They are hypotheses to evaluate.

- A "live turn stage" where the current question and answer are central.
- A compact memory rail instead of full transcript dominance.
- A stateful AI Aura that behaves like body language.
- A visible "You said..." anchor before some follow-ups.
- A calm "reviewing your answer" state for latency.
- A graceful barge-in transition.
- A transcript correction affordance.
- A premium closing sequence before report generation.

## 15. Research Output Format

Please structure your response as:

1. Summary recommendation.
2. Key principles.
3. Proposed information architecture.
4. State-by-state UI behavior.
5. Transcript strategy.
6. Visual/motion strategy.
7. Candidate controls.
8. Candidate trust and safety.
9. Recruiter/internal separation.
10. Prototype plan.
11. Risks and mitigations.
12. Open research questions.

## 16. Final Note

The current Antigravity team has explored many visual ideas, but we are explicitly asking you to think independently.

Please challenge the prototypes. If the Aura should move, say so. If transcript should be hidden, say so. If the current layout is wrong, say so. If the page should be radically simpler, say so.

The desired output is not praise. The desired output is a clear, research-backed UI philosophy and plan for the live AI interview room.


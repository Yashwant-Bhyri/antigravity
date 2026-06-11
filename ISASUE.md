Conversational Interviewing System —
Summary Document
Current Project flow :
1. Resume Upload & Map Generation Users upload details via
frontend/app/page.tsx. Data routes through POST /api/prepare_interview_map
(backend/api/routes.py) to backend/services/interview_map.py. There,
resume_agent.py uses Claude 3 Haiku to generate a tailored "Interview Trajectory Map.
"
2. Interview Initialization The frontend triggers POST /api/start_interview.
backend/services/orchestrator.py initializes the Redis session state and loads the
live UI at frontend/app/interview/[session_id]/page.tsx.
3. Real-Time Voice Processing frontend/lib/audio.ts streams voice via Deepgram
ASR. Interim transcripts hit POST /api/partial_transcript, where
backend/services/orchestrator.py and followup_agent.py use Claude 3.5
Sonnet to speculatively prepare the next question.
4. Turn Evaluation & Agent Dispatch Final transcripts go to POST /api/process_turn.
backend/services/orchestrator.py dispatches them to four parallel agents:
●
weakness_agent.py (Claude 3.5 Sonnet): Grades logical flaws.
●
concept_agent.py (Claude 3 Haiku): Extracts technical jargon.
●
discrepancy_agent.py (Claude 3.5 Sonnet): Checks resume contradictions.
●
reasoning_behavior_agent.py (Claude 3 Haiku / Claude 3.5 Sonnet):
Analyzes behavior.
5. Follow-up Generation & Cartesia TTS Aggregated signals route to
followup_agent.py (Claude 3.5 Sonnet) to generate a dynamic follow-up or pivot. The
text response goes to backend/services/tts_service.py for Cartesia TTS synthesis,
while the frontend plays pre-cached filler words to mask latency.
6. Post-Session Evaluation The session concludes via POST /api/end_interview.
The orchestrator passes the history to backend/agents/evaluation_agent.py, where
Claude 3 Opus performs a deep evaluation. The frontend fetches the final "Hire / No Hire"
verdict via GET /api/report and visualizes it at
frontend/app/report/[session_id]/page.tsx.
1. Problems With Current Model
1. Robotic and Unnatural Tone
●
Conversations feel mechanical and system-like despite an advanced backend
(multi-agent orchestration, weakness detection).
●
The system prioritizes technical accuracy but lacks a definition for what makes an
interaction feel authentic, natural, and human.
2. Adversarial and Prosecutorial Approach
●
The interview flow heavily over-indexes on probing, verification, pressure escalation,
and inconsistency detection.
●
Questions like “Which module did you actually own?” create suspicion,
defensiveness, and a stressful environment rather than fostering openness.
3. Psychologically Uninviting Questioning
●
Technically relevant questions (e.g.,
“What broke first?” or "What was the hardest
bottleneck?") act as rigid information extractors rather than natural conversation
openers.
●
The system optimizes for generating generic “good” technical questions but ignores
human-preferred, inviting interview behavior.
4. Missing Conversational Psychology
●
The interaction relies on a rigid "probe → verify → challenge → pressure" loop.
●
It fails to utilize a balanced conversational oscillation that includes curiosity, reflection,
and exploration.
5. Absence of Reflective and Narrative Dimensions
●
The current ontology is strictly focused on implementation details, ownership,
failures, and debugging.
●
It completely misses crucial conversational elements like narrative flow, high-level
reflection, tradeoff analysis, and prioritization.
2. Proposed Solutions
Solutions Proposed by User
A. Build human-feedback-driven conversational alignment
Collect large-scale human evaluator signals to understand:
●
what feels natural,
●
what feels human,
●
what creates openness,
●
what creates authentic technical expression.
B. Create structured question ontology
Questions categorized by:
●
role,
●
domain,
●
experience level,
●
implementation depth,
●
architecture,
●
product thinking,
●
deployment,
●
communication style,
●
reasoning type.
C. Use RLHF / preference learning ideas
Use human evaluators to:
●
compare question trajectories,
●
rank conversational quality,
●
identify better transitions,
●
evaluate reasoning.
Then use these signals to:
●
refine policy layer,
●
improve prompting,
●
improve interview maps,
●
steer runtime behavior.
D. Focus on conversational pathways, not just questions
Core insight:
A technically strong question wrapped in the right conversational pathway
becomes psychologically inviting.
E. Use async reasoning pipeline
Current architecture:
●
reasons over question N-1,
●
prepares N+1 while candidate answers current question,
●
dynamically adapts follow-ups.
D. Optimize for authentic signal, not maximum probing
Better objective:
maximize authentic technical expression
instead of:
maximize pressure and verification
E. Add conversational state tracking
Track:
●
pressure accumulation,
●
openness,
●
narrative flow,
Then adapt:
●
escalation,
●
pacing,
●
question type,
●
conversational mode.
F. Separate evaluation dimensions
Instead of generic scoring,
split evaluation into:
1. Technical quality
2. Conversational quality
3. Psychological dynamics
4. Reasoning quality
3. RL / Preference Learning Experiment
Goal
Learn:
What interview conversations feel technically rigorous yet genuinely human?
and to refine policy layer with the help of RL
optimizing:
●
authentic technical expression,
●
conversational openness,
●
natural transitions,
●
psychologically inviting interviewing.
Expected workflow for the experiment :
User uploads Resume → Model Creates questions and creates trajectories → Need
web page here to evaluate model trajectories with the help of human interviewers →
→ Collect responses and feed to Model → Use these as signal for reward system
(Technical, Communicational, Physiological, Reasoning → Model optimizes Policy
Result of experiment: Optimized policy so that we can use it directly

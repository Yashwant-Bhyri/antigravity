"use client";

import { createClient, LiveTranscriptionEvents } from "@deepgram/sdk";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { AgentState } from "@livekit/components-react";

import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";
import { getApiBaseUrl } from "@/lib/api";

type Phase = "ready" | "asking" | "listening" | "reviewing" | "closing";

const API = getApiBaseUrl();
const FALLBACK_API = "http://localhost:8000/api";
const API_CANDIDATES = Array.from(new Set([API, FALLBACK_API]));

type ProviderStatus = {
  openai_configured: boolean;
  deepgram_configured: boolean;
  default_realtime_model: string;
  realtime_models: string[];
  default_transcribe_model: string;
  transcribe_models: string[];
  realtime_transcription_model: string;
};

type ProviderRuntime = {
  baseUrl: string;
  status: ProviderStatus;
};

type LabEvent = {
  id: string;
  ts: string;
  type: string;
  detail?: string;
};

type AnswerSignal = "strong" | "partial" | "honest_gap" | "evasive" | "stuck" | "closing";
type OperationalInteraction = "repeat" | "slow_down" | "rephrase" | "pause";

type AnswerOption = {
  signal: AnswerSignal;
  label: string;
  text: string;
  nextTurn?: number;
};

type SimulationTurn = {
  question: string;
  answer: string;
  said: string;
  testing: string;
  route: string;
  posture: string;
  focus: string;
  answerOptions: AnswerOption[];
  nextBySignal: Partial<Record<AnswerSignal, number | "close">>;
};

type UsageTurn = {
  id: string;
  label: string;
  question: string;
  answer: string;
  inputAudioMs: number;
  outputAudioMs: number;
  inputTextTokens: number;
  outputTextTokens: number;
  providerUsage?: unknown;
};

type RealtimeRateCard = {
  audioInputPerMTokens: number;
  audioOutputPerMTokens: number;
  textInputPerMTokens: number;
  textOutputPerMTokens: number;
};

type BackendDiagnostics = {
  summary: any;
  actualModel: string;
  usage: {
    providerUsageEvents: number;
    inputTextTokens: number;
    outputTextTokens: number;
    inputAudioTokens: number;
    outputAudioTokens: number;
    cachedTokens: number;
    totalTokens: number;
    estimatedCost: number;
  };
  refreshedAt: string;
};

type TurnGuardStatus = "clean" | "asking" | "blocked" | "warning";

const REALTIME_RATE_CARDS: Record<string, RealtimeRateCard> = {
  "gpt-realtime-mini": {
    audioInputPerMTokens: 10,
    audioOutputPerMTokens: 20,
    textInputPerMTokens: 0.6,
    textOutputPerMTokens: 2.4,
  },
  "gpt-realtime-2": {
    audioInputPerMTokens: 32,
    audioOutputPerMTokens: 64,
    textInputPerMTokens: 4,
    textOutputPerMTokens: 16,
  },
  "gpt-realtime": {
    audioInputPerMTokens: 32,
    audioOutputPerMTokens: 64,
    textInputPerMTokens: 4,
    textOutputPerMTokens: 16,
  },
};

const TRANSCRIBE_MINUTE_RATES: Record<string, number> = {
  "gpt-4o-mini-transcribe": 0.003,
  "gpt-4o-transcribe": 0.006,
  "whisper-1": 0.006,
};

const CANDIDATE = {
  name: "S. V. S. Apparao",
  role: "Product Analyst",
  experience: "1 year experience",
};

const TURNS = [
  {
    "question": "Hey, thanks so much for coming in — really glad to have you here. Let's start easy. Just give me a quick intro about yourself — who you are, what you've been up to lately, whatever feels natural.",
    "answer": "I am a product analyst at AppsforBharat with a year of experience focusing on Daily Mantra. My strongest work includes architecting the zero-to-one event taxonomy, which enabled stable denominators for retention and conversion experiments. I successfully optimized retention from 25% to 42% and trial conversion from 27% to 42% while monitoring critical guardrails. Additionally, I automated complex marketing dashboards in AppsFlyer. I prioritize measurement discipline by isolating variables, managing cohort guardrails, and ensuring feature adoption metrics reflect true user habits rather than vanity event counts.",
    "said": "strong direct",
    "testing": "Retention & Engagement Experimentation"
  },
  {
    "question": "That 25% to 42% retention number — what exactly was the definition? Which day retention, what counted as a retained user, and what was the measurement window?",
    "answer": "For that 25% to 42% retention uplift, the metric was 7-day retention (D7). The denominator was users who joined the app in a specific week. A 'retained' user was defined as one who performed a track_start event at least once in the week following their install week. Because other experiments like 'Videos' and 'Today' were live, I segmented these cohorts by feature exposure and app version to isolate the impact, ensuring the lift wasn't just driven by an underlying increase in total traffic or concurrent product changes.",
    "said": "strong direct",
    "testing": "Test whether the candidate can precisely define the metric they claimed to move, including cohort definition, day window, and what event counted as retention."
  },
  {
    "question": "To achieve that jump to 42% retention, what specific behavioral shift were you looking to trigger with the AI Guruji feature?",
    "answer": "With AI Guruji, the behavioral shift I targeted was 'task discovery'—bridging the gap between a user opening the app and starting a mantra track. I designed the feature to provide personalized, intent-based guidance, aiming to increase the frequency of track_start events per session. By measuring the transition from discovery to listening, I ensured we weren't just seeing feature exposure, but actual behavioral adoption. This helped us stabilize the habit loop, contributing to the broader 42% retention uplift by turning passive app opens into active devotional sessions.",
    "said": "strong direct",
    "testing": "Retention & Engagement Experimentation"
  },
  {
    "question": "Track End completion went from 27.5% to 55.5% — walk me through how you decided the problem was in the path from task discovery to listening, not somewhere else in the flow.",
    "answer": "For the 55.5% Track End metric, the denominator was sessions that fired a valid track_start after task discovery, excluding all app opens. I focused specifically on the path from task discovery to completion by excluding accidental starts below a minimum listening threshold. By checking unique-user and session-level versions separately, I confirmed the lift in completion was driven by deeper user engagement within the mantra-listening loop, rather than just an increase in casual traffic or changes at another point in the navigation flow.",
    "said": "strong direct",
    "testing": "Understand the funnel reasoning and diagnostic work that led to the specific hypothesis about task discovery as the bottleneck, not another step."
  },
  {
    "question": "Video and the Today feature launched close together for retention — how do you know the retention lift wasn't just from new content giving users a reason to come back, rather than the specific product change you tested?",
    "answer": "I controlled for this by segregating the cohort analysis. To isolate the Today feature and Video impact, I split users by feature-exposure buckets and app version. I compared retention and track completion for users exposed and not exposed to these features within the same acquisition window. Since the Today feature had a specific entry-point event, I could isolate the change in 'task discovery' to 'track start' funnel velocity. By holding acquisition source constant and comparing feature-exposed users against the control, the lift remained significant, confirming the product improvement, not just content density.",
    "said": "strong direct",
    "testing": "Test whether the candidate can articulate the novelty effect / content confound risk and whether they took any steps to separate feature design lift from content freshness lift."
  },
  {
    "question": "Imagine your PM comes to you tomorrow and says: 'The personalized intent-to-mantra recommendation system you designed is working well for our existing users, but we're launching in a completely new market — Southeast Asia — where user intent language, spiritual traditions, and content libraries are entirely different. We want to understand whether the same recommendation logic holds, and whether the feature is actually driving session starts in this new cohort before we invest in localizing the full content library.' How would you approach measuring whether the recommendation system is working in this new market, and what would tell you it needs to be redesigned versus just retuned?",
    "answer": "In a new market like Southeast Asia, I would first check if our event taxonomy captures 'intent' accurately for local traditions. I'd define success as 'session starts' (denominator: app opens, success: track_start). If recommendation logic fails, I would compare the conversion rate from item-impression to track_start against the India cohort. If the drop-off is high despite high exposure, the content taxonomy is likely misaligned, requiring a redesign. I would treat D7 retention and trial-subscription rates as guardrails to ensure that even early engagement is deep, not just superficial curiosity.",
    "said": "strong direct",
    "testing": "Retention & Engagement Experimentation"
  },
  {
    "question": "I’m curious how you’d go about disentangling whether those lower session-start rates are a signal that the recommendation logic is missing the mark, or if there might be other structural factors in play that we should be looking at first?",
    "answer": "To disentangle this, I would first check if the session-start rate drop correlates with app-crash logs or load-time latency, which are structural, not logic-based. If technical health is stable, I’d investigate the denominator: is it total app opens or sessions starting after feature exposure? I would verify if the recommendation engine is surfacing relevant mantras by cross-referencing task discovery events. If exposure is high but conversion to track-start is low, it’s a logic issue; if users reach the screen but don't see content, it's a structural library deficiency.",
    "said": "strong direct",
    "testing": "Tests whether the candidate recognizes that success metrics from the original market (e.g., session start rate, track completion) may have different denominators or behavioral baselines in a new market, and that applying the same KPIs without revalidating what 'good' looks like could lead to false conclusions."
  },
  {
    "question": "It’s a quiet period for data, so I’m curious—beyond just tracking clicks, what specific user behaviors or \"tells\" would you look for to decide if the recommendations are actually adding value versus just being noise?",
    "answer": "To distinguish value from noise, I look at 'deep-engagement' markers beyond simple track starts. I monitor average listening duration vs. total track length, repeat-listen frequency for the same mantra, and the 'task discovery-to-completion' conversion velocity. If a user completes a track and immediately triggers another session or saves the content, that is a high-intent signal. I also track 'time-to-first-completion' after app open; if users are just tapping everything to exit, the session-depth metric will remain low, indicating the recommendations aren't actually surfacing resonant content.",
    "said": "strong direct",
    "testing": "Tests whether the candidate can reason about what happens when the recommendation system has no prior behavioral data for a new user population — and how to instrument early signals that are leading indicators of system effectiveness before enough data accumulates."
  },
  {
    "question": "What specific signals in the performance data would convince you that your current model has reached its limit and requires a structural shift rather than just further optimization?",
    "answer": "I would look for a persistent divergence between 'feature exposure' and 'task completion' velocity that persists across all cohorts regardless of UI iteration. If our taxonomy shows high session starts but cratering engagement intensity (e.g., track endpoints dropping below 30%) and flat D7 retention despite optimizations, the structural model of the 'on-demand' content delivery may be misaligned with user intent. At that point, further A/B testing on UI tweaks won't help; we would need a fundamental shift in content structure or the core recommendation, rather than just optimizing the current flow.",
    "said": "strong direct",
    "testing": "Tests whether the candidate can articulate a structured decision rule for when observed underperformance means the feature logic needs fundamental redesign versus parameter adjustment — a key product analytics judgment that requires both quantitative thresholds and qualitative signal."
  },
  {
    "question": "In your specific implementation, what did the actual decision logic look like when you had to distinguish between a need to retune the recommendation algorithm versus a need to redesign the user journey flow?",
    "answer": "My decision logic relied on segmenting the event taxonomy by feature exposure versus session depth. If users triggered 'task discovery' and 'mantra start' but dropped off before 'track end' or D7 return, I diagnosed a recommendation tuning issue. If users stopped at the session-start or discovery screen without ever surfacing a feature, I shifted focus to the user journey flow. I prioritized fixing the journey when the top-of-funnel friction was high, and refined the algorithm only when intent was established but content resonance proved chronically insufficient.",
    "said": "strong direct",
    "testing": "Tests whether the candidate can articulate a structured decision rule for when observed underperformance means the feature logic needs fundamental redesign versus parameter adjustment — a key product analytics judgment that requires both quantitative thresholds and qualitative signal."
  },
  {
    "question": "That 42% conversion number — what exactly was in the denominator? Trial starts, app installs, something else — and over what time window did you measure it?",
    "answer": "For the 42% conversion metric, the denominator was unique users who reached the paywall and clicked 'Start Trial.' The numerator was users who successfully transitioned to a paid subscription after that trial. I measured this over a rolling 30-day window to account for users who transitioned shortly after the reduced 1-day trial limit. I also analyzed this by cohort and acquisition source to ensure the improvement wasn't just a byproduct of shifting traffic quality or concurrent feature updates like the AI Guruji launch.",
    "said": "strong direct",
    "testing": "Check whether the candidate defined and owned the metric rigorously, or used a number that was already handed to them."
  },
  {
    "question": "You mentioned monitoring cancellation and refund guardrails during this — what specific thresholds were you watching, and at what point would you have called the experiment off?",
    "answer": "I monitored four primary KPIs against the pre-change baseline: refund rate, same-cycle cancellation, support complaints, and D7 retention. My rollback protocol wasn't anchored to a single magic number; rather, I triggered a review if conversion lift evaporated or if refund and cancellation rates moved materially above the baseline confidence interval for that specific paywall cohort. This ensured the 1-day trial limit drove revenue growth without damaging long-term user trust or retention, preventing 'cheap' conversion gains that would have degraded our core subscription quality.",
    "said": "strong direct",
    "testing": "Test whether guardrail monitoring was real and operational, or a line added to look responsible."
  },
  {
    "question": "Alright, we're almost done — before we finish, is there anything about your work or what you've been building that you wanted to talk about that we didn't get to?",
    "answer": "The strongest claim is the Daily Mantra event taxonomy. I defined session start, task discovery, mantra start, track end, feature exposure, trial start, payment initiated, and subscription success so retention and conversion experiments had stable denominators. This analytical foundation allowed me to clearly distinguish between feature adoption and user friction. Beyond that, the common thread is my measurement discipline: define the event, protect the denominator, inspect guardrails, and only then connect product changes to outcomes. It ensured that our 42% retention and conversion gains were robust and high-quality.",
    "said": "closing",
    "testing": "Retention & Engagement Experimentation"
  },
  {
    "question": "Looking at the retention work as a whole — which part are you most confident about: that retention actually improved by that magnitude, that Video or AI Guruji specifically caused it, that the measurement was clean, or something else?",
    "answer": "I am most confident that the measurement was clean, specifically the denominator and guardrails. I architected the taxonomy to track unique cohorts, ensuring we weren't double-counting or misattributing. Regarding the magnitude, I am more reserved; while the lift correlated heavily with the 1-day trial change, I cannot scientifically decompose the full 15% jump between trial length, AI Guruji, and Video. I own the rigour of the data, but I’m honest that individual feature attribution in a multi-release window is more directional than perfectly isolated.",
    "said": "honest gap",
    "testing": "Assess the candidate's epistemic honesty — can they separate what they know confidently from what they inferred or assumed, without collapsing everything into one confident claim."
  },
  {
    "question": "Alright, we're almost done — before we finish, is there anything about your work or what you've been building that you wanted to talk about that we didn't get to?",
    "answer": "Beyond what we discussed, I’d highlight the synthesis of my AppsFlyer dashboard automation. While the mantra work focused on product instrumentation, the marketing analytics project required reconciling spend lag with subscription outcomes. Scaling CAC and CPI metrics meant navigating attribution windows, which mirrors my product discipline: protecting the integrity of the denominator so that metrics like conversion aren't just vanity figures. In both cases, I prioritize transparency in measurement so product teams can focus on outcomes rather than the uncertainty of raw event data.",
    "said": "closing",
    "testing": "Retention & Engagement Experimentation"
  }
];

const DEFAULT_ANSWER_BY_SIGNAL: Record<AnswerSignal, string> = {
  strong:
    "The exact answer is that I owned the metric definition, the segment split, and the validation pass. I would use the backend-confirmed event as the source of truth, compare it against client telemetry, and only make a recommendation after the two agree across the affected cohorts.",
  partial:
    "I can explain the reasoning, but I do not remember every field name. I would first separate assignment, exposure, and conversion, then check whether the lift survives by cohort and acquisition channel.",
  honest_gap:
    "I do not want to pretend I remember the exact implementation detail. My role was closer to analysis and recommendation than raw pipeline ownership, so I would verify the schema or ask the data engineer before making a hard claim.",
  evasive:
    "The project had many moving parts, including AI models, dashboards, and cross-functional work. The overall impact was strong, but I would need to check the documentation to explain the exact technical mechanism.",
  stuck:
    "I am not fully sure. Could you repeat that a little slower or give me the specific angle you want me to focus on?",
  closing:
    "The main thing I want to add is that my strongest work is turning ambiguous product metrics into a decision framework, even when the data is messy.",
};

function buildRealtimeInterviewInstruction(question: string, mode: "assessment" | "interaction" | "recovery" | "tool" = "assessment") {
  const normalizedQuestion = question.trim();
  if (mode === "tool") return normalizedQuestion;
  const moveLabel =
    mode === "interaction"
      ? "INTERACTION MOVE: Say only the approved non-counting interaction wording below."
      : mode === "recovery"
        ? "RECOVERY MOVE: Say only the approved recovery wording below."
        : "ASSESSMENT MOVE: Ask only the approved question below.";
  return [
    "VOICE INTERVIEW CONTRACT:",
    "You are Antigravity's live AI interviewer voice. You are currently inside an interview.",
    "The backend/UI is the interview brain. You are only the spoken delivery layer.",
    "Do not behave like a general assistant, companion, debugger, coach, or out-of-interview chatbot.",
    "Speak exactly one backend-approved move, then stop and wait for the candidate.",
    "Do not add your own follow-up, topic, hint, answer, advice, summary, or second question.",
    "If the candidate previously sounded confused, vague, off-topic, or said they need to check something, stay in interviewer mode.",
    "Do not apologize your way into a chat. Do not ask what interview this is. Do not forget the interview frame.",
    "Never reveal route names, policy, score, hidden state, action deck, telemetry, or evaluator logic.",
    "Do not read these contract labels aloud.",
    "Use calm natural voice. Maximum two spoken sentences.",
    moveLabel,
    `APPROVED WORDING: ${normalizedQuestion}`,
  ].join("\n");
}

function classifyOperationalInteraction(text: string): OperationalInteraction | null {
  const normalized = text.toLowerCase();
  if (/(hold on|one second|give me a second|give me a moment|wait a second|pause)/.test(normalized)) return "pause";
  if (/(speak|say|ask|read).*(slower|slowly)|slow down|too fast|little slower/.test(normalized)) return "slow_down";
  if (/(repeat|say that again|ask that again|can you say it again|could you repeat)/.test(normalized)) return "repeat";
  if (/(what do you mean|didn't understand|do not understand|don't understand|could you clarify|can you clarify|rephrase|simpler|explain the question)/.test(normalized)) {
    return "rephrase";
  }
  return null;
}

function buildOperationalInteractionInstruction(kind: OperationalInteraction, currentQuestion: string) {
  const question = currentQuestion.trim();
  if (kind === "pause") {
    return buildRealtimeInterviewInstruction(
      "Of course. Take a moment. I will hold the question here.",
      "interaction",
    );
  }
  if (kind === "slow_down") {
    return buildRealtimeInterviewInstruction(
      `Say this same interview question again more slowly, with a calmer pace, and do not add anything else: ${question}`,
      "interaction",
    );
  }
  if (kind === "repeat") {
    return buildRealtimeInterviewInstruction(
      `Repeat this exact interview question once, without changing the wording and without adding anything else: ${question}`,
      "interaction",
    );
  }
  return buildRealtimeInterviewInstruction(
    `Rephrase this same interview question in simpler words while preserving the exact assessment intent. Do not add a new probe: ${question}`,
    "interaction",
  );
}

const SIMULATION_FLOW: Partial<Record<number, Partial<SimulationTurn>>> = {
  "0": {
    "route": "trajectory_map_surface",
    "posture": "warm_open",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "I am a product analyst at AppsforBharat with a year of experience focusing on Daily Mantra. My strongest work includes architecting the zero-to-one event taxonomy, which enabled stable denominators for retention and conversion experiments. I successfully optimized retention from 25% to 42% and trial conversion from 27% to 42% while monitoring critical guardrails. Additionally, I automated complex marketing dashboards in AppsFlyer. I prioritize measurement discipline by isolating variables, managing cohort guardrails, and ensuring feature adoption metrics reflect true user habits rather than vanity event counts.",
        "nextTurn": 1
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 1
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 1
      }
    ],
    "nextBySignal": {
      "strong": 1,
      "partial": 1,
      "honest_gap": 1,
      "evasive": 1,
      "closing": 1,
      "stuck": 0
    }
  },
  "1": {
    "route": "clarification_fast",
    "posture": "clarify",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "For that 25% to 42% retention uplift, the metric was 7-day retention (D7). The denominator was users who joined the app in a specific week. A 'retained' user was defined as one who performed a track_start event at least once in the week following their install week. Because other experiments like 'Videos' and 'Today' were live, I segmented these cohorts by feature exposure and app version to isolate the impact, ensuring the lift wasn't just driven by an underlying increase in total traffic or concurrent product changes.",
        "nextTurn": 2
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 2
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 2
      }
    ],
    "nextBySignal": {
      "strong": 2,
      "partial": 2,
      "honest_gap": 2,
      "evasive": 2,
      "closing": 2,
      "stuck": 1
    }
  },
  "2": {
    "route": "trajectory_map_mechanism",
    "posture": "primary_depth",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "With AI Guruji, the behavioral shift I targeted was 'task discovery'—bridging the gap between a user opening the app and starting a mantra track. I designed the feature to provide personalized, intent-based guidance, aiming to increase the frequency of track_start events per session. By measuring the transition from discovery to listening, I ensured we weren't just seeing feature exposure, but actual behavioral adoption. This helped us stabilize the habit loop, contributing to the broader 42% retention uplift by turning passive app opens into active devotional sessions.",
        "nextTurn": 3
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 3
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 3
      }
    ],
    "nextBySignal": {
      "strong": 3,
      "partial": 3,
      "honest_gap": 3,
      "evasive": 3,
      "closing": 3,
      "stuck": 2
    }
  },
  "3": {
    "route": "trajectory_map_boundary",
    "posture": "explore",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "For the 55.5% Track End metric, the denominator was sessions that fired a valid track_start after task discovery, excluding all app opens. I focused specifically on the path from task discovery to completion by excluding accidental starts below a minimum listening threshold. By checking unique-user and session-level versions separately, I confirmed the lift in completion was driven by deeper user engagement within the mantra-listening loop, rather than just an increase in casual traffic or changes at another point in the navigation flow.",
        "nextTurn": 4
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 4
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 4
      }
    ],
    "nextBySignal": {
      "strong": 4,
      "partial": 4,
      "honest_gap": 4,
      "evasive": 4,
      "closing": 4,
      "stuck": 3
    }
  },
  "4": {
    "route": "application_transfer",
    "posture": "pressure",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "I controlled for this by segregating the cohort analysis. To isolate the Today feature and Video impact, I split users by feature-exposure buckets and app version. I compared retention and track completion for users exposed and not exposed to these features within the same acquisition window. Since the Today feature had a specific entry-point event, I could isolate the change in 'task discovery' to 'track start' funnel velocity. By holding acquisition source constant and comparing feature-exposed users against the control, the lift remained significant, confirming the product improvement, not just content density.",
        "nextTurn": 5
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 5
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 5
      }
    ],
    "nextBySignal": {
      "strong": 5,
      "partial": 5,
      "honest_gap": 5,
      "evasive": 5,
      "closing": 5,
      "stuck": 4
    }
  },
  "5": {
    "route": "coverage_surface",
    "posture": "coverage_surface",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "In a new market like Southeast Asia, I would first check if our event taxonomy captures 'intent' accurately for local traditions. I'd define success as 'session starts' (denominator: app opens, success: track_start). If recommendation logic fails, I would compare the conversion rate from item-impression to track_start against the India cohort. If the drop-off is high despite high exposure, the content taxonomy is likely misaligned, requiring a redesign. I would treat D7 retention and trial-subscription rates as guardrails to ensure that even early engagement is deep, not just superficial curiosity.",
        "nextTurn": 6
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 6
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 6
      }
    ],
    "nextBySignal": {
      "strong": 6,
      "partial": 6,
      "honest_gap": 6,
      "evasive": 6,
      "closing": 6,
      "stuck": 5
    }
  },
  "6": {
    "route": "coverage_surface",
    "posture": "coverage_surface",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "To disentangle this, I would first check if the session-start rate drop correlates with app-crash logs or load-time latency, which are structural, not logic-based. If technical health is stable, I’d investigate the denominator: is it total app opens or sessions starting after feature exposure? I would verify if the recommendation engine is surfacing relevant mantras by cross-referencing task discovery events. If exposure is high but conversion to track-start is low, it’s a logic issue; if users reach the screen but don't see content, it's a structural library deficiency.",
        "nextTurn": 7
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 7
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 7
      }
    ],
    "nextBySignal": {
      "strong": 7,
      "partial": 7,
      "honest_gap": 7,
      "evasive": 7,
      "closing": 7,
      "stuck": 6
    }
  },
  "7": {
    "route": "coverage_surface",
    "posture": "coverage_surface",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "To distinguish value from noise, I look at 'deep-engagement' markers beyond simple track starts. I monitor average listening duration vs. total track length, repeat-listen frequency for the same mantra, and the 'task discovery-to-completion' conversion velocity. If a user completes a track and immediately triggers another session or saves the content, that is a high-intent signal. I also track 'time-to-first-completion' after app open; if users are just tapping everything to exit, the session-depth metric will remain low, indicating the recommendations aren't actually surfacing resonant content.",
        "nextTurn": 8
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 8
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 8
      }
    ],
    "nextBySignal": {
      "strong": 8,
      "partial": 8,
      "honest_gap": 8,
      "evasive": 8,
      "closing": 8,
      "stuck": 7
    }
  },
  "8": {
    "route": "coverage_depth_probe",
    "posture": "coverage_surface",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "I would look for a persistent divergence between 'feature exposure' and 'task completion' velocity that persists across all cohorts regardless of UI iteration. If our taxonomy shows high session starts but cratering engagement intensity (e.g., track endpoints dropping below 30%) and flat D7 retention despite optimizations, the structural model of the 'on-demand' content delivery may be misaligned with user intent. At that point, further A/B testing on UI tweaks won't help; we would need a fundamental shift in content structure or the core recommendation, rather than just optimizing the current flow.",
        "nextTurn": 9
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 9
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 9
      }
    ],
    "nextBySignal": {
      "strong": 9,
      "partial": 9,
      "honest_gap": 9,
      "evasive": 9,
      "closing": 9,
      "stuck": 8
    }
  },
  "9": {
    "route": "second_anchor",
    "posture": "second_anchor",
    "focus": "Subscription Funnel & Paywall Mechanics",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "My decision logic relied on segmenting the event taxonomy by feature exposure versus session depth. If users triggered 'task discovery' and 'mantra start' but dropped off before 'track end' or D7 return, I diagnosed a recommendation tuning issue. If users stopped at the session-start or discovery screen without ever surfacing a feature, I shifted focus to the user journey flow. I prioritized fixing the journey when the top-of-funnel friction was high, and refined the algorithm only when intent was established but content resonance proved chronically insufficient.",
        "nextTurn": 10
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 10
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 10
      }
    ],
    "nextBySignal": {
      "strong": 10,
      "partial": 10,
      "honest_gap": 10,
      "evasive": 10,
      "closing": 10,
      "stuck": 9
    }
  },
  "10": {
    "route": "second_anchor",
    "posture": "clarify",
    "focus": "Subscription Funnel & Paywall Mechanics",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "For the 42% conversion metric, the denominator was unique users who reached the paywall and clicked 'Start Trial.' The numerator was users who successfully transitioned to a paid subscription after that trial. I measured this over a rolling 30-day window to account for users who transitioned shortly after the reduced 1-day trial limit. I also analyzed this by cohort and acquisition source to ensure the improvement wasn't just a byproduct of shifting traffic quality or concurrent feature updates like the AI Guruji launch.",
        "nextTurn": 11
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 11
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 11
      }
    ],
    "nextBySignal": {
      "strong": 11,
      "partial": 11,
      "honest_gap": 11,
      "evasive": 11,
      "closing": 11,
      "stuck": 10
    }
  },
  "11": {
    "route": "synthesis_close",
    "posture": "explore",
    "focus": "Subscription Funnel & Paywall Mechanics",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "I monitored four primary KPIs against the pre-change baseline: refund rate, same-cycle cancellation, support complaints, and D7 retention. My rollback protocol wasn't anchored to a single magic number; rather, I triggered a review if conversion lift evaporated or if refund and cancellation rates moved materially above the baseline confidence interval for that specific paywall cohort. This ensured the 1-day trial limit drove revenue growth without damaging long-term user trust or retention, preventing 'cheap' conversion gains that would have degraded our core subscription quality.",
        "nextTurn": 12
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 12
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 12
      }
    ],
    "nextBySignal": {
      "strong": 12,
      "partial": 12,
      "honest_gap": 12,
      "evasive": 12,
      "closing": 12,
      "stuck": 11
    }
  },
  "12": {
    "route": "second_anchor",
    "posture": "second_anchor",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Closing answer",
        "text": "The strongest claim is the Daily Mantra event taxonomy. I defined session start, task discovery, mantra start, track end, feature exposure, trial start, payment initiated, and subscription success so retention and conversion experiments had stable denominators. This analytical foundation allowed me to clearly distinguish between feature adoption and user friction. Beyond that, the common thread is my measurement discipline: define the event, protect the denominator, inspect guardrails, and only then connect product changes to outcomes. It ensured that our 42% retention and conversion gains were robust and high-quality.",
        "nextTurn": 13
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 13
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 13
      }
    ],
    "nextBySignal": {
      "strong": 13,
      "partial": 13,
      "honest_gap": 13,
      "evasive": 13,
      "closing": 13,
      "stuck": 12
    }
  },
  "13": {
    "route": "synthesis_close",
    "posture": "synthesize",
    "focus": "Subscription Funnel & Paywall Mechanics",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Successful-run answer",
        "text": "I am most confident that the measurement was clean, specifically the denominator and guardrails. I architected the taxonomy to track unique cohorts, ensuring we weren't double-counting or misattributing. Regarding the magnitude, I am more reserved; while the lift correlated heavily with the 1-day trial change, I cannot scientifically decompose the full 15% jump between trial length, AI Guruji, and Video. I own the rigour of the data, but I’m honest that individual feature attribution in a multi-release window is more directional than perfectly isolated.",
        "nextTurn": 14
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 14
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 14
      }
    ],
    "nextBySignal": {
      "strong": 14,
      "partial": 14,
      "honest_gap": 14,
      "evasive": 14,
      "closing": 14,
      "stuck": 13
    }
  },
  "14": {
    "route": "complete",
    "posture": "complete",
    "focus": "Retention & Engagement Experimentation",
    "answerOptions": [
      {
        "signal": "strong",
        "label": "Closing answer",
        "text": "Beyond what we discussed, I’d highlight the synthesis of my AppsFlyer dashboard automation. While the mantra work focused on product instrumentation, the marketing analytics project required reconciling spend lag with subscription outcomes. Scaling CAC and CPI metrics meant navigating attribution windows, which mirrors my product discipline: protecting the integrity of the denominator so that metrics like conversion aren't just vanity figures. In both cases, I prioritize transparency in measurement so product teams can focus on outcomes rather than the uncertainty of raw event data.",
        "nextTurn": 14
      },
      {
        "signal": "honest_gap",
        "label": "Honest gap",
        "text": "I do not want to overstate the implementation detail. I can explain the decision framework and the metric I would verify, but I would check the exact taxonomy or schema before claiming ownership of every field.",
        "nextTurn": 14
      },
      {
        "signal": "evasive",
        "label": "Vague answer",
        "text": "The project had several moving parts across dashboards, experiments, and stakeholder decisions. The impact was strong, but I would need to revisit the documentation to explain the exact technical mechanism.",
        "nextTurn": 14
      }
    ],
    "nextBySignal": {
      "strong": "close",
      "partial": "close",
      "honest_gap": "close",
      "evasive": "close",
      "closing": "close",
      "stuck": 14
    }
  }
};

const PHASE_MURAL: Record<
  Phase,
  {
    aura: `#${string}`;
    shift: number;
    a: string;
    b: string;
    c: string;
    auraState: AgentState;
    label: string;
    title: string;
    caption: string;
  }
> = {
  ready: {
    aura: "#7AA7FF",
    shift: 0.16,
    a: "oklch(0.66 0.14 248)",
    b: "oklch(0.62 0.1 282)",
    c: "oklch(0.72 0.08 220)",
    auraState: "idle",
    label: "Ready",
    title: "Ready when you are",
    caption: "The room is quiet. Start when you are ready.",
  },
  asking: {
    aura: "#FF9A3D",
    shift: 0.5,
    a: "oklch(0.74 0.18 50)",
    b: "oklch(0.7 0.16 32)",
    c: "oklch(0.68 0.11 76)",
    auraState: "speaking",
    label: "Question",
    title: "Asking question",
    caption: "The interviewer owns the floor. Listen to the question.",
  },
  listening: {
    aura: "#1FD5F9",
    shift: 0.3,
    a: "oklch(0.72 0.19 222)",
    b: "oklch(0.66 0.13 278)",
    c: "oklch(0.76 0.14 154)",
    auraState: "listening",
    label: "Your turn",
    title: "Listening to candidate's answer",
    caption: "The question remains anchored while your answer flows below it.",
  },
  reviewing: {
    aura: "#FFBE59",
    shift: 0.46,
    a: "oklch(0.78 0.14 72)",
    b: "oklch(0.68 0.14 34)",
    c: "oklch(0.72 0.12 292)",
    auraState: "thinking",
    label: "Reviewing",
    title: "Reviewing candidate's answer",
    caption: "Answer received. The next question is being prepared.",
  },
  closing: {
    aura: "#6CFF9E",
    shift: 0.26,
    a: "oklch(0.76 0.15 154)",
    b: "oklch(0.68 0.13 204)",
    c: "oklch(0.78 0.1 92)",
    auraState: "thinking",
    label: "Complete",
    title: "Closing interview",
    caption: "The interview is closing and the report is being prepared.",
  },
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function float32ToPcm16(float32: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);
  for (let index = 0; index < float32.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, float32[index]));
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

function nowLabel() {
  return new Date().toLocaleTimeString();
}

function shortJson(value: unknown) {
  try {
    return JSON.stringify(value).slice(0, 240);
  } catch {
    return String(value).slice(0, 240);
  }
}

function estimateTextTokens(text: string) {
  const words = String(text || "").trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.ceil(words * 1.35));
}

function estimateSpeechMs(text: string, wordsPerMinute: number) {
  const words = String(text || "").trim().split(/\s+/).filter(Boolean).length;
  if (!words) return 0;
  return Math.ceil((words / wordsPerMinute) * 60_000);
}

function estimateRealtimeUsage(turns: UsageTurn[], model: string, transcribeModel: string, transcribeSamples: number) {
  const rate = REALTIME_RATE_CARDS[model] || REALTIME_RATE_CARDS["gpt-realtime-2"];
  const inputAudioMs = turns.reduce((sum, turn) => sum + turn.inputAudioMs, 0);
  const outputAudioMs = turns.reduce((sum, turn) => sum + turn.outputAudioMs, 0);
  const inputAudioTokens = Math.ceil(inputAudioMs / 100);
  const outputAudioTokens = Math.ceil(outputAudioMs / 50);
  const inputTextTokens = turns.reduce((sum, turn) => sum + turn.inputTextTokens, 0);
  const outputTextTokens = turns.reduce((sum, turn) => sum + turn.outputTextTokens, 0);
  const realtimeCost =
    (inputAudioTokens / 1_000_000) * rate.audioInputPerMTokens +
    (outputAudioTokens / 1_000_000) * rate.audioOutputPerMTokens +
    (inputTextTokens / 1_000_000) * rate.textInputPerMTokens +
    (outputTextTokens / 1_000_000) * rate.textOutputPerMTokens;
  const transcribeMinutes = (transcribeSamples * 8) / 60;
  const transcribeCost = transcribeMinutes * (TRANSCRIBE_MINUTE_RATES[transcribeModel] || 0);

  return {
    inputAudioMs,
    outputAudioMs,
    inputAudioTokens,
    outputAudioTokens,
    inputTextTokens,
    outputTextTokens,
    realtimeCost,
    transcribeMinutes,
    transcribeCost,
    totalCost: realtimeCost + transcribeCost,
    rate,
  };
}

function numberFrom(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function parseMaybeJson(value: unknown): any {
  if (!value) return null;
  if (typeof value === "object") return value;
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

function usageFromEvent(event: any): any {
  return (
    parseMaybeJson(event?.provider_usage) ||
    parseMaybeJson(event?.usage) ||
    parseMaybeJson(event?.transcript_preview) ||
    parseMaybeJson(event?.detail)
  );
}

function hasRealtimeTokenUsage(usage: any) {
  if (!usage || typeof usage !== "object") return false;
  return [
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "input_token_details",
    "output_token_details",
    "input_tokens_details",
    "output_tokens_details",
  ].some((key) => usage[key] !== undefined);
}

function summarizeBackendRealtimeUsage(summary: any, model: string) {
  const rate = REALTIME_RATE_CARDS[model] || REALTIME_RATE_CARDS["gpt-realtime-mini"];
  const totals = {
    providerUsageEvents: 0,
    inputTextTokens: 0,
    outputTextTokens: 0,
    inputAudioTokens: 0,
    outputAudioTokens: 0,
    cachedTokens: 0,
    totalTokens: 0,
    estimatedCost: 0,
  };
  const events = Array.isArray(summary?.recent_events) ? summary.recent_events : [];
  for (const event of events) {
    const usage = usageFromEvent(event);
    if (!hasRealtimeTokenUsage(usage)) continue;
    const inputDetails = usage.input_token_details || usage.input_tokens_details || {};
    const outputDetails = usage.output_token_details || usage.output_tokens_details || {};
    const inputText = numberFrom(inputDetails.text_tokens);
    const outputText = numberFrom(outputDetails.text_tokens);
    const inputAudio = numberFrom(inputDetails.audio_tokens);
    const outputAudio = numberFrom(outputDetails.audio_tokens);
    const cached = numberFrom(inputDetails.cached_tokens) || numberFrom(usage.cached_tokens);
    const inputTotal = numberFrom(usage.input_tokens);
    const outputTotal = numberFrom(usage.output_tokens);
    const total = numberFrom(usage.total_tokens) || inputTotal + outputTotal;

    totals.providerUsageEvents += 1;
    totals.inputTextTokens += inputText || Math.max(0, inputTotal - inputAudio - cached);
    totals.outputTextTokens += outputText || Math.max(0, outputTotal - outputAudio);
    totals.inputAudioTokens += inputAudio;
    totals.outputAudioTokens += outputAudio;
    totals.cachedTokens += cached;
    totals.totalTokens += total;
  }
  totals.estimatedCost =
    (totals.inputAudioTokens / 1_000_000) * rate.audioInputPerMTokens +
    (totals.outputAudioTokens / 1_000_000) * rate.audioOutputPerMTokens +
    (totals.inputTextTokens / 1_000_000) * rate.textInputPerMTokens +
    (totals.outputTextTokens / 1_000_000) * rate.textOutputPerMTokens;
  return totals;
}

function actualRealtimeModelFromSummary(summary: any) {
  const events = Array.isArray(summary?.recent_events) ? summary.recent_events : [];
  for (const event of [...events].reverse()) {
    const payload = parseMaybeJson(event?.detail);
    const model = payload?.session?.model || payload?.response?.model || payload?.model || event?.model;
    if (typeof model === "string" && model.trim()) return model.trim();
  }
  return "";
}

function money(value: number) {
  if (value < 0.0001) return `$${value.toFixed(6)}`;
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function seconds(value: number) {
  return `${(value / 1000).toFixed(1)}s`;
}

function flowForTurn(index: number) {
  return SIMULATION_FLOW[index] || {};
}

function answerOptionsForTurn(index: number): AnswerOption[] {
  const turn = TURNS[Math.min(index, TURNS.length - 1)];
  return (
    flowForTurn(index).answerOptions || [
      {
        signal: "strong",
        label: "Strong answer",
        text: turn.answer,
        nextTurn: Math.min(index + 1, TURNS.length - 1),
      },
      {
        signal: "honest_gap",
        label: "Honest gap",
        text: DEFAULT_ANSWER_BY_SIGNAL.honest_gap,
        nextTurn: Math.min(index + 1, TURNS.length - 1),
      },
      {
        signal: "evasive",
        label: "Evasive answer",
        text: DEFAULT_ANSWER_BY_SIGNAL.evasive,
        nextTurn: Math.min(index + 1, TURNS.length - 1),
      },
    ]
  );
}

function classifyAnswerSignal(answer: string): AnswerSignal {
  const text = answer.toLowerCase();
  if (!text.trim()) return "stuck";
  if (/(repeat|slower|slow down|don't understand|not sure what you mean|could you clarify)/.test(text)) return "stuck";
  if (/(don't remember|do not remember|don't recall|do not recall|not overstate|verify|check the schema|check the documentation|not personally)/.test(text)) return "honest_gap";
  if (/(many moving parts|ai-driven|dashboard|overall impact|cross-functional|robust|synergy|strategic)/.test(text) && !/(user_id|session_id|denominator|cohort|order_id|event_time|backend|holdout|variant)/.test(text)) return "evasive";
  if (/(denominator|cohort|user_id|session_id|order_id|event_time|variant|backend|holdout|guardrail|margin|confidence|segment|schema|field|join)/.test(text)) return "strong";
  if (text.split(/\s+/).length < 18) return "partial";
  return "partial";
}

function nextTurnIndex(currentIndex: number, signal: AnswerSignal) {
  const flow = flowForTurn(currentIndex);
  const next = flow.nextBySignal?.[signal] ?? flow.nextBySignal?.partial ?? Math.min(currentIndex + 1, TURNS.length - 1);
  if (next === "close") return "close";
  return clamp(Number(next), 0, TURNS.length - 1);
}

function normalizeProviderStatus(payload: any): ProviderStatus {
  const realtimeModel = String(payload?.default_realtime_model || payload?.openai_realtime_model || "gpt-realtime-mini");
  const transcribeModel = String(
    payload?.default_transcribe_model || payload?.openai_realtime_transcribe_model || "gpt-4o-mini-transcribe",
  );
  const realtimeModels = Array.isArray(payload?.realtime_models)
    ? payload.realtime_models
    : ["gpt-realtime-mini", realtimeModel, "gpt-realtime-2", "gpt-realtime"].filter(Boolean);
  const transcribeModels = Array.isArray(payload?.transcribe_models)
    ? payload.transcribe_models
    : [transcribeModel, "gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"].filter(Boolean);

  return {
    openai_configured: Boolean(payload?.openai_configured ?? payload?.openai_realtime_configured),
    deepgram_configured: Boolean(payload?.deepgram_configured),
    default_realtime_model: "gpt-realtime-mini",
    realtime_models: Array.from(new Set(realtimeModels.map(String))),
    default_transcribe_model: transcribeModel,
    transcribe_models: Array.from(new Set(transcribeModels.map(String))),
    realtime_transcription_model: String(
      payload?.realtime_transcription_model || payload?.openai_realtime_transcribe_model || transcribeModel,
    ),
  };
}

export default function LiveKitRoomFloorPreviewPage() {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [openaiApiBase, setOpenaiApiBase] = useState(API);
  const [deepgramApiBase, setDeepgramApiBase] = useState(API);
  const [sessionId, setSessionId] = useState("");
  const [realtimeModel, setRealtimeModel] = useState("gpt-realtime-mini");
  const [transcribeModel, setTranscribeModel] = useState("gpt-4o-mini-transcribe");
  const [enableRealtime, setEnableRealtime] = useState(true);
  const [enableDeepgram, setEnableDeepgram] = useState(true);
  const [voiceLabRunning, setVoiceLabRunning] = useState(false);
  const [realtimeRunning, setRealtimeRunning] = useState(false);
  const [deepgramRunning, setDeepgramRunning] = useState(false);
  const [recordingSample, setRecordingSample] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [realtimePartial, setRealtimePartial] = useState("");
  const [realtimeFinal, setRealtimeFinal] = useState("");
  const [deepgramPartial, setDeepgramPartial] = useState("");
  const [deepgramFinal, setDeepgramFinal] = useState("");
  const [openaiTranscribeText, setOpenaiTranscribeText] = useState("");
  const [aiTranscript, setAiTranscript] = useState("");
  const [functionCalls, setFunctionCalls] = useState(0);
  const [usageTurns, setUsageTurns] = useState<UsageTurn[]>([]);
  const [backendDiagnostics, setBackendDiagnostics] = useState<BackendDiagnostics | null>(null);
  const [backendDiagnosticsError, setBackendDiagnosticsError] = useState("");
  const [backendDiagnosticsLoading, setBackendDiagnosticsLoading] = useState(false);
  const [turnGuardStatus, setTurnGuardStatus] = useState<TurnGuardStatus>("clean");
  const [turnGuardMessage, setTurnGuardMessage] = useState("No duplicate Realtime responses detected.");
  const [spokenQuestionText, setSpokenQuestionText] = useState("");
  const [transcribeSamples, setTranscribeSamples] = useState(0);
  const [events, setEvents] = useState<LabEvent[]>([]);
  const [answerSignalMode, setAnswerSignalMode] = useState<AnswerSignal>("strong");
  const [lastAnswerSignal, setLastAnswerSignal] = useState<AnswerSignal | "">("");
  const [autoAdvanceRealtime, setAutoAdvanceRealtime] = useState(true);
  const [phase, setPhase] = useState<Phase>("ready");
  const [turnIndex, setTurnIndex] = useState(0);
  const [liveAnswer, setLiveAnswer] = useState("");
  const [committed, setCommitted] = useState<typeof TURNS>([]);
  const [liveTranscriptOpen, setLiveTranscriptOpen] = useState(true);
  const [fullTranscriptOpen, setFullTranscriptOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [energy, setEnergy] = useState(0.16);
  const [showClosing, setShowClosing] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraVisible, setCameraVisible] = useState(true);
  const [cameraError, setCameraError] = useState("");
  const [questionFontSize, setQuestionFontSize] = useState<number | null>(null);
  const questionCardRef = useRef<HTMLElement | null>(null);
  const questionTextRef = useRef<HTMLHeadingElement | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
  const dgConnectionRef = useRef<any>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sessionIdRef = useRef("");
  const deepgramSeqRef = useRef(0);
  const realtimeSeqRef = useRef(0);
  const candidateSpeechStartedAtRef = useRef<number | null>(null);
  const aiSpeechStartedAtRef = useRef<number | null>(null);
  const pendingAiQuestionRef = useRef("");
  const responseInFlightRef = useRef(false);
  const activeResponseIdRef = useRef("");
  const spokenQuestionCompleteRef = useRef(false);
  const spokenQuestionTextRef = useRef("");
  const responseCountForQuestionRef = useRef(0);
  const questionInstructionSeqRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const typingRef = useRef<number | null>(null);
  const energyRef = useRef<number | null>(null);

  const mural = PHASE_MURAL[phase];
  const activeTurn = TURNS[Math.min(turnIndex, TURNS.length - 1)];
  const activeFlow = flowForTurn(turnIndex);
  const activeAnswerOptions = answerOptionsForTurn(turnIndex);
  const selectedAnswerOption =
    activeAnswerOptions.find((option) => option.signal === answerSignalMode) || activeAnswerOptions[0];
  const colorShift = clamp(mural.shift + energy * 0.1, 0.08, 0.68);
  const candidateVoiceText = realtimePartial || deepgramPartial || realtimeFinal || deepgramFinal || openaiTranscribeText;
  const candidateFinalText = realtimeFinal || deepgramFinal || openaiTranscribeText;
  const activeVoiceQuestion = aiTranscript.trim() || activeTurn.question;
  const floorOwner = phase === "listening" ? "candidate" : phase === "ready" ? "ready" : "ai";
  const floorLabel =
    floorOwner === "candidate"
      ? "Candidate turn"
      : floorOwner === "ai"
        ? "Interviewer turn"
        : "Turn";
  const activityText =
    voiceError
      ? "Voice lab needs attention"
      : phase === "asking"
      ? "AI interviewer is asking the question"
      : phase === "listening"
        ? "Candidate is speaking"
        : phase === "reviewing"
          ? "AI interviewer is thinking"
          : phase === "closing"
            ? "AI interviewer is closing the interview"
            : "Interview room is ready";
  const displayedQuestion =
    phase === "ready"
      ? "When you are ready, start the live interview room."
      : phase === "closing"
        ? "That gives me enough signal. I am closing the interview and preparing your report."
        : activeVoiceQuestion;
  const questionDensity =
    displayedQuestion.length > 110
      ? "dense"
      : displayedQuestion.length > 84
        ? "compact"
        : displayedQuestion.length > 64
          ? "medium"
          : "short";

  const recentTurns = useMemo(() => committed.slice(-4).reverse(), [committed]);
  const realtimeModelOptions = useMemo(
    () => Array.from(new Set(["gpt-realtime-mini", ...(status?.realtime_models || []), "gpt-realtime-2", "gpt-realtime"])),
    [status?.realtime_models],
  );
  const transcribeModelOptions = useMemo(
    () => Array.from(new Set([...(status?.transcribe_models || []), "gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"])),
    [status?.transcribe_models],
  );
  const usageEstimate = useMemo(
    () => estimateRealtimeUsage(usageTurns, realtimeModel, transcribeModel, transcribeSamples),
    [realtimeModel, transcribeModel, transcribeSamples, usageTurns],
  );
  const turnHistory = useMemo(
    () =>
      (fullTranscriptOpen ? [...committed].reverse() : recentTurns).map((turn, index, source) => ({
        turn,
        turnNumber: TURNS.findIndex((item) => item.question === turn.question) + 1 || source.length - index,
      })),
    [committed, fullTranscriptOpen, recentTurns],
  );

  useEffect(() => {
    const nextSessionId = `voice-room-${crypto.randomUUID()}`;
    sessionIdRef.current = nextSessionId;
    setSessionId(nextSessionId);
    void refreshStatus();
    return () => {
      clearTimers();
      stopVoiceLab();
      stopCamera(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useLayoutEffect(() => {
    const card = questionCardRef.current;
    const text = questionTextRef.current;
    if (!card || !text) return;

    const fitQuestion = () => {
      const cardStyles = window.getComputedStyle(card);
      const availableWidth =
        card.clientWidth - parseFloat(cardStyles.paddingLeft) - parseFloat(cardStyles.paddingRight);
      const availableHeight =
        card.clientHeight - parseFloat(cardStyles.paddingTop) - parseFloat(cardStyles.paddingBottom);
      if (availableWidth <= 0 || availableHeight <= 0) return;

      const collapsedBoost = historyOpen ? 0 : 2;
      const bounds =
        questionDensity === "dense"
          ? { min: 17, max: 44 + collapsedBoost, line: 1.08 }
          : questionDensity === "compact"
            ? { min: 19, max: 52 + collapsedBoost, line: 1.06 }
            : questionDensity === "medium"
              ? { min: 22, max: 60 + collapsedBoost, line: 1.05 }
              : { min: 26, max: 64 + collapsedBoost, line: 1.04 };

      const previousFont = text.style.fontSize;
      const previousLine = text.style.lineHeight;
      const previousWidth = text.style.width;
      text.style.width = `${availableWidth}px`;
      text.style.lineHeight = String(bounds.line);

      let low = bounds.min;
      let high = bounds.max;
      let best = bounds.min;
      for (let i = 0; i < 9; i += 1) {
        const mid = (low + high) / 2;
        text.style.fontSize = `${mid}px`;
        const fits =
          text.scrollHeight <= availableHeight + 1 &&
          text.scrollWidth <= availableWidth + 1;
        if (fits) {
          best = mid;
          low = mid;
        } else {
          high = mid;
        }
      }

      text.style.fontSize = previousFont;
      text.style.lineHeight = previousLine;
      text.style.width = previousWidth;
      setQuestionFontSize(Math.floor(best * 10) / 10);
    };

    fitQuestion();
    const observer = new ResizeObserver(fitQuestion);
    observer.observe(card);
    return () => observer.disconnect();
  }, [displayedQuestion, historyOpen, questionDensity]);

  function appendEvent(type: string, detail = "") {
    setEvents((current) => [
      { id: crypto.randomUUID(), ts: nowLabel(), type, detail },
      ...current,
    ].slice(0, 80));
    postBackendTelemetry(type, { detail }).catch(() => undefined);
  }

  async function postBackendTelemetry(event: string, fields: Record<string, unknown> = {}) {
    const activeSessionId = sessionIdRef.current || sessionId || "voice-lab";
    await fetch(`${openaiApiBase}/telemetry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: activeSessionId,
        event: `voice_lab.${event}`,
        source: "frontend.voice_lab",
        fields: {
          turn_index: turnIndex,
          phase,
          realtime_model: realtimeModel,
          transcribe_model: transcribeModel,
          openai_api_base: openaiApiBase,
          deepgram_api_base: deepgramApiBase,
          ...fields,
        },
      }),
    });
  }

  function addUsageTurn(turn: Omit<UsageTurn, "id">) {
    setUsageTurns((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        ...turn,
      },
    ]);
    postBackendTelemetry("usage_turn_added", {
      label: turn.label,
      input_audio_ms: turn.inputAudioMs,
      output_audio_ms: turn.outputAudioMs,
      input_text_tokens: turn.inputTextTokens,
      output_text_tokens: turn.outputTextTokens,
      has_provider_usage: Boolean(turn.providerUsage),
    }).catch(() => undefined);
  }

  function addEstimatedUsageForTurn(turn: (typeof TURNS)[number], index: number) {
    addUsageTurn({
      label: `T${index + 1}`,
      question: turn.question,
      answer: turn.answer,
      inputAudioMs: estimateSpeechMs(turn.answer, 155),
      outputAudioMs: estimateSpeechMs(turn.question, 145),
      inputTextTokens: estimateTextTokens(turn.answer),
      outputTextTokens: estimateTextTokens(turn.question),
    });
  }

  function resetUsage() {
    setUsageTurns([]);
    setTranscribeSamples(0);
    candidateSpeechStartedAtRef.current = null;
    aiSpeechStartedAtRef.current = null;
    pendingAiQuestionRef.current = "";
    responseInFlightRef.current = false;
    activeResponseIdRef.current = "";
    spokenQuestionCompleteRef.current = false;
    spokenQuestionTextRef.current = "";
    responseCountForQuestionRef.current = 0;
    questionInstructionSeqRef.current = 0;
    setSpokenQuestionText("");
    setTurnGuardStatus("clean");
    setTurnGuardMessage("No duplicate Realtime responses detected.");
    appendEvent("usage.reset");
  }

  function loadAnswerScript(option = selectedAnswerOption) {
    setAnswerSignalMode(option.signal);
    setLiveAnswer(option.text);
    setLiveTranscriptOpen(true);
    transitionPhase("listening");
    appendEvent("answer_script.loaded", `${option.signal}: ${option.label}`);
  }

  function handleOperationalInteraction(text: string, provider: "openai" | "deepgram") {
    const interaction = classifyOperationalInteraction(text);
    if (!interaction) return false;

    const questionText = spokenQuestionTextRef.current || aiTranscript.trim() || activeTurn.question;
    appendEvent("interaction.non_counting", `${interaction}: ${text.slice(0, 140)}`);
    setTurnGuardStatus("clean");
    setTurnGuardMessage(`Handled ${interaction.replace("_", " ")} as a non-counting interaction move.`);
    void postVoiceEvent(provider, `interaction_${interaction}`, text, true);
    void postBackendTelemetry("interaction.non_counting", {
      interaction,
      provider,
      transcript_preview: text.slice(0, 500),
      current_question_preview: questionText.slice(0, 500),
    });
    candidateSpeechStartedAtRef.current = null;

    if (interaction === "pause") {
      transitionPhase("listening");
      stopEnergy(0.12);
      return true;
    }

    sendRealtimeInstruction(buildOperationalInteractionInstruction(interaction, questionText));
    return true;
  }

  function applyNextQuestionFromAnswer(answer: string, source = "synthetic") {
    if (source === "realtime" && responseInFlightRef.current) {
      setTurnGuardStatus("blocked");
      setTurnGuardMessage("Blocked auto-advance because the current Realtime question is still speaking.");
      appendEvent("turn_guard.blocked_auto_next", answer.slice(0, 160));
      void postBackendTelemetry("turn_guard.blocked_auto_next", {
        answer_preview: answer.slice(0, 220),
        active_response_id: activeResponseIdRef.current,
      });
      return;
    }
    const signal = classifyAnswerSignal(answer);
    setLastAnswerSignal(signal);
    const next = nextTurnIndex(turnIndex, signal);
    appendEvent("backend_sim.decision", `answer_signal=${signal} next=${next}`);
    if (next === "close") {
      closeRoom();
      return;
    }
    setTurnIndex(next);
    setAiTranscript("");
    setSpokenQuestionText("");
    if (source === "realtime" && autoAdvanceRealtime) {
      const nextQuestion = TURNS[next]?.question || "";
      window.setTimeout(() => {
        if (responseInFlightRef.current) {
          setTurnGuardStatus("blocked");
          setTurnGuardMessage("Blocked delayed Realtime question because the previous response was still active.");
          appendEvent("turn_guard.blocked_delayed_question", nextQuestion.slice(0, 160));
          return;
        }
        sendRealtimeInstruction(
          buildRealtimeInterviewInstruction(nextQuestion),
        );
      }, 550);
      return;
    }
    transitionPhase("asking");
    startEnergy("ai");
  }

  async function refreshStatus() {
    try {
      const probes = await Promise.all(
        API_CANDIDATES.map(async (baseUrl): Promise<ProviderRuntime | null> => {
          try {
            const res = await fetch(`${baseUrl}/voice/status`, { cache: "no-store" });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(payload?.detail || `Status failed (${res.status})`);
            return { baseUrl, status: normalizeProviderStatus(payload) };
          } catch {
            return null;
          }
        }),
      );
      const runtimes = probes.filter((probe): probe is ProviderRuntime => Boolean(probe));
      if (!runtimes.length) throw new Error("No voice backend responded.");

      const openaiRuntime = runtimes.find((runtime) => runtime.status.openai_configured) || runtimes[0];
      const deepgramRuntime = runtimes.find((runtime) => runtime.status.deepgram_configured) || runtimes[0];
      const mergedStatus = {
        ...openaiRuntime.status,
        deepgram_configured: deepgramRuntime.status.deepgram_configured,
      };

      setOpenaiApiBase(openaiRuntime.baseUrl);
      setDeepgramApiBase(deepgramRuntime.baseUrl);
      setStatus(mergedStatus);
      setRealtimeModel(openaiRuntime.status.default_realtime_model || "gpt-realtime-mini");
      setTranscribeModel(openaiRuntime.status.default_transcribe_model || "gpt-4o-mini-transcribe");
      appendEvent(
        "status.refresh",
        `openai=${mergedStatus.openai_configured} via ${openaiRuntime.baseUrl.replace(/^https?:\/\//, "")} deepgram=${mergedStatus.deepgram_configured} via ${deepgramRuntime.baseUrl.replace(/^https?:\/\//, "")}`,
      );
    } catch (error) {
      const message = String(error);
      setVoiceError(message);
      appendEvent("status.failed", message);
    }
  }

  async function refreshBackendDiagnostics() {
    const activeSessionId = sessionIdRef.current || sessionId;
    if (!activeSessionId) return;
    setBackendDiagnosticsLoading(true);
    setBackendDiagnosticsError("");
    try {
      const res = await fetch(`${openaiApiBase}/telemetry/${encodeURIComponent(activeSessionId)}?limit=500`, {
        cache: "no-store",
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `Backend diagnostics failed (${res.status})`);
      setBackendDiagnostics({
        summary: payload,
        actualModel: actualRealtimeModelFromSummary(payload),
        usage: summarizeBackendRealtimeUsage(payload, realtimeModel),
        refreshedAt: nowLabel(),
      });
      appendEvent("backend_diagnostics.refresh", `events=${payload?.event_count ?? 0}`);
    } catch (error) {
      const message = String(error);
      setBackendDiagnosticsError(message);
      appendEvent("backend_diagnostics.failed", message);
    } finally {
      setBackendDiagnosticsLoading(false);
    }
  }

  async function ensureMic() {
    if (micStreamRef.current) return micStreamRef.current;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone capture is not available in this browser.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    micStreamRef.current = stream;
    appendEvent("mic.opened");
    return stream;
  }

  async function startVoiceLab() {
    setVoiceError("");
    setRealtimePartial("");
    setRealtimeFinal("");
    setDeepgramPartial("");
    setDeepgramFinal("");
    setOpenaiTranscribeText("");
    setAiTranscript("");
    setLiveAnswer("");
    try {
      const stream = await ensureMic();
      setVoiceLabRunning(true);
      setLiveTranscriptOpen(true);
      transitionPhase("asking");
      startEnergy("ai");
      if (enableDeepgram) await startDeepgram(stream);
      if (enableRealtime) await startRealtime(stream);
      if (!enableRealtime) {
        transitionPhase("listening");
        startEnergy("candidate");
      }
    } catch (error) {
      const message = String(error);
      setVoiceError(message);
      appendEvent("voice.start_failed", message);
      stopVoiceLab();
    }
  }

  function stopVoiceLab() {
    stopRealtime();
    stopDeepgram();
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    setVoiceLabRunning(false);
    appendEvent("voice.stopped");
    window.setTimeout(() => void refreshBackendDiagnostics(), 300);
  }

  async function startRealtime(stream: MediaStream) {
    if (realtimeRunning || peerRef.current) return;
    if (!status?.openai_configured) throw new Error("OpenAI is not configured on any reachable voice backend.");
    let offerSessionId = sessionIdRef.current || sessionId;

    const peer = new RTCPeerConnection();
    const dc = peer.createDataChannel("oai-events");
    peerRef.current = peer;
    dataChannelRef.current = dc;

    peer.ontrack = (event) => {
      const [remoteStream] = event.streams;
      if (remoteAudioRef.current && remoteStream) {
        remoteAudioRef.current.srcObject = remoteStream;
        remoteAudioRef.current.play().catch(() => undefined);
      }
    };
    peer.onconnectionstatechange = () => {
      appendEvent("realtime.connection", peer.connectionState);
      if (peer.connectionState === "connected") {
        setRealtimeRunning(true);
      }
      if (peer.connectionState === "failed" || peer.connectionState === "disconnected" || peer.connectionState === "closed") {
        setRealtimeRunning(false);
      }
    };
    dc.onopen = () => {
      appendEvent("realtime.data_channel_open", realtimeModel);
      sendRealtimeSessionUpdate();
      sendRealtimeInstruction(
        buildRealtimeInterviewInstruction(activeTurn.question),
      );
    };
    dc.onmessage = (event) => handleRealtimeEvent(event.data);
    dc.onerror = () => appendEvent("realtime.data_channel_error");
    dc.onclose = () => appendEvent("realtime.data_channel_closed");

    stream.getAudioTracks().forEach((track) => peer.addTrack(track, stream));
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    const createVoiceTestOffer = async () => {
      const startRes = await fetch(`${openaiApiBase}/voice/test_session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: "openai",
          question: activeTurn.question,
        }),
      });
      const startPayload = await startRes.json().catch(() => ({}));
      if (!startRes.ok) throw new Error(startPayload?.detail || `Voice test session failed (${startRes.status})`);
      offerSessionId = String(startPayload?.session_id || offerSessionId);
      sessionIdRef.current = offerSessionId;
      setSessionId(offerSessionId);
      const voiceRes = await fetch(`${openaiApiBase}/voice/openai/realtime_offer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: offerSessionId,
          sdp: offer.sdp || "",
          model: realtimeModel,
          voice: "marin",
          turn_id: `room-voice-${turnIndex + 1}`,
        }),
      });
      return { res: voiceRes, answerSdp: await voiceRes.text() };
    };
    const createSimulationOffer = async () => {
      const startRes = await fetch(`${openaiApiBase}/simulation/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate_context: {
            name: CANDIDATE.name,
            role: CANDIDATE.role,
            source: "visualizer-livekit-room-voice-lab",
            requested_question: activeTurn.question,
          },
        }),
      });
      const startPayload = await startRes.json().catch(() => ({}));
      if (!startRes.ok) throw new Error(startPayload?.detail || `Simulation start failed (${startRes.status})`);
      offerSessionId = String(startPayload?.session_id || offerSessionId);
      sessionIdRef.current = offerSessionId;
      setSessionId(offerSessionId);
      const simulationRes = await fetch(`${openaiApiBase}/simulation/realtime_offer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: offerSessionId,
          sdp: offer.sdp || "",
          stage_key: activeFlow.route || "voice_lab",
          voice: "marin",
          model: realtimeModel,
        }),
      });
      return { res: simulationRes, answerSdp: await simulationRes.text() };
    };
    const offerPayload = {
      session_id: offerSessionId,
      sdp: offer.sdp || "",
      model: realtimeModel,
      voice: "marin",
      vad_mode: "semantic_vad",
      vad_eagerness: "low",
    };
    let res: Response;
    let answerSdp: string;
    if (offerSessionId.startsWith("voice-room-")) {
      appendEvent("realtime.offer_mode", "voice/openai/realtime_offer");
      try {
        ({ res, answerSdp } = await createVoiceTestOffer());
      } catch (error) {
        appendEvent("realtime.offer_fallback", `simulation/realtime_offer after ${String(error).slice(0, 120)}`);
        ({ res, answerSdp } = await createSimulationOffer());
      }
    } else {
      res = await fetch(`${openaiApiBase}/voice/openai/realtime_offer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(offerPayload),
      });
      answerSdp = await res.text();
      if (res.status === 404 || res.status === 405 || /Session not found/i.test(answerSdp)) {
        appendEvent("realtime.offer_fallback", "simulation/realtime_offer");
        ({ res, answerSdp } = await createSimulationOffer());
      }
    }
    if (!res.ok) throw new Error(answerSdp);
    await peer.setRemoteDescription({ type: "answer", sdp: answerSdp });
    appendEvent("realtime.offer_answered", `${realtimeModel} via ${openaiApiBase.replace(/^https?:\/\//, "")}`);
  }

  function stopRealtime() {
    dataChannelRef.current?.close();
    dataChannelRef.current = null;
    peerRef.current?.close();
    peerRef.current = null;
    if (remoteAudioRef.current) remoteAudioRef.current.srcObject = null;
    responseInFlightRef.current = false;
    activeResponseIdRef.current = "";
    spokenQuestionCompleteRef.current = false;
    spokenQuestionTextRef.current = "";
    responseCountForQuestionRef.current = 0;
    setRealtimeRunning(false);
  }

  async function startDeepgram(stream: MediaStream) {
    if (deepgramRunning || dgConnectionRef.current) return;
    if (!status?.deepgram_configured) throw new Error("Deepgram is not configured on the backend runtime.");

    const tokenRes = await fetch(`${deepgramApiBase}/deepgram_token`);
    const tokenPayload = await tokenRes.json();
    if (!tokenRes.ok) throw new Error(tokenPayload?.detail || "Deepgram token failed.");
    const dg = createClient(tokenPayload.token);
    const connection = dg.listen.live({
      model: "nova-3",
      language: "en",
      encoding: "linear16",
      sample_rate: 16000,
      channels: 1,
      interim_results: true,
      vad_events: true,
      endpointing: 1500,
      utterance_end_ms: 2800,
      smart_format: true,
      punctuate: true,
    });
    dgConnectionRef.current = connection;

    await new Promise<void>((resolve, reject) => {
      connection.on(LiveTranscriptionEvents.Open, () => resolve());
      connection.on(LiveTranscriptionEvents.Error, (error: unknown) => reject(error));
      window.setTimeout(() => reject(new Error("Deepgram connection timeout")), 8000);
    });

    connection.on(LiveTranscriptionEvents.Transcript, (data: any) => {
      const text = String(data?.channel?.alternatives?.[0]?.transcript || "").trim();
      if (!text) return;
      const isFinal = Boolean(data?.is_final || data?.speech_final);
      if (isFinal) {
        setDeepgramFinal(text);
        setLiveAnswer(text);
        appendEvent("deepgram.final", text);
        if (!enableRealtime) {
          if (handleOperationalInteraction(text, "deepgram")) {
            return;
          }
          commitVoiceTurn(text);
          addUsageTurn({
            label: `Shadow T${turnIndex + 1}`,
            question: activeTurn.question,
            answer: text,
            inputAudioMs: candidateSpeechStartedAtRef.current
              ? Math.max(900, performance.now() - candidateSpeechStartedAtRef.current)
              : estimateSpeechMs(text, 155),
            outputAudioMs: estimateSpeechMs(activeTurn.question, 145),
            inputTextTokens: estimateTextTokens(text),
            outputTextTokens: estimateTextTokens(activeTurn.question),
          });
          applyNextQuestionFromAnswer(text, "deepgram");
          candidateSpeechStartedAtRef.current = null;
        }
      } else {
        setDeepgramPartial(text);
        setLiveAnswer(text);
      }
      transitionPhase("listening");
      startEnergy("candidate");
      void postVoiceEvent("deepgram", isFinal ? "transcript_final" : "transcript_delta", text, isFinal);
    });
    connection.on(LiveTranscriptionEvents.UtteranceEnd, () => appendEvent("deepgram.utterance_end"));
    connection.on(LiveTranscriptionEvents.SpeechStarted, () => {
      candidateSpeechStartedAtRef.current = performance.now();
      appendEvent("deepgram.speech_started");
    });
    connection.on(LiveTranscriptionEvents.Error, (error: unknown) => appendEvent("deepgram.error", String(error)));

    const audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(2048, 1, 1);
    processor.onaudioprocess = (event) => {
      if (!dgConnectionRef.current) return;
      dgConnectionRef.current.send(float32ToPcm16(event.inputBuffer.getChannelData(0)));
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    audioContextRef.current = audioContext;
    processorRef.current = processor;
    setDeepgramRunning(true);
    appendEvent("deepgram.open");
  }

  function stopDeepgram() {
    processorRef.current?.disconnect();
    processorRef.current = null;
    audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
    dgConnectionRef.current?.finish?.();
    dgConnectionRef.current = null;
    setDeepgramRunning(false);
  }

  function sendRealtimeInstruction(instructions: string) {
    const dc = dataChannelRef.current;
    if (!dc || dc.readyState !== "open") {
      appendEvent("realtime.not_open");
      return;
    }
    if (responseInFlightRef.current) {
      setTurnGuardStatus("blocked");
      setTurnGuardMessage("Blocked duplicate Realtime response.create while the current question is still active.");
      appendEvent("turn_guard.blocked_response_create", instructions.slice(0, 180));
      void postBackendTelemetry("turn_guard.blocked_response_create", {
        attempted_instruction: instructions.slice(0, 500),
        active_response_id: activeResponseIdRef.current,
      });
      return;
    }
    questionInstructionSeqRef.current += 1;
    responseInFlightRef.current = true;
    activeResponseIdRef.current = "";
    spokenQuestionCompleteRef.current = false;
    spokenQuestionTextRef.current = "";
    responseCountForQuestionRef.current = 0;
    pendingAiQuestionRef.current = instructions;
    aiSpeechStartedAtRef.current = null;
    setAiTranscript("");
    setSpokenQuestionText("");
    setRealtimePartial("");
    setRealtimeFinal("");
    setDeepgramPartial("");
    setDeepgramFinal("");
    setTurnGuardStatus("asking");
    setTurnGuardMessage(`Realtime question ${questionInstructionSeqRef.current} is active.`);
    transitionPhase("asking");
    startEnergy("ai");
    dc.send(JSON.stringify({ type: "response.create", response: { instructions } }));
    appendEvent("realtime.response_create", instructions);
    void postVoiceEvent("openai", "question_instruction_sent", instructions, true);
  }

  function sendRealtimeSessionUpdate() {
    const dc = dataChannelRef.current;
    if (!dc || dc.readyState !== "open") return;
    dc.send(JSON.stringify({
      type: "session.update",
      session: {
        instructions: buildRealtimeInterviewInstruction(
          "Wait silently until the frontend sends a backend-approved question.",
          "recovery",
        ),
        audio: {
          input: {
            turn_detection: {
              type: "semantic_vad",
              eagerness: "low",
              create_response: false,
              interrupt_response: false,
            },
            transcription: {
              model: transcribeModel,
            },
          },
        },
      },
    }));
    appendEvent("realtime.session_update", "manual_response_only");
  }

  function sendFunctionCallTest() {
    sendRealtimeInstruction(
      buildRealtimeInterviewInstruction(
        "Call the report_voice_lab_signal function with event_type 'room_ui_function_test', confidence 0.92, and notes 'locked-room copy function path is being tested'. After the tool result, say one short confirmation and return to interview mode.",
        "tool",
      ),
    );
  }

  function handleRealtimeEvent(raw: string) {
    let message: any = null;
    try {
      message = JSON.parse(raw);
    } catch {
      appendEvent("realtime.raw", raw.slice(0, 180));
      return;
    }

    const type = String(message?.type || "realtime.event");
    if (!type.includes("delta")) appendEvent(type, shortJson(message));

    if (type === "response.created") {
      responseCountForQuestionRef.current += 1;
      activeResponseIdRef.current = String(message?.response?.id || "");
      if (responseCountForQuestionRef.current > 1) {
        setTurnGuardStatus("warning");
        setTurnGuardMessage("Realtime created more than one response for the same displayed question.");
        appendEvent("turn_guard.duplicate_response", activeResponseIdRef.current);
        void postBackendTelemetry("turn_guard.duplicate_response", {
          response_id: activeResponseIdRef.current,
          response_count: responseCountForQuestionRef.current,
          pending_instruction: pendingAiQuestionRef.current.slice(0, 500),
        });
      }
      return;
    }

    if (type === "conversation.item.input_audio_transcription.delta") {
      const text = String(message?.delta || message?.transcript || "");
      if (!candidateSpeechStartedAtRef.current) candidateSpeechStartedAtRef.current = performance.now();
      setRealtimePartial((current) => `${current}${text}`);
      setLiveAnswer((current) => `${current}${text}`);
      if (responseInFlightRef.current && !spokenQuestionCompleteRef.current) {
        setTurnGuardStatus("warning");
        setTurnGuardMessage("Candidate audio arrived while the AI question was still speaking; holding turn advancement.");
        appendEvent("turn_guard.candidate_audio_during_ai", text.slice(0, 140));
      }
      transitionPhase("listening");
      startEnergy("candidate");
      void postVoiceEvent("openai", "transcript_delta", text, false, message?.item_id);
      return;
    }
    if (type === "conversation.item.input_audio_transcription.completed") {
      const text = String(message?.transcript || "").trim();
      setRealtimeFinal(text);
      setLiveAnswer(text);
      if (responseInFlightRef.current && !spokenQuestionCompleteRef.current) {
        setTurnGuardStatus("blocked");
        setTurnGuardMessage("Blocked candidate final because Realtime has not finished the spoken question.");
        appendEvent("turn_guard.blocked_candidate_final", text.slice(0, 180));
        void postBackendTelemetry("turn_guard.blocked_candidate_final", {
          transcript_preview: text.slice(0, 500),
          active_response_id: activeResponseIdRef.current,
        });
        void postVoiceEvent("openai", "transcript_final_held_during_ai", text, true, message?.item_id);
        return;
      }
      if (handleOperationalInteraction(text, "openai")) {
        return;
      }
      transitionPhase("reviewing");
      stopEnergy(0.28);
      commitVoiceTurn(text);
      const inputAudioMs =
        candidateSpeechStartedAtRef.current
          ? Math.max(900, performance.now() - candidateSpeechStartedAtRef.current)
          : estimateSpeechMs(text, 155);
      const questionText = spokenQuestionTextRef.current || aiTranscript.trim() || activeTurn.question;
      const outputAudioMs =
        aiSpeechStartedAtRef.current
          ? Math.max(900, performance.now() - aiSpeechStartedAtRef.current)
          : estimateSpeechMs(questionText, 145);
      addUsageTurn({
        label: `Live T${turnIndex + 1}`,
        question: questionText,
        answer: text,
        inputAudioMs,
        outputAudioMs,
        inputTextTokens: estimateTextTokens(text),
        outputTextTokens: estimateTextTokens(questionText),
      });
      candidateSpeechStartedAtRef.current = null;
      applyNextQuestionFromAnswer(text, "realtime");
      void postVoiceEvent("openai", "transcript_final", text, true, message?.item_id);
      return;
    }
    if (type === "response.audio_transcript.delta" || type === "response.output_audio_transcript.delta") {
      if (!aiSpeechStartedAtRef.current) aiSpeechStartedAtRef.current = performance.now();
      setAiTranscript((current) => `${current}${String(message?.delta || "")}`);
      transitionPhase("asking");
      startEnergy("ai");
      return;
    }
    if (
      type === "response.output_audio_transcript.done" ||
      type === "response.audio_transcript.done" ||
      type === "response.content_part.done"
    ) {
      const transcript = String(
        message?.transcript ||
        message?.part?.transcript ||
        message?.content?.transcript ||
        "",
      ).trim();
      if (transcript) {
        spokenQuestionTextRef.current = transcript;
        setAiTranscript(transcript);
        setSpokenQuestionText(transcript);
        spokenQuestionCompleteRef.current = true;
        appendEvent("turn_guard.spoken_question_captured", transcript.slice(0, 180));
        void postVoiceEvent("openai", "spoken_question_captured", transcript, true, activeResponseIdRef.current);
      }
      return;
    }
    if (type === "response.audio.done" || type === "response.output_audio.done" || type === "response.done") {
      const questionText = spokenQuestionTextRef.current || aiTranscript.trim() || activeTurn.question;
      const outputAudioMs =
        aiSpeechStartedAtRef.current
          ? Math.max(900, performance.now() - aiSpeechStartedAtRef.current)
          : estimateSpeechMs(questionText, 145);
      if (message?.response?.usage || message?.usage) {
        const providerUsage = message?.response?.usage || message?.usage;
        setUsageTurns((current) => {
          if (!current.length) {
            return [
              {
                id: crypto.randomUUID(),
                label: `AI T${turnIndex + 1}`,
                question: questionText,
                answer: "",
                inputAudioMs: 0,
                outputAudioMs,
                inputTextTokens: 0,
                outputTextTokens: estimateTextTokens(questionText),
                providerUsage,
              },
            ];
          }
          const next = [...current];
          next[next.length - 1] = { ...next[next.length - 1], providerUsage };
          return next;
        });
        appendEvent("realtime.usage", shortJson(providerUsage));
        void postBackendTelemetry("realtime.provider_usage", {
          provider_usage: providerUsage,
        });
      } else if (type === "response.audio.done" || type === "response.output_audio.done") {
        addUsageTurn({
          label: `AI T${turnIndex + 1}`,
          question: questionText,
          answer: "",
          inputAudioMs: 0,
          outputAudioMs,
          inputTextTokens: 0,
          outputTextTokens: estimateTextTokens(questionText),
        });
      }
      if (type === "response.done") {
        responseInFlightRef.current = false;
        activeResponseIdRef.current = "";
        spokenQuestionCompleteRef.current = true;
        if (!spokenQuestionTextRef.current) {
          spokenQuestionTextRef.current = questionText;
          setSpokenQuestionText(questionText);
        }
        if (turnGuardStatus !== "warning" && turnGuardStatus !== "blocked") {
          setTurnGuardStatus("clean");
          setTurnGuardMessage("Realtime completed one response for the displayed question.");
        }
        transitionPhase("listening");
        startEnergy("candidate");
      } else {
        transitionPhase("asking");
        startEnergy("ai");
      }
    }
    if (type === "response.output_item.done" && message?.item?.type === "function_call") {
      handleRealtimeFunctionCall(message.item);
    }
    if (type === "response.function_call_arguments.done") {
      handleRealtimeFunctionCall(message);
    }
  }

  function handleRealtimeFunctionCall(item: any) {
    const callId = String(item?.call_id || "");
    const name = String(item?.name || "");
    if (!callId || name !== "report_voice_lab_signal") return;
    let args: Record<string, unknown> = {};
    try {
      args = JSON.parse(String(item?.arguments || "{}"));
    } catch {
      args = { raw_arguments: item?.arguments || "" };
    }
    setFunctionCalls((count) => count + 1);
    appendEvent("function_call.received", shortJson(args));
    const dc = dataChannelRef.current;
    if (!dc || dc.readyState !== "open") return;
    dc.send(JSON.stringify({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: callId,
        output: JSON.stringify({
          ok: true,
          received_at: new Date().toISOString(),
          lab_session_id: sessionId,
          args,
        }),
      },
    }));
    dc.send(JSON.stringify({
      type: "response.create",
      response: { instructions: "Acknowledge the function-call result in one sentence." },
    }));
    appendEvent("function_call.output_sent", callId);
  }

  function commitVoiceTurn(answer: string) {
    if (!answer.trim()) return;
    setCommitted((previous) => [
      ...previous,
      {
        ...activeTurn,
        question: spokenQuestionTextRef.current || aiTranscript.trim() || activeTurn.question,
        answer,
        said: "voice input",
        testing: "voice lab",
      },
    ].slice(-TURNS.length));
  }

  async function postVoiceEvent(provider: string, eventType: string, transcript: string, isFinal: boolean, itemId = "") {
    const payload = {
      session_id: sessionIdRef.current || sessionId,
      event_type: eventType,
      provider,
      turn_id: `room-voice-${turnIndex + 1}`,
      item_id: itemId,
      transcript,
      is_final: isFinal,
      snapshot_seq: provider === "deepgram" ? ++deepgramSeqRef.current : ++realtimeSeqRef.current,
      metadata: {
        phase,
        turn_index: turnIndex,
        answer_signal_mode: answerSignalMode,
        realtime_model: realtimeModel,
      },
    };
    await postBackendTelemetry(`voice_event.${eventType}`, {
      provider,
      item_id: itemId,
      transcript_chars: transcript.length,
      transcript_preview: transcript.slice(0, 240),
      is_final: isFinal,
      snapshot_seq: payload.snapshot_seq,
      metadata: payload.metadata,
    }).catch(() => undefined);
  }

  async function captureOpenAiTranscribeSample() {
    setVoiceError("");
    setRecordingSample(true);
    try {
      const stream = await ensureMic();
      const recorder = new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      const stopped = new Promise<Blob>((resolve) => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
      });
      recorder.start();
      appendEvent("openai_transcribe.recording", "8 seconds");
      window.setTimeout(() => {
        if (recorder.state !== "inactive") recorder.stop();
      }, 8000);
      const blob = await stopped;
      const uploadInit = {
        method: "POST",
        headers: {
          "Content-Type": blob.type || "audio/webm",
          "X-Content-Type": blob.type || "audio/webm",
          "X-Filename": "room-voice-sample.webm",
        },
        body: blob,
      };
      let res = await fetch(
        `${openaiApiBase}/voice/openai/transcribe_audio/${encodeURIComponent(sessionIdRef.current || sessionId)}?model=${encodeURIComponent(transcribeModel)}`,
        uploadInit,
      );
      if (res.status === 404 || res.status === 405) {
        res = await fetch(
          `${openaiApiBase}/simulation/transcribe_audio/${encodeURIComponent(sessionIdRef.current || sessionId)}`,
          uploadInit,
        );
      }
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `OpenAI transcription failed (${res.status})`);
      const text = String(payload?.transcript || "");
      setOpenaiTranscribeText(text);
      setLiveAnswer(text);
      setTranscribeSamples((count) => count + 1);
      commitVoiceTurn(text);
      appendEvent("openai_transcribe.final", text);
    } catch (error) {
      const message = String(error);
      setVoiceError(message);
      appendEvent("openai_transcribe.failed", message);
    } finally {
      setRecordingSample(false);
    }
  }

  function clearTimers() {
    if (timerRef.current) window.clearTimeout(timerRef.current);
    if (typingRef.current) window.clearInterval(typingRef.current);
    if (energyRef.current) window.clearInterval(energyRef.current);
    timerRef.current = null;
    typingRef.current = null;
    energyRef.current = null;
  }

  function startEnergy(kind: "ai" | "candidate" = "candidate") {
    if (energyRef.current) window.clearInterval(energyRef.current);
    let tick = 0;
    energyRef.current = window.setInterval(() => {
      tick += kind === "ai" ? 0.115 : 0.18;
      const base = kind === "ai" ? 0.28 : 0.2;
      const primary = kind === "ai" ? 0.18 : 0.42;
      const secondary = kind === "ai" ? 0.05 : 0.08;
      const next = base + Math.abs(Math.sin(tick)) * primary + Math.abs(Math.sin(tick * 0.43)) * secondary;
      setEnergy(clamp(next, 0.12, kind === "ai" ? 0.58 : 0.82));
    }, 80);
  }

  function stopEnergy(next = 0.18) {
    if (energyRef.current) window.clearInterval(energyRef.current);
    energyRef.current = null;
    setEnergy(next);
  }

  async function startCamera() {
    setCameraError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("Camera is not available in this browser.");
      return;
    }

    try {
      stopCamera(false);
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          width: { ideal: 640 },
          height: { ideal: 360 },
          facingMode: "user",
        },
      });
      cameraStreamRef.current = stream;
      setCameraVisible(true);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setCameraOn(true);
    } catch {
      setCameraOn(false);
      setCameraVisible(true);
      setCameraError("Camera preview blocked. Mock presence remains active.");
    }
  }

  function stopCamera(updateState = true) {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    if (updateState) {
      setCameraOn(false);
      setCameraVisible(true);
    }
  }

  function toggleCamera() {
    if (!cameraOn) {
      void startCamera();
      return;
    }
    setCameraVisible((visible) => !visible);
  }

  function transitionPhase(nextPhase: Phase) {
    setPhase(nextPhase);
  }

  function ask(index = turnIndex) {
    clearTimers();
    setShowClosing(false);
    transitionPhase("asking");
    startEnergy("ai");
    setTurnIndex(Math.min(index, TURNS.length - 1));
    setLiveAnswer("");
    setLiveTranscriptOpen(true);
  }

  function listen(index = turnIndex, onDone?: (answer: string) => void, answerOverride = "") {
    clearTimers();
    transitionPhase("listening");
    setTurnIndex(Math.min(index, TURNS.length - 1));
    setLiveAnswer("");
    setLiveTranscriptOpen(true);
    startEnergy("candidate");

    const answerText = answerOverride || TURNS[Math.min(index, TURNS.length - 1)].answer;
    const words = answerText.split(" ");
    let cursor = 0;
    typingRef.current = window.setInterval(() => {
      cursor += 1;
      setLiveAnswer(words.slice(0, cursor).join(" "));
      if (cursor >= words.length) {
        if (typingRef.current) window.clearInterval(typingRef.current);
        typingRef.current = null;
        timerRef.current = window.setTimeout(() => onDone?.(answerText), 650);
      }
    }, 105);
  }

  function review(index = turnIndex, answerOverride = "", signalOverride: AnswerSignal | "" = "") {
    clearTimers();
    const safeIndex = Math.min(index, TURNS.length - 1);
    const answer = answerOverride || TURNS[safeIndex].answer;
    const signal = signalOverride || classifyAnswerSignal(answer);
    setLastAnswerSignal(signal);
    setCommitted((previous) => {
      const nextCommitted = [...previous];
      nextCommitted[safeIndex] = {
        ...TURNS[safeIndex],
        answer,
        said: signal === "strong" ? TURNS[safeIndex].said : signal.replace("_", " "),
      };
      return nextCommitted.filter(Boolean);
    });
    setTurnIndex(safeIndex);
    transitionPhase("reviewing");
    stopEnergy(0.28);
    setLiveTranscriptOpen(false);
    appendEvent("backend_sim.review", `turn=${safeIndex + 1} signal=${signal}`);
  }

  function runSession() {
    clearTimers();
    resetUsage();
    setIsRunning(true);
    setCommitted([]);
    setTurnIndex(0);
    setLiveAnswer("");
    setLiveTranscriptOpen(false);
    setFullTranscriptOpen(false);
    setShowClosing(false);

    const runTurn = (index: number) => {
      if (index >= TURNS.length) {
        closeRoom();
        return;
      }
      const options = answerOptionsForTurn(index);
      const option = options.find((item) => item.signal === answerSignalMode) || options[0];
      ask(index);
      addUsageTurn({
        label: `Sim AI T${index + 1}`,
        question: TURNS[index].question,
        answer: "",
        inputAudioMs: 0,
        outputAudioMs: estimateSpeechMs(TURNS[index].question, 145),
        inputTextTokens: 0,
        outputTextTokens: estimateTextTokens(TURNS[index].question),
      });
      timerRef.current = window.setTimeout(() => {
        listen(index, (answer) => {
          addUsageTurn({
            label: `Sim candidate T${index + 1}`,
            question: "",
            answer,
            inputAudioMs: estimateSpeechMs(answer, 155),
            outputAudioMs: 0,
            inputTextTokens: estimateTextTokens(answer),
            outputTextTokens: 0,
          });
          review(index, answer, option.signal);
          const next = nextTurnIndex(index, option.signal);
          timerRef.current = window.setTimeout(() => {
            if (next === "close") closeRoom();
            else runTurn(next);
          }, 1600);
        }, option.text);
      }, 1500);
    };

    runTurn(0);
  }

  function bargeIn() {
    clearTimers();
    const dc = dataChannelRef.current;
    if (dc?.readyState === "open" && responseInFlightRef.current) {
      dc.send(JSON.stringify({ type: "response.cancel" }));
      appendEvent("turn_guard.intentional_barge_in", activeResponseIdRef.current);
      void postBackendTelemetry("turn_guard.intentional_barge_in", {
        active_response_id: activeResponseIdRef.current,
        pending_instruction: pendingAiQuestionRef.current.slice(0, 500),
      });
      responseInFlightRef.current = false;
      activeResponseIdRef.current = "";
      spokenQuestionCompleteRef.current = false;
      setTurnGuardStatus("warning");
      setTurnGuardMessage("Intentional barge-in cancelled AI audio; no assessment turn advanced.");
    }
    setIsRunning(false);
    setLiveTranscriptOpen(true);
    listen(turnIndex, () => review(turnIndex));
  }

  function needMoment() {
    clearTimers();
    setIsRunning(false);
    transitionPhase("listening");
    stopEnergy(0.12);
    setLiveTranscriptOpen(true);
    setLiveAnswer("Take a moment. The room will hold the question here.");
  }

  function fixLastTerm() {
    if (!committed.length) {
      setLiveTranscriptOpen(true);
      setLiveAnswer("Correction appears after an answer is committed.");
      return;
    }
    const next = [...committed];
    const last = next[next.length - 1];
    next[next.length - 1] = {
      ...last,
      answer: last.answer.replace("storage write boundary", "storage write boundary (corrected term)"),
    };
    setCommitted(next);
    setLiveTranscriptOpen(true);
    setLiveAnswer(next[next.length - 1].answer);
  }

  function closeRoom() {
    clearTimers();
    setIsRunning(false);
    transitionPhase("closing");
    stopEnergy(0.2);
    setLiveTranscriptOpen(false);
    timerRef.current = window.setTimeout(() => setShowClosing(true), 700);
  }

  function resetPreview() {
    clearTimers();
    setIsRunning(false);
    transitionPhase("ready");
    setTurnIndex(0);
    setLiveAnswer("");
    setCommitted([]);
    setLiveTranscriptOpen(false);
    setFullTranscriptOpen(false);
    setHistoryOpen(true);
    setShowClosing(false);
    resetUsage();
    stopEnergy(0.16);
  }

  return (
    <main
      className="lk-room"
      data-phase={phase}
      data-floor={floorOwner}
      style={
        {
          "--energy": energy.toFixed(3),
          "--center-glow": `${0.13 + energy * 0.08}`,
          "--edge-glow": `${0.14 + energy * 0.07}`,
          "--caustic-opacity": `${0.05 + energy * 0.035}`,
          "--border-glow": `${22 + energy * 36}px`,
          "--mural-a": mural.a,
          "--mural-b": mural.b,
          "--mural-c": mural.c,
        } as CSSProperties
      }
    >
      <style>{`
        .lk-room {
          min-height: 100vh;
          overflow: hidden;
          color: white;
          background:
            radial-gradient(74rem 44rem at 52% 46%, color-mix(in oklch, var(--mural-a) calc(var(--center-glow) * 100%), transparent), transparent 56%),
            radial-gradient(54rem 32rem at 52% 52%, color-mix(in oklch, var(--mural-c) 9%, transparent), transparent 62%),
            radial-gradient(44rem 30rem at 18% 8%, color-mix(in oklch, var(--mural-b) 5%, transparent), transparent 66%),
            linear-gradient(180deg, #071014, #020304 82%);
          isolation: isolate;
        }
        .lk-room::before {
          content: "";
          position: fixed;
          inset: -10%;
          z-index: 0;
          pointer-events: none;
          opacity: var(--caustic-opacity);
          mix-blend-mode: screen;
          filter: blur(10px);
          background:
            radial-gradient(42rem 24rem at 50% 46%, color-mix(in oklch, var(--mural-a) 48%, transparent), transparent 66%),
            repeating-linear-gradient(38deg, transparent 0 56px, color-mix(in oklch, var(--mural-c) 9%, transparent) 64px 69px, transparent 82px 142px, color-mix(in oklch, var(--mural-a) 7%, transparent) 154px 160px, transparent 176px 252px);
          mask-image:
            radial-gradient(ellipse at 50% 46%, black 0 45%, transparent 72%),
            linear-gradient(38deg, transparent 0 18%, black 30% 70%, transparent 86%);
          animation: lk-caustic-drift 18s ease-in-out infinite alternate;
        }
        .lk-room::after {
          content: "";
          position: fixed;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          opacity: 0.08;
          background:
            radial-gradient(circle at 50% 44%, transparent 0 42%, rgba(0,0,0,0.18) 72%, rgba(0,0,0,0.76) 100%),
            radial-gradient(circle, rgba(255,255,255,0.15) 0 1px, transparent 1.5px);
          background-size: auto, 30px 30px;
          mask-image: linear-gradient(180deg, black 0 72%, transparent 100%);
        }
        .lk-shell {
          position: relative;
          z-index: 3;
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          gap: 14px;
          width: min(1480px, calc(100vw - 32px));
          height: 100vh;
          margin: 0 auto;
          padding: 18px 0;
        }
        .lk-glass {
          position: relative;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.1);
          background:
            linear-gradient(180deg, rgba(255,255,255,0.048), transparent 58%),
            rgba(4, 8, 10, 0.72);
          box-shadow:
            0 24px 80px rgba(0,0,0,0.34),
            0 0 var(--border-glow) color-mix(in oklch, var(--mural-a) 5%, transparent),
            inset 0 0 0 1px rgba(255,255,255,0.035);
          backdrop-filter: blur(22px) saturate(1.12);
        }
        .lk-glass::before {
          content: "";
          position: absolute;
          inset: -2px;
          z-index: 0;
          pointer-events: none;
          border-radius: inherit;
          opacity: 0.52;
          background:
            radial-gradient(44rem 18rem at 50% -8%, color-mix(in oklch, var(--mural-a) 10%, transparent), transparent 70%),
            radial-gradient(28rem 18rem at -4% 54%, color-mix(in oklch, var(--mural-c) 5%, transparent), transparent 74%),
            radial-gradient(28rem 18rem at 104% 54%, color-mix(in oklch, var(--mural-a) 5%, transparent), transparent 74%);
        }
        .lk-glass > * {
          position: relative;
          z-index: 1;
        }
        .lk-topbar {
          display: flex;
          min-height: 72px;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          border-radius: 26px;
          padding: 15px 18px;
        }
        .lk-brand {
          display: flex;
          min-width: 0;
          align-items: center;
          gap: 14px;
        }
        .lk-mark {
          display: grid;
          height: 40px;
          width: 40px;
          place-items: center;
          border-radius: 14px;
          background: radial-gradient(circle at 30% 24%, color-mix(in oklch, var(--mural-a) 82%, white 8%), #071014 72%);
          box-shadow: 0 0 30px color-mix(in oklch, var(--mural-a) 28%, transparent);
        }
        .lk-mark::after {
          content: "";
          height: 16px;
          width: 16px;
          border: 2px solid white;
          border-left-color: transparent;
          border-radius: 999px;
          transform: rotate(-35deg);
        }
        .lk-eyebrow {
          margin: 0;
          color: color-mix(in oklch, var(--mural-a) 62%, white 10%);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.24em;
          text-transform: uppercase;
        }
        .lk-title {
          margin: 4px 0 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 21px;
          font-weight: 680;
          letter-spacing: 0;
        }
        .lk-chips {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: 8px;
        }
        .lk-chip {
          display: inline-flex;
          min-height: 34px;
          align-items: center;
          gap: 8px;
          border: 1px solid rgba(255,255,255,0.09);
          border-radius: 999px;
          padding: 7px 11px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.68);
          font-size: 12px;
        }
        .lk-dot {
          height: 8px;
          width: 8px;
          border-radius: 999px;
          background: color-mix(in oklch, var(--mural-a) 80%, white 8%);
          box-shadow: 0 0 18px color-mix(in oklch, var(--mural-a) 70%, transparent);
        }
        .lk-workspace {
          display: grid;
          min-height: 0;
          grid-template-columns: minmax(250px, 310px) minmax(0, 1fr) minmax(280px, 330px);
          align-items: stretch;
          gap: 14px;
          transition: grid-template-columns 260ms ease;
        }
        .lk-workspace.history-collapsed {
          grid-template-columns: minmax(250px, 310px) minmax(0, 1fr) 58px;
        }
        .lk-presence,
        .lk-stage,
        .lk-memory {
          min-height: 0;
          border-radius: 30px;
        }
        .lk-presence {
          display: grid;
          grid-template-rows: auto 1fr auto;
          gap: 14px;
          padding: 18px;
          transition: border-color 180ms ease, box-shadow 180ms ease, opacity 180ms ease;
        }
        .lk-room[data-floor="candidate"] .lk-presence {
          opacity: 0.78;
        }
        .lk-room[data-floor="ai"] .lk-presence {
          border-color: color-mix(in oklch, var(--mural-a) 20%, rgba(255,255,255,0.08));
          box-shadow: 0 0 28px color-mix(in oklch, var(--mural-a) 8%, transparent);
        }
        .lk-label {
          margin: 0;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.22em;
          text-transform: uppercase;
        }
        .lk-state-title {
          margin: 7px 0 0;
          font-size: clamp(26px, 2.2vw, 32px);
          font-weight: 720;
          letter-spacing: 0;
          line-height: 1.08;
        }
        .lk-aura-wrap {
          position: relative;
          display: grid;
          min-height: 322px;
          place-items: center;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 26px;
          background: rgba(0,0,0,0.28);
        }
        .lk-aura-wrap::before {
          content: none;
        }
        .lk-aura-caption {
          position: absolute;
          right: 14px;
          bottom: 14px;
          left: 14px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 18px;
          padding: 12px;
          background: rgba(0,0,0,0.36);
          color: rgba(255,255,255,0.66);
          font-size: 13px;
          line-height: 1.45;
        }
        .lk-meter {
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 22px;
          padding: 14px;
          background: rgba(255,255,255,0.04);
        }
        .lk-meter-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          color: rgba(255,255,255,0.44);
          font-size: 10px;
          font-weight: 820;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .lk-meter-bar {
          height: 8px;
          margin-top: 13px;
          overflow: hidden;
          border-radius: 999px;
          background: rgba(255,255,255,0.09);
        }
        .lk-meter-fill {
          height: 100%;
          width: calc(var(--energy) * 100%);
          border-radius: inherit;
          background: linear-gradient(90deg, var(--mural-a), var(--mural-c), var(--mural-b));
          transition: width 180ms ease;
        }
        .lk-provider-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }
        .lk-switch,
        .lk-select {
          min-height: 34px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 13px;
          background: rgba(0,0,0,0.26);
          color: rgba(255,255,255,0.72);
          font-size: 11px;
        }
        .lk-switch {
          display: flex;
          align-items: center;
          gap: 7px;
          padding: 7px 9px;
        }
        .lk-switch input {
          accent-color: color-mix(in oklch, var(--mural-a) 82%, white 8%);
        }
        .lk-select {
          grid-column: span 2;
          padding: 7px 9px;
          outline: none;
        }
        .lk-select.compact {
          grid-column: span 1;
        }
        .lk-stage {
          position: relative;
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          align-self: stretch;
          overflow: hidden;
          box-shadow:
            0 0 calc(28px + var(--energy) * 18px) color-mix(in oklch, var(--mural-a) 12%, transparent),
            inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 10%, transparent);
        }
        .lk-room:not([data-phase="ready"]) .lk-stage {
          animation: lk-stage-edge-sync 2.7s ease-in-out infinite;
        }
        .lk-stage::before {
          content: "";
          position: absolute;
          inset: -20px;
          z-index: 0;
          pointer-events: none;
          opacity: calc(0.18 + var(--energy) * 0.08);
          background:
            radial-gradient(56rem 18rem at 50% 0%, color-mix(in oklch, var(--mural-a) 18%, transparent), transparent 68%),
            radial-gradient(50rem 18rem at 50% 100%, color-mix(in oklch, var(--mural-c) 13%, transparent), transparent 72%),
            radial-gradient(16rem 40rem at 0% 48%, color-mix(in oklch, var(--mural-a) 12%, transparent), transparent 70%),
            radial-gradient(16rem 40rem at 100% 48%, color-mix(in oklch, var(--mural-c) 10%, transparent), transparent 70%);
          filter: blur(18px);
          animation: lk-stage-ripple 2.9s ease-in-out infinite;
        }
        .lk-stage::after {
          content: "";
          position: absolute;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          border-radius: inherit;
          box-shadow:
            inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 16%, transparent),
            inset 0 0 44px color-mix(in oklch, var(--mural-a) 6%, transparent),
            0 0 34px color-mix(in oklch, var(--mural-a) 8%, transparent);
        }
        .lk-stage > * {
          position: relative;
          z-index: 1;
        }
        .lk-stage-top {
          display: grid;
          grid-template-columns: 1fr;
          align-items: stretch;
          gap: 7px;
          border-bottom: 1px solid rgba(255,255,255,0.09);
          padding: 10px 22px 10px;
        }
        .lk-turn-summary {
          display: grid;
          justify-items: center;
          min-height: 6px;
        }
        .lk-stage-status {
          margin: 0;
          color: rgba(255,255,255,0.56);
          font-size: 13px;
          line-height: 1.2;
        }
        .lk-floorline {
          grid-column: 1 / -1;
          display: grid;
          grid-template-columns: minmax(108px, 148px) minmax(28px, 1fr) auto minmax(28px, 1fr) minmax(108px, 148px);
          align-items: center;
          gap: 10px;
          width: min(860px, 100%);
          margin: 6px auto 0;
        }
        .lk-floor-endpoint {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          width: 100%;
          min-height: 26px;
          border: 1px solid transparent;
          border-radius: 999px;
          padding: 4px 9px;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          white-space: nowrap;
          transition: color 180ms ease, border-color 180ms ease, background 180ms ease, box-shadow 180ms ease, opacity 180ms ease;
        }
        .lk-corner-short {
          display: none;
        }
        .lk-floor-endpoint::before {
          content: "";
          height: 8px;
          width: 8px;
          border-radius: 999px;
          background: rgba(255,255,255,0.22);
          transition: background 180ms ease, box-shadow 180ms ease;
        }
        .lk-floor-endpoint.ai::before {
          background: rgba(255,154,61,0.34);
        }
        .lk-floor-endpoint.candidate::before {
          background: rgba(42,208,245,0.34);
        }
        .lk-room[data-floor="ai"] .lk-floor-endpoint.ai {
          color: rgba(255,255,255,0.82);
          border-color: rgba(255,154,61,0.28);
          background: rgba(255,154,61,0.075);
          box-shadow: 0 0 22px rgba(255,154,61,0.16);
        }
        .lk-room[data-floor="candidate"] .lk-floor-endpoint.candidate {
          color: rgba(255,255,255,0.82);
          border-color: rgba(42,208,245,0.28);
          background: rgba(42,208,245,0.07);
          box-shadow: 0 0 22px rgba(42,208,245,0.16);
        }
        .lk-room[data-floor="ai"] .lk-floor-endpoint.ai::before {
          background: rgba(255,154,61,0.94);
          box-shadow: 0 0 18px rgba(255,154,61,0.72);
        }
        .lk-room[data-floor="candidate"] .lk-floor-endpoint.candidate::before {
          background: rgba(42,208,245,0.94);
          box-shadow: 0 0 18px rgba(42,208,245,0.74);
        }
        .lk-floor-track {
          height: 3px;
          border-radius: 999px;
          background: rgba(255,255,255,0.09);
          overflow: hidden;
        }
        .lk-floor-track::before {
          content: "";
          display: block;
          height: 100%;
          width: 100%;
          border-radius: inherit;
          transform: scaleX(0);
          transition: transform 260ms cubic-bezier(.2,.8,.2,1);
        }
        .lk-floor-track.ai::before {
          background: linear-gradient(90deg, rgba(255,154,61,0.12), rgba(255,154,61,0.95));
          box-shadow: 0 0 16px rgba(255,154,61,0.58);
        }
        .lk-floor-track.candidate::before {
          background: linear-gradient(90deg, rgba(42,208,245,0.95), rgba(42,208,245,0.12));
          box-shadow: 0 0 16px rgba(42,208,245,0.6);
        }
        .lk-floor-track.ai::before {
          transform-origin: right;
        }
        .lk-floor-track.candidate::before {
          transform-origin: left;
        }
        .lk-room[data-floor="ai"] .lk-floor-track.ai::before,
        .lk-room[data-floor="candidate"] .lk-floor-track.candidate::before {
          transform: scaleX(1);
        }
        .lk-floor-pill {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 26px;
          min-width: 68px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 5px 10px;
          background: rgba(0,0,0,0.36);
          color: rgba(255,255,255,0.72);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          white-space: nowrap;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .lk-floor-center {
          display: flex;
          align-items: center;
          justify-content: center;
          min-width: 68px;
        }
        .lk-room[data-floor="ai"] .lk-floor-pill,
        .lk-room[data-floor="candidate"] .lk-floor-pill {
          border-color: rgba(255,255,255,0.15);
          color: rgba(255,255,255,0.88);
        }
        .lk-activity-box {
          display: inline-flex;
          width: fit-content;
          max-width: 100%;
          min-height: 34px;
          align-items: center;
          justify-self: center;
          gap: 10px;
          margin-top: 10px;
          border: 1px solid color-mix(in oklch, var(--mural-a) 20%, rgba(255,255,255,0.08));
          border-radius: 999px;
          padding: 7px 14px;
          background: rgba(0,0,0,0.32);
          color: rgba(255,255,255,0.76);
          font-size: 16px;
          font-weight: 800;
          line-height: 1.2;
          box-shadow: 0 0 22px color-mix(in oklch, var(--mural-a) 8%, transparent);
        }
        .lk-turn-counter {
          margin: 8px 0 0;
          color: rgba(255,255,255,0.48);
          font-size: 11px;
          font-weight: 820;
          letter-spacing: 0.16em;
          text-align: center;
          text-transform: uppercase;
        }
        .lk-progress {
          display: flex;
          flex-shrink: 0;
          align-items: center;
          justify-content: center;
          gap: 4px;
          width: min(560px, 100%);
          min-width: 0;
        }
        .lk-progress span {
          flex: 1 1 10px;
          height: 4px;
          min-width: 8px;
          max-width: 24px;
          border-radius: 999px;
          background: rgba(255,255,255,0.11);
        }
        .lk-progress span.done {
          background: color-mix(in oklch, var(--mural-a) 72%, white 8%);
          box-shadow: 0 0 18px color-mix(in oklch, var(--mural-a) 28%, transparent);
        }
        .lk-room[data-phase="asking"] .lk-memory,
        .lk-room[data-phase="asking"] .lk-answer-panel {
          opacity: 0.72;
        }
        .lk-stage-body {
          display: grid;
          grid-template-rows: auto auto auto;
          align-content: start;
          gap: 12px;
          min-height: 0;
          overflow: hidden;
          padding: clamp(8px, 1.1vw, 12px) clamp(20px, 3vw, 34px) 16px;
        }
        .lk-question-card {
          position: relative;
          display: flex;
          flex-direction: column;
          justify-content: center;
          height: clamp(156px, 20vh, 196px);
          align-items: stretch;
          overflow: hidden;
          border: 1px solid color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.08));
          border-radius: 28px;
          padding: clamp(14px, 1.8vw, 22px) clamp(18px, 2.6vw, 34px);
          background: #020304;
          box-shadow:
            inset 0 0 0 1px rgba(255,255,255,0.03),
            inset 0 0 28px rgba(255,255,255,0.018);
          backdrop-filter: none;
        }
        .lk-question-card.question-medium {
          height: clamp(168px, 21.5vh, 210px);
        }
        .lk-question-card.question-compact {
          height: clamp(184px, 23.5vh, 230px);
        }
        .lk-question-card.question-dense {
          height: clamp(198px, 25.5vh, 250px);
        }
        .lk-question-card.focus-question {
          animation: lk-question-focus 960ms ease-out both;
          border-color: color-mix(in oklch, var(--mural-a) 42%, rgba(255,255,255,0.18));
        }
        .lk-question-card.sync-glow {
          border-color: color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.1));
        }
        .lk-question-card.focus-question.sync-glow {
          animation: lk-question-focus 760ms ease-out both;
        }
        .lk-question-card.focus-question .lk-question {
          animation: lk-question-settle 700ms cubic-bezier(.2,.8,.2,1) both;
        }
        .lk-question-card::before {
          content: none;
        }
        .lk-question-card::after {
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          border-radius: inherit;
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.08),
            inset 0 -1px 0 rgba(255,255,255,0.04);
        }
        .lk-question-label {
          position: absolute;
          top: clamp(12px, 1.5vw, 18px);
          left: clamp(18px, 2.6vw, 34px);
          z-index: 1;
          margin: 0;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.18em;
          line-height: 1;
          text-transform: uppercase;
        }
        .lk-question {
          position: relative;
          z-index: 1;
          width: 100%;
          max-width: 1040px;
          margin: 32px 0 0;
          font-size: clamp(34px, 3.12vw, 48px);
          font-weight: 750;
          letter-spacing: 0;
          line-height: 1.04;
        }
        .lk-question-ink {
          padding: 0;
          background: transparent;
          box-shadow: none;
          text-shadow: 0 2px 18px rgba(0,0,0,0.64);
        }
        .lk-workspace.history-collapsed .lk-question {
          max-width: 1140px;
          font-size: clamp(35px, 3.32vw, 50px);
        }
        .lk-workspace.history-collapsed .lk-question.medium {
          font-size: clamp(31px, 3.02vw, 45px);
        }
        .lk-workspace.history-collapsed .lk-question.compact {
          font-size: clamp(27px, 2.62vw, 39px);
        }
        .lk-workspace.history-collapsed .lk-question.dense {
          font-size: clamp(23px, 2.24vw, 34px);
        }
        .lk-question.medium {
          font-size: clamp(29px, 2.54vw, 39px);
          line-height: 1.05;
        }
        .lk-question.compact {
          font-size: clamp(25px, 2.14vw, 33px);
          line-height: 1.06;
        }
        .lk-question.dense {
          font-size: clamp(22px, 1.9vw, 30px);
          line-height: 1.08;
        }
        .lk-answer-panel {
          overflow: hidden;
          max-height: 72px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 22px;
          background:
            linear-gradient(180deg, rgba(255,255,255,0.04), transparent 64%),
            rgba(0,0,0,0.2);
          opacity: 1;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
          transition: max-height 280ms ease, border-color 180ms ease, background 180ms ease;
        }
        .lk-room[data-floor="candidate"] .lk-answer-panel {
          border-color: color-mix(in oklch, var(--mural-a) 34%, rgba(255,255,255,0.08));
          background:
            linear-gradient(180deg, color-mix(in oklch, var(--mural-a) 5%, transparent), transparent 68%),
            rgba(0,0,0,0.24);
          box-shadow:
            0 0 24px color-mix(in oklch, var(--mural-a) 10%, transparent),
            inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .lk-answer-panel.open {
          min-height: 178px;
          max-height: 246px;
          border-color: color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.08));
        }
        .lk-answer-inner {
          padding: 12px 16px;
        }
        .lk-answer-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px;
        }
        .lk-answer-toggle {
          flex-shrink: 0;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 6px 10px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.62);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          cursor: pointer;
        }
        .lk-answer-text {
          display: -webkit-box;
          max-height: 7.1em;
          margin: 9px 0 0;
          overflow: hidden;
          color: rgba(255,255,255,0.72);
          font-size: clamp(14px, 1.25vw, 17px);
          line-height: 1.42;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 1;
        }
        .lk-answer-panel.open .lk-answer-text {
          overflow: auto;
          -webkit-line-clamp: 5;
        }
        .lk-answer-text.live {
          color: rgba(255,255,255,0.6);
        }
        .lk-transcript-sources {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 7px;
          margin-top: 10px;
          color: rgba(255,255,255,0.4);
          font-size: 11px;
          line-height: 1.35;
        }
        .lk-transcript-sources span {
          min-height: 38px;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 12px;
          padding: 7px 8px;
          background: rgba(255,255,255,0.035);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: normal;
          display: -webkit-box;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
        }
        .lk-caret {
          display: inline-block;
          height: 1em;
          width: 0.42em;
          margin-left: 3px;
          transform: translateY(0.16em);
          border-radius: 2px;
          background: color-mix(in oklch, var(--mural-a) 82%, white 8%);
          animation: lk-blink 850ms step-end infinite;
        }
        .lk-review {
          display: none;
          border: 1px solid color-mix(in oklch, var(--mural-b) 18%, transparent);
          border-radius: 24px;
          padding: 18px 20px;
          background: rgba(255,255,255,0.04);
          color: rgba(255,255,255,0.72);
          font-size: 18px;
          line-height: 1.55;
        }
        .lk-review.open {
          display: block;
        }
        .lk-actions,
        .lk-dock {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
          justify-content: center;
          border-top: 1px solid rgba(255,255,255,0.09);
          padding: 12px 18px;
        }
        .lk-btn {
          min-height: 42px;
          border: 1px solid rgba(255,255,255,0.11);
          border-radius: 15px;
          padding: 10px 14px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.78);
          cursor: pointer;
          transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
        }
        .lk-btn:hover {
          transform: translateY(-1px);
          border-color: color-mix(in oklch, var(--mural-a) 36%, white 6%);
          background: rgba(255,255,255,0.075);
        }
        .lk-btn.primary {
          border-color: color-mix(in oklch, var(--mural-a) 36%, transparent);
          background: color-mix(in oklch, var(--mural-a) 13%, rgba(255,255,255,0.05));
          color: white;
        }
        .lk-btn.danger {
          border-color: rgba(255,95,127,0.26);
          color: rgba(255,180,190,0.9);
        }
        .lk-memory {
          position: relative;
          display: grid;
          grid-auto-rows: max-content;
          gap: 12px;
          min-height: clamp(420px, calc(100vh - 220px), 640px);
          overflow: auto;
          padding: 18px;
          transition: padding 220ms ease;
        }
        .lk-memory.collapsed {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 10px;
        }
        .lk-memory.collapsed .lk-memory-content {
          display: none;
        }
        .lk-memory.collapsed .lk-candidate-camera {
          display: none;
        }
        .lk-memory.collapsed .lk-answer-map {
          display: none;
        }
        .lk-memory.collapsed .lk-voice-diagnostics,
        .lk-memory.collapsed .lk-cost-panel {
          display: none;
        }
        .lk-memory.collapsed .lk-rail-toolbar {
          display: none;
        }
        .lk-rail-toolbar {
          display: flex;
          min-height: 34px;
          align-items: center;
          justify-content: flex-end;
          gap: 8px;
        }
        .lk-candidate-camera {
          position: relative;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 24px;
          background: #030506;
          box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
          transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
        }
        .lk-room[data-floor="candidate"] .lk-candidate-camera {
          border-color: color-mix(in oklch, var(--mural-a) 40%, rgba(255,255,255,0.1));
          box-shadow:
            0 0 28px color-mix(in oklch, var(--mural-a) 16%, transparent),
            inset 0 0 0 1px rgba(255,255,255,0.04);
        }
        .lk-camera-frame {
          position: relative;
          display: grid;
          aspect-ratio: 16 / 9;
          min-height: 150px;
          place-items: center;
          overflow: hidden;
          border-bottom: 1px solid rgba(255,255,255,0.07);
          background:
            radial-gradient(14rem 9rem at 50% 38%, color-mix(in oklch, var(--mural-a) 14%, transparent), transparent 62%),
            linear-gradient(135deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012)),
            #030506;
        }
        .lk-camera-frame::before {
          content: "";
          position: absolute;
          inset: 0;
          opacity: 0.16;
          background:
            linear-gradient(120deg, transparent 0 44%, rgba(255,255,255,0.18) 50%, transparent 58%),
            radial-gradient(circle at 50% 48%, transparent 0 45%, rgba(0,0,0,0.62) 78%);
        }
        .lk-camera-video {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          opacity: 0;
          transition: opacity 180ms ease;
        }
        .lk-candidate-camera.camera-on:not(.stream-hidden) .lk-camera-video {
          opacity: 1;
        }
        .lk-camera-avatar {
          position: relative;
          z-index: 1;
          display: grid;
          height: 74px;
          width: 74px;
          place-items: center;
          border: 1px solid color-mix(in oklch, var(--mural-a) 32%, rgba(255,255,255,0.12));
          border-radius: 24px;
          background: rgba(0,0,0,0.45);
          color: rgba(255,255,255,0.88);
          font-size: 20px;
          font-weight: 800;
          letter-spacing: 0.08em;
          box-shadow: 0 0 28px color-mix(in oklch, var(--mural-a) 14%, transparent);
        }
        .lk-candidate-camera.camera-on:not(.stream-hidden) .lk-camera-avatar {
          opacity: 0;
        }
        .lk-candidate-camera.stream-hidden .lk-camera-frame::after {
          content: "Camera preview hidden";
          position: absolute;
          right: 12px;
          bottom: 12px;
          z-index: 2;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 5px 8px;
          background: rgba(0,0,0,0.5);
          color: rgba(255,255,255,0.58);
          font-size: 10px;
          font-weight: 760;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        .lk-camera-meta {
          display: grid;
          gap: 10px;
          padding: 12px;
        }
        .lk-camera-status {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          color: rgba(255,255,255,0.62);
          font-size: 12px;
          line-height: 1.4;
        }
        .lk-camera-status strong {
          color: rgba(255,255,255,0.86);
        }
        .lk-camera-action {
          min-height: 34px;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 12px;
          background: rgba(255,255,255,0.052);
          color: rgba(255,255,255,0.74);
          cursor: pointer;
        }
        .lk-camera-error {
          margin: 0;
          color: rgba(255,190,196,0.72);
          font-size: 11px;
          line-height: 1.4;
        }
        .lk-answer-map {
          display: grid;
          gap: 11px;
          margin: 0 16px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 13px;
          background: rgba(0,0,0,0.22);
        }
        .lk-script-card {
          display: grid;
          gap: 10px;
          margin: 0 16px;
          border: 1px solid color-mix(in oklch, var(--mural-a) 16%, rgba(255,255,255,0.08));
          border-radius: 20px;
          padding: 13px;
          background:
            linear-gradient(180deg, color-mix(in oklch, var(--mural-a) 5%, transparent), transparent 70%),
            rgba(0,0,0,0.24);
        }
        .lk-script-card p {
          margin: 0;
        }
        .lk-script-text {
          display: -webkit-box;
          overflow: auto;
          max-height: 142px;
          color: rgba(255,255,255,0.72);
          font-size: 13px;
          line-height: 1.48;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 6;
        }
        .lk-script-actions {
          display: flex;
          gap: 8px;
        }
        .lk-script-actions .lk-btn {
          flex: 1;
          min-height: 36px;
          padding: 8px 10px;
          font-size: 12px;
        }
        .lk-answer-options {
          display: grid;
          gap: 8px;
          max-height: 260px;
          overflow: auto;
        }
        .lk-answer-options article {
          display: grid;
          gap: 7px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 14px;
          padding: 10px;
          background: rgba(255,255,255,0.035);
        }
        .lk-answer-options article.selected {
          border-color: color-mix(in oklch, var(--mural-a) 34%, rgba(255,255,255,0.1));
          box-shadow: 0 0 18px color-mix(in oklch, var(--mural-a) 9%, transparent);
        }
        .lk-answer-options small {
          display: block;
          color: color-mix(in oklch, var(--mural-a) 62%, white 8%);
          font-size: 10px;
          text-transform: uppercase;
        }
        .lk-answer-options strong {
          color: rgba(255,255,255,0.82);
          font-size: 12px;
        }
        .lk-answer-options p {
          margin: 0;
          color: rgba(255,255,255,0.58);
          font-size: 12px;
          line-height: 1.45;
        }
        .lk-answer-map-btn {
          justify-self: start;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          padding: 6px 9px;
          background: rgba(255,255,255,0.045);
          color: rgba(255,255,255,0.72);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          cursor: pointer;
        }
        .lk-voice-diagnostics {
          display: grid;
          gap: 11px;
          margin: 0 16px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 13px;
          background: rgba(0,0,0,0.22);
        }
        .lk-status-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px;
        }
        .lk-status-grid span {
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 999px;
          padding: 6px 8px;
          color: rgba(255,255,255,0.48);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        .lk-status-grid span.active {
          border-color: color-mix(in oklch, var(--mural-a) 28%, rgba(255,255,255,0.08));
          color: rgba(255,255,255,0.86);
          box-shadow: 0 0 16px color-mix(in oklch, var(--mural-a) 10%, transparent);
        }
        .lk-event-log {
          display: grid;
          max-height: 144px;
          gap: 7px;
          overflow: auto;
          padding-right: 3px;
        }
        .lk-provider-lines {
          display: grid;
          gap: 6px;
          color: rgba(255,255,255,0.48);
          font-size: 11px;
          line-height: 1.35;
        }
        .lk-provider-lines span {
          overflow-wrap: anywhere;
        }
        .lk-diagnostic-actions {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }
        .lk-diagnostic-actions .lk-btn {
          width: 100%;
          min-height: 36px;
          padding: 8px 10px;
          font-size: 12px;
        }
        .lk-event-log > p,
        .lk-event-log article {
          margin: 0;
          border-top: 1px solid rgba(255,255,255,0.07);
          padding-top: 7px;
          color: rgba(255,255,255,0.46);
          font-size: 11px;
          line-height: 1.35;
        }
        .lk-event-log small {
          display: block;
          color: color-mix(in oklch, var(--mural-a) 58%, white 8%);
          font-size: 10px;
        }
        .lk-event-log p {
          margin: 3px 0 0;
          overflow-wrap: anywhere;
        }
        .lk-cost-panel {
          display: grid;
          gap: 11px;
          margin: 0 16px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 13px;
          background:
            linear-gradient(180deg, color-mix(in oklch, var(--mural-a) 5%, transparent), transparent),
            rgba(0,0,0,0.26);
        }
        .lk-cost-head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
        }
        .lk-cost-head strong {
          color: color-mix(in oklch, var(--mural-a) 72%, white 18%);
          font-size: 22px;
          letter-spacing: 0;
          white-space: nowrap;
        }
        .lk-cost-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px;
        }
        .lk-cost-grid span {
          display: flex;
          min-height: 32px;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 12px;
          padding: 6px 8px;
          color: rgba(255,255,255,0.5);
          font-size: 11px;
        }
        .lk-cost-grid strong {
          color: rgba(255,255,255,0.88);
          font-size: 12px;
        }
        .lk-cost-note {
          display: grid;
          gap: 5px;
          color: rgba(255,255,255,0.42);
          font-size: 11px;
          line-height: 1.4;
        }
        .lk-cost-note p {
          margin: 0;
        }
        .lk-usage-turns {
          display: grid;
          max-height: 154px;
          gap: 7px;
          overflow: auto;
        }
        .lk-usage-turns > p,
        .lk-usage-turns article {
          margin: 0;
          border-top: 1px solid rgba(255,255,255,0.07);
          padding-top: 7px;
          color: rgba(255,255,255,0.48);
          font-size: 11px;
          line-height: 1.35;
        }
        .lk-usage-turns small {
          display: block;
          color: color-mix(in oklch, var(--mural-a) 62%, white 8%);
          font-size: 10px;
        }
        .lk-usage-turns p {
          margin: 3px 0 0;
        }
        .lk-usage-turns em {
          display: inline-block;
          margin-top: 4px;
          color: rgba(108,255,158,0.72);
          font-size: 10px;
          font-style: normal;
          text-transform: uppercase;
        }
        .lk-backend-panel {
          display: grid;
          gap: 11px;
          margin: 0 16px;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 13px;
          background:
            linear-gradient(180deg, rgba(255,255,255,0.035), transparent 70%),
            rgba(0,0,0,0.22);
        }
        .lk-backend-head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 10px;
        }
        .lk-backend-head .lk-btn {
          min-height: 34px;
          padding: 7px 10px;
          font-size: 12px;
          white-space: nowrap;
        }
        .lk-backend-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px;
        }
        .lk-backend-grid span {
          display: flex;
          min-height: 32px;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 12px;
          padding: 6px 8px;
          color: rgba(255,255,255,0.5);
          font-size: 11px;
        }
        .lk-backend-grid strong {
          color: rgba(255,255,255,0.88);
          font-size: 12px;
        }
        .lk-backend-path,
        .lk-backend-explain {
          margin: 0;
          color: rgba(255,255,255,0.42);
          font-size: 11px;
          line-height: 1.42;
          overflow-wrap: anywhere;
        }
        .lk-backend-issues {
          display: grid;
          gap: 7px;
          max-height: 132px;
          overflow: auto;
        }
        .lk-backend-issues article,
        .lk-backend-issues > p {
          margin: 0;
          border-top: 1px solid rgba(255,255,255,0.07);
          padding-top: 7px;
          color: rgba(255,255,255,0.48);
          font-size: 11px;
          line-height: 1.35;
        }
        .lk-backend-issues small {
          display: block;
          color: color-mix(in oklch, var(--mural-a) 62%, white 8%);
          font-size: 10px;
        }
        .lk-memory-content {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr) auto;
          gap: 12px;
          height: 100%;
          min-height: 0;
        }
        .lk-history-toggle {
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 999px;
          background: rgba(255,255,255,0.055);
          color: rgba(255,255,255,0.66);
          cursor: pointer;
        }
        .lk-history-toggle.expanded {
          min-height: 34px;
          padding: 7px 11px;
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        .lk-history-toggle.collapsed {
          display: grid;
          width: 38px;
          height: 78%;
          min-height: 220px;
          place-items: center;
          padding: 10px 0;
          writing-mode: vertical-rl;
          text-orientation: mixed;
          font-size: 10px;
          font-weight: 850;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .lk-memory-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
          min-height: 0;
          overflow: auto;
          padding-right: 3px;
          scrollbar-gutter: stable;
        }
        .lk-memory-list.full {
          padding-bottom: 4px;
        }
        .lk-memory .lk-btn {
          width: 100%;
          justify-content: center;
          text-align: center;
        }
        .lk-turn-card {
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 14px;
          background: rgba(255,255,255,0.04);
        }
        .lk-memory-list.full .lk-turn-card {
          padding: 12px;
        }
        .lk-memory-list:not(.full) .lk-turn-card {
          padding: 10px 12px;
        }
        .lk-memory-list:not(.full) .lk-turn-card:not(.current) {
          opacity: 0.74;
        }
        .lk-memory-list:not(.full) .lk-turn-card p {
          display: -webkit-box;
          overflow: hidden;
          -webkit-box-orient: vertical;
          -webkit-line-clamp: 2;
        }
        .lk-memory-list:not(.full) .lk-turn-card.current p {
          -webkit-line-clamp: 4;
        }
        .lk-turn-card.current {
          border-color: color-mix(in oklch, var(--mural-a) 26%, transparent);
          background: color-mix(in oklch, var(--mural-a) 7%, rgba(255,255,255,0.035));
        }
        .lk-turn-card small {
          display: block;
          margin-bottom: 7px;
          color: rgba(255,255,255,0.42);
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .lk-turn-card p {
          margin: 0;
          color: rgba(255,255,255,0.66);
          font-size: 13px;
          line-height: 1.5;
        }
        .lk-dock {
          align-items: center;
          justify-content: space-between;
          min-height: 70px;
          border-radius: 26px;
          border-top: 1px solid rgba(255,255,255,0.1);
        }
        .lk-dock-group {
          display: flex;
          flex-wrap: wrap;
          gap: 9px;
        }
        .lk-note {
          color: rgba(255,255,255,0.48);
          font-size: 13px;
        }
        .lk-closing {
          position: fixed;
          inset: 0;
          z-index: 20;
          display: none;
          place-items: center;
          padding: 24px;
          background: radial-gradient(circle at 50% 44%, color-mix(in oklch, var(--mural-c) 18%, transparent), transparent 44%), rgba(0,0,0,0.58);
          backdrop-filter: blur(24px);
        }
        .lk-closing.open {
          display: grid;
        }
        .lk-closing-card {
          width: min(720px, 100%);
          border-radius: 30px;
          padding: 34px;
          text-align: center;
        }
        .lk-closing-card h2 {
          margin: 0;
          font-size: clamp(36px, 7vw, 70px);
          letter-spacing: 0;
          line-height: 1.06;
        }
        .lk-closing-card p {
          max-width: 560px;
          margin: 18px auto 0;
          color: rgba(255,255,255,0.66);
          font-size: 18px;
          line-height: 1.55;
        }
        @keyframes lk-caustic-drift {
          from { transform: translate3d(-1.4%, 1%, 0) rotate(-0.4deg) scale(1); }
          to { transform: translate3d(1.4%, -1%, 0) rotate(0.45deg) scale(1.025); }
        }
        @keyframes lk-fluid {
          from { transform: translate3d(-2%, 1%, 0) rotate(-1deg) scale(1); }
          to { transform: translate3d(2%, -1%, 0) rotate(1deg) scale(1.04); }
        }
        @keyframes lk-stage-edge-sync {
          0%, 100% {
            box-shadow:
              0 0 calc(26px + var(--energy) * 18px) color-mix(in oklch, var(--mural-a) 12%, transparent),
              0 0 calc(12px + var(--energy) * 12px) color-mix(in oklch, var(--mural-c) 8%, transparent),
              inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 10%, transparent),
              inset 0 0 42px color-mix(in oklch, var(--mural-a) 5%, transparent);
          }
          48% {
            box-shadow:
              0 0 calc(52px + var(--energy) * 28px) color-mix(in oklch, var(--mural-a) 24%, transparent),
              0 0 calc(22px + var(--energy) * 16px) color-mix(in oklch, var(--mural-c) 14%, transparent),
              inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 20%, transparent),
              inset 0 0 58px color-mix(in oklch, var(--mural-a) 8%, transparent);
          }
        }
        @keyframes lk-stage-ripple {
          0%, 100% {
            opacity: calc(0.14 + var(--energy) * 0.06);
            transform: scaleX(1) translateY(0);
          }
          48% {
            opacity: calc(0.2 + var(--energy) * 0.08);
            transform: scaleX(1.012) translateY(-1px);
          }
        }
        @keyframes lk-question-focus {
          0% {
            box-shadow:
              inset 0 0 0 1px rgba(255,255,255,0.03),
              inset 0 0 38px rgba(255,255,255,0.025);
          }
          42% {
            box-shadow:
              inset 0 0 0 1px color-mix(in oklch, var(--mural-a) 18%, rgba(255,255,255,0.04)),
              inset 0 0 42px rgba(255,255,255,0.035);
          }
          100% {
            box-shadow:
              inset 0 0 0 1px rgba(255,255,255,0.03),
              inset 0 0 38px rgba(255,255,255,0.025);
          }
        }
        @keyframes lk-question-settle {
          0% { opacity: 0.72; transform: translateY(6px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes lk-blink {
          50% { opacity: 0; }
        }
        @media (max-width: 1120px) {
          .lk-room { overflow: auto; }
          .lk-shell { height: auto; min-height: 100vh; }
          .lk-workspace,
          .lk-workspace.history-collapsed { grid-template-columns: 1fr; }
          .lk-presence { grid-template-columns: minmax(220px, 320px) 1fr; grid-template-rows: auto auto; align-items: stretch; }
          .lk-presence > header { grid-column: 1 / -1; }
          .lk-aura-wrap { min-height: 260px; }
          .lk-memory { max-height: 360px; }
          .lk-memory.collapsed { max-height: 86px; min-height: 70px; display: flex; padding: 12px; }
          .lk-history-toggle.collapsed {
            width: auto;
            height: auto;
            min-height: 34px;
            padding: 7px 11px;
            writing-mode: horizontal-tb;
          }
        }
        @media (max-width: 720px) {
          .lk-shell { width: min(100% - 18px, 1480px); padding: 9px 0; }
          .lk-topbar, .lk-dock { align-items: flex-start; flex-direction: column; }
          .lk-presence { display: block; }
          .lk-aura-wrap { margin-top: 14px; }
          .lk-stage-top { flex-direction: column; }
          .lk-stage-body { padding: 20px; }
          .lk-floorline { gap: 6px; width: 100%; }
          .lk-transcript-sources { grid-template-columns: 1fr; }
          .lk-floor-endpoint {
            gap: 6px;
            padding: 5px 7px;
            font-size: 9px;
            letter-spacing: 0.1em;
          }
          .lk-corner-full { display: none; }
          .lk-corner-short { display: inline; }
          .lk-question,
          .lk-question.medium,
          .lk-question.compact,
          .lk-question.dense { font-size: clamp(23px, 8vw, 30px); }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 1ms !important;
            transition-duration: 1ms !important;
          }
        }
      `}</style>
      <audio ref={remoteAudioRef} autoPlay playsInline />

      <div className="lk-shell">
        <header className="lk-topbar lk-glass">
          <div className="lk-brand">
            <div className="lk-mark" aria-hidden="true" />
            <div>
              <p className="lk-eyebrow">Antigravity Voice Room Lab</p>
              <h1 className="lk-title">
                {CANDIDATE.name} - {CANDIDATE.role}
              </h1>
            </div>
          </div>
          <div className="lk-chips">
            <span className="lk-chip floor-chip">
              <span className="lk-dot" />
              <strong>{floorLabel}</strong>
            </span>
            <span className="lk-chip">OpenAI {status?.openai_configured ? "ready" : "not loaded"}</span>
            <span className="lk-chip">Deepgram {status?.deepgram_configured ? "ready" : "not loaded"}</span>
            <span className="lk-chip">{voiceLabRunning ? "Mic live" : "Mic idle"}</span>
          </div>
        </header>

        <section className={["lk-workspace", historyOpen ? "" : "history-collapsed"].join(" ")}>
          <aside className="lk-presence lk-glass">
            <header>
              <p className="lk-label">AI interviewer</p>
              <h2 className="lk-state-title">{mural.title}</h2>
            </header>

            <div className="lk-aura-wrap">
              <AgentAudioVisualizerAura
                size="lg"
                state={mural.auraState}
                color={mural.aura}
                colorShift={colorShift}
                themeMode="dark"
                className="relative z-10"
              />
              <p className="lk-aura-caption">{mural.caption}</p>
            </div>

            <div className="lk-meter">
              <div className="lk-meter-row">
                <span>Voice signal</span>
                <span>
                  {realtimeRunning
                    ? realtimeModel
                    : deepgramRunning
                      ? "deepgram"
                      : phase === "listening"
                        ? "live"
                        : mural.label}
                </span>
              </div>
              <div className="lk-meter-bar">
                <div className="lk-meter-fill" />
              </div>
            </div>
          </aside>

          <section className="lk-stage lk-glass">
            <div className="lk-stage-top">
              <div className="lk-turn-summary">
                <div className="lk-progress" aria-label="Interview progress">
                  {TURNS.map((_, item) => (
                    <span key={item} className={item <= turnIndex ? "done" : ""} />
                  ))}
                </div>
              </div>
              <span className="lk-activity-box" aria-live="polite">
                <span className="lk-dot" />
                <span>{activityText}</span>
              </span>
              <p className="lk-turn-counter">Turn {turnIndex + 1} of {TURNS.length}</p>
              <div className="lk-floorline" aria-label={`Floor owner: ${floorLabel}`}>
                <span className="lk-floor-endpoint ai">
                  <span className="lk-corner-full">AI corner</span>
                  <span className="lk-corner-short">AI</span>
                </span>
                <span className="lk-floor-track ai" />
                <span className="lk-floor-center">
                  <span className="lk-floor-pill">Turn</span>
                </span>
                <span className="lk-floor-track candidate" />
                <span className="lk-floor-endpoint candidate">
                  <span className="lk-corner-full">Candidate corner</span>
                  <span className="lk-corner-short">You</span>
                </span>
              </div>
            </div>

            <div className="lk-stage-body">
              <article
                ref={questionCardRef}
                key={`${turnIndex}-${displayedQuestion}`}
                className={[
                  "lk-question-card",
                  `question-${questionDensity}`,
                  phase !== "ready" ? "sync-glow" : "",
                  phase === "asking" ? "focus-question" : "",
                ].join(" ")}
              >
                <p className="lk-question-label">Interviewer's question</p>
                <h2
                  ref={questionTextRef}
                  className={["lk-question", questionDensity].join(" ")}
                  style={questionFontSize ? { fontSize: `${questionFontSize}px` } : undefined}
                >
                  <span className="lk-question-ink">{displayedQuestion}</span>
                </h2>
              </article>

              <article className={["lk-answer-panel", liveTranscriptOpen ? "open" : ""].join(" ")}>
                <div className="lk-answer-inner">
                  <div className="lk-answer-header">
                    <p className="lk-label">
                      {liveTranscriptOpen
                        ? "Candidate answer live transcription"
                        : phase === "reviewing"
                          ? "Latest answer"
                          : "Current answer"}
                    </p>
                    <button
                      className="lk-answer-toggle"
                      type="button"
                      onClick={() => setLiveTranscriptOpen((open) => !open)}
                    >
                      {liveTranscriptOpen ? "Hide live transcription" : "Show live transcription"}
                    </button>
                  </div>
                  <p className={["lk-answer-text", phase === "listening" ? "live" : ""].join(" ")}>
                    {liveAnswer || candidateVoiceText ||
                      (liveTranscriptOpen
                        ? "Live transcription will appear here while the candidate speaks."
                        : "Latest answer appears here without moving the question.")}
                    {phase === "listening" && (liveAnswer || candidateVoiceText) && <span className="lk-caret" />}
                  </p>
                  <div className="lk-transcript-sources">
                    <span>Realtime: {realtimeFinal || realtimePartial || "waiting"}</span>
                    <span>Deepgram: {deepgramFinal || deepgramPartial || "waiting"}</span>
                    <span>GPT sample: {openaiTranscribeText || "waiting"}</span>
                  </div>
                </div>
              </article>

              <article className={["lk-review", phase === "reviewing" || phase === "closing" ? "open" : ""].join(" ")}>
                {phase === "closing"
                  ? "The room is settling. The candidate leaves with a clear report-preparation state."
                  : "Answer received. Preparing the next question from what was just said."}
              </article>
            </div>

            <div className="lk-actions">
              <button className="lk-btn primary" type="button" onClick={voiceLabRunning ? stopVoiceLab : startVoiceLab}>
                {voiceLabRunning ? "Stop voice" : "Start voice room"}
              </button>
              <button className="lk-btn" type="button" onClick={bargeIn}>
                Barge-in
              </button>
              <button className="lk-btn" type="button" onClick={() => setDiagnosticsOpen((open) => !open)}>
                {diagnosticsOpen ? "Hide diagnostics" : "Diagnostics"}
              </button>
              <button className="lk-btn danger" type="button" onClick={closeRoom}>
                Close
              </button>
            </div>
          </section>

          <aside className={["lk-memory lk-glass", historyOpen ? "" : "collapsed"].join(" ")}>
            {!historyOpen && (
              <button className="lk-history-toggle collapsed" type="button" onClick={() => setHistoryOpen(true)}>
                Turn history
              </button>
            )}
            {historyOpen && (
              <div className="lk-rail-toolbar">
                <button className="lk-history-toggle expanded" type="button" onClick={() => setDiagnosticsOpen((open) => !open)}>
                  {diagnosticsOpen ? "Hide diagnostics" : "Diagnostics"}
                </button>
                <button className="lk-history-toggle expanded" type="button" onClick={() => setHistoryOpen(false)}>
                  Collapse
                </button>
              </div>
            )}
            <section
              className={[
                "lk-candidate-camera",
                cameraOn ? "camera-on" : "",
                cameraOn && !cameraVisible ? "stream-hidden" : "",
              ].join(" ")}
            >
              <div className="lk-camera-frame">
                <video ref={videoRef} className="lk-camera-video" muted playsInline />
                <div className="lk-camera-avatar" aria-hidden="true">
                  SV
                </div>
              </div>
              <div className="lk-camera-meta">
                <div className="lk-camera-status">
                  <div>
                    <p className="lk-label">Candidate presence</p>
                    <strong>
                      {cameraOn && !cameraVisible
                        ? "Stream hidden"
                        : floorOwner === "candidate"
                          ? "Your floor is active"
                          : "Camera ready"}
                    </strong>
                  </div>
                  <span className="lk-dot" />
                </div>
                <button className="lk-camera-action" type="button" onClick={toggleCamera}>
                  {!cameraOn ? "Test camera" : cameraVisible ? "Hide stream" : "Show stream"}
                </button>
                {cameraError && <p className="lk-camera-error">{cameraError}</p>}
              </div>
            </section>
            <section className="lk-voice-diagnostics">
              <div>
                <p className="lk-label">Voice health</p>
                <p className="lk-stage-status">
                  {voiceError || `Session ${sessionId || "starting"}`}
                </p>
              </div>
              <div className="lk-status-grid">
                <span className={voiceLabRunning ? "active" : ""}>Mic {voiceLabRunning ? "on" : "idle"}</span>
                <span className={realtimeRunning ? "active" : ""}>Realtime {realtimeRunning ? "live" : "idle"}</span>
                <span className={deepgramRunning ? "active" : ""}>Deepgram {deepgramRunning ? "live" : "idle"}</span>
                <span className={functionCalls > 0 ? "active" : ""}>Tools {functionCalls}</span>
                <span className={turnGuardStatus === "clean" ? "active" : ""}>Guard {turnGuardStatus}</span>
              </div>
              <div className="lk-provider-lines">
                <span>Model: {realtimeModel}</span>
                <span>OpenAI: {openaiApiBase.replace(/^https?:\/\//, "")}</span>
                <span>Deepgram: {deepgramApiBase.replace(/^https?:\/\//, "")}</span>
                <span>Turn guard: {turnGuardMessage}</span>
                <span>Spoken question: {spokenQuestionText || aiTranscript || "waiting"}</span>
              </div>
            </section>
            <section className="lk-script-card">
              <div>
                <p className="lk-label">Answer to speak</p>
                <p className="lk-stage-status">
                  Suggested {selectedAnswerOption.signal.replace("_", " ")} path for this question.
                </p>
              </div>
              <p className="lk-script-text">{selectedAnswerOption.text}</p>
              <div className="lk-script-actions">
                <button className="lk-btn" type="button" onClick={() => loadAnswerScript(selectedAnswerOption)}>
                  Load into transcript
                </button>
                <button className="lk-btn" type="button" onClick={() => setDiagnosticsOpen(true)}>
                  More scripts
                </button>
              </div>
            </section>
            {diagnosticsOpen && (
              <section className="lk-answer-map">
                <div>
                  <p className="lk-label">Diagnostics</p>
                  <p className="lk-stage-status">
                    Scripts, provider controls, function calls, and raw event log.
                  </p>
                </div>
                <div className="lk-provider-grid">
                  <label className="lk-switch">
                    <input type="checkbox" checked={autoAdvanceRealtime} onChange={(event) => setAutoAdvanceRealtime(event.target.checked)} />
                    <span>Auto next</span>
                  </label>
                  <select className="lk-select compact" value={answerSignalMode} onChange={(event) => setAnswerSignalMode(event.target.value as AnswerSignal)}>
                    {(["strong", "partial", "honest_gap", "evasive", "stuck"] as AnswerSignal[]).map((signal) => (
                      <option key={signal} value={signal}>{signal}</option>
                    ))}
                  </select>
                  <label className="lk-switch">
                    <input type="checkbox" checked={enableRealtime} onChange={(event) => setEnableRealtime(event.target.checked)} />
                    <span>Realtime</span>
                  </label>
                  <label className="lk-switch">
                    <input type="checkbox" checked={enableDeepgram} onChange={(event) => setEnableDeepgram(event.target.checked)} />
                    <span>Deepgram</span>
                  </label>
                  <select className="lk-select" value={realtimeModel} onChange={(event) => setRealtimeModel(event.target.value)}>
                    {realtimeModelOptions.map((model) => (
                      <option key={model} value={model}>{model}</option>
                    ))}
                  </select>
                  <select className="lk-select" value={transcribeModel} onChange={(event) => setTranscribeModel(event.target.value)}>
                    {transcribeModelOptions.map((model) => (
                      <option key={model} value={model}>{model}</option>
                    ))}
                  </select>
                </div>
                <div className="lk-diagnostic-actions">
                  <button className="lk-btn" type="button" onClick={() => sendRealtimeInstruction(buildRealtimeInterviewInstruction(activeTurn.question))}>
                    Ask via Realtime
                  </button>
                  <button className="lk-btn" type="button" onClick={() => loadAnswerScript()}>
                    Load script
                  </button>
                  <button className="lk-btn" type="button" onClick={captureOpenAiTranscribeSample} disabled={recordingSample}>
                    {recordingSample ? "Recording" : "GPT sample"}
                  </button>
                  <button className="lk-btn" type="button" onClick={sendFunctionCallTest}>
                    Function test
                  </button>
                </div>
                <div className="lk-answer-options">
                  {activeAnswerOptions.map((option) => {
                    const next = nextTurnIndex(turnIndex, option.signal);
                    return (
                      <article key={`${option.signal}-${option.label}`} className={option.signal === answerSignalMode ? "selected" : ""}>
                        <div>
                          <small>{option.signal} · next {next}</small>
                          <strong>{option.label}</strong>
                        </div>
                        <p>{option.text}</p>
                        <button className="lk-answer-map-btn" type="button" onClick={() => loadAnswerScript(option)}>
                          Use script
                        </button>
                      </article>
                    );
                  })}
                </div>
                <div className="lk-event-log">
                  {events.length === 0 ? (
                    <p>No provider events yet.</p>
                  ) : (
                    events.slice(0, 16).map((event) => (
                      <article key={event.id}>
                        <small>{event.ts} · {event.type}</small>
                        {event.detail && <p>{event.detail}</p>}
                      </article>
                    ))
                  )}
                </div>
              </section>
            )}
            <section className="lk-cost-panel">
              <div className="lk-cost-head">
                <div>
                  <p className="lk-label">Realtime cost meter</p>
                  <p className="lk-stage-status">
                    Estimate uses OpenAI audio-token timing plus current model rates.
                  </p>
                </div>
                <strong>{money(usageEstimate.totalCost)}</strong>
              </div>
              <div className="lk-cost-grid">
                <span>Input audio <strong>{usageEstimate.inputAudioTokens}</strong></span>
                <span>Output audio <strong>{usageEstimate.outputAudioTokens}</strong></span>
                <span>Input text <strong>{usageEstimate.inputTextTokens}</strong></span>
                <span>Output text <strong>{usageEstimate.outputTextTokens}</strong></span>
                <span>Candidate audio <strong>{seconds(usageEstimate.inputAudioMs)}</strong></span>
                <span>AI audio <strong>{seconds(usageEstimate.outputAudioMs)}</strong></span>
              </div>
              <div className="lk-cost-note">
                <p>
                  {realtimeModel}: audio ${usageEstimate.rate.audioInputPerMTokens}/M in,
                  ${usageEstimate.rate.audioOutputPerMTokens}/M out. Text $
                  {usageEstimate.rate.textInputPerMTokens}/M in, ${usageEstimate.rate.textOutputPerMTokens}/M out.
                </p>
                <p>
                  GPT Transcribe samples: {transcribeSamples} · estimated add-on {money(usageEstimate.transcribeCost)}
                </p>
              </div>
              <div className="lk-usage-turns">
                {usageTurns.length === 0 ? (
                  <p>No usage yet. Run mock room or start voice room.</p>
                ) : usageTurns.slice(-5).reverse().map((turn) => (
                  <article key={turn.id}>
                    <small>{turn.label} · in {seconds(turn.inputAudioMs)} · out {seconds(turn.outputAudioMs)}</small>
                    <p>{turn.question}</p>
                    {turn.providerUsage ? <em>Provider usage captured</em> : null}
                  </article>
                ))}
              </div>
              <button className="lk-btn" type="button" onClick={resetUsage}>
                Reset usage
              </button>
            </section>
            <section className="lk-backend-panel">
              <div className="lk-backend-head">
                <div>
                  <p className="lk-label">Backend diagnostics</p>
                  <p className="lk-stage-status">
                    {backendDiagnostics
                      ? `Refreshed ${backendDiagnostics.refreshedAt}`
                      : "Pulls the backend telemetry trace for this active session."}
                  </p>
                </div>
                <button className="lk-btn" type="button" onClick={refreshBackendDiagnostics} disabled={backendDiagnosticsLoading}>
                  {backendDiagnosticsLoading ? "Loading" : "Refresh"}
                </button>
              </div>
              {backendDiagnosticsError && <p className="lk-backend-explain">{backendDiagnosticsError}</p>}
              <div className="lk-backend-grid">
                <span>Actual model <strong>{backendDiagnostics?.actualModel || "unknown"}</strong></span>
                <span>Selected model <strong>{realtimeModel}</strong></span>
                <span>Events <strong>{backendDiagnostics?.summary?.event_count ?? 0}</strong></span>
                <span>Issues <strong>{backendDiagnostics?.summary?.issues?.length ?? 0}</strong></span>
                <span>Usage events <strong>{backendDiagnostics?.usage.providerUsageEvents ?? 0}</strong></span>
                <span>Est. backend cost <strong>{money(backendDiagnostics?.usage.estimatedCost ?? 0)}</strong></span>
                <span>Input audio <strong>{backendDiagnostics?.usage.inputAudioTokens ?? 0}</strong></span>
                <span>Output audio <strong>{backendDiagnostics?.usage.outputAudioTokens ?? 0}</strong></span>
                <span>Input text <strong>{backendDiagnostics?.usage.inputTextTokens ?? 0}</strong></span>
                <span>Output text <strong>{backendDiagnostics?.usage.outputTextTokens ?? 0}</strong></span>
                <span>Total tokens <strong>{backendDiagnostics?.usage.totalTokens ?? 0}</strong></span>
                <span>Cached <strong>{backendDiagnostics?.usage.cachedTokens ?? 0}</strong></span>
              </div>
              <p className="lk-backend-explain">
                Realtime “output tokens” can include audio tokens. Audio output is dense: a few spoken sentences can look like thousands of tokens even when text output is small.
              </p>
              {backendDiagnostics?.summary?.trace_path && (
                <p className="lk-backend-path">{backendDiagnostics.summary.trace_path}</p>
              )}
              <div className="lk-backend-issues">
                {!backendDiagnostics ? (
                  <p>Click refresh after a voice run to inspect backend events.</p>
                ) : (backendDiagnostics.summary.issues || []).length === 0 ? (
                  <p>No issue-level backend events in this trace window.</p>
                ) : (
                  (backendDiagnostics.summary.issues || []).slice(-5).reverse().map((issue: any, index: number) => (
                    <article key={`${issue.event}-${index}`}>
                      <small>{issue.event || "event"} · {issue.source || "unknown"}</small>
                      <p>{issue.detail || issue.level || shortJson(issue).slice(0, 160)}</p>
                    </article>
                  ))
                )}
              </div>
            </section>
            <div className="lk-memory-content">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="lk-label">Turn history</p>
                  <p className="lk-stage-status">
                    {candidateFinalText
                      ? "Latest committed voice text is available below."
                      : "Committed turns. Open full transcript for the whole interview."}
                  </p>
                </div>
              </div>
              <div className={["lk-memory-list", fullTranscriptOpen ? "full" : ""].join(" ")}>
                {turnHistory.length === 0 ? (
                  <article className="lk-turn-card current">
                    <small>Waiting</small>
                    <p>No answer has been committed yet.</p>
                  </article>
                ) : (
                  turnHistory.map(({ turn, turnNumber }, index) => (
                    <article key={`${turn.question}-${index}`} className={["lk-turn-card", index === 0 ? "current" : ""].join(" ")}>
                      <small>
                        {fullTranscriptOpen
                          ? `Turn ${turnNumber}`
                          : index === 0
                            ? "Latest turn"
                            : "Prior turn"}
                      </small>
                      <p>
                        <strong className="text-white">Q:</strong> {turn.question}
                      </p>
                      <p className="mt-2">
                        <strong className="text-white">A:</strong> {turn.answer}
                      </p>
                    </article>
                  ))
                )}
              </div>
              <button className="lk-btn" type="button" onClick={() => setFullTranscriptOpen((open) => !open)}>
                {fullTranscriptOpen ? "Hide full transcript" : "Show full transcript"}
              </button>
            </div>
          </aside>
        </section>

        <footer className="lk-dock lk-glass">
          <div className="lk-dock-group">
            <button className="lk-btn" type="button" onClick={refreshStatus}>
              Refresh status
            </button>
            <button className="lk-btn" type="button" onClick={needMoment}>
              Need a moment
            </button>
            <button className="lk-btn" type="button" onClick={runSession}>
              Run mock room
            </button>
          </div>
          <div className="lk-dock-group">
            <button className="lk-btn" type="button" onClick={resetPreview}>
              Reset
            </button>
            <button className="lk-btn danger" type="button" onClick={closeRoom}>
              End interview
            </button>
          </div>
        </footer>
      </div>

      <section className={["lk-closing", showClosing ? "open" : ""].join(" ")}>
        <article className="lk-closing-card lk-glass">
          <p className="lk-eyebrow">Interview complete</p>
          <h2>Report is being prepared</h2>
          <p>
            The room has captured the conversation. The live assessment is closing and the report will be
            ready after final review.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {["Fencing boundary", "Replication delay", "Failure semantics", "Application transfer"].map((topic) => (
              <span key={topic} className="lk-chip">
                {topic}
              </span>
            ))}
          </div>
          <div className="mt-7">
            <button className="lk-btn primary" type="button" onClick={resetPreview}>
              Reset preview
            </button>
          </div>
        </article>
      </section>
    </main>
  );
}

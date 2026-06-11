"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import type { AgentState } from "@livekit/components-react";
import { AgentAudioVisualizerAura } from "@/components/agents-ui/agent-audio-visualizer-aura";

// ─── Content ─────────────────────────────────────────────────────────────────

const CLAIM    = "Owned launch analytics";
const Q1       = "How would you separate a real conversion drop from instrumentation noise?";
// A1 deliberately uses the phrase that Q2 will echo back
const A1_PRE   = "I'd look at backend ";
const A1_KEY   = "order records";           // ← highlighted phrase
const A1_POST  = " first — they're server-side and immune to client-side instrumentation failures.";
const A1       = A1_PRE + A1_KEY + A1_POST;
// Q2 opens by echoing the highlighted phrase
const Q2       = "You mentioned order records specifically. What makes you trust those over the event stream?";
const A2       = "Server-side writes happen on confirmed payment intent. They can't be dropped by an ad blocker, a flaky JS load, or a schema migration mid-session.";

// ─── Phases ──────────────────────────────────────────────────────────────────

type Phase =
  | "dark"       // aura only, breathing
  | "claim"      // resume claim surfaces
  | "q1"         // first question appears
  | "a1"         // candidate answers
  | "q2"         // follow-up, echoing the highlighted key phrase
  | "a2"         // second answer
  | "verdict";   // judgment card

// each phase fires at this cumulative ms offset
const TIMELINE: [Phase, number][] = [
  ["dark",    0],
  ["claim",   2200],
  ["q1",      4400],
  ["a1",      4400 + wordMs(Q1, 62)],
  ["q2",      4400 + wordMs(Q1, 62) + wordMs(A1, 48) + 900],
  ["a2",      4400 + wordMs(Q1, 62) + wordMs(A1, 48) + 900 + wordMs(Q2, 62) + 600],
  ["verdict", 4400 + wordMs(Q1, 62) + wordMs(A1, 48) + 900 + wordMs(Q2, 62) + 600 + wordMs(A2, 48) + 1400],
];

function wordMs(text: string, msPerWord: number) {
  return text.split(" ").length * msPerWord + 600;
}

// ─── Word-reveal component ────────────────────────────────────────────────────

function Words({
  text, msPerWord = 62, className = "", color,
}: {
  text: string; msPerWord?: number; className?: string; color?: string;
}) {
  const words = text.split(" ");
  return (
    <span className={className} style={color ? { color } : undefined}>
      {words.map((w, i) => (
        <motion.span
          key={i}
          style={{ display: "inline-block", marginRight: "0.24em" }}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * (msPerWord / 1000), duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
        >
          {w}
        </motion.span>
      ))}
    </span>
  );
}

// ─── Evidence items ───────────────────────────────────────────────────────────

const EVIDENCE = [
  { label: "ROLE FIT",         value: "Scoped yes",               note: "Strong for product analytics with metric-quality ambiguity." },
  { label: "STRONGEST SIGNAL", value: "Judgment under follow-up",  note: "Separated real conversion movement from instrumentation noise." },
  { label: "CALIBRATION",      value: "Mostly supported",          note: "Launch analytics ownership verified. Governance depth partial." },
  { label: "FOLLOW-UPS",       value: "2 actionable asks",         note: "One governance question. One dashboard-quality question onsite." },
];

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function InvestorDemo() {
  const [phase, setPhase] = useState<Phase>("dark");
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (!playing) return;
    setPhase("dark");
    const timers = TIMELINE.map(([p, ms]) => window.setTimeout(() => setPhase(p), ms));
    return () => timers.forEach(window.clearTimeout);
  }, [playing]);

  const restart = () => { setPhase("dark"); setPlaying(false); requestAnimationFrame(() => setPlaying(true)); };

  const auraState: AgentState =
    phase === "q1" || phase === "q2" ? "speaking" :
    phase === "claim" || phase === "a1" || phase === "a2" ? "thinking" :
    "idle";

  const showInterview = phase !== "verdict";

  return (
    <>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,700&family=JetBrains+Mono:wght@400;500;700&family=DM+Sans:wght@300;400;500;600&display=swap"
        rel="stylesheet"
      />

      <div data-id="ag-demo">
        <style>{CSS}</style>

        {/* Noise layer */}
        <div className="noise" aria-hidden />

        {/* Thin brand bar */}
        <div className="bar">
          <span className="bar-name">ANTIGRAVITY</span>
          <span className="bar-dot">·</span>
          <span className="bar-sub">INVESTOR DEMO</span>
          <span className="bar-spacer" />
          <button className="bar-btn" onClick={() => setPlaying(p => !p)}>{playing ? "⏸" : "▶"}</button>
          <button className="bar-btn bar-btn--dim" onClick={restart}>↺</button>
        </div>

        {/* ─── INTERVIEW VIEW ─────────────────────────────────────── */}
        <AnimatePresence>
          {showInterview && (
            <motion.div
              key="iv"
              className="iv"
              exit={{ opacity: 0, scale: 0.97, filter: "blur(14px)", transition: { duration: 0.7, ease: [0.4, 0, 1, 1] } }}
            >
              {/* Aura — the fixed anchor of the whole demo */}
              <motion.div
                className="aura-wrap"
                initial={{ opacity: 0, scale: 0.6 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 1.4, ease: [0.16, 1, 0.3, 1] }}
              >
                <AgentAudioVisualizerAura
                  size="xl"
                  state={auraState}
                  color="#C15F3C"
                  colorShift={0.28}
                  themeMode="dark"
                />
              </motion.div>

              {/* Conversation stream */}
              <div className="stream">

                {/* ① Claim */}
                <AnimatePresence>
                  {(phase === "claim" || phase === "q1") && (
                    <motion.div
                      key="claim"
                      className="claim-block"
                      initial={{ opacity: 0, y: 16 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10, transition: { duration: 0.3 } }}
                      transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
                    >
                      <span className="chip chip--amber">RESUME CLAIM</span>
                      <p className="claim-text">"{CLAIM}"</p>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* ② Q1 — the system's targeted question from the claim */}
                <AnimatePresence>
                  {["q1", "a1", "q2", "a2"].includes(phase) && (
                    <motion.div
                      key="q1"
                      className="q-block"
                      initial={{ opacity: 0, y: 18 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                    >
                      <span className="chip chip--muted">INTERVIEWER</span>
                      <p className="q-text">
                        <Words text={Q1} msPerWord={62} />
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* ③ A1 — candidate answer, with one phrase highlighted */}
                <AnimatePresence>
                  {["a1", "q2", "a2"].includes(phase) && (
                    <motion.div
                      key="a1"
                      className="a-block"
                      initial={{ opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
                    >
                      <span className="chip chip--teal">CANDIDATE</span>
                      <p className="a-text">
                        <Words text={A1_PRE} msPerWord={46} />
                        {/* The key phrase that Q2 will echo — highlighted */}
                        <motion.span
                          className="key-phrase"
                          initial={{ background: "transparent" }}
                          animate={
                            phase === "q2" || phase === "a2"
                              ? { background: "rgba(217,162,77,0.18)", color: "#ffd37a" }
                              : { background: "transparent", color: "inherit" }
                          }
                          transition={{ duration: 0.5, delay: phase === "q2" ? 0.1 : 0 }}
                        >
                          <Words
                            text={A1_KEY}
                            msPerWord={46}
                          />
                        </motion.span>
                        <Words text={A1_POST} msPerWord={46} />
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* ④ Q2 — the follow-up that PROVES adaptive intelligence */}
                <AnimatePresence>
                  {["q2", "a2"].includes(phase) && (
                    <motion.div
                      key="q2"
                      className="q-block q-block--followup"
                      initial={{ opacity: 0, y: 18 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                    >
                      <div className="q2-chips">
                        <span className="chip chip--muted">INTERVIEWER</span>
                        <motion.span
                          className="chip chip--amber-glow"
                          initial={{ opacity: 0, x: -8 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: 0.15, duration: 0.4 }}
                        >
                          FROM HER ANSWER ↑
                        </motion.span>
                      </div>
                      <p className="q-text q-text--followup">
                        <Words text={Q2} msPerWord={62} />
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* ⑤ A2 */}
                <AnimatePresence>
                  {phase === "a2" && (
                    <motion.div
                      key="a2"
                      className="a-block"
                      initial={{ opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.45 }}
                    >
                      <span className="chip chip--teal">CANDIDATE</span>
                      <p className="a-text">
                        <Words text={A2} msPerWord={46} />
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>

              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ─── VERDICT VIEW ────────────────────────────────────────── */}
        <AnimatePresence>
          {phase === "verdict" && (
            <motion.div
              key="verdict"
              className="vv"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5 }}
            >
              {/* Verdict card — cream, dominates the left */}
              <motion.div
                className="vv-card"
                initial={{ opacity: 0, y: 70, scale: 0.88 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
              >
                {/* Seal */}
                <motion.div
                  className="seal"
                  initial={{ scale: 0, rotate: -32 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ delay: 0.75, duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
                >
                  <span className="seal-text">AG</span>
                </motion.div>

                <motion.p className="vv-kicker" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}>
                  DECISION PACKAGE
                </motion.p>

                <motion.h1
                  className="vv-headline"
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.25, duration: 0.75, ease: [0.16, 1, 0.3, 1] }}
                >
                  Scoped yes,<br />with two<br />follow-ups.
                </motion.h1>

                <motion.div
                  className="vv-rule"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ delay: 0.5, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                  style={{ transformOrigin: "left" }}
                />

                <motion.p className="vv-subtext" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.75, duration: 0.5 }}>
                  What was tested.<br />What held up.<br />What to clarify next.
                </motion.p>
              </motion.div>

              {/* Right: evidence + CTA */}
              <div className="vv-right">
                <motion.p
                  className="chip chip--muted"
                  style={{ marginBottom: 20 }}
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.35 }}
                >EVIDENCE</motion.p>

                {EVIDENCE.map((item, i) => (
                  <motion.div
                    key={item.label}
                    className="ev"
                    initial={{ opacity: 0, x: 22 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.4 + i * 0.1, duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
                    whileHover={{ x: 6, borderColor: "rgba(217,162,77,0.2)", transition: { duration: 0.12 } }}
                  >
                    <p className="ev-label">{item.label}</p>
                    <p className="ev-val">{item.value}</p>
                    <p className="ev-note">{item.note}</p>
                  </motion.div>
                ))}

                <motion.div
                  className="ctas"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.9 }}
                >
                  <motion.button
                    className="cta-fill"
                    whileHover={{ scale: 1.03, transition: { duration: 0.12 } }}
                    whileTap={{ scale: 0.97 }}
                  >Open live room →</motion.button>
                  <motion.button
                    className="cta-outline"
                    whileHover={{ borderColor: "rgba(243,238,228,0.3)", transition: { duration: 0.12 } }}
                  >Engineering simulation</motion.button>
                </motion.div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
}

// ─── CSS ──────────────────────────────────────────────────────────────────────

const CSS = `
  [data-id="ag-demo"] {
    --cr: #C15F3C; --am: #D9A24D; --tl: #31C5DF; --gn: #7FE2AE;
    --cm: #F3EEE4; --pp: #EBE1CF; --ink: #14110F;
    --fd: 'Cormorant Garamond', Georgia, serif;
    --fm: 'JetBrains Mono', 'Fira Code', monospace;
    --fs: 'DM Sans', system-ui, sans-serif;

    position: fixed; inset: 0; overflow: hidden;
    font-family: var(--fs); color: white;
    /* Pure near-black — Aura provides the only warm light */
    background: #060402;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  button { font: inherit; cursor: pointer; background: none; border: none; }

  /* ── Noise ───────────────────────────────────────────────── */
  .noise {
    position: fixed; inset: 0; z-index: 9000; pointer-events: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='250' height='250'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.7' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='250' height='250' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
    background-size: 250px; opacity: 0.7; mix-blend-mode: overlay;
  }

  /* ── Brand bar ───────────────────────────────────────────── */
  .bar {
    position: fixed; top: 0; left: 0; right: 0; z-index: 100;
    height: 38px;
    display: flex; align-items: center; gap: 8px;
    padding: 0 22px;
    background: rgba(6,4,2,0.85); backdrop-filter: blur(24px);
    border-bottom: 1px solid rgba(243,238,228,0.06);
  }
  .bar-name {
    font-family: var(--fm); font-size: 10px; font-weight: 700;
    letter-spacing: 0.24em; color: rgba(243,238,228,0.72);
  }
  .bar-dot  { color: rgba(243,238,228,0.22); font-size: 12px; }
  .bar-sub  { font-family: var(--fm); font-size: 9px; font-weight: 500; letter-spacing: 0.18em; color: rgba(243,238,228,0.34); text-transform: uppercase; }
  .bar-spacer { flex: 1; }
  .bar-btn  {
    font-family: var(--fm); font-size: 11px; font-weight: 500;
    color: rgba(243,238,228,0.44); padding: 4px 9px;
    border: 1px solid rgba(243,238,228,0.12); border-radius: 6px;
    background: rgba(255,255,255,0.04);
    transition: color 0.15s, border-color 0.15s;
  }
  .bar-btn:hover { color: rgba(243,238,228,0.8); border-color: rgba(243,238,228,0.24); }
  .bar-btn--dim { color: rgba(243,238,228,0.26); }

  /* ── Interview view ──────────────────────────────────────── */
  .iv {
    position: absolute; inset: 0;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    gap: 32px; padding: 52px 48px 60px;
  }
  .aura-wrap { flex-shrink: 0; }

  /* ── Conversation stream ─────────────────────────────────── */
  .stream {
    display: flex; flex-direction: column; gap: 18px;
    width: min(720px, 100%); max-height: 48vh;
    overflow: hidden;
  }

  /* ── Chips ───────────────────────────────────────────────── */
  .chip {
    display: inline-block;
    font-family: var(--fm); font-size: 9px; font-weight: 700;
    letter-spacing: 0.2em; text-transform: uppercase;
    padding: 4px 9px;
    border-radius: 5px;
    margin-bottom: 8px;
  }
  .chip--amber {
    color: rgba(217,162,77,0.9); background: rgba(217,162,77,0.1);
    border: 1px solid rgba(217,162,77,0.2);
  }
  .chip--muted {
    color: rgba(243,238,228,0.36); background: rgba(255,255,255,0.04);
    border: 1px solid rgba(243,238,228,0.1);
  }
  .chip--teal {
    color: rgba(49,197,223,0.85); background: rgba(49,197,223,0.08);
    border: 1px solid rgba(49,197,223,0.18);
  }
  .chip--amber-glow {
    color: rgba(217,162,77,0.9); background: rgba(217,162,77,0.12);
    border: 1px solid rgba(217,162,77,0.3);
    box-shadow: 0 0 12px rgba(217,162,77,0.18);
  }

  /* ── Claim block ─────────────────────────────────────────── */
  .claim-block { text-align: center; }
  .claim-text {
    font-family: var(--fd); font-weight: 700; font-style: italic;
    font-size: clamp(28px, 3.4vw, 50px); line-height: 1;
    color: rgba(243,238,228,0.65); letter-spacing: -0.01em;
  }

  /* ── Question blocks ─────────────────────────────────────── */
  .q-block { text-align: center; }
  .q-block--followup { position: relative; }
  .q2-chips { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 8px; }
  .q-text {
    font-family: var(--fd); font-weight: 700;
    font-size: clamp(24px, 2.8vw, 42px); line-height: 1.06;
    color: white; letter-spacing: -0.01em;
  }
  .q-text--followup { color: rgba(243,238,228,0.95); }

  /* ── Answer blocks ───────────────────────────────────────── */
  .a-block { text-align: center; }
  .a-text {
    font-family: var(--fs); font-size: clamp(14px, 1.5vw, 18px);
    line-height: 1.55; color: rgba(49,197,223,0.78);
  }
  .key-phrase {
    display: inline; border-radius: 3px;
    padding: 1px 3px; margin: 0 1px;
    transition: background 0.5s, color 0.5s;
  }

  /* ── Verdict view ────────────────────────────────────────── */
  .vv {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    gap: 36px; padding: 48px 60px;
    background: #060402;
  }

  /* ── Verdict card ────────────────────────────────────────── */
  .vv-card {
    position: relative; flex-shrink: 0;
    width: 310px; min-height: 460px;
    border-radius: 28px; padding: 30px 28px 26px;
    background: linear-gradient(160deg, var(--cm) 0%, var(--pp) 100%);
    color: var(--ink);
    box-shadow:
      0 50px 140px rgba(0,0,0,0.55),
      0 0 0 1px rgba(255,255,255,0.3);
    display: flex; flex-direction: column;
  }
  .seal {
    position: absolute; top: 18px; right: 18px;
    width: 46px; height: 46px; border-radius: 50%;
    border: 1.5px solid rgba(217,162,77,0.45);
    background: radial-gradient(circle, rgba(217,162,77,0.14), transparent 68%);
    display: grid; place-items: center;
  }
  .seal-text {
    font-family: var(--fm); font-size: 10px; font-weight: 700;
    color: rgba(217,162,77,0.8); letter-spacing: 0.06em;
  }
  .vv-kicker {
    font-family: var(--fm); font-size: 10px; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase;
    color: rgba(20,17,15,0.44); margin-bottom: 14px;
  }
  .vv-headline {
    font-family: var(--fd); font-weight: 700;
    font-size: clamp(40px, 4.6vw, 66px); line-height: 0.88;
    letter-spacing: -0.025em; color: var(--ink);
    flex: 1; margin-top: 2px;
  }
  .vv-rule {
    height: 1px; background: rgba(20,17,15,0.14);
    margin: 20px 0;
  }
  .vv-subtext {
    font-family: var(--fm); font-size: 10px; font-weight: 500;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: rgba(20,17,15,0.44); line-height: 1.65;
  }

  /* ── Evidence ────────────────────────────────────────────── */
  .vv-right {
    display: flex; flex-direction: column;
    flex: 1; max-width: 500px; min-height: 0;
  }
  .ev {
    border: 1px solid rgba(243,238,228,0.09);
    border-radius: 16px; padding: 15px 14px;
    background: rgba(255,255,255,0.03);
    margin-bottom: 10px; cursor: default;
    transition: border-color 0.15s;
  }
  .ev-label {
    font-family: var(--fm); font-size: 9px; font-weight: 700;
    letter-spacing: 0.18em; text-transform: uppercase;
    color: rgba(243,238,228,0.34); margin-bottom: 5px;
  }
  .ev-val {
    font-family: var(--fd); font-weight: 700;
    font-size: clamp(17px, 1.9vw, 25px); line-height: 1.05; color: var(--cm);
  }
  .ev-note {
    font-family: var(--fs); font-size: 12px;
    color: rgba(243,238,228,0.46); line-height: 1.45; margin-top: 7px;
  }

  /* ── CTAs ────────────────────────────────────────────────── */
  .ctas { display: flex; gap: 10px; margin-top: 6px; }
  .cta-fill {
    border: none; border-radius: 999px; padding: 13px 24px;
    background: var(--cm); color: var(--ink);
    font-family: var(--fs); font-size: 14px; font-weight: 600;
    animation: cta-breathe 2.6s ease-in-out infinite; animation-delay: 1.2s;
  }
  @keyframes cta-breathe {
    0%,100% { box-shadow: 0 0 0 0 rgba(243,238,228,0); }
    50%      { box-shadow: 0 0 0 6px rgba(243,238,228,0.12); }
  }
  .cta-outline {
    border: 1px solid rgba(243,238,228,0.18); border-radius: 999px;
    padding: 12px 22px; color: rgba(243,238,228,0.62);
    font-family: var(--fs); font-size: 14px;
    transition: border-color 0.15s;
  }

  /* ── Responsive ──────────────────────────────────────────── */
  @media (max-width: 900px) {
    .iv { gap: 22px; padding: 50px 24px 56px; }
    .stream { max-height: 52vh; }
    .vv { flex-direction: column; padding: 44px 24px; gap: 20px; }
    .vv-card { width: 100%; max-width: 400px; min-height: auto; }
    .vv-right { max-width: 100%; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
  }
`;

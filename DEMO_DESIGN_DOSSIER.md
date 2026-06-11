# Antigravity Investor/Internal Demo — World-Class Design Dossier

**Prepared for:** The `visualizer-interview-demo-flash` route  
**Status:** Prescriptive specification — implement verbatim for maximum signal  
**Date:** 2026-06-09

---

## 00. The Only Principle That Matters

The best product demos in the world (Claude, Linear, Base44, Suno, ElevenLabs) do one thing the rest don't: **the action IS the explanation.** The viewer understands the product by watching it work, not by reading text about what it does.

Right now, this demo is a slide deck that describes a product. It should be a product that narrates itself.

Every frame should answer: *"What am I watching happen right now?"* — not *"What is the slide telling me?"*

---

## 01. Audit — What The Current Demo Gets Right and Wrong

### What's Working

- **Color palette**: Crail/amber/teal/cream against near-black is sophisticated and right. The warm-cool tension maps perfectly to the AI↔candidate dynamic.
- **The signal flow arc**: Problem → setup → room → report → close is the correct narrative skeleton.
- **The fake cursor**: The concept is correct. Product demos at the level of Linear and Base44 all use animated cursor choreography. It signals "watch what this does."
- **The cream "paper" artifact**: The evidence brief and verdict card using cream/paper gradients as the "human-legible output" color is a strong visual metaphor. Keep it.
- **Stage titles**: "Hiring still relies on weak evidence" and "The floor moves visibly between interviewer and candidate" are genuinely good copy.

### What's Not Working

| Problem | Root cause | Impact |
|---|---|---|
| Stage transitions are hard cuts | No cross-fade between body content | Feels like slides, not a product |
| Everything appears simultaneously per stage | No staggered entry animation | Viewer's eye has nowhere to land |
| The cursor doesn't interact — it just drifts | No click simulation, no element response | Cursor feels like a decoration, not a demo |
| The Aura is buried in one frame | Appears once, medium-sized, in a side panel | The product's most distinctive UI element is hidden |
| Builder stage looks like a terminal log | "loaded / ready / visible / armed" status rows | Describes the product instead of showing it |
| 8 report cards at tiny size | Grid over-density | The decision package moment doesn't land |
| Typography is Geist/Inter — the default | Same font as every other AI product | Zero character, forgettable |
| The thesis stage duplicates the problem stage | Both explain the same loop | Viewer disengages, narrative loses momentum |
| Nav is text buttons ("Previous / Play / Next / Restart") | No icon affordance | Takes visual space, adds no signal |
| Cursor coordinates are hardcoded pixel offsets | CSS transform values, not semantic positions | Doesn't scale, feels arbitrary |

---

## 02. Aesthetic Direction — "The Assessment Room"

### The Concept

This is not a startup tool. It is a **precision instrument for high-stakes human decisions.** The UI should feel like it was designed by people who also designed the software Bloomberg terminals run on — dense with signal, rigorous in structure, but with moments of warmth where the human stakes surface.

Tone: Serious. Controlled. Premium. With warmth at the right moments.

Not: Playful. Not: Cold tech. Not: Surveillance dashboard. Not: Startup-clean.

Reference feel:
- The interior of a private equity conference room (dark surfaces, cream documents, precise lighting)
- DeepMind's research visualizations (abstract but purposeful)
- A surgical instrument tray (everything has a place, everything signals its function)

### Typography System — UPGRADE REQUIRED

The current use of Geist/Inter is the single biggest aesthetic miss. Every AI company uses these. Antigravity should own a different register.

**Display (stage titles, verdict headlines):**
`Cormorant Garamond` — a classical serif with extreme contrast between thick and thin strokes. At large sizes it reads as *authority*. Free on Google Fonts. Import it.

```css
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&display=swap');

.stage-title {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-weight: 700;
  font-size: clamp(52px, 6.4vw, 100px);
  line-height: 0.90;
  letter-spacing: -0.02em;
}
```

Why Cormorant: At 80px, the thin serifs create a visual elegance that makes "Scoped yes, with two follow-ups" feel like a *verdict*, not a label. It signals: old-world judgment meets new-world intelligence.

**Labels, metrics, machine-output:**
`JetBrains Mono` — the cleanest monospace for UI. Import it alongside Cormorant.

```css
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');

.label, .metric, .kicker {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
  letter-spacing: 0.18em;
  font-size: 10px;
  text-transform: uppercase;
}
```

Why JetBrains Mono: The serif/mono contrast creates the exact register split needed — Cormorant says "this is a serious judgment," JetBrains Mono says "this is a machine-precise measurement." Together they signal: *AI-native assessment institution.*

**Body / card text:**
Keep a clean sans — but use `'DM Sans'` instead of Geist. Same legibility, but its rounded geometry softens the sharpness of the serif/mono combination without going generic.

### Color System — Refine, Don't Change

The palette is correct. Sharpen the role assignment:

```css
--crail: #C15F3C;      /* AI presence — warm, authoritative */
--amber: #D9A24D;      /* Signal quality — golden, valuable */
--teal: #31C5DF;       /* Candidate — cool, responsive */
--green: #7FE2AE;      /* Confirmation — cleared, positive */
--cream: #F3EEE4;      /* Human output — paper, legible */
--ink: #14110F;        /* Text on cream surfaces */
--black: #050505;      /* Base background */
```

New rules to enforce:
- Crail glow = AI presence. ONLY use for Aura context, AI-turn state, AI-side highlights.
- Teal glow = candidate presence. ONLY use for candidate corner, camera, transcription.
- Cream backgrounds = the "human-legible output." When the hiring team receives something, it goes on cream.
- Amber = signal/evidence quality. Used for progress, highlights, important data points.

### Spatial Composition — Break The Uniform Grid

Current: Almost every stage uses equal-column grids. This creates visual monotony.

New rule: **Dominant-secondary asymmetry.** Every frame has one element that is clearly the most important. That element gets more space, more visual weight, or more contrast.

Frame-level ratios to follow:
- Problem stage: 30% / 25% / 45% (small input, medium live test, large output)
- Turns stage: 22% / 56% / 22% (small AI corner, wide turn rail, small candidate corner)
- Room stage: 230px / 1fr / 230px (side panels fixed, center dominates)
- Report stage: 36% / 64% (small verdict, large evidence grid)

**The 60/40 rule**: When in doubt, make the dominant visual 60% of available width and give 40% to supporting content. Never 50/50 except for deliberate symmetry (e.g., the turn rail).

---

## 03. The Aura — Elevate To Hero

The `AgentAudioVisualizerAura` component is the product's most distinctive visual asset. It is also the most underused in the current demo.

### Why The Aura Matters So Much

In the live product, the Aura IS the AI interviewer's visible presence. It is abstract (avoids uncanny valley), it communicates state (idle / thinking / speaking), and it pulses with audio data. In a demo where there's no live audio, it should be *choreographed* — its state should tell the story.

### Aura Presence Map — Every Frame It Should Appear

| Stage | Size | State | Position | Why |
|---|---|---|---|---|
| `seed` (ignition pill) | 28px | `idle` | Inside pill, left of text | "The system is alive and ready" |
| `problem` | 0 (absent) | — | — | Problem frame should feel like the BEFORE state — no AI yet |
| `evidence` | 56px | `idle` | Top-right of the paper card | "The AI is reading the brief" |
| `builder` | 120px | `thinking` | Centered in the build frame | "The room is being assembled around the AI" |
| `turns` | 96px | alternates | Left AI-corner box | Aura replaces the "AI" text box — it IS the interviewer |
| `room` | 180px | `speaking` | Left panel, full-height fill | Full product fidelity |
| `report` | 52px | `idle` | Inside verdict card, above headline | "The AI has completed its job" |
| `close` | 72px | `idle` | Left of CTA card | Persistent character through to the end |

### Aura State-to-Story Mapping

The Aura's state should always reflect what the product is doing narratively:

- **`idle`** = "reading," "waiting," "at rest" — low pulsation, slow ambient glow
- **`thinking`** = "processing an answer," "preparing the next question" — active but inward
- **`speaking`** = "asking a question," "actively testing the candidate" — outward energy

In the turns stage, the state should cycle: `speaking` (2.8s) → `thinking` (0.8s) → `idle` (0.4s) → repeat. This simulates the interview rhythm without needing real audio.

---

## 04. Stage Transitions — Fix The Hardest Problem First

This is the #1 fix for immediate impact. Currently: hard cuts. Target: seamless morphs.

### The Transition System

The shell should persist. The header should persist. Only the BODY content transitions.

```css
.body-content {
  animation: stage-enter 440ms cubic-bezier(.16, 1, .3, 1) both;
}

@keyframes stage-enter {
  from {
    opacity: 0;
    transform: translateY(14px) scale(0.99);
    filter: blur(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: blur(0);
  }
}
```

Additionally:
- The progress bar transition should be `transition: width 600ms cubic-bezier(.4, 0, .2, 1)` — the bar should feel like it's loading something real.
- On stage advance, the progress bar should briefly show a subtle "loading" shimmer (moving highlight across it) before settling at the new value.

The stage label in the header (`stage.label`) should cross-dissolve — old label fades out in 120ms, new label fades in over 180ms. Currently it hard-swaps.

---

## 05. Frame-by-Frame Design Specification

### FRAME 1 — Ignition (`seed`)

**Purpose**: Create the desire to start. Signal that something precise and purposeful is about to happen.

**Current problems**: The pill is too small. The cursor just sits there. Nothing about the pill communicates what the product is.

**Target state**:

Layout:
```
[centered vertically and horizontally]
    
  ○  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ○  
  ↑                                      ↑
Aura 28px                            End dot
  
           Start interview simulation
  
     Observe a Product Analyst being assessed.
```

Spec:
- Shell collapses to pill: `width: 440px; height: 72px; border-radius: 999px`
- Inside pill: `[Aura 28px, idle] — "Start interview simulation" — [→ arrow]`
- BELOW the pill (not inside): a secondary line in JetBrains Mono: `"Observe a Product Analyst being assessed."`
- Font for pill text: Cormorant Garamond, 22px, weight 600 — not sans-serif
- Pill glow: `box-shadow: 0 0 60px rgba(193,95,60,0.18), 0 0 120px rgba(193,95,60,0.08)`
- Ambient radial glow behind pill: 600px diameter, crail at 6% opacity, slow pulse 3s ease-in-out infinite

**Cursor behavior**:
1. Cursor enters from bottom-left, offscreen, moves to just left of the pill text (650ms travel)
2. Cursor pauses at pill for 400ms — cursor shape should become "pointer" (add a small dot to the arrow)
3. Cursor clicks: pill scales `0.96` in 80ms, then `1.04` in 120ms, then `1.0` in 100ms — "press and release"
4. On "click": the auto-advance timer resets and moves to next stage immediately
5. The pill-to-shell expansion: `width` and `height` animate from pill dimensions to full shell over 420ms using `cubic-bezier(.16,1,.3,1)` — the pill grows into the full UI

**Copy**:
- Main: `Start interview simulation`
- Sub: `Observe a Product Analyst being assessed.` (this is important — it names the stakes)

---

### FRAME 2 — The Problem (`problem`)

**Purpose**: In 5 seconds, the viewer understands the market gap and how Antigravity closes it. The 3 cards should feel like a before→during→after revelation.

**Current problems**: Cards appear simultaneously. Too much text per card. Cards are equal size. The "flow" between them is invisible.

**Target state**: Three cards. Sequential entry. Asymmetric sizing. A visible flow connector.

**Card proportions** (within the signal-flow grid):
```
grid-template-columns: 26fr 22fr 52fr
```
The output card (cream background) is almost twice as wide as the input card. This visually prioritizes the RESULT of the Antigravity loop.

**Card entry sequence**:
- 0ms: first card (Input) enters from left with `translateX(-24px)` → `translateX(0)`, 380ms
- 120ms: second card (Live test) enters from below with `translateY(20px)` → `translateY(0)`, 380ms
- 280ms: third card (Output/cream) enters from right with `translateX(24px)` → `translateX(0)`, 380ms
- 480ms: flow arrows draw between cards (animated SVG lines, 300ms each)

**Flow arrows**: Draw left-to-right connecting lines between cards. A thin line (1px, amber at 40% opacity) with an arrowhead at the end. The line draws itself with `stroke-dasharray` animation.

**Card redesign**:

Card 1 — Input:
```
[RESUME CLAIM]                        ← JetBrains Mono label, crail
"Owned launch analytics"              ← Cormorant Garamond, 28px
─────────────────────
The team cannot verify the 
judgment without a live test.         ← DM Sans, 14px, muted
```

Card 2 — Live Test:
```
[LIVE TEST]                           ← JetBrains Mono, teal
"Metric drop under                    ← Cormorant Garamond, 28px
 follow-up"  
─────────────────────
The room asks from what the
candidate just said.                  ← DM Sans, 14px, muted
```

Card 3 — Output (cream background, ink text):
```
[DECISION EVIDENCE]                   ← JetBrains Mono, amber, on cream
"Scoped yes.                          ← Cormorant Garamond, 40px, ink
 Two follow-ups."
─────────────────────
Role fit, strongest signal,
tested risks, and what a human
interviewer should ask next.          ← DM Sans, 15px, ink 60% opacity
```

**Cursor behavior**:
1. Cursor starts on card 1, hovers — card 1 lifts (+Y -10px, amber border glow)
2. After 1.4s cursor moves to card 2 — card 2 lifts (+Y -10px, teal border glow)
3. After 1.4s cursor moves to card 3 — card 3 lifts (+Y -10px, amber border glow, larger lift since card is more important)
4. Card 3 lift should be more dramatic: `-16px` instead of `-10px`, box-shadow `0 32px 100px rgba(0,0,0,0.36)`

**What to cut**:
- Remove "The resume sounds strong" in the subtitle. The subtitle should be: `"The claim enters. The room tests it. The report explains what held up."` — one sentence, three acts.

---

### FRAME 3 — Evidence Brief (`evidence`)

**Purpose**: Show the interviewer brief — the evidence packet that the system assembles before the live room starts. Make it feel like it's being GENERATED, not shown.

**Current problems**: Static cream paper card. Rows just appear. No sense of the machine doing something.

**Target state**: The paper card should enter and then rows should appear sequentially, as if being GENERATED in real time. A small Aura in the top-right corner of the card signals "the AI is building this."

**Entry animation**:
- Paper card enters from slightly below (translateY 20px) with scale 0.97 → 1.0, 400ms
- Card appears slightly blank first — headline visible, rows empty
- Rows appear one by one, 90ms apart, each with a 200ms `opacity 0 → 1` + `translateX(-8px) → translateX(0)`
- This gives the impression of being filled in by the system

**Small Aura placement**:
```
[paper card top-right corner — position: absolute; top: 20px; right: 20px]
  Aura component, size 48px, state "thinking"
  Below it, in JetBrains Mono 9px: "PREPARING ROOM"
```
The Aura in "thinking" state here contextualizes what's happening: the system is reading this brief and building the interview.

**Row redesign** — each row should have a LEFT INDICATOR:

```
[●] CANDIDATE        S. V. S. Apparao
[●] ROLE             Product Analyst
[●] EXPERIENCE       Launch analytics, dashboard quality
[●] LIVE SCENARIO    Conversion drop — may be instrumentation
[●] INTERVIEW GOAL   Observe reasoning, recovery, communication
[●] HIRING OUTPUT    Decision package with fit, signal, risks
```

The `[●]` should be:
- A small 6px circle
- Color matches the row type: amber for candidate/role data, teal for live scenario/goal, green for hiring output

**The final row** (hiring output) should appear with a slightly different treatment — its dot should pulse once (0.4s glow animation) when it enters, and the text should be slightly brighter than other rows. This signals: "this is the point of all this."

---

### FRAME 4 — Room Assembly (`builder`)

**Purpose**: The room forms. This should feel CINEMATIC — like watching the set for a stage production being assembled in fast-forward.

**Current problem**: Status log rows ("Candidate context: loaded / Live room layout: ready") feel like terminal output. Replace entirely.

**Target state**: A spatial assembly animation. The room components appear around a central Aura.

**Layout — completely new design**:

```
┌─────────────────────────────────────────────────┐
│                                                   │
│         [ASSEMBLING ROOM]    ← kicker             │
│                                                   │
│    ┌───────┐                    ┌───────────────┐ │
│    │ Aura  │ ←120px thinking→  │ Turn rail     │ │
│    │       │                   │ ◄──── ○ ────► │ │
│    └───────┘                   └───────────────┘ │
│                                                   │
│    ┌──────────────────────────────────────────┐   │
│    │                                          │   │
│    │  [ Question text appears here ]          │   │
│    │                                          │   │
│    └──────────────────────────────────────────┘   │
│                                                   │
│    ┌───────────────┐    ┌────────────────────┐   │
│    │  Live transcript│   │  History / Camera  │   │
│    └───────────────┘    └────────────────────┘   │
│                                                   │
└─────────────────────────────────────────────────┘
```

**Assembly sequence** (total 5.5s):
1. `0ms`: Aura appears center, small (40px), `idle`. Background is dark, nothing else visible.
2. `400ms`: Aura grows to 96px, state changes to `thinking`. Label appears below: "Reading candidate brief..."
3. `900ms`: Turn rail slides in from top, `translateY(-30px) → translateY(0)`, opacity 0 → 1. 
4. `1300ms`: Question card slides in from right, `translateX(40px) → translateX(0)`. Blank at first.
5. `1800ms`: Question TEXT types in — use word-by-word animation: "How would you tell whether a conversion drop is real or instrumentation noise?" — each word appears 60ms apart.
6. `2600ms`: Live transcript strip slides up from below.
7. `3000ms`: Camera/history panel slides in from right.
8. `3600ms`: Control pills appear one by one (80ms apart): "Repeat question" / "Need a moment" / "Fix last term" / "Full transcript"
9. `4200ms`: The Aura state changes to `speaking`. The label below it changes to "Room ready."
10. `4600ms`: Everything glows briefly — a subtle 300ms "ready" pulse where all borders increase opacity to 0.3, then settle back to 0.12.

**The effect**: The viewer watches the interview room BUILD ITSELF around the AI presence. By the time the room is "ready," the viewer has a spatial map of every component without ever reading a list.

**What to put in the hero copy for this stage**:
```
kicker: "ROOM ASSEMBLY"
title: "The room builds around the candidate."
subtitle: "Every component — presence, turn ownership, question, transcript, controls, history — exists to eliminate ambiguity in the live interview."
```

---

### FRAME 5 — The Exchange (`turns`)

**Purpose**: Show the floor transferring between AI and candidate. This is the product's core UX promise made visible.

**Current problems**: "AI" and "SV" boxes are static. The beam animation is good but undercontextualized. "Ask / Answer / Review" captions are generic labels.

**Target state**: Replace the static "AI" avatar box with the actual Aura component. Show real question text and simulated transcription. Let the beam animation drive the emotional rhythm.

**Layout redesign**:

```
┌──────────────────────────────────────────────────────┐
│  ┌──────────────┐   [turn beam rail]   ┌────────────┐│
│  │              │  ◄═══════════════►   │            ││
│  │   Aura 96px  │  ○──────●──────○     │   SV  96px ││
│  │   speaking   │     FLOOR            │   [teal]   ││
│  │              │                      │            ││
│  └──────────────┘                      └────────────┘│
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │                                                │  │
│  │  [AI TURN]  "How would you tell whether a     │  │
│  │             conversion drop is real or         │  │
│  │             instrumentation noise?"            │  │
│  │                                                │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │  [CANDIDATE ANSWER — LIVE]                     │  │
│  │  "I would compare raw event volume..."  █      │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

**Animation cycle** (loops continuously):

Phase 1 — AI Turn (0ms → 2800ms):
- Beam is on left third of rail (crail color)
- Aura is `speaking`, warm crail glow on its panel border
- Question card shows the full question text — it types in over 800ms
- Candidate box is dimmed (60% opacity), teal border gone

Phase 2 — Floor transfer (2800ms → 3400ms):
- Beam animates from left → right over 600ms with a smooth ease
- Both panels dim briefly during the cross
- Aura state: `thinking`

Phase 3 — Candidate Turn (3400ms → 5600ms):
- Beam is on right third (teal color)
- Candidate box lights up with teal border glow
- Aura dims slightly (still `thinking`)
- Live transcription appears in the transcript strip, word by word
- Simulated answer: "I would compare raw event volume, schema changes, funnel step counts, and a holdout metric before calling it a regression."

Phase 4 — Review (5600ms → 6200ms):
- Beam centers (amber color, briefly)
- Both panels at neutral brightness
- Question card briefly shows "Processing answer..." in small JetBrains Mono text below the question
- Then: transition to next stage

**Aura state in turns stage**:
- AI Turn: `speaking` — highest intensity, warm rings
- Floor transfer: brief `thinking`
- Candidate Turn: `idle` with slight warmth — "listening"

**Hero copy**:
```
kicker: "FLOOR TRANSFER"
title: "The floor moves visibly between interviewer and candidate."
subtitle: "Turn ownership is explicit — no guessing, no dead air, no hidden state. The candidate always knows when to speak."
```

---

### FRAME 6 — The Live Room (`room`)

**Purpose**: Full product fidelity. This is the most important frame. The viewer should feel like they're watching the actual product in action.

**Current problems**: Aura is medium-sized in a side panel. Question font is undersized. Answer strip is too subtle. Controls are inert.

**This frame needs the most investment. Specification is most detailed here.**

**Layout** (three-column):
```
[AI Panel 240px] | [Main Panel 1fr] | [Candidate Panel 240px]
```

**Left panel — AI Presence**:
- Background: `rgba(0,0,0,0.72)` with a radial crail glow: `radial-gradient(160px at 50% 40%, rgba(193,95,60,0.14), transparent 70%)`
- Aura component: `180px × 180px`, state: `speaking`
- Below Aura, in JetBrains Mono 9px, crail 60% opacity: `AI INTERVIEWER`
- Panel left border: `1px solid rgba(193,95,60,0.22)` — subtle crail edge
- The entire left panel should have a very faint crail ambient light — `box-shadow: inset 2px 0 40px rgba(193,95,60,0.06)` on the right side of the panel

**Center panel — The Interview**:

Turn rail at top:
```
[AI CORNER]  ═══════●═══════  [CANDIDATE CORNER]
```
- Three-part with clear floor indicator (dot/beam)
- When it's AI's turn: left side glows with crail, dot sits left
- Use `JetBrains Mono` for "AI CORNER" / "CANDIDATE CORNER" labels
- The floor indicator should be a glowing dot, not just a beam — `width: 12px; height: 12px; border-radius: 50%; background: var(--crail); box-shadow: 0 0 20px rgba(193,95,60,0.7)`

Question card (the anchor):
```css
.question {
  background: #000;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 24px;
  padding: 32px;
  box-shadow: inset 0 0 0 1px rgba(243,238,228,0.05), 
              0 0 50px rgba(193,95,60,0.10),
              0 20px 60px rgba(0,0,0,0.40);
}
```
- Label: `JetBrains Mono 10px` — `INTERVIEWER'S QUESTION`
- Question text: `Cormorant Garamond 700`, `clamp(32px, 3.2vw, 50px)`, white, line-height 1.0
- The question text should have a BLINK CURSOR at the end — a 2px white bar blinking at 1Hz — this subtly communicates "this text just arrived"

Live transcript strip:
```css
.answer-strip {
  border: 1px solid rgba(49,197,223,0.24);
  border-radius: 18px;
  padding: 14px 16px;
  background: rgba(49,197,223,0.04);
  color: rgba(243,238,228,0.72);
  font-size: 15px;
  line-height: 1.5;
}
```
- Label: `JetBrains Mono 10px` — `CANDIDATE ANSWER — LIVE`
- Text: A simulated partial answer, ending with `█` (a block cursor blinking)
- This makes it OBVIOUS that this is live capture in progress

Control pills redesign:
- More spacious: `padding: 11px 18px`, `font-size: 13px`
- Controls should be: "Repeat question" | "Need a moment" | "Fix last term" | "Full transcript"
- The cursor in this frame should hover over "Repeat question" and it should respond with a visible hover state:
  ```css
  .pill:hover, .pill.cursor-hover {
    border-color: rgba(243,238,228,0.32);
    background: rgba(255,255,255,0.1);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.24);
  }
  ```
- This is the one moment in the demo where a control actually RESPONDS to the cursor — it signals "this is a real interactive product"

**Right panel — Candidate Corner**:
- Background: `rgba(0,0,0,0.58)` with teal glow: `radial-gradient(120px at 50% 30%, rgba(49,197,223,0.1), transparent 70%)`
- Panel right border: `1px solid rgba(49,197,223,0.16)`
- Camera preview: A rounded dark rectangle with the candidate's initials ("SV") centered in a teal-tinted circle
- When it's the candidate's turn: camera rectangle should have a subtle teal pulse on its border (`animation: camera-live 2s ease-in-out infinite`)
- Turn history: 2 small cards showing prior Q/A. Most recent card slightly brighter. Second card dimmed (`opacity: 0.6`).
- History should feel like scrollable context — not like a list of items to read

**Hero copy** (inline, top of frame before the main layout, not in a separate left column):
```
kicker: "LIVE ROOM"
title: "The live room makes the interview legible."

[The room layout follows immediately below the title]
```
This frame is the one where the visual should dominate. The title should be smaller than usual — this is not a slide, it's a product view.

---

### FRAME 7 — The Decision Package (`report`)

**Purpose**: The payoff. Show the hiring team what they receive. The "Scoped yes" verdict should land like a gavel.

**Current problems**: Verdict headline ("Scoped yes, with two follow-ups") is 36-66px via clamp but feels small in the cream card. 8 cards are too many and too small. No sense of revelation — everything is already there.

**Target state**: A reveal animation. The verdict lands first. Then evidence cards materialize around it.

**Layout** (two-column):
```
[Verdict column 38%] | [Evidence grid 62%]
```

**Verdict card entry animation**:
1. Card enters with `scale(0.92) opacity(0)` → `scale(1.0) opacity(1)` over 500ms
2. A brief "stamp" effect at the end: `scale(1.04)` at 380ms → `scale(1.0)` at 500ms
3. After the card settles (600ms), a subtle seal badge appears in the top-right of the verdict card

**The seal badge**:
```
A 44px × 44px circular element, absolutely positioned in top-right of verdict card
Background: radial-gradient from amber/golden center
In the center: a small checkmark icon or AG monogram
Ring text: "ASSESSED" in tiny 6px JetBrains Mono, around the circle
Animation: rotates in from scale(0) over 300ms with overshoot, enters after the card lands
```
This is a critical touch. It makes the verdict feel OFFICIAL. Like a notary seal on a legal document. It signals: "this is the output of a rigorous process."

**Verdict headline**:
```css
.verdict h3 {
  font-family: 'Cormorant Garamond', serif;
  font-size: clamp(48px, 5.5vw, 80px);
  font-weight: 700;
  line-height: 0.90;
  letter-spacing: -0.02em;
  color: var(--ink);
}
```
Text: `"Scoped yes, with two follow-ups."` — this is already good. Keep it exactly.

Sub-copy below verdict:
```
"The report tells the hiring team what was tested, 
what held up, and where a human interviewer should go next."
```
In DM Sans, 15px, ink at 60% opacity.

**Evidence grid — reduce to 4 key cards**:

Cut from 8 to these 4:
```
┌─────────────────────┬─────────────────────┐
│ ROLE FIT             │ STRONGEST SIGNAL     │
│ Scoped yes          │ Judgment under        │
│                     │ follow-up             │
├─────────────────────┼─────────────────────┤
│ RESUME CALIBRATION  │ FOLLOW-UPS           │
│ Mostly supported    │ 2 actionable          │
│                     │ questions             │
└─────────────────────┴─────────────────────┘
```

These 4 are the hiring team's most critical decisions. Cut the rest.

**Evidence card entry** (after verdict lands):
- Cards enter sequentially: top-left → top-right → bottom-left → bottom-right
- Each 100ms apart, each `translateY(10px) opacity(0)` → `translateY(0) opacity(1)`, 350ms

**Evidence card design**:
```css
.report-item {
  border: 1px solid rgba(243,238,228,0.1);
  border-radius: 22px;
  padding: 22px;
  background: rgba(255,255,255,0.04);
}
/* Card title */
.report-item .title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: rgba(243,238,228,0.5);
  margin-bottom: 12px;
}
/* Card value — the big verdict word */
.report-item .value {
  font-family: 'Cormorant Garamond', serif;
  font-size: 28px;
  font-weight: 700;
  color: var(--cream);
  line-height: 1.0;
}
/* Card body text */
.report-item .body {
  margin-top: 12px;
  font-size: 13px;
  color: rgba(243,238,228,0.62);
  line-height: 1.45;
}
```

**Cursor behavior in report frame**:
- Cursor moves to "Strongest signal" card and lifts it with amber border glow
- This is a deliberate choice: "strongest signal" is the #1 buyer question. The cursor draws attention to it.

**Hero copy**:
```
kicker: "DECISION PACKAGE"
title: "The output is a verdict, not a transcript."
subtitle: "Every statement is bounded: what was tested, what held up, what remains uncertain, and what a human should ask next."
```

---

### FRAME 8 — The Close (`close`)

**Purpose**: Crystallize the whole story and present two clear paths: run the live demo, or see it extended.

**Current problems**: Headline "Experience the full interview loop" is generic. CTAs are two identical pills. No reference to the simulation product.

**Target state**: Show the DUALITY — voice interview and engineering simulation — as two paths. The Aura persists as a closing presence.

**Layout**:
```
┌────────────────────────────────────────────────────┐
│                                                    │
│  ┌───────────────┐     ┌───────────────────────┐  │
│  │               │     │                       │  │
│  │  [Aura 72px]  │     │  One system.          │  │
│  │  [idle state] │     │  Two surfaces.        │  │
│  │               │     │                       │  │
│  │               │     │  Voice interview →    │  │
│  │               │     │  Engineering sim →    │  │
│  │               │     │                       │  │
│  └───────────────┘     │  [ Open live room → ] │  │
│                         │                       │  │
│                         │  [ Simulation demo  ] │  │
│                         └───────────────────────┘  │
│                                                    │
└────────────────────────────────────────────────────┘
```

**Headline**: `"One system. Two surfaces."` — strong. Frames Antigravity as a platform, not a feature.

**Sub-copy**: `"Voice interviews that produce defensible evidence. Engineering simulations that produce observable work. Both resolve into a decision package."`

**The two surface previews** (simple visual callouts):

Voice interview callout:
```
[small Aura 28px] Voice interview
Resume → Live room → Decision package
─────────────────────────────────────
```

Engineering simulation callout:
```
[code icon, 28px] Engineering simulation  
Incident → Real code → Evidence ledger
─────────────────────────────────────
```

**CTAs**:
- Primary: `"Open live room →"` — black background, cream text, full border-radius pill
- Secondary: `"Engineering simulation"` — ghost, cream border

The primary CTA should have a subtle "breathing" animation: `box-shadow` pulses between `0 0 0 0 rgba(243,238,228,0.0)` and `0 0 0 4px rgba(243,238,228,0.16)` on 2s loop. This draws the eye without being distracting.

---

## 06. Motion Grammar — The Complete Specification

### Entry Animations (apply to all elements entering the stage)

```css
/* Standard entry — for cards, panels, rows */
@keyframes enter-standard {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Entry from left — for first cards in a sequence */
@keyframes enter-left {
  from { opacity: 0; transform: translateX(-20px); }
  to   { opacity: 1; transform: translateX(0); }
}

/* Entry from right */
@keyframes enter-right {
  from { opacity: 0; transform: translateX(20px); }
  to   { opacity: 1; transform: translateX(0); }
}

/* The stamp — for official/verdict moments */
@keyframes enter-stamp {
  0%   { opacity: 0; transform: scale(0.88); }
  72%  { opacity: 1; transform: scale(1.04); }
  100% { transform: scale(1.0); }
}
```

All entries use `cubic-bezier(.16, 1, .3, 1)` — fast attack, soft settle. Duration: 380-420ms.

### Stagger Rules

When multiple elements of the same type enter:
- Cards in a row: 90ms between each
- List rows: 70ms between each
- Never stagger more than 6 items — remainder enter together
- Maximum first→last stagger: 450ms total

### The Cursor Specification

The cursor is a key narrative device. It needs more specificity than the current implementation.

**Cursor HTML structure**:
```html
<div class="cursor">
  <div class="cursor-arrow" />
  <div class="cursor-ring" />  <!-- New: hover state ring -->
</div>
```

**Click simulation sequence** (triggered when cursor "arrives" at a target):
```css
@keyframes cursor-click {
  0%   { transform: scale(1); }
  30%  { transform: scale(0.85); }
  65%  { transform: scale(1.05); }
  100% { transform: scale(1.0); }
}
```
Duration: 280ms. Triggered 400ms after cursor stops moving.

**Target element response** (when cursor clicks):
- Element scales `1.0 → 1.025 → 1.0` (180ms)  
- Element border-color brightens for 400ms then settles
- A very faint "ripple" radiates from cursor position (optional but strong)

**Cursor trail** (new):
```css
.cursor-trail {
  position: fixed;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(217,162,77,0.5);
  pointer-events: none;
  animation: trail-fade 400ms ease forwards;
}

@keyframes trail-fade {
  from { opacity: 0.5; transform: scale(1); }
  to   { opacity: 0; transform: scale(0.4); }
}
```
Drop 2-3 trail dots as the cursor moves. This creates a kinetic impression of speed.

### The Spotlight — A New Element

Add a "spotlight" to replace the purely CSS `fake-cursor`. This is a blurred radial gradient that follows the cursor position and highlights the "active" area:

```css
.spotlight {
  position: fixed;
  width: 240px;
  height: 240px;
  pointer-events: none;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(217,162,77,0.06), transparent 70%);
  transform: translate(-50%, -50%);
  transition: all 800ms cubic-bezier(.25,.46,.45,.94);
  mix-blend-mode: screen;
}
```

This creates a soft warm pool of light that follows the cursor's conceptual position. Barely perceptible but subliminally focuses attention.

### Background Atmosphere Shifts Per Stage

The background radial gradients should evolve through the narrative:

- **Stages 1-3** (setup): Background cool, muted. `rgba(193,95,60,0.1)` crail gradient at 72% position (far away).
- **Stages 4-5** (room forms + exchange): Background warms slightly. Crail gradient at 65% position, opacity 0.16. As if the AI's presence is "heating" the room.
- **Stage 6** (live room): Warmest. Crail at 60%, opacity 0.20. The room is ALIVE.
- **Stage 7** (report): Cools back toward neutral. Amber gradient replaces crail — the evidence is delivered, the machine has done its job.
- **Stage 8** (close): Neutral, calm. Both crail and teal at low opacity. Balance.

Implement with CSS transitions on the background-attachment gradients: `transition: background 1200ms ease`.

---

## 07. Copy Refinements — Stage-by-Stage

### The Copy Principle

Following the product brief: **precision over polish.** Every word should earn its place. No AI-language filler. No "powered by" or "seamlessly" or "leverage."

The audience is smart, time-pressed, and skeptical. Short declarative sentences. Active verbs. The copy should tell them what they're watching, not explain why it's impressive.

| Stage | Current title | Recommended title | Why |
|---|---|---|---|
| seed | "Start interview simulation" | `"Start interview simulation"` | Correct, keep |
| problem | "Hiring still relies on weak evidence." | `"Hiring still relies on weak evidence."` | Strong, keep |
| evidence | "The interview starts with role context, not generic questions." | `"The room knows the candidate before the first question."` | More concrete, points to the map prep |
| builder | "The room assembles around the candidate experience." | `"The room assembles itself."` | Shorter, more visual |
| turns | "The floor moves visibly between interviewer and candidate." | `"The floor moves visibly. No guessing who's on."` | Second sentence lands the promise harder |
| room | "The live room makes the interview legible." | `"The live room makes the interview legible."` | Correct, keep |
| report | "The output is a decision package." | `"The transcript becomes a verdict."` | More concrete: input → output transformation |
| close | "One flow: prepare, interview, decide." | `"One system. Two surfaces."` | Reframes Antigravity as platform, not feature |

### Subtitle Refinements

**Problem stage sub**: 
Before: "The resume sounds strong. The interview feels promising. The decision package is often too thin to defend."  
After: `"The claim enters. The room tests it. The report explains what held up."` — three acts, one sentence.

**Turns stage sub**:  
Before: "This is the core interaction promise: no guessing who owns the turn, no hidden state, no awkward dead air."  
After: `"The candidate sees the active question, owns their answer, and can pause, repeat, or correct — without breaking the assessment."` — more candidate-centric, surfaces the key controls.

**Report stage sub**:  
Before: "The report translates the conversation into role fit, strongest signal, claim calibration, coverage, and follow-ups."  
After: `"Every claim is bounded: what was tested, what held up under follow-up, and what a human should clarify next."` — shows epistemics, not a feature list.

### Labels to Replace

| Current label | Replace with | Reason |
|---|---|---|
| `"Candidate corner"` | `"CANDIDATE CORNER"` (all caps) | Should match the turn rail's visual language |
| `"AI interviewer"` | `"AI INTERVIEWER"` (all caps) | Consistency |
| `"Candidate answer live transcription"` | `"LIVE TRANSCRIPTION"` | Shorter, clearer |
| `"Experience assembly"` | `"ASSEMBLING ROOM"` | More active |
| `"Interactive interview demo"` in header | `"INTERVIEW SIMULATION"` | Cleaner, more precise |
| `"Decision package"` kicker | `"DECISION PACKAGE"` (keep) | Already good |

---

## 08. What To Cut — The Subtraction List

These elements should be removed. Each weakens the story.

### Cut: The "Thesis" Stage

The thesis stage ("Antigravity turns the interview itself into the product") covers the same ground as the problem stage and the close stage. It adds a beat to an arc that doesn't need it.

**Action**: Delete this stage. Move the product-loop content (candidate experience + hiring outcome) into the close/CTA frame as a brief summary row.

Result: 8 → 7 stages. Tighter. Faster. No repeated narrative.

### Cut: The "01 / 09" Stage Counter

The `stage-count` display at the bottom of hero copy. This adds a bureaucratic feeling. Investors don't need to know you have 9 slides. Replace with nothing, or with a single stage label pill.

### Cut: Text Nav Buttons

Replace "Previous / Play / Pause / Next / Restart" text buttons with icon-only:
```
[←]  [▮▮] / [▶]  [→]  [↺]
```
This is the kind of detail that separates product people from developers. The text buttons look like they belong in a developer test harness. Icon buttons look like they belong in a product demo.

### Cut: The Builder Console Status Rows

The "Candidate context: loaded / Live room layout: ready / Turn ownership: visible / Decision package: armed" rows look like a deploy log. Replace entirely with the spatial assembly animation described in Frame 4.

### Cut: All Paragraph Text Inside Signal Flow Cards

The paragraph text inside the problem-stage cards is too long to read at demo pace. Cut to one-sentence max. The HEADLINE of each card is what the viewer reads. The paragraph is never read in a 5-second stage.

### Cut: 8 Report Cards → 4

Already specified above. The 8-card grid at demo size is too dense to read. The viewer scans and gets nothing from it. 4 larger cards with the right 4 metrics communicates more clearly than 8 small ones.

### Cut: "Show / Hide stream" and "End interview" from the room controls

These are operational controls, not the message. In the demo context, showing "End interview" as a control says "this can end" — wrong psychological note mid-demo. Show only: "Repeat question" / "Need a moment" / "Fix last term" / "Full transcript".

---

## 09. The 6 Single "One Moment" Per Frame

Each frame should have ONE visual moment that the viewer will remember after closing the tab. If you can't name it for a given frame, the frame needs work.

| Frame | The One Moment |
|---|---|
| Ignition | The cursor clicks the pill and it expands into the full product shell |
| Problem | The cream card (output) is visually dominant — the largest card, the one the cursor lingers on |
| Evidence | The rows appear one-by-one as if being written by the machine, with the Aura in the corner |
| Builder | The room assembles itself spatially around the growing Aura |
| Turns | The floor beam animates from AI to candidate as real question/answer text appears |
| Live Room | The Aura at 180px in full `speaking` state, with the question text in Cormorant at 46px on a pure black card |
| Report | The "Scoped yes, with two follow-ups." headline in Cormorant at 72px, stamped with a notary seal badge |
| Close | "One system. Two surfaces." — the framing that elevates Antigravity from tool to platform |

---

## 10. Implementation Roadmap — Ordered by ROI

Work in this order. Each item is independent and adds value even if later items aren't done.

### Day 1 — Highest Impact (visual before engineering)

1. **Import Cormorant Garamond + JetBrains Mono** — Add Google Fonts import. Apply Cormorant to all `h2` stage titles and the verdict headline. Apply JetBrains Mono to all `.kicker` and `.label` elements. 2-hour change. Immediately distinguishes the demo from every other AI product.

2. **Fix stage body cross-fade** — Wrap body content in a keyed div that re-mounts on stage change. Add `stage-enter` keyframe. Eliminates the hard-cut between stages.

3. **Reduce report cards from 8 → 4** — Simple content cut. Larger, more readable, more impactful.

4. **Enlarge the Aura in the room stage** — Change `size="md"` to `size="lg"` or specify `180px` directly. Immediate improvement to the most important frame.

### Day 2 — Motion Polish

5. **Add staggered entry animations to signal-flow cards** — The three cards entering sequentially (left, bottom, right) instead of simultaneously.

6. **Add sequential row entry to evidence brief** — CSS `animation-delay` stagger on each `.paper-row`.

7. **Make the cursor "click"** — Add click animation to cursor and scale response on target element.

8. **Add Aura to evidence frame and close frame** — Extend the Aura's presence across more stages.

### Day 3 — Stage Redesigns

9. **Redesign the builder stage** — Replace status-log console with spatial assembly animation.

10. **Upgrade the turns stage** — Replace "AI" text box with actual Aura. Add question text and live transcription animation.

11. **Upgrade close stage** — New headline, two-surface layout, refined CTAs.

### Day 4 — Finishing

12. **Add the seal badge to the report verdict** — The circular badge appearing on the cream card.

13. **Background atmosphere shifts** — Subtle crail glow intensification during room stages.

14. **Replace text nav buttons with icons** — Small polish that signals product maturity.

15. **Cut the thesis stage** — Reduces 9 → 8 → effectively 8 stages. Tightens the arc.

---

## 11. Reference Comparisons — What Each Benchmark Does

### What Claude's Demo Does Right

Claude's "computer use" and "artifacts" demos show the system DOING something — the cursor moves, text appears, a result materializes. The ACTION is the explanation. You understand what Claude does from watching 10 seconds without reading a word.

**Lesson for Antigravity**: The room assembly frame (Frame 4) and the turns frame (Frame 5) need to show the system DOING its core thing, not illustrate it with diagrams.

### What Base44 Does Right

Base44 shows a cursor selecting text, the AI completing it, then a deployed app appearing. The speed is high. Cuts are fast. Every 3 seconds something new is ON SCREEN. The product is shown at near-full fidelity.

**Lesson for Antigravity**: The room frame (Frame 6) should be at full product fidelity. Don't simplify the UI for the demo — show the real thing. Trust that complexity signals depth, not confusion.

### What ElevenLabs Does Right

The waveform IS the product. When you hear the voice and see the waveform respond in real time, you understand the product immediately. The Aura is Antigravity's equivalent of the ElevenLabs waveform.

**Lesson for Antigravity**: The Aura should be as prominent in this demo as a waveform is in an ElevenLabs demo. It is the "living" element that makes the AI feel present. It should never be in a corner. It should have its own moment.

### What Suno Does Right

Suno's demo shows a typed genre prompt → a click → a full song playing. The gap between input and output is compressed to seconds. This creates genuine surprise.

**Lesson for Antigravity**: The evidence frame (Frame 3) should create the same feeling. A resume claim enters → in seconds, a fully formed interview plan is on screen → the live room activates. Compress the input→output gap visually.

### What Linear Does Right

Linear shows their product at full speed, as a real user would use it. The UI doesn't slow down for the viewer. Transitions are smooth, actions are purposeful. It signals: "the product is this fast. This is not a simplified demo."

**Lesson for Antigravity**: The live room frame (Frame 6) should show the actual components at actual density. The question at full size. The controls all visible. The history panel visible. This signals to an investor: "the product UI is this good. We built this."

---

## 12. The Single Most Important Recommendation

If you implement one thing from this document:

**Import Cormorant Garamond and apply it to `h2` stage titles and the report verdict.**

"Scoped yes, with two follow-ups." in Cormorant Garamond at 72px on a cream background is the moment that will make an investor stop scrolling. It is the moment the product says: *"This is an institution, not a chatbot. We take hiring seriously. We take evidence seriously. And we have the elegance to say so in the most precise, authoritative typography available."*

Typography is the cheapest high-leverage change in frontend design. One import. One font-family change. The entire demo shifts register.

Everything else in this document builds on top of that foundation.

---

*End of dossier.*

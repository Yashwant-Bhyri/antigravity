# Antigravity Demo Variant Intention Brief

Prepared for: Yash, multimodal UI reviewers, consulting/product advisors, and future implementation agents  
Date: 2026-06-09  
Scope: Four parallel interactive demo routes for the Antigravity investor/internal product story

This document explains the intention behind each current demo variant, what each version was supposed to prove, what UI translations should be visible on screen, and how a multimodal reviewer should evaluate the real screenshots against the intended design.

The four variants are intentionally separate. They should not be blended yet. The purpose of this comparison pool is to learn from distinct source directions, then later combine the best ideas into a final high-signal product demo.

Routes:

- `/visualizer-interview-demo-flash`
- `/visualizer-interview-demo-cursor`
- `/visualizer-interview-demo-claude`
- `/visualizer-interview-demo-dossier`

Source files:

- `/Users/yash/antigravity/app/visualizer-interview-demo-flash/page.tsx`
- `/Users/yash/antigravity/app/visualizer-interview-demo-cursor/page.tsx`
- `/Users/yash/antigravity/app/visualizer-interview-demo-claude/page.tsx`
- `/Users/yash/antigravity/app/visualizer-interview-demo-dossier/page.tsx`

Related strategy/design references:

- `/Users/yash/antigravity/ANTIGRAVITY_PRODUCT_STRATEGY_AND_DEMO_BRIEF.md`
- `/Users/yash/antigravity/DEMO_DESIGN_DOSSIER.md`
- `/Users/yash/Downloads/claude-PLAN copy.md`
- `/Users/yash/Downloads/claude-UI- PLAN .md`

---

## 1. Why These Variants Exist

Antigravity is difficult to explain with a static pitch deck because the product value is experiential. The product is not simply "AI interviews candidates." The actual claim is stronger:

Antigravity turns a resume claim into live-tested hiring evidence.

That means the demo must make the viewer feel the transformation:

1. A candidate has a claim on paper.
2. The system prepares a role-specific assessment room.
3. The AI interviewer asks from the candidate's actual answer, not a static script.
4. The candidate always understands whose turn it is and what is being asked.
5. The hiring team receives a bounded decision package, not a transcript dump.
6. For engineering roles, the same evidence-first philosophy extends into realistic simulations with real code/test actions.

The variants test different ways of making that transformation visible:

- Variant 1 tests the baseline narrative structure.
- Variant 2 tests cursor-driven interaction and state ownership.
- Variant 3 tests sharper product copy and claim-to-evidence choreography.
- Variant 4 tests a more distinctive premium brand register and "assessment room" aesthetic.

The final product demo will likely combine the strongest elements of all four.

---

## 2. Shared Product Story All Variants Must Serve

The common story is:

Resume claim -> live pressure -> structured evidence -> hiring decision.

The demo should not become a generic AI product animation. It should not be a "cool dark UI" that could belong to any AI company. Every scene should help the viewer understand one of the following product truths:

- Resumes are insufficient evidence.
- Generic interviews are inconsistent.
- Static tests miss live judgment, recovery, communication, and tradeoffs.
- Antigravity starts from role and resume context.
- The live room is designed for clarity under pressure.
- Turn ownership is explicit.
- Live transcription is current utterance only, not committed history.
- Turn history is committed context, not live transcription.
- The report is a decision package, not a transcript.
- The engineering simulation workbench extends the same evidence-first model into real work.

The viewer should come away with:

- "I understand what Antigravity does."
- "I understand why it is different from a normal AI interviewer."
- "I can see the product quality."
- "I can imagine an investor, HR buyer, or technical hiring leader taking this seriously."

---

## 3. Evaluation Lens For The Multimodal Agent

For each screenshot or video capture, evaluate against these axes:

1. Narrative clarity
   - Can the viewer tell what is happening without reading paragraphs?
   - Does the frame show an action, or only describe an action?

2. Product specificity
   - Does the frame feel uniquely Antigravity?
   - Does it show resume-grounded interviews, turn ownership, live answer capture, report evidence, or simulation work?

3. Visual hierarchy
   - Is there one dominant thing per frame?
   - Does the user's eye know where to land first?
   - Are secondary elements supportive rather than competitive?

4. Motion purpose
   - Does motion explain state, sequence, causality, or interaction?
   - Or is motion merely decorative?

5. Candidate trust
   - Does the live room feel serious and clear?
   - Does it avoid surveillance/interrogation vibes?
   - Are candidate controls visible but not overbearing?

6. Buyer impact
   - Does the report moment feel valuable?
   - Does the demo show why the output is defensible?
   - Does it avoid generic claims like "AI-powered" without proof?

7. Aesthetic maturity
   - Does it feel like state-of-the-art product communication?
   - Does it avoid looking like a PowerPoint, internal dashboard, or debug harness?

8. Technical believability
   - Does the UI look like a product that could really exist?
   - Do cursor motions, hover states, typing, progress, and component transitions feel synchronized?

---

# Variant 1: Flash Baseline

Route: `/visualizer-interview-demo-flash`  
Source: `/Users/yash/antigravity/app/visualizer-interview-demo-flash/page.tsx`

## 1. Core Intention

The flash version was created as the first full internal/investor demo skeleton. Its purpose was to establish the end-to-end product story in a compact interactive sequence.

This variant asks:

Can we show the whole Antigravity loop in one guided visualizer?

It is not primarily a brand experiment or a cursor mechanics experiment. It is the baseline product narrative:

1. Start the simulation.
2. Explain the hiring evidence problem.
3. Introduce Antigravity's product loop.
4. Show role/context setup.
5. Show the room being built.
6. Show turn ownership.
7. Show the live room.
8. Show the report.
9. Close with prepare/interview/decide.

The intended viewer is an internal stakeholder, investor, HR buyer, or advisor who needs to quickly understand the entire product arc.

## 2. Intended Positioning

This version positions Antigravity as:

An AI interview system that turns live conversation into decision evidence.

The emphasis is not on "AI magic." It is on a structured assessment loop:

- Candidate context enters.
- The interview room is configured.
- The AI interviewer and candidate exchange turns.
- The UI makes the live interview legible.
- The final report explains role fit, strongest signal, tested strengths, risks, coverage, and follow-ups.

## 3. Intended UI Translation

The UI was supposed to translate the product thesis into a staged visual loop:

### Seed

Intention:

- Minimal product-start gesture.
- A small centered control that invites the viewer to start the interview simulation.

What should be visible:

- A central pill/button.
- Low ambient background.
- A fake cursor or guided demo affordance.
- The user should feel: "I am about to watch a product do something."

Risk:

- If the seed is too plain, it feels like a loading screen.
- If it is too decorative, it feels like marketing fluff.

### Problem

Intention:

- Establish that hiring still relies on weak evidence.
- Set up the pain before showing the product.

What should be visible:

- A strong headline.
- A few signal cards or visual examples showing the gap between resume claims, interview impressions, and thin decision packages.

What should not happen:

- The frame should not become a long text explanation.
- It should not feel like a generic HR pitch.

### Product Loop / Thesis

Intention:

- Show that the interview itself becomes the product experience.
- Connect candidate experience to hiring-team evidence.

What should be visible:

- A loop or multi-zone product model.
- Candidate side and hiring team side should both be represented.
- The viewer should understand that Antigravity is not only a candidate UI; it produces buyer-facing evidence.

Risk:

- This stage may duplicate the problem and close stages.
- If it becomes abstract, it can feel like a pitch slide.

### Setup / Evidence

Intention:

- Show that Antigravity starts from role context, not generic questions.

What should be visible:

- Candidate identity.
- Role.
- Experience context.
- Decision goal.
- Interview map/evidence packet.

Best visual metaphor:

- A structured brief or evidence card.
- It should feel generated/prepared, not pasted.

### Room Build

Intention:

- Show all components of the interview room landing into one coherent system.

What should be visible:

- AI interviewer presence.
- Candidate corner.
- Anchored question.
- Live transcription.
- Turn history.
- Decision report output.

Original translation:

- Component list/cards describing AI interviewer, candidate corner, anchored question, live transcription, turn history, and decision report.

Issue to evaluate:

- Does this look like the room is assembling, or merely like cards listing features?

### Turns

Intention:

- Make "floor ownership" visible.

What should be visible:

- AI/interviewer side.
- Candidate side.
- A central turn rail or beam.
- The active side should glow or receive emphasis.

Core product promise:

- No guessing who owns the turn.
- No hidden state.
- No awkward dead air.

The frame should make turn-taking feel like a product capability, not a label.

### Live Room

Intention:

- Show the actual interview interface as a premium assessment room.

What should be visible:

- Left AI interviewer presence/Aura.
- Center current question.
- Live answer/transcription under the question.
- Candidate controls.
- Right camera/history panel.

The candidate should appear oriented, not watched.

The interviewer should appear present, not human-faked.

### Report

Intention:

- Show that the output is a decision package.

What should be visible:

- Role fit.
- Strongest signal.
- Interview quality.
- Resume claim calibration.
- Tested strengths.
- Scoped tested risks.
- Knowledge coverage.
- Recommended follow-ups.

Original translation:

- 8 report cards.

Issue to evaluate:

- Does the density help or hurt?
- Can the viewer read the payoff fast enough?

### Close

Intention:

- Resolve the loop: prepare, interview, decide.

What should be visible:

- Final CTA.
- Serious but concise platform promise.

## 4. What This Variant Does Best

The flash baseline is the best "table of contents" for the entire Antigravity story. It has the broadest coverage of product ideas:

- Problem.
- Product loop.
- Setup.
- Room build.
- Turn ownership.
- Live room.
- Report.
- Close.

It is useful because it gives later variants a structural spine.

## 5. Main Weaknesses To Watch

1. It can feel like a moving pitch deck.
2. It sometimes describes components instead of showing them.
3. The product loop/thesis stage may be redundant.
4. The report card grid can be too dense.
5. The cursor may feel decorative if it does not cause visible UI response.
6. The Aura may not be central enough as the AI presence.

## 6. Review Questions For Screenshots

Ask the multimodal agent:

- Which stage feels most like a real product action?
- Which stage feels most like a slide?
- Does the report frame land as the payoff?
- Is the live room credible and legible?
- Does the turn ownership frame visibly explain who is speaking?
- What should be cut to make the sequence feel faster?
- Which component should become the dominant visual in each frame?

## 7. What To Potentially Harvest Into Final

Harvest:

- Overall stage skeleton.
- Full product arc from problem to report.
- Live room component inventory.
- Report fields.
- Prepare/interview/decide loop.

Avoid copying directly:

- Overly dense report grid.
- Feature-list style room build.
- Any frame where text is doing more work than UI action.

---

# Variant 2: Cursor / Multimodal-Agent Mechanics Version

Route: `/visualizer-interview-demo-cursor`  
Source: `/Users/yash/antigravity/app/visualizer-interview-demo-cursor/page.tsx`

## 1. Core Intention

The cursor version was created in response to the multimodal agent's critique that the synthetic cursor should not be decorative. The core idea was:

The cursor should drive the demo.

This variant asks:

Can a synthetic cursor make the UI feel interactive, causal, and product-like instead of slide-like?

The source philosophy came from the multimodal agent's detailed technical dossier around:

- Synthetic cursor mechanics.
- Bounding-box targeting.
- Collision-driven active states.
- Sibling defocus.
- Cursor as guided narrator.
- Interaction as explanation.

In this version, the cursor is not just a pointer moving through a presentation. It is supposed to be the thing that activates the product story.

## 2. Intended Positioning

This version positions Antigravity as:

A product whose internal intelligence can be understood through interaction.

The viewer should feel:

- The UI is responding to the cursor.
- The cursor selects evidence.
- Cards lift and defocus.
- The product loop is not static; it is being operated.
- The demo behaves like a real app being used.

## 3. Intended UI Translation

The UI translation was supposed to be more "interaction-theater" than "deck."

### Seed

Intention:

- A guided product loop begins.
- Cursor establishes itself as narrator.

What should be visible:

- Cursor enters.
- A central start object responds to click/hover.
- The UI should not feel like auto-advancing slides.

### Problem

Intention:

- Show claim, live test, and output as a sequence of selectable cards.

What should be visible:

- Three cards:
  - Resume claim: "Owned launch analytics."
  - Live test: "Metric drop under follow-up."
  - Output: "Scoped yes + follow-ups."
- Cursor visits each.
- Active card lifts.
- Inactive siblings dim or scale down.

The intended interaction:

- Cursor lands on first card -> first card becomes active.
- Cursor moves to second -> second becomes active, first recedes.
- Cursor moves to third -> output card becomes the payoff.

This card sequence is critical. It should not look like arrows or lines are the main subject. The main subject is the cursor selecting evidence states.

### Product Loop

Intention:

- Show Antigravity as a loop connecting candidate experience and hiring output.

What should be visible:

- Zones for candidate, interview, report, and evidence.
- Cursor should highlight the next meaningful area.

Potential problem:

- If the loop is too abstract, it becomes a diagram.

### Setup

Intention:

- Role context becomes the first constraint.

What should be visible:

- Candidate context.
- Role.
- Decision goal.
- Evidence packet.

Cursor role:

- It should indicate where data enters the system.

### Build

Intention:

- The live room assembles before the call starts.

What should be visible:

- Components moving into place:
  - Interview presence.
  - Turn ownership.
  - Candidate controls.
  - History.
  - Report output.

Cursor role:

- Potentially dragging/activating build modules.

### Turns

Intention:

- The cursor helps explain floor movement.

What should be visible:

- AI side.
- Candidate side.
- A floor/turn rail.
- Cursor moves between zones.
- Active zone lights up.

The key visual promise:

- Turn state is spatial.
- The viewer should understand turn-taking without needing a paragraph.

### Room

Intention:

- Show the actual room while cursor points at components.

What should be visible:

- Anchored question.
- Live transcription.
- Camera/history.
- Controls.
- Turn rail.

Cursor role:

- It should pause on meaningful components.
- Hovered controls should visually respond.

### Report

Intention:

- Cursor highlights the decision package and strongest evidence.

What should be visible:

- Verdict.
- Report cards.
- Strongest signal card should receive focus.

Cursor role:

- It should make the report feel inspectable, not static.

## 4. What This Variant Does Best

This variant is the best one for testing "demo as interaction."

Its strongest contributions:

- Cursor as narrative driver.
- Cards responding to cursor state.
- Active/inactive contrast.
- Product causality: the viewer sees the cursor select/trigger parts of the product.
- Less dependence on explanatory copy.

## 5. Main Weaknesses To Watch

The risk is precision.

If the cursor is even slightly misaligned, mistimed, or visually weird, the viewer will notice. A synthetic cursor is high-risk/high-reward:

- Good cursor = premium product demo.
- Bad cursor = fake, clumsy, distracting.

Specific risks:

1. Cursor floats without causing state changes.
2. Cursor appears to point at wrong coordinates.
3. Active card timing does not match cursor hover.
4. Sibling defocus is too weak, so focus does not land.
5. The cursor becomes the star instead of Antigravity.
6. The route may still lack the aesthetic refinement of the dossier version.

## 6. Review Questions For Screenshots

Ask the multimodal agent:

- Does the cursor clearly drive state changes?
- Do cards lift exactly when the cursor reaches them?
- Is sibling defocus strong enough?
- Does the interaction feel human and intentional?
- Are there any "ghost cursor" moments where the cursor and UI disagree?
- Does cursor movement clarify the product, or distract from it?
- Which cursor-driven moments should be brought into the final version?

## 7. What To Potentially Harvest Into Final

Harvest:

- Cursor-driven card focus.
- Active/sibling defocus pattern.
- A real hover response for controls.
- Cursor as tour guide through the live room.
- Cursor highlighting report evidence.

Avoid copying directly:

- Any hardcoded cursor movement that does not scale.
- Any stage where cursor motion is cosmetic.
- Any UI state not synchronized with cursor presence.

---

# Variant 3: Claude-Plan Copy / Choreography Version

Route: `/visualizer-interview-demo-claude`  
Source: `/Users/yash/antigravity/app/visualizer-interview-demo-claude/page.tsx`  
Source inspiration: `/Users/yash/Downloads/claude-PLAN copy.md`

## 1. Core Intention

The Claude-plan version was created from the first Claude source document. Its purpose was to sharpen the narrative and copy around what Antigravity actually does.

This variant asks:

Can the demo say the right thing, in the right order, with enough product specificity?

It is less about final visual identity and more about narrative structure:

- A resume claim is not evidence.
- The interview starts from the resume, not a template.
- Role context and resume evidence prepare the room.
- The next question comes from what the candidate just said.
- The live room makes the interview legible.
- The interview becomes evidence.
- Engineering simulation extends the same logic to real work.

## 2. Intended Positioning

This version positions Antigravity as:

A claim-to-evidence engine.

The key idea is:

Antigravity does not automate interviews. It converts ambiguous claims into observable evidence.

That is more precise and more defensible than "AI interviewer."

## 3. Intended UI Translation

The UI translation was supposed to follow a clear causal chain:

### Seed

Intention:

- Start interview simulation.

What should be visible:

- Minimal start object.
- The demo begins like an interactive product sequence.

### Claim

Intention:

- The core thesis: a resume claim is not evidence.

What should be visible:

- Claim enters.
- Live question tests it.
- Decision evidence emerges.

The frame should feel like a before/during/after transformation.

Current intended copy:

- "A resume claim is not evidence. This is."
- "Owned launch analytics."
- "How would you separate a real conversion drop from instrumentation noise?"
- "Scoped yes - 2 follow-ups."

### Brief

Intention:

- Show that the interview starts with the candidate, not a generic template.

What should be visible:

- Candidate.
- Role.
- Experience signal.
- Claim under test.
- Live scenario.
- Session goal.

This is a strong frame because it shows specificity.

The viewer should think:

"This system knows who is being interviewed and what evidence it needs."

### Assembly

Intention:

- Show preparation of the room.

Original translation:

- Terminal-like build lines:
  - Reading resume evidence.
  - Extracting claim surfaces.
  - Selecting test scenarios.
  - Calibrating turn cadence.
  - Preparing room handoff.

What this was supposed to convey:

- The system is actively constructing the interview map.
- The map is not a template.

Risk:

- Terminal lines may feel too technical or too much like a log.
- It may describe work instead of showing work.

### Turn

Intention:

- Show the core live interview intelligence:

The next question comes from what the candidate just said.

What should be visible:

- AI interviewer.
- Candidate.
- Turn rail.
- Question typing in.
- Candidate answer typing in.
- Floor transfer from AI to candidate.

This is one of the most important stages.

It should visually prove:

- The interview is adaptive.
- The candidate is not trapped in a script.
- The AI asks grounded follow-ups.

### Room

Intention:

- Show the actual room and its components:

  - AI presence.
  - Anchored question.
  - Live answer.
  - Candidate controls.
  - Camera/history.

What should be visible:

- The room is legible.
- The components are separated.
- The question remains central.
- The transcript does not dominate.

### Report

Intention:

- Show that the interview became evidence.

What should be visible:

- Verdict.
- Role fit.
- Strongest signal.
- Resume claim calibration.
- Recommended follow-ups.

The report should not feel like a transcript viewer. It should feel like a decision artifact.

### Simulation

Intention:

- Expand Antigravity beyond voice interviews into engineering simulation.

What should be visible:

- Test failure.
- Code/reasoning action.
- Evidence trail.

The point is:

The same evidence-first assessment model applies to realistic work.

### Close

Intention:

- Resolve the story:

Claim -> live test -> decision evidence.

What should be visible:

- Clear CTA.
- Final product thesis.

## 4. What This Variant Does Best

This is the best copy/narrative variant.

Strongest contributions:

- "A resume claim is not evidence. This is."
- "The next question comes from what they just said."
- "The interview became evidence."
- Inclusion of simulation/workbench as part of the story.
- Stronger focus on claim-to-evidence transformation.
- Less generic HR language.

## 5. Main Weaknesses To Watch

1. It may not yet have enough brand distinctiveness.
2. Some stages may still be static.
3. Assembly can feel like a terminal log.
4. The Aura is present but not yet the visual protagonist.
5. It may need stronger visual asymmetry.
6. It may not yet feel "premium institution" enough for investor memory.

## 6. Review Questions For Screenshots

Ask the multimodal agent:

- Does the copy clearly explain Antigravity's difference?
- Which phrase lands hardest?
- Which stage still feels generic?
- Does the claim-to-evidence transformation visually read?
- Does the simulation stage feel connected or tacked on?
- Does the room stage look like the actual product?
- What one visual action should replace the assembly terminal log?

## 7. What To Potentially Harvest Into Final

Harvest:

- Core copy.
- Claim/live-test/evidence sequence.
- Simulation stage.
- Adaptive follow-up framing.
- Concise product explanation.

Avoid copying directly:

- Any stage that is only a static card.
- Builder status text that explains instead of showing.
- Generic labels that could belong to any AI interviewer.

---

# Variant 4: Design Dossier / Assessment-Room Version

Route: `/visualizer-interview-demo-dossier`  
Source: `/Users/yash/antigravity/app/visualizer-interview-demo-dossier/page.tsx`  
Source inspiration: `/Users/yash/antigravity/DEMO_DESIGN_DOSSIER.md` and `/Users/yash/Downloads/claude-UI- PLAN .md`

## 1. Core Intention

The dossier version was created to test a more distinctive visual and emotional register.

This variant asks:

Can Antigravity feel like a premium assessment institution rather than another AI SaaS demo?

This is the brand/aesthetic experiment. It tries to move the product out of the generic dark-mode AI space by using:

- Cormorant Garamond for verdict/stage authority.
- JetBrains Mono for machine precision.
- DM Sans for readable body copy.
- Cream paper surfaces for human-legible evidence.
- Aura as a recurring living AI presence.
- A more official "decision package" report moment.
- A closing platform thesis: one system, two surfaces.

The intended tone:

- Serious.
- Controlled.
- Premium.
- Warm at the right moments.
- Not playful.
- Not generic.
- Not surveillance-heavy.

## 2. Intended Positioning

This version positions Antigravity as:

A precision instrument for high-stakes hiring evidence.

It is meant to feel more like:

- A private equity conference room.
- A surgical instrument tray.
- A research visualization.
- A formal assessment artifact.

And less like:

- Startup dashboard.
- Chatbot UI.
- Generic AI animation.
- PowerPoint deck.

## 3. Intended UI Translation

### Seed

Intention:

- The system begins as a living object.
- The Aura is present from the first moment.

What should be visible:

- A centered seed pill.
- Aura icon inside the pill.
- "Start interview simulation."
- Subcopy: "Observe a Product Analyst being assessed."

The seed should feel like an ignition, not a button.

### Problem / Claim

Intention:

- Establish the market gap with authority.

Current title:

- "Hiring still relies on weak evidence."

Intended visual:

- A signal chain:
  - Resume claim.
  - Live question.
  - Decision evidence.

Compared with the Claude version, this should feel more designed and more official.

The output card should ideally dominate. The viewer should feel the transformation from weak claim to bounded evidence.

### Evidence Brief

Intention:

- Show the room knows the candidate before the first question.

UI translation:

- Cream evidence paper.
- Rows appear/scanned sequentially.
- Aura in the top-right corner as "Preparing room."

This is supposed to make map prep feel like an intelligent preparation process, not a static settings page.

The cream surface matters:

- In this design language, cream means human-legible output or evidence.
- It should not dominate every frame.
- It should be reserved for important artifacts.

### Room Assembly

Intention:

- Replace builder logs with spatial assembly.

UI translation:

- Aura is central.
- Components land around it:
  - AI interviewer presence.
  - Turn rail and floor ownership.
  - Anchored question and live answer.
  - History and report contract.

The stage should feel like the room is forming around the intelligence.

This is one of the most important differences from earlier versions.

### Floor Transfer

Intention:

- Make turn ownership emotionally and spatially clear.

UI translation:

- AI side with Aura.
- Candidate side with avatar.
- Central turn rail.
- AI question types in.
- Candidate answer types in.
- Active side glows.

The title is:

- "The floor moves visibly. No guessing who is on."

This should be evaluated for:

- Does the viewer know whose turn it is?
- Does the turn movement feel like an interaction, not a diagram?
- Does the candidate side feel calm and safe?

### Live Room

Intention:

- Full product fidelity with stronger Aura presence.

UI translation:

- Left panel: larger Aura, speaking state.
- Center: turn rail, pitch-black question card, live answer strip, controls.
- Right: candidate camera and history.

The room should show:

- AI interviewer presence without a fake face.
- Anchored question.
- Live transcription separated from committed history.
- Candidate controls.
- Candidate corner.

This version intentionally makes the Aura larger than in previous versions, because the dossier argues that the Aura is Antigravity's equivalent of the ElevenLabs waveform: the living visual identity of the product.

### Decision Package

Intention:

- Make the report feel like a formal verdict.

UI translation:

- Cream verdict card.
- Cormorant Garamond headline:
  - "Scoped yes, with two follow-ups."
- Seal badge.
- Four supporting report cards:
  - Role fit.
  - Strongest signal.
  - Resume claim calibration.
  - Recommended follow-ups.

This is intentionally less dense than the flash version.

The report should feel like:

- A notary seal.
- A formal evidence artifact.
- A serious hiring decision package.

It should not feel like:

- A generic analytics dashboard.
- A long transcript summary.
- A pile of metrics.

### Simulation

Intention:

- Show that Antigravity has a second surface beyond voice interviews.

UI translation:

- Terminal/test failure.
- Payment retry bug.
- Idempotency fix comment.
- Real-work evidence.

This is a teaser, not the full simulation product.

### Close

Intention:

- Reframe Antigravity as a platform.

UI translation:

- "One system. Two surfaces."
- Voice interview:
  - Resume -> live room -> decision package.
- Engineering simulation:
  - Incident -> real code -> evidence ledger.
- Aura persists as a final presence.

This closing is stronger than "prepare, interview, decide" because it makes Antigravity feel larger than one interview UI.

## 4. What This Variant Does Best

The dossier version is the strongest visual identity candidate.

Strongest contributions:

- Serif verdict/report typography.
- Premium assessment-room tone.
- Aura continuity.
- Cream paper as evidence metaphor.
- Report payoff feels more official.
- Stronger close: "One system. Two surfaces."
- Less generic AI SaaS feel.

## 5. Main Weaknesses To Watch

1. It may become too theatrical if not tuned.
2. Cormorant can feel elegant, but if overused it may reduce software sharpness.
3. The Aura can become too dominant if it competes with the question.
4. Cream paper can feel Claude-adjacent if overused.
5. The report seal could feel gimmicky if not subtle.
6. Assembly still needs to feel like real product action, not decorative component landing.
7. If the live room is simplified too much, it loses product credibility.

## 6. Review Questions For Screenshots

Ask the multimodal agent:

- Does this feel distinct from Claude and other AI demos?
- Does the typography improve authority or feel too editorial?
- Does the report frame land hardest among all variants?
- Is the Aura a living product identity or a visual distraction?
- Does the cream evidence metaphor work?
- Does the room feel premium and serious?
- Which parts feel too theatrical or too slow?
- Does "One system. Two surfaces." land as a platform thesis?

## 7. What To Potentially Harvest Into Final

Harvest:

- Typography hierarchy.
- Report verdict treatment.
- Aura continuity.
- Cream evidence/paper metaphor.
- One-system/two-surfaces platform close.
- Stronger "assessment room" tone.

Avoid copying directly:

- Overuse of serif.
- Overuse of cream.
- Any theatrical motion that slows down the demo.
- Any visual treatment that feels too close to Claude.

---

# Cross-Variant Comparison

## 1. Which Variant Owns Which Strength

| Variant | Primary strength | Best use in final |
|---|---|---|
| Flash baseline | Complete product story skeleton | Overall stage arc and product coverage |
| Cursor version | Interaction mechanics and cursor-driven focus | Cursor behavior, hover states, card focus, UI causality |
| Claude-plan version | Sharpest product copy and claim-to-evidence story | Stage copy, narrative beats, simulation inclusion |
| Dossier version | Strongest brand register and report payoff | Typography, Aura continuity, verdict/report aesthetic |

## 2. Likely Final Direction

The final demo should probably combine:

- Flash's full end-to-end structure.
- Cursor's interaction discipline.
- Claude-plan's copy clarity.
- Dossier's visual authority.

In practical terms:

1. Use the flash route as the basic sequence.
2. Replace generic stage copy with Claude-plan/dossier copy.
3. Use cursor-driven card focusing from the cursor version.
4. Use Cormorant/JetBrains/DM Sans selectively from the dossier version.
5. Make the Aura a recurring narrative object.
6. Make the report frame less dense and more official.
7. Make the live room more product-faithful.
8. Make the simulation stage a real teaser of workbench evidence.

## 3. What The Final Demo Must Avoid

Avoid:

- Looking like a PowerPoint.
- Looking like Claude copied too literally.
- Generic "AI-powered" language.
- Overly technical architecture terms in investor-facing frames.
- Revealing candidate-hidden assessment internals.
- Report cards too small to read.
- Cursor motion that does not trigger UI response.
- Aura as decorative ornament.
- Live room layout that is too simplified or too cramped.
- Any frame where the viewer must read a paragraph to understand the action.

## 4. What The Final Demo Must Nail

The final demo must nail these five moments:

1. Start
   - The user clicks into a living product, not a slide deck.

2. Claim to live test
   - A resume claim visibly becomes a tested question.

3. Floor transfer
   - The viewer instantly sees AI turn vs candidate turn.

4. Live room
   - The product looks real, clear, premium, and candidate-safe.

5. Report
   - The output feels like a defensible decision artifact.

If those five moments work, the demo can carry the product story.

---

# Suggested Multimodal-Agent Prompt

Use this prompt when showing screenshots or recordings to the multimodal agent:

```
You are reviewing four separate Antigravity interactive demo variants.

Do not judge them as finished products. Judge them against their intended purpose.

The variants are:
1. Flash baseline: meant to establish the full product narrative skeleton.
2. Cursor version: meant to test cursor-driven interaction and UI causality.
3. Claude-plan version: meant to test sharper claim-to-evidence copy and choreography.
4. Dossier version: meant to test premium assessment-room brand, Aura continuity, and report payoff.

For each screenshot or recording, evaluate:
- Does it achieve its stated intention?
- What is the strongest visible moment?
- What is the weakest visible moment?
- Does the screen show product action or just explain product action?
- Does visual hierarchy guide the eye?
- Does the cursor, if present, actually drive UI state?
- Does the Aura feel like a living AI presence or decoration?
- Does the live room feel credible and candidate-safe?
- Does the report feel like a decision package, not a transcript summary?
- What should be harvested into the final version?
- What should be cut?

Be brutally specific. Reference visible UI details, spacing, typography, motion, layout, and copy.
Do not give generic praise. Give actionable diagnosis.
```

---

# Recommended Next Iteration After Review

After the multimodal agent reviews screenshots/videos with this document:

1. Make a decision matrix.
   - Rows: major demo moments.
   - Columns: four variants.
   - Mark which variant wins each moment.

2. Decide the final route's skeleton.
   - Most likely: flash or Claude-plan sequence.

3. Decide the final visual language.
   - Most likely: dossier typography/report treatment, but moderated.

4. Decide the final interaction language.
   - Most likely: cursor version's focus/hover discipline, but with less technical rigidity.

5. Build a fifth route, not an overwrite.
   - Suggested route: `/visualizer-interview-demo-synthesis`.

6. Only after synthesis works, retire or archive weaker variants.

---

# Closing Position

These four variants are not competing as "which one is right." They are testing different hypotheses:

- Flash asks: Is the story complete?
- Cursor asks: Does interaction make the story believable?
- Claude-plan asks: Is the claim-to-evidence narrative sharp enough?
- Dossier asks: Does the product feel like a premium assessment institution?

The final Antigravity demo should answer yes to all four.


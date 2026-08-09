# Cross-world adversarial audit

Status: five structurally ambitious exploratory worlds; none accepted as gold.

## What the set covers well

The set spans product analytics, backend engineering, data science, junior full-stack engineering, and senior product management. It varies level, speech behavior, correction shape, ownership topology, and type of emergent evidence:

- concise analytical speech with downstream product-rule ownership;
- defensive scope correction with strong service correctness;
- fluent abstraction with predictive depth and causal weakness;
- nervous short answers with bounded junior debugging evidence;
- persuasive senior narrative with numerical supersession and portfolio opportunity cost.

Across all worlds, frozen truth is separated from behavior; owned and unowned layers are explicit; protected details have safe abstractions; reports can distinguish weakness, uncertainty, untested dimensions, and interviewer failure; and representative junctions permit multiple move families.

That breadth is useful for a capability trial. It is not evidence that the worlds are representative of candidates or hiring.

## Missing behaviors and realities

The set omits many important candidate realities:

- English-language translation difficulty, code-switching, or culturally different conversational norms.
- A candidate who rambles through irrelevant but true detail without fluent technical polish.
- Memory uncertainty where the exact number or sequence cannot be recovered during the interview.
- Deliberate deception as frozen truth, as distinct from compression, overclaim, or correction.
- A candidate who becomes angry, disengages, refuses the premise, or ends the interview.
- A candidate who asks excellent clarifying questions before answering.
- A candidate whose strongest evidence comes from failure without a clean remediation.
- A candidate with broad but average competence and no dramatic emergent surface.
- A candidate whose resume is sparse because of confidentiality, caregiving, career break, contracting, or nontraditional work.
- A candidate with a disability explicitly modeled with consent and domain expertise.
- Hardware, mobile, security, design, research, sales, operations, finance, clinical, or public-sector roles.
- Group, pair, or work-sample interview behavior.
- Interviewer interruptions, ASR mistakes, poor audio, and repairs not caused by candidate knowledge.
- A world where the candidate's correction is wrong or incomplete and later corrected again.

These omissions prevent claims of broad coverage.

## Role overfitting

The roles cluster around software and data products with artifacts that map cleanly to modern tech interviews: metrics, state machines, models, React bugs, portfolio tradeoffs. Even the PM and analyst worlds are highly legible to a technical product organization. The set may overvalue candidates who can narrate artifacts in those terms and underrepresent operational, relational, craft, or tacit expertise.

Each world has a conveniently assessable core mechanism. Real interviews often contain ambiguous, partial, or mundane evidence that does not resolve cleanly. Domain reviewers should add ordinary average work and inconclusive episodes before any benchmark use.

## Repeated templates and shared skeleton

The schema enforces a repeated structure, and the authoring briefs produce a visible recipe:

1. coherent career context;
2. one strong role capability;
3. one requested weakness;
4. one ownership boundary;
5. one emergent high-value surface;
6. one protected area;
7. one attractive low-value temptation;
8. one correction or scope update;
9. three representative junctions;
10. a nuanced uncertainty map.

This improves reviewability but risks making the worlds predictable. An interviewer or actor trained on the set may learn that every candidate hides a valuable omitted fact and every side project should be deferred. That is not a valid population assumption.

The worlds also share the same exact schema minimums—six or more move families, several hard-invalid moves, five sufficiency conditions—which can make human lives look mechanically symmetric. A future set should include worlds with no meaningful emergent surface, no correction, several ordinary neutral facts, or evidence that remains ambiguous after a good interview.

## Labels and oracle leakage

Reviewer-facing fields explicitly name weaknesses, value, discriminative scores, opportunities, temptations, valid families, invalid moves, and sufficiency. Those fields are useful for audit but are oracle-shaped if exposed to an interviewer, actor, or model judge. The actor contract excludes them, but no runtime isolation has been tested.

Even filenames and titles can leak intended phenomena. World 04's “small owned surfaces” and some evidence labels guide interpretation. The index's `primary_human_context` summaries are reviewer aids, not blinded-evaluation material.

The checkpoint now materializes four physically separate projections under `projections/`: actor-private truth/behavior, turn-scoped actor prompt, interviewer resume/conversation state, and evaluator-only truth/audit metadata. `check_projections.py` recursively checks nested field shapes, exact fact-grant scope, evaluator metadata leakage, natural-text integrity, controller gating, and response citation scope for all five worlds. This is structural evidence only; a future runtime still needs prompt/cache/trace isolation tests.

## Demographic and stereotype risks

The names, pronouns, and locations add human texture but may activate stereotypes in reviewers or models. The set risks several specific associations:

- Women candidates are represented in analytics, data science, and product management; men in backend and junior engineering. This can reinforce gendered occupational patterns.
- The East Asian male junior is quiet and nervous, a harmful familiar stereotype even though the world does not intend ethnicity as causal.
- The Latino male backend engineer is defensive about an overclaim, which may interact with bias around credibility or communication.
- Locations and names could cue accent, education, immigration, or culture even though none is specified.
- The senior woman PM is highly polished and relational; the male backend candidate is mechanically technical.

Names and identities must not be used to score. Before any external trial, run name/pronoun/location swaps while keeping frozen work truth constant and compare interviewer and report outcomes. Human reviewers with fairness expertise should decide whether to remove demographic cues entirely for model evaluation or deliberately balance them across many more worlds.

The junior-nervousness world is especially sensitive. It must not imply that a demographic group is inherently anxious, quiet, or dependent on accommodation. Nervousness is a fictional individual trait only.

## Excessive edge-case density

Every world contains nearly all requested phenomena. That density is useful for an authoring trial but unlike ordinary hiring reality. It may make a controller that knows the schema look unusually capable because there is always a rich fact to discover. It may also punish controllers that rationally rotate because each omitted surface was authored to be interesting.

The set needs low-drama controls:

- an average candidate with no hidden high-value fact;
- a strong candidate whose resume is accurate and behavior straightforward;
- a weak candidate whose fluent or nervous behavior does not conceal stronger evidence;
- an interview where a good controller still ends with broad uncertainty;
- a candidate whose off-role detail is not obviously low-value.

Without those controls, benchmark conclusions would be biased.

## Can weak interviewers game the set?

Yes. The worlds contain recurring evidence vocabulary: denominator, ownership, operation identity, temporal split, first debugging step, opportunity cost, corrected claim. A keyword-seeking interviewer can ask the authored examples or produce superficially “correct” moves without understanding incremental value.

Conversely, an adversarial interviewer can force bad outcomes by repeating known failure shapes. Because evaluator truth includes explicit invalid moves, a model judge may simply match taxonomy rather than assess the conversation.

Mitigations needed before benchmarking:

- blind interviewer prompts without move labels or world summaries;
- paraphrased and novel question sets;
- actor realizations not copied from examples;
- human judgment of full trajectories, not exact action labels;
- negative-control worlds without the recurring phenomena;
- scoring that credits several reasonable trajectories.

## Report-attribution risk

The schema gives evaluator truth enough information to mark interviewer failure, but no report generator has been tested. A report can still unfairly:

- score an unasked fact as candidate weakness;
- treat protected or unowned details as missing competence;
- preserve superseded claims;
- infer deception from correction;
- infer shallowness from fluent or short speech;
- infer strong competence from a polished example that was prompted with the answer;
- erase a real weakness under a fairness explanation;
- over-weight one salient incident or emergent surface.

Gold suitability requires trajectory-level tests where different interviewers produce different evidence coverage and the report correctly attributes why.

## Areas requiring human domain review

- Product analytics: cohort, campaign-rule, and causal-limit realism.
- Backend engineering: retry state, ambiguous external outcome, tenant isolation, and incident plausibility.
- Data science: uplift terminology, temporal validation, leakage, experiment validity, and monitoring boundaries.
- Junior web engineering: level calibration, timezone bug, accessibility repair, and recovery behavior.
- Senior product management: migration strategy, denominator governance, marketplace pilot economics, and technical-partnership bar.
- Interview fairness: nervousness, defensive tone, correction, demographic cues, and accommodation versus coaching.
- Industrial-organizational psychology: whether latent traits, speech behavior, and hiring inference are validly separated.
- Legal/privacy: use of synthetic candidate worlds in hiring-tool evaluation and treatment of protected or demographic attributes.

## Ten strongest reasons these worlds may still be invalid as gold

1. **They were authored by one model in one pass.** Shared blind spots, prose habits, and theory preferences can appear as consistency.
2. **They are unusually edge-case dense.** Every world contains a strength, weakness, correction, boundary, emergence, temptation, and report trap.
3. **The evaluator metadata is oracle-shaped.** Value scores, valid families, hard-invalid moves, and sufficiency conditions could leak into judgments.
4. **No candidate actor has been run.** Structural facts do not prove a model can render natural, stable speech without leakage or invention.
5. **No human domain expert has approved factual realism.** Technical and product details may be subtly implausible or too clean.
6. **No diverse interviewer study exists.** Multiple move families are declared by the author, not demonstrated across independent human trajectories.
7. **Demographic cues may trigger stereotypes.** Name, gender, location, role, and behavior patterns are not balanced or counterfactually tested.
8. **Example answers are unusually polished.** They may train or bias actor and reviewer behavior and make evidence easier to extract than in real voice interviews.
9. **Report attribution is only specified.** No evidence shows a report system can separate candidate weakness, uncertainty, protected gaps, and interviewer failure.
10. **The worlds reflect Antigravity's current conceptual vocabulary.** Despite anti-overfitting work, ownership, emergence, absorption, opportunity cost, and rotation remain prominent design assumptions that could favor one interview philosophy.

Additional reasons include limited role diversity, no deliberate deception world, no ordinary low-drama controls, no ASR/audio effects, no longitudinal memory calibration, no inter-rater reliability, and no external outcome validity.

## Provisional cross-world conclusion

Luna's output is strongest as a structured authoring foundation: the worlds have stable facts, nuanced ownership, temporal disclosure, plausible capability contrasts, and multiple stated trajectories. The weakest aspect is not JSON structure; it is ecological validity. The set is too neat, too dense, too semantically labeled, and too close to the product's current interview-control concerns to become gold without substantial independent challenge.

Recommended next step after structural validation: human domain review of one world at a time, followed by blind actor sampling and three independent interviewer trajectories per world. Do not expand the set or benchmark a controller until those reviews reveal which parts of the schema and authoring method survive contact with human judgment.

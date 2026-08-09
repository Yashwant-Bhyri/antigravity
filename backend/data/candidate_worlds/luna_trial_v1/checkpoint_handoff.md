# CandidateWorldV1 Luna trial — structural/projection checkpoint

Status: ready for independent Codex judgment; not gold and not wired into production.

## Trust model

- `projections/actor_private/` is candidate-private truth: complete factual units, ownership/disclosure metadata, protected-boundary behavior, and the candidate behavior model. It deliberately excludes evaluator scoring, move values, acceptable moves, sufficiency, capability verdicts, expected reports, and interviewer strategy.
- `projections/actor/` is the actor turn prompt. It contains verbatim shared identity/resume/context and only facts in the trusted grant ledger for that turn. The disclosure controller accepts explicit fact IDs only; it does not accept question semantics and rejects unknown, protected, too-early, or prerequisite-incomplete grants.
- `projections/interviewer/` is resume plus conversation events only. It contains no frozen facts, actor eligibility, or reviewer metadata.
- `projections/evaluator/` is the evaluator-only copy of frozen truth, evidence graph, attribution rules, acceptable move sets/tradeoffs, invalid reality violations, and sufficiency conditions.
- Natural language is copied verbatim. No token-level substitution or `[later detail]` redaction is used.

## Acceptance results

```text
python3 data/candidate_worlds/luna_trial_v1/validate_trial.py
PASS worlds=5 schema_pass=5 reference_pass=5 reveal_pass=5 citation_pass=5 errors=0

python3 data/candidate_worlds/luna_trial_v1/check_projections.py
PASS base_worlds=5 schema=5 reference_prerequisite=5
PASS actor_private=5 actor_turn_prompt=5 interviewer=5 evaluator=5
PASS recursive_boundary_checks=0 forbidden_key_leakage=0 evaluator_metadata_leakage=0
PASS disclosure_controller=5 response_citation_scope=5 natural_text_coherence=5
SUMMARY projection_errors=0

The projection schema is deep-strict for actor-private behavior internals and actor-turn/interviewer fields. The checker mutation-negative suite injects an unexpected nested key into short-answer, every response policy, correction, contradiction, and every fatigue item and requires rejection. Evaluator `frozen_truth` is the intentional exception: its nested shape is delegated to the strict CandidateWorldV1 validator and exact-copy equality, because duplicating the full world schema would create a second drift-prone schema.

python3 data/candidate_worlds/luna_trial_v1/materialize_projections.py --verify
PASS projection manifest verified sources=11 projections=20 writes=0
```

Additional exercised cases:

- Explicit controller grant of `fact_identity_role` at turn 0 succeeded and emitted one `actor_turn_prompt` fact with `question_semantics_used=false`.
- Attempted turn-0 grant of gated `fact_ai_segmentation` failed: `newly granted fact is not available at turn 0`.
- Response citation validator accepted a response citing the granted fact and rejected `fact_ai_segmentation` when it was absent from the turn grant.

## Reproducible commands

From the backend worktree:

```bash
python3 data/candidate_worlds/luna_trial_v1/validate_trial.py
python3 data/candidate_worlds/luna_trial_v1/materialize_projections.py --force
python3 data/candidate_worlds/luna_trial_v1/materialize_projections.py --verify
python3 data/candidate_worlds/luna_trial_v1/check_projections.py
python3 data/candidate_worlds/luna_trial_v1/disclosure_controller.py \
  --world-id world_01_product_analyst --turn 0 --grant fact_identity_role
```

`--verify` is read-only. `--force` is required only for intentional projection regeneration after a source change.

## Exact frozen files and SHA-256

The machine-readable `projection_manifest.json` contains the authoritative hashes for 11 source files and 20 projections. The complete non-cache trial inventory at this checkpoint is below. The handoff file itself is omitted to avoid a self-referential hash; its content is covered by the focused commit.

| File | SHA-256 |
| --- | --- |
| `README.md` | `f184d222f2cc6a8dad5dd4f09c472159ccbaecc3c93efd3c9d8adfc262f5c9c5` |
| `actor_contract.md` | `df39dcd7056d872e0c4cc7083254990a9c0ef389bed6b1e0213cd0a80c7d6b6c` |
| `audits/cross_world_audit.md` | `604146123caf74ccacd81b9373c9a8aa14ed344a7b08cc5e4f0ae3aad98c9806` |
| `audits/world_01_audit.md` | `239a95bd9806dd87bf5473e0fa872d307ecdc47d6ba93bb2d7b1a748bf1c342d` |
| `audits/world_02_audit.md` | `837963f0c427203d0baa6cdcd239b1675ff02e888fc48134c883c807bcbbec48` |
| `audits/world_03_audit.md` | `ff1c272997ca23f7a57eb5b6ce83c7e3f9cbaa0b4e82ba3b4438d9dab6e553b3` |
| `audits/world_04_audit.md` | `bfaf38fa069719f36ec6e079c24426095da963d1aae7d55cfc8b9b694d81be26` |
| `audits/world_05_audit.md` | `7674f784f9ac41f1299b165e5605b776e54859aa30181841168fed4675e5bf4d` |
| `authoring_calibration.md` | `6b2506f9bd017f5112cc0458dd55236b19e946cd623d3ba03c6a86cb9b59267a` |
| `candidate_world_v1.schema.json` | `d59841c34aadcd0cd869b33625b1f76cbc93f7b90d1f7cb5413e52b9880a6b2a` |
| `check_projections.py` | `477cfcf68a139b549726194134010cc7c34d2a7ad61369bc406efd4ef955582c` |
| `disclosure_controller.py` | `9f307be42409659fc332bc1cbb9eeeca04583f938be32b33e4ea3cb918ea8384` |
| `materialize_projections.py` | `4fef4b4f718b67a9e99b8d1bf5d0b49717bcebe6bc685428449933a47779835f` |
| `projection_manifest.json` | `de582bfce448d6b608f0ced49daf1f656cdfa55ac435931a03707fd0be9e4ca8` |
| `projection_v1.schema.json` | `5fa9930dc203cae4dd5a9d5f0560f63a6674530706c90b843a9dd6cd4191f88b` |
| `reviewer_scorecard.md` | `96262a06ac8ee32fbd2bce078ea4b7effca06355c012c50ae5865cb8593634ab` |
| `validate_actor_response.py` | `c2d3f4abf601486d211bbdbed63a802ac7f1d27e0b603af920db6e531349c4e4` |
| `validate_trial.py` | `e9f04f45c4c819400445fe3b714a21d915eeb4b0e3bfdda905f811f71588c78f` |
| `world_index.json` | `250023859457abe3ef4d5b814a377a2a6fa4158b15f0c2b8d185678871ae81d7` |
| `worlds/world_01_product_analyst.json` | `461df5f83eadf8c65498cd1d9898f9d27822ac784e237328d413b8e944c66f6b` |
| `worlds/world_02_backend_engineer.json` | `23ff9803fa9cd3eae6ed062fff6ac03d95055d95ffe145fa2ed538059a1ee90c` |
| `worlds/world_03_data_scientist.json` | `e86bf5674244239c518d0da2b1e51b0c18dec63d6d31021f1728601271cf4d63` |
| `worlds/world_04_junior_fullstack.json` | `64bce27c37a915fe0523cc20671a4dfb644038b8e000a4bea62ff33c2790658d` |
| `worlds/world_05_senior_pm.json` | `b5c56f0201ddc7b36050f954b520f897068412c2b5cbe109e2142f512fe6c269` |
| `projections/actor/world_01_product_analyst.json` | `80d0c4bf0e09c3cc4d37b68af5b006c46a8af2fc7fd840ad0cfd20557550f952` |
| `projections/actor/world_02_backend_engineer.json` | `183473ae753176ff56acf4bf23e91ad5b0d7ea9df8534ea7ff1ad0b536b391e5` |
| `projections/actor/world_03_data_scientist.json` | `88baecf075735fb6736e8139810ee7fcfb4599c15f277daa1585ca6ba687b296` |
| `projections/actor/world_04_junior_fullstack.json` | `6a8647446ef3bbaf2fd2afb2572ee0f621555b806c687f5699ce3324bd9d35d7` |
| `projections/actor/world_05_senior_pm.json` | `9f06aafa7f2a397c86208379c979cec5ba755ee4ed99614172bf89ea38a1d0a4` |
| `projections/actor_private/world_01_product_analyst.json` | `4070029f718c27a139d27d0baadf0264c465466d3e4ddbeaa3b7bd026d4ffa4e` |
| `projections/actor_private/world_02_backend_engineer.json` | `220b510ef82318cf57b2602d23aa3344e27b1578ff0b90206ce53e8b376735a6` |
| `projections/actor_private/world_03_data_scientist.json` | `82f897cffce6f8828c686f004bf85eb2d6c54329f5788ba70faa50d4032c2ab7` |
| `projections/actor_private/world_04_junior_fullstack.json` | `d7bf23be5dee756c16f5517815d3a35b78b6de193edd8e536d454c629a1afc9a` |
| `projections/actor_private/world_05_senior_pm.json` | `3920e3bcab8cb6958ebf2b99664003e5fa9762e1e12be8add2df15567722812e` |
| `projections/evaluator/world_01_product_analyst.json` | `f0cf81319476234588f380fbe03bde4c1c2dc202288e57045666cb7370b232f1` |
| `projections/evaluator/world_02_backend_engineer.json` | `1880164537682767746f591ebfc9d74fa0461508817370be88001cd191b2643e` |
| `projections/evaluator/world_03_data_scientist.json` | `f24248a260aa9952ad7deb9e70f7769e282ef128dda0aff1cfcccebc510bc1d0` |
| `projections/evaluator/world_04_junior_fullstack.json` | `c0b89ead77d77fee2bba7ccc407b3110e32067d4967ad48051d5353915fa0ded` |
| `projections/evaluator/world_05_senior_pm.json` | `714e8e55cef91d00ebed6d7751d5e0de5e01a190cf05adc725b61eff2325ad9d` |
| `projections/interviewer/world_01_product_analyst.json` | `a91e219ff4ae0c65c40dbf52c5640bd920f793ee7be72fd6e6a93bc61b516cd5` |
| `projections/interviewer/world_02_backend_engineer.json` | `a897060bb704e77753512aa0bf26a2079e307c08b24cfaf448ef43c09d79b6db` |
| `projections/interviewer/world_03_data_scientist.json` | `a8cfbcf2b4eb3cecb02c69d57e9ad7462528662f1e0b9dd74bfdd4d08084d357` |
| `projections/interviewer/world_04_junior_fullstack.json` | `1c7ed5906edb01c95fca4b3b1e7a9984377479478937ffd012c68d3eccd46559` |
| `projections/interviewer/world_05_senior_pm.json` | `ea3aa441eb281af282af0761b7721e59f01d846ad2b32bf562c395a4bb94c860` |

## Remaining risks and review request

1. The actor-private artifact is sensitive by design; file permissions, prompt-cache isolation, and production secret handling are not implemented here.
2. The disclosure controller trusts the caller that supplies explicit fact IDs. It validates IDs, prerequisites, turn, eligibility, and protected status, but it is not an authenticated runtime authority or durable ledger.
3. The response validator enforces citation scope, not semantic coverage of every factual clause in prose.
4. Exact-key, exact-ID, exact-text, and source-text checks cannot prove that an LLM will not paraphrase a hidden fact from outside the prompt; human/adversarial actor testing is still required.
5. The worlds remain exploratory, edge-case dense, and non-gold. Domain realism, demographic fairness, multi-interviewer trajectory validity, and report attribution still need independent review.

Please review the repaired World 01/02 references and correction semantics, inspect all four projection boundaries, attempt prerequisite/protected/leading-question bypasses, and judge whether the actor-private/turn split is sufficient for a future runtime. This checkpoint is explicitly ready for Codex judgment; do not promote it without that review.

Commit hash: to be recorded after the focused trial-only commit.

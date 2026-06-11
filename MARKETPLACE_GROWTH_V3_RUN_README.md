# Marketplace Growth V3 Run README

Last updated: 2026-06-03

This document explains the latest paid `marketplace_growth` Launch-Ready Map Prep V3 run. It is a companion to:

- `ANTIGRAVITY_INTERVIEW_SYSTEM_TECHNICAL_README.md`
- `/Users/yash/Downloads/antigravity_latest_marketplace_growth_v3_full_dump_20260603.json`

## Purpose Of This Run

The `marketplace_growth` case was created to test the system without relying on the Apparao-style product analyst resume.

It was designed to stress:

- role-relevant focus ranking;
- off-role OCR/CV demotion;
- LaunchTrackLite startup;
- V2 ladder compatibility;
- app-transfer grounding;
- earned coverage depth;
- second-anchor semantic rotation;
- honest correction handling;
- Report V2 fairness.

The candidate was intentionally strong but imperfect.

## Candidate Fixture

Candidate:

- Tanvi Menon
- Target role: Product Analytics Engineer
- Years: 2.8

Resume themes:

- seller onboarding event taxonomy;
- seller activation from 22 percent to 38 percent;
- checklist, support-call, and KYC UX concurrent rollout;
- BigQuery and dbt models joining seller events, tickets, KYC, approvals;
- metric definitions and analysis ownership;
- platform engineering owning SDK/deployment;
- marketplace health dashboard;
- first-order lag claim with support-staffing confound;
- OCR invoice parser side project;
- college CV pothole classifier.

The intended high-value surfaces were:

- marketplace activation attribution;
- seller onboarding taxonomy;
- dashboard/ops analytics;
- data modeling and reconciliation;
- ownership boundaries.

## Primary Artifacts

Full gate:

- `/tmp/antigravity_map_v3_marketplace_growth_full_anchorfix_20260603_full_gate.json`
- `/tmp/antigravity_map_v3_marketplace_growth_full_anchorfix_20260603_full_gate.md`

Downloadable mega bundle:

- `/Users/yash/Downloads/antigravity_latest_marketplace_growth_v3_full_dump_20260603.json`

Map-only support artifact:

- `/tmp/antigravity_map_v3_marketplace_growth_fix5_20260603_map_policy.json`
- `/tmp/antigravity_map_v3_marketplace_growth_fix5_20260603_map_policy.md`

Saved-map replay:

- `/tmp/antigravity_map_v3_marketplace_growth_fix5_post_anchor_fix_replay_20260603_20260603_005759.json`
- `/tmp/antigravity_map_v3_marketplace_growth_fix5_post_anchor_fix_replay_20260603_20260603_005759.md`

Scaffolding audit:

- `/tmp/antigravity_scaffolding_audit_20260603_005746.json`
- `/tmp/antigravity_scaffolding_audit_20260603_005746.md`

Runtime trace:

- `backend/runtime/interview_traces/aa480a9f-dcbd-42b4-9665-4573df662510.jsonl`

## Result Summary

Session:

- `aa480a9f-dcbd-42b4-9665-4573df662510`

Outcome:

- `ok=true`
- quality gate passed
- 15 questions
- history length 15
- `report_ready=true`
- `finalization_status=complete`
- app transfer by turn 6
- coverage turns 7-8
- earned coverage-depth probe fired
- second anchor at turn 11
- final recommendation `MAYBE`
- final score `6.5`
- confidence `0.72`

Remaining warnings:

- `late_generic_route`
- `question_readiness_warning`

These warnings did not fail the gate. The main cleanup is terminal close statements being scored as if they were normal questions.

## Startup Map Prep

Startup elapsed:

- about 85.6 seconds in the robust harness

Map policy:

- map generator: Gemini 3.5 Flash
- launch repair: GPT-5.4 Mini
- compact launch critic: Sonnet 4.6
- audit: DeepSeek V4 Flash advisory
- SurfacePlanV2: GPT-5.4 Mini

Launch tracks:

1. `product_event_taxonomy_and_metrics_onboarding`
   - label: Product Onboarding Event Taxonomy And Metric Definition
   - schema: `v3_launch_lite`
   - contract: `launch_track_lite`
   - opener: "Can you walk me through how you structured the seller onboarding event taxonomy from signup to first order?"

2. `data_modeling_and_dashboard_reporting_multi`
   - label: Multi-Dataset Modeling And Reporting
   - schema: `v3_launch_lite`
   - contract: `launch_track_lite`
   - opener: "When you built the BigQuery and dbt models joining seller events with support tickets, how did you structure the core relationships between transactional states and user-reported issues?"

Important map-quality note:

- The compact critic accepted launch with score about `8.1`.
- It correctly noted weak `follow_up_if_strong` fields, but treated that as a warning, not a launch blocker.
- OCR and college CV did not get promoted into launch tracks.

## Transcript Walkthrough

The table below is simplified. For deep analysis, use the JSON bundle.

| Turn | Route | Phase | Question Summary | What It Tested |
|---:|---|---|---|---|
| 1 | `trajectory_map_surface` | `warm_open` | Warm intro | Human start, candidate background |
| 2 | `clarification_fast` | `primary_depth` | dbt grain and schema ownership | Scope, ownership boundary |
| 3 | `trajectory_map_mechanism` | `primary_depth` | isolate UX effect from ops shifts | Attribution under concurrent rollout |
| 4 | `trajectory_map_mechanism` | `primary_depth` | activation and conversion metric definitions | Denominator and metric taxonomy |
| 5 | `trajectory_map_boundary` | `primary_depth` | joining high-volume events with SLA states | dbt joins, fanout, performance |
| 6 | `application_transfer` | `primary_depth` | hardest event/metric definition | Conflict resolution and metric governance |
| 7 | `coverage_surface` | `coverage_surface` | new onboarding guide plus support improvement | Transfer to adjacent scenario |
| 8 | `coverage_depth_probe` | `coverage_surface` | stakeholder disagreement with data | Earned depth / communication integrity |
| 9 | `trajectory_map_metric_probe` | `primary_depth` | selection bias in guide users | Causal reasoning weakness |
| 10 | `trajectory_map_surface` | `primary_depth` | platform engineering vs analytics ownership | Ownership boundary |
| 11 | `second_anchor` | `second_anchor` | choosing onboarding taxonomy events | Secondary surface / taxonomy |
| 12 | `second_anchor` | `second_anchor` | dbt joins with support SLA states | Secondary modeling/dashboard surface |
| 13 | `graceful_exit` | `primary_depth` | anything not fairly tested | Candidate-safe close / honest correction |
| 14 | `graceful_exit` | `synthesis_close` | wrap and report generation | Terminal close |
| 15 | `graceful_exit` | `synthesis_close` | strongest untested signal | Final calibration |

## What Worked Well

### Launch readiness worked

The interview started from two launch-safe tracks rather than waiting for a perfect full V2 map.

This is the core V3 win.

### App transfer landed on time

Application transfer appeared by turn 6. This is inside the target window.

### Coverage followed immediately

Coverage started at turn 7 and continued at turn 8.

The coverage arc evaluated two dimensions and fired an earned depth probe.

### Second-anchor holding pattern was reduced

The previous failing run had a longer second-anchor holding pattern. This run had second anchor at turns 11-12, then moved to close.

The new spent-surface retirement logic was active.

### Report was fair

The final report did not punish honest correction as fraud.

It gave:

- `MAYBE`
- score `6.5`
- confidence `0.72`

It identified strong analytics/BI/product-ops fit while preserving causal-inference risk.

## What Still Needs Review

### Close messages are scored like questions

Turns 14 and 15 are terminal close/calibration turns. The question-quality system flags some close statements as weak because they are not normal questions.

This is not a candidate-assessment failure. It is a routing/scoring cleanup.

Future fix:

- terminal close should become a terminal message state;
- or close route should be exempted from normal question-quality scoring.

### `legacy_agenda_backup` still appears in policy traces

The actual served questions were often map-backed, but background staging can still produce `legacy_agenda_backup`.

Fast path replaced it in several places, but the route label remains a smell.

Future fix:

- rename or retire `legacy_agenda_backup`;
- separate "fallback route label" from "candidate-visible served route".

### Flat `turns[]` focus labels are incomplete

In this artifact, `turns[]` has several `focus=None` fields even though focus information exists elsewhere.

For analytics, prefer:

- `route_repetition.focus_sequence`;
- `route_repetition.surface_sequence`;
- `assessment_coverage.surfaces_by_focus`;
- `policy_checker_events`;
- runtime trace events.

Future fix:

- enrich `turns[]` with final packet focus/sub-focus metadata before writing artifacts.

### Dashboard signal was present but still not ideal

The run touched marketplace health/dashboard-ish surfaces through modeling/reporting, but it still did not deeply ask:

- which dashboard metric caused disagreement;
- which tile mattered most;
- what looked healthy while the business was deteriorating;
- refund/SLA/first-order-lag reconciliation.

This did not fail the gate, but for a stronger marketplace analytics interview, dashboard/ops thinking should receive cleaner second-anchor engagement.

## Coverage Read

Coverage summary:

- coverage dimensions: 3
- evaluated: 2
- coverage score: about `0.67`

Evaluated dimensions:

- attribution strategy: voluntary
- confound guardrail: missed or not fully resolved

Application-transfer arc:

- grounding needed: false
- main transfer served: true
- surface count: 2
- depth count: 1
- confirmed depth level: 2
- max depth level: 3

Interpretation:

- The candidate showed strong instrumentation and analytics judgment.
- The main risk remained formal causal inference depth.

## Final Evaluation Read

Final recommendation:

- `MAYBE`

Score:

- `6.5`

Confidence:

- `0.72`

Strongest verified signal:

- seller funnel taxonomy;
- denominator hygiene;
- metric governance;
- guardrails;
- honest calibration.

Largest risk:

- causal inference under concurrent interventions;
- over-reliance on segmentation without deeper treatment of endogeneity.

Alternate fit:

- Analytics Engineer;
- Product Operations Analyst;
- BI/Reporting Analyst.

This report direction is aligned with the product philosophy: scoped risk, preserved strength, no overconfident rejection.

## How The Intern Should Use The JSON Bundle

Open:

```text
/Users/yash/Downloads/antigravity_latest_marketplace_growth_v3_full_dump_20260603.json
```

Important top-level sections:

- `bundle_metadata`
- `quick_read`
- `primary_full_gate_result`
- `runtime_trace_events`
- `llm_usage_rows_for_session_and_sim_turns`
- `llm_usage_summary_by_model_and_call_site`
- `supporting_artifacts.map_only_result`
- `supporting_artifacts.saved_map_replay_result`
- `supporting_artifacts.scaffolding_audit_result`

Suggested analysis order:

1. Read `quick_read`.
2. Read `primary_full_gate_result.map_policy_trace`.
3. Read `primary_full_gate_result.map_focus_areas`.
4. Read `primary_full_gate_result.turns`.
5. Compare with `route_repetition`.
6. Inspect `application_transfer_arc`.
7. Inspect `coverage_details` and `assessment_coverage`.
8. Inspect `policy_checker_events`.
9. Inspect `final_evaluation`.
10. Inspect `runtime_trace_events` for timing and route staging.

## Why This Run Matters

This run shows that the V3 startup architecture is structurally viable:

```text
launch-safe first two tracks
  -> start interview
  -> app transfer
  -> coverage
  -> second anchor
  -> report
```

It does not prove production readiness for every resume.

It proves we have moved past the main repeated failure:

```text
good focus plan dies because full V2 track contract is too heavy before turn 1
```

The next evidence needed is whether `best_product` and `strong_ai` also pass under V3 without reintroducing map-prep failure, hidden internals, or second-anchor loops.


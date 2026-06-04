# Antigravity Scaffolding Audit

Date: 2026-06-01
Owner: Codex

This audit covers deterministic code around LLM calls and live interview state. The goal is to keep model quality failures separate from product scaffolding failures. If an LLM is weak, the system should expose that honestly. If deterministic code is brittle, it should be tested and fixed.

## Scope

Assessment-critical scaffolding includes:

- LLM output parsing and JSON repair.
- Agent output consumers.
- Interview-map normalization, critic routing, repair routing, and hydration.
- Question packet construction and queue handling.
- Agenda/focus/sub-focus state hydration.
- Application-transfer and coverage-map hydration.
- Completion and final verdict gates.
- Metadata-only token usage auditing.

Out of scope for this pass:

- Frontend demo-only visualizer routes.
- Payment/inventory simulation internals unless they feed the live interview path.
- Paid model-quality reruns.

## Findings And Fixes

### 1. LLM JSON Parsing

Risk: The router could parse a nested array from a malformed outer object, creating a false top-level result.

Fix:

- `LLMRouter._load_json_lenient()` now honors the first JSON shape.
- `json-repair` is allowed only when the original text shows object-style key/value intent.
- Tests: `backend/test_llm_router_json.py`.

### 2. Agent Output Consumers

Risk: Agents could accept a dict with wrong enum/list shapes, shifting bad model output into live routing.

Fix:

- `ConceptAgent` requires `concepts` to be a list.
- `WeaknessAgent` validates weakness type, severity, and probe direction.
- `DiscrepancyAgent` validates conflict level and severity.
- `ApplicationAgent` validates dimension lists, surfacing questions, weights, and coverage confidence.
- Tests: `backend/test_parser_contracts.py`.

### 3. Interview Map And Critic Parsing

Risk: Map track/critic parsing had local ad hoc JSON extraction and duplicate/dead coercion code.

Fix:

- Map candidates, dimension tracks, legacy tracks, schema validation, and critic coercion now use the shared safer parser.
- Duplicate dead critic parser removed.
- Critic output still validates through typed schemas; local repair is syntax-only.
- Tests: `backend/test_parser_contracts.py`, `backend/test_interview_map_contract.py`.

### 4. Question Packets And Follow-Up Queues

Risk: `list(string)` style coercions can turn one question into character-level followups.

Fix:

- Follow-up normalization accepts only actual lists.
- Packet clone and packet remaining helpers use the same normalizer.
- Map-backed packets still hard-fail when focus attribution is missing.
- Tests: `backend/test_scaffolding_contracts.py`.

### 5. Coverage And Verdict Gates

Risk: Bad scalar values in coverage/evaluation state can crash finalization or distort verdict gating.

Fix:

- Coverage progress and hard coverage gates use safe numeric coercion.
- Coverage-map hydration no longer char-splits `expected_approaches`.
- Bad coverage shapes evaluate to incomplete/insufficient data, not a hard verdict.
- Tests: `backend/test_scaffolding_contracts.py`, `backend/test_parser_contracts.py`.

### 6. Saved-State Hydration

Risk: Redis/session state can contain old or malformed list/dict/scalar shapes after code changes.

Fix:

- Candidate state and agenda state hydrate with safe dict/list/int/float coercion.
- Bad phase values reset to `warm_open`.
- Tests: `backend/test_parser_contracts.py`.

### 7. Token Usage Audit

Risk: Cost analysis can leak raw prompts/resumes or miscount retries.

Existing coverage confirmed:

- Per-attempt and aggregate usage records omit raw prompt/output text.
- Retry overhead is counted.
- Provider token usage wins when present; estimates are fallback only.
- Tests: `backend/test_llm_usage_audit.py`.

## Verification

No paid LLM calls are required for this audit.

```bash
python3 -m py_compile backend/models/llm_router.py backend/agents/application_agent.py backend/agents/concept_agent.py backend/agents/discrepancy_agent.py backend/agents/followup_agent.py backend/agents/weakness_agent.py backend/agents/evaluation_agent.py backend/models/coverage_map.py backend/services/interview_map.py backend/services/orchestrator.py backend/state/interview_agenda.py backend/state/candidate_state.py backend/state/session_manager.py backend/api/routes.py backend/test_llm_router_json.py backend/test_parser_contracts.py backend/test_scaffolding_contracts.py backend/test_llm_usage_audit.py backend/test_interview_agenda_contract.py backend/test_interview_map_contract.py backend/test_interview_map_validation.py
PYTHONPATH=. python3 backend/test_llm_router_json.py
PYTHONPATH=. python3 backend/test_parser_contracts.py
PYTHONPATH=. python3 backend/test_scaffolding_contracts.py
PYTHONPATH=. python3 backend/test_llm_usage_audit.py
PYTHONPATH=. python3 backend/test_interview_agenda_contract.py
PYTHONPATH=. python3 backend/test_interview_map_contract.py
PYTHONPATH=. python3 backend/test_interview_map_validation.py
```

## Residual Risks

- Some simulation/admin/demo utilities still use plain JSON parsing and scalar casts. They are lower-risk for the live interview path but should be brought under the same contract style before those products become production-critical.
- The full live 15-turn simulation should be rerun after this no-credit hardening pass to confirm no behavior drift.
- Token audit exactness depends on provider usage fields. When OpenRouter/provider usage is absent, the system still uses estimates.

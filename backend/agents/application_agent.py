from __future__ import annotations

import os
import re

from backend.models.llm_router import JSON_OBJECT_FORMAT, LLMRouter
from backend.models.coverage_map import AnswerCoverageMap, CoverageDimension


APPLICATION_SYSTEM = """You are designing an application transfer question for a technical interview.

Given what a candidate just described building, you must:
1. Create ONE application transfer question — a new role-relevant scenario with ONE new constraint.
2. Generate 2-3 coverage dimensions that a strong answer should address.
3. If the anchor may hide multiple depth layers, generate a short grounding question before the transfer.

Rules for the application question:
- MUST reference the implementation_anchor specifically, but do not overstate ownership. If the anchor is broad, frame it as "the work you described" or "the claim we discussed," not as proof they personally built every internal piece.
- If anchor_source is "resume_focus_fallback", the anchor is a resume/map claim selected only because live answers were too vague for a primary anchor. In that case, reference it as the claim being tested, not as proven live ownership.
- Target-role relevance is mandatory. The transfer scenario should test application skill for the role being hired for, not simply copy the current focus domain.
- If candidate_domain conflicts with target_role, keep the scenario in the target_role domain and use the anchor only as reasoning evidence.
- Adjacent constraint — role-relevant domain, ONE meaningful shift (e.g. cohort→new market, dashboard→executive decision, controlled→messy production data)
- Situational framing should be short and spoken. You may use "Suppose..." or "Imagine..." but do not write a long case paragraph.
- Multiple valid implementation approaches must exist
- Calibrate to experience: junior→surface design; senior→failure modes and boundary conditions
- Use the transfer to test role-critical application breadth that the direct resume probes have NOT yet tested. Do not merely re-ask the original mechanism question.
- Incremental depth is mandatory. The application question should test how they reason across a new situation first; deeper mechanism follow-ups are allowed only after their answer opens that layer.
- Do not jump from a workflow/product claim to hidden internals such as engine parameters, model parameters, embeddings, latent space, diffusion behavior, model training, optimizer behavior, or database schema unless the grounded transfer anchor explicitly supports that layer.
- Keep application_question under 55 words when possible. It must be one clear scenario and one clear ask.
- If giving answer lanes helps, use "A, B, C, or something else?" so the candidate can reason beyond the examples. Do not make it a yes/no or multiple-choice question.
- Do not make the first transfer question narrow or internally deep. It should test adjacent application breadth first.
- If the anchor could mean either high-level orchestration or specialized internals, set grounding_needed=true and ask a short grounding_question first.

Depth language:
- L1 = decision/framing layer.
- L2 = operating mechanism/tradeoff layer.
- L3 = failure boundary/edge-case layer.
- L4 = specialized internal layer. L4 is rare and must not be used unless the candidate explicitly confirms that layer.
- Most application-transfer arcs should stay within L1-L3.

Rules for dimensions:
- 2-3 dimensions total. These should be different role-relevant surfaces, not three versions of the same depth probe.
- At least 2 dimensions must be breadth/surface dimensions.
- Only 1 dimension should normally be depth_eligible; 2 is the hard maximum. Never make every dimension depth_eligible.
- Each dimension: a distinct aspect of a strong answer to the application question.
- expected_approaches: 2-3 valid implementations for this dimension (candidate doesn't need to name these, just address the concept)
- surfacing_question: a single exploratory prompt that names the SITUATION, not the SOLUTION
  - Wrong: "Did you consider caching?" (names the solution)
  - Right: "What happens when the pipeline falls behind real-time?" (names the problem space)
- surfacing_question MUST be a real question ending in "?", not an imperative like "Walk me through..."
- Include at most one dimension about the hardest boundary/guardrail for the role: metric denominator/causal guardrail for analytics, state consistency/reconciliation for backend, uncertainty/confidence for AI systems.
- `surface_kind` must be "breadth" or "depth". Use "depth" only when a same-thread follow-up would be fair.
- `depth_eligible` must be true only for dimensions where a deeper follow-up is fair from the anchor and target role.
- weight: 1.0-3.0 based on importance to role fitness

Return JSON only:
{
  "application_question": "string",
  "adjacent_constraint": "string (what changed)",
  "anchor_reference": "string (the specific thing from their answer the question references)",
  "coverage_confidence": 0.0-1.0,
  "grounding_needed": false,
  "grounding_question": "short clarification question if grounding_needed is true, else empty string",
  "max_depth_level": 3,
  "depth_allowed_terms": ["terms/layers that are fair only if evidence supports them"],
  "dimensions": [
    {
      "id": "snake_case_id",
      "label": "short label",
      "description": "what this dimension tests",
      "expected_approaches": ["approach_a", "approach_b"],
      "surfacing_question": "the single exploratory prompt for this dimension",
      "surface_kind": "breadth|depth",
      "depth_eligible": false,
      "weight": 1.5
    }
  ]
}"""


class ApplicationAgent:
    def __init__(self) -> None:
        self.llm = LLMRouter(tier="medium")
        self.repair_llm = LLMRouter(tier="small")
        self.verify_llm = LLMRouter(tier="small")
        fallback_models = [
            model.strip()
            for model in os.environ.get(
                "OPENROUTER_APP_TRANSFER_REPAIR_FALLBACK_MODELS",
                "openai/gpt-5.4-mini,google/gemini-3.1-flash-lite",
            ).split(",")
            if model.strip()
        ]
        self.repair_fallback_llms = [
            {
                "label": f"fallback_{index}",
                "model": model,
                "llm": LLMRouter(tier="small", model_override=model, timeout_override=60.0),
            }
            for index, model in enumerate(fallback_models, start=1)
        ]
        self.last_repair_verification: dict = {"repair_attempted": False}

    @staticmethod
    def _question_too_long(question: str) -> bool:
        words = question.split()
        return len(words) > 55 or len(question) > 360 or question.count("?") > 1

    @staticmethod
    def _contains_answer_lanes(question: str) -> bool:
        cleaned = str(question or "").lower()
        if " or " not in cleaned:
            return False
        if re.search(r"\b(mainly|whether|which of|came from|because of|driven by)\b", cleaned):
            return True
        return len(re.findall(r",", cleaned)) >= 1

    @staticmethod
    def _has_escape_hatch(question: str) -> bool:
        return bool(re.search(
            r"\b(or something else|something else|anything else|what else|some other|another reason|other reason|beyond these|if not these)\b",
            str(question or ""),
            flags=re.IGNORECASE,
        ))

    @staticmethod
    def _anchor_depth_ambiguous(anchor: str) -> bool:
        text = str(anchor or "").lower()
        if not text.strip():
            return False
        broad_layer_terms = (
            "workflow", "pipeline", "system", "agent", "model", "schema", "architecture",
            "infrastructure", "optimization", "orchestration", "benchmark", "evaluation",
            "classifier", "automation", "platform", "engine", "tracking", "taxonomy",
        )
        explicit_scope_terms = (
            "personally", "i built", "i implemented", "i designed", "i owned",
            "human review", "regression", "dashboard", "sql", "event", "metric",
        )
        return any(term in text for term in broad_layer_terms) and not any(
            term in text for term in explicit_scope_terms
        )

    @staticmethod
    def _default_grounding_question(anchor: str, target_role: str = "") -> str:
        role_hint = f" for the {target_role} role" if str(target_role or "").strip() else ""
        return (
            "Before I apply this to a new case, when you describe that work"
            f"{role_hint}, were you mainly handling the decision logic, the operating workflow, "
            "specialized internals, or something else?"
        )

    @staticmethod
    def _hidden_assumption_terms(question: str, anchor: str) -> list[str]:
        q = str(question or "").lower()
        a = str(anchor or "").lower()
        flagged = []
        support_aliases = {
            "model weights": (
                "tensorflow lite",
                "tflite",
                "int8",
                "quantization",
                "quantizing",
                "classifier",
                "model invocation",
                "model optimization",
                "fine-tune",
                "fine tune",
                "training",
                "weights",
            ),
            "database schema": (
                "sql schema",
                "sql schemas",
                "schema",
                "bigquery",
                "dbt",
                "data model",
                "data models",
                "models joining",
                "join grain",
                "grain",
            ),
            "foreign key": (
                "sql schema",
                "sql schemas",
                "relational",
                "join",
                "joining",
                "bigquery",
                "dbt",
                "source evidence",
            ),
            "optimizer": ("training", "fine-tune", "fine tune", "optimizer"),
            "backprop": ("training", "fine-tune", "fine tune", "backprop"),
            "training loop": ("training", "fine-tune", "fine tune", "training loop"),
        }
        for term in (
            "engine parameter", "engine parameters", "internal parameter", "internal parameters",
            "model parameter", "model parameters", "latent", "latent space", "latent state",
            "diffusion", "training loop", "optimizer", "backprop", "embedding",
            "identity embedding", "embedding space", "fine-tune", "fine tune",
            "model weights", "sampler", "denoising", "database schema", "foreign key",
        ):
            supported = term in a or any(alias in a for alias in support_aliases.get(term, ()))
            if term in q and not supported:
                flagged.append(term)
        return flagged

    @classmethod
    def _deterministic_repair_flags(cls, question: str, *, original: str = "", anchor: str = "") -> list[str]:
        cleaned = " ".join(str(question or "").split()).strip()
        flags: list[str] = []
        word_count = len(cleaned.split())
        if not cleaned.endswith("?"):
            flags.append("missing_question_mark")
        if cleaned.count("?") != 1:
            flags.append("wrong_question_mark_count")
        if word_count < 15:
            flags.append("too_short")
        if word_count > 65 or len(cleaned) > 430:
            flags.append("too_long")
        if original and cls._question_too_long(str(original or "")) and len(cleaned) >= len(str(original or "")):
            flags.append("not_shorter_than_original")
        if cls._contains_answer_lanes(cleaned) and not cls._has_escape_hatch(cleaned):
            flags.append("answer_lanes_without_escape_hatch")
        if re.search(r"\byou personally (built|implemented|wrote|designed|owned|architected)\b", cleaned, flags=re.IGNORECASE):
            flags.append("new_personal_ownership_claim")
        hidden_terms = cls._hidden_assumption_terms(cleaned, anchor)
        if hidden_terms:
            flags.append("hidden_implementation_assumption:" + ",".join(hidden_terms[:3]))
        return flags

    @classmethod
    def _valid_short_question(cls, question: str, original: str, anchor: str = "") -> bool:
        cleaned = " ".join(str(question or "").split()).strip()
        return not cls._deterministic_repair_flags(cleaned, original=original, anchor=anchor)

    @classmethod
    def _question_speakable_enough(cls, question: str, anchor: str = "") -> bool:
        cleaned = " ".join(str(question or "").split()).strip()
        if not cleaned.endswith("?") or cleaned.count("?") > 1:
            return False
        if len(cleaned.split()) > 90 or len(cleaned) > 700:
            return False
        severe = {
            "answer_lanes_without_escape_hatch",
            "new_personal_ownership_claim",
        }
        flags = set(cls._deterministic_repair_flags(cleaned, anchor=anchor))
        if flags & severe:
            return False
        return not any(flag.startswith("hidden_implementation_assumption") for flag in flags)

    async def _verify_repaired_application_question(
        self,
        *,
        original_question: str,
        repaired_question: str,
        target_role: str,
        implementation_anchor: str,
    ) -> dict:
        deterministic_flags = self._deterministic_repair_flags(
            repaired_question,
            original=original_question,
            anchor=implementation_anchor,
        )
        if deterministic_flags:
            return {
                "accepted": False,
                "reason": "deterministic repair checks failed",
                "risk_flags": deterministic_flags,
                "source": "deterministic",
            }

        prompt = (
            "Verify whether this rewritten application-transfer interview question is safe to use.\n"
            "Accept only if it preserves the original assessment intent, target-role relevance, answer space, "
            "and does not add unsupported technical or personal-ownership assumptions.\n"
            "Return JSON only: {\"accepted\": true|false, \"reason\": \"...\", \"risk_flags\": [\"...\"]}\n\n"
            f"Target role: {target_role or 'not specified'}\n"
            f"Grounded transfer anchor: {implementation_anchor[:700]}\n"
            f"Original question: {original_question}\n"
            f"Repaired question: {repaired_question}"
        )
        try:
            result = await self.verify_llm.call(
                system="You are a strict verifier for rewritten interview questions. You check preservation of intent, role relevance, answer space, and unsupported assumptions.",
                user=prompt,
                max_tokens=300,
                response_format=JSON_OBJECT_FORMAT,
            )
        except Exception as exc:
            return {
                "accepted": False,
                "reason": f"verifier_call_failed:{type(exc).__name__}",
                "risk_flags": ["verifier_call_failed"],
                "source": "llm_verifier",
            }

        if not isinstance(result, dict):
            return {
                "accepted": False,
                "reason": "verifier returned non-json output",
                "risk_flags": ["verifier_non_json"],
                "source": "llm_verifier",
            }
        accepted = bool(result.get("accepted"))
        reason = str(result.get("reason") or "").strip() or ("accepted" if accepted else "rejected")
        raw_flags = result.get("risk_flags") or []
        risk_flags = [str(item).strip() for item in raw_flags if str(item).strip()] if isinstance(raw_flags, list) else [str(raw_flags)]
        return {
            "accepted": accepted,
            "reason": reason,
            "risk_flags": risk_flags,
            "source": "llm_verifier",
        }

    async def _run_repair_once(
        self,
        *,
        question: str,
        target_role: str,
        implementation_anchor: str,
        verifier_feedback: str = "",
        repair_llm: LLMRouter | None = None,
        repair_label: str = "primary",
    ) -> str:
        feedback_block = f"\nVerifier feedback to fix: {verifier_feedback}\n" if verifier_feedback else ""
        prompt = (
            "Rewrite this application-transfer interview question for voice.\n"
            "Keep the same assessment intent and role relevance, but make it one spoken question.\n"
            "Rules:\n"
            "- 35-60 words preferred; up to 65 only if needed.\n"
            "- One scenario, one ask, one question mark.\n"
            "- Keep light answer lanes only if useful: 'A, B, C, or something else?'\n"
            "- If you give examples or lanes, include an escape hatch like 'or something else'.\n"
            "- Do not add new technical assumptions or ownership claims.\n"
            "- Return JSON only: {\"question\": \"...\"}\n\n"
            f"Target role: {target_role or 'not specified'}\n"
            f"Grounded transfer anchor: {implementation_anchor[:600]}\n"
            f"{feedback_block}"
            f"Original question: {question}"
        )
        router = repair_llm or self.repair_llm
        result = await router.call(
            system="You rewrite long interview questions into clear spoken questions without changing the evidence being tested.",
            user=prompt,
            max_tokens=350,
            response_format=JSON_OBJECT_FORMAT,
            audit_call_name=f"ApplicationAgent.application_transfer_voice_repair.{repair_label}",
            audit_metadata={"repair_label": repair_label},
        )
        return str((result or {}).get("question") if isinstance(result, dict) else "").strip()

    def _repair_chain(self) -> list[dict]:
        chain = [{
            "label": "primary_small",
            "model": getattr(self.repair_llm, "model", "primary"),
            "llm": self.repair_llm,
            "max_attempts": 2,
        }]
        for fallback in getattr(self, "repair_fallback_llms", []) or []:
            if not isinstance(fallback, dict) or not fallback.get("llm"):
                continue
            chain.append({
                "label": str(fallback.get("label") or "fallback"),
                "model": str(fallback.get("model") or getattr(fallback.get("llm"), "model", "")),
                "llm": fallback["llm"],
                "max_attempts": 1,
            })
        return chain

    async def _repair_spoken_application_question(
        self,
        *,
        question: str,
        target_role: str,
        implementation_anchor: str,
    ) -> str:
        self.last_repair_verification = {"repair_attempted": False}
        if not self._question_too_long(question) and self._question_speakable_enough(question, implementation_anchor):
            return question

        attempts: list[dict] = []
        feedback = ""
        attempt_index = 0
        for repair_step in self._repair_chain():
            step_feedback = feedback
            for _ in range(int(repair_step.get("max_attempts") or 1)):
                attempt_index += 1
                repair_label = str(repair_step.get("label") or "repair")
                repair_model = str(repair_step.get("model") or "")
                try:
                    repaired = await self._run_repair_once(
                        question=question,
                        target_role=target_role,
                        implementation_anchor=implementation_anchor,
                        verifier_feedback=step_feedback,
                        repair_llm=repair_step.get("llm"),
                        repair_label=repair_label,
                    )
                except Exception as exc:
                    attempts.append({
                        "attempt": attempt_index,
                        "repair_label": repair_label,
                        "repair_model": repair_model,
                        "accepted": False,
                        "reason": f"repair_call_failed:{type(exc).__name__}",
                        "risk_flags": ["repair_call_failed"],
                    })
                    step_feedback = f"Previous repair call failed: {type(exc).__name__}"
                    feedback = step_feedback
                    continue

                verifier = await self._verify_repaired_application_question(
                    original_question=question,
                    repaired_question=repaired,
                    target_role=target_role,
                    implementation_anchor=implementation_anchor,
                )
                verifier.update({
                    "attempt": attempt_index,
                    "repair_label": repair_label,
                    "repair_model": repair_model,
                    "repaired_question": repaired,
                    "word_count": len(repaired.split()),
                })
                attempts.append(verifier)
                if verifier.get("accepted"):
                    self.last_repair_verification = {
                        "repair_attempted": True,
                        "repair_accepted": True,
                        "attempts": attempts,
                        "final_reason": verifier.get("reason", ""),
                        "final_risk_flags": verifier.get("risk_flags", []),
                        "final_repair_label": repair_label,
                        "final_repair_model": repair_model,
                        "fallback_to_original": False,
                    }
                    return repaired
                step_feedback = f"{verifier.get('reason', '')}; risk_flags={verifier.get('risk_flags', [])}"
                feedback = step_feedback

        if self._question_speakable_enough(question, implementation_anchor) and not self._question_too_long(question):
            self.last_repair_verification = {
                "repair_attempted": True,
                "repair_accepted": False,
                "attempts": attempts,
                "final_reason": "repair rejected; original question retained because it remains speakable",
                "final_risk_flags": ["fallback_to_original"],
                "fallback_to_original": True,
            }
            return question

        final_flags = [
            "fail_closed",
            *self._deterministic_repair_flags(question, anchor=implementation_anchor),
        ]
        if self._question_too_long(question):
            final_flags.append("original_overlong")
        self.last_repair_verification = {
            "repair_attempted": True,
            "repair_accepted": False,
            "attempts": attempts,
            "final_reason": "repair rejected and original question is not safe to retain",
            "final_risk_flags": final_flags,
            "fallback_to_original": False,
        }
        risk_summary = ", ".join(self.last_repair_verification["final_risk_flags"][:6])
        raise RuntimeError(
            "Application-transfer voice repair failed verifier and original question is not safe to retain"
            + (f": {risk_summary}" if risk_summary else ".")
        )

    async def generate(
        self,
        implementation_anchor: str,
        candidate_domain: str,
        target_role: str,
        years_experience: str,
        resume_snippets: list[str],
        anchor_source: str = "live_answer",
    ) -> AnswerCoverageMap:
        """
        Generate an application transfer question and AnswerCoverageMap.
        Raises on invalid LLM output; application transfer is assessment-critical.
        """
        resume_context = "\n".join(f"- {s}" for s in (resume_snippets or [])[:5])
        user = (
            f"Target role: {target_role or 'not specified'}\n"
            f"Experience level: {years_experience or 'mid'}\n"
            f"Candidate domain: {candidate_domain or 'not specified'}\n\n"
            f"Anchor source: {anchor_source or 'live_answer'}\n\n"
            f"Resume context:\n{resume_context or '(none)'}\n\n"
            f"Grounded transfer anchor (live evidence or role-relevant claim being transferred):\n{implementation_anchor}\n\n"
            "Generate the application transfer question and coverage map."
        )
        result = await self.llm.call(
            system=APPLICATION_SYSTEM,
            user=user,
            max_tokens=5000,
            response_format=JSON_OBJECT_FORMAT,
        )
        if not isinstance(result, dict):
            raise RuntimeError("ApplicationAgent returned non-JSON output.")

        app_question = str(result.get("application_question", "")).strip()
        if not app_question:
            raise RuntimeError("ApplicationAgent output missing application_question.")
        support_context = "\n".join(
            part for part in [
                implementation_anchor,
                f"Candidate domain: {candidate_domain}" if candidate_domain else "",
                f"Target role: {target_role}" if target_role else "",
                resume_context,
            ]
            if str(part or "").strip()
        )
        app_question = await self._repair_spoken_application_question(
            question=app_question,
            target_role=target_role,
            implementation_anchor=support_context,
        )
        app_question_flags = self._deterministic_repair_flags(app_question, anchor=support_context)
        if not self._question_speakable_enough(app_question, support_context):
            raise RuntimeError(
                "ApplicationAgent output contains unsupported or unspeakable application question: "
                + ", ".join(app_question_flags[:5])
            )

        raw_dims = result.get("dimensions") or []
        if not isinstance(raw_dims, list):
            raise RuntimeError("ApplicationAgent output key 'dimensions' must be a list.")
        dims: list[CoverageDimension] = []
        depth_eligible_count = 0
        for d in raw_dims:
            if not isinstance(d, dict):
                continue
            dim_id = str(d.get("id", "")).strip()
            label = str(d.get("label", "")).strip()
            if not dim_id:
                continue
            expected_approaches_raw = d.get("expected_approaches") or []
            if not isinstance(expected_approaches_raw, list):
                raise RuntimeError(f"ApplicationAgent dimension '{dim_id}' expected_approaches must be a list.")
            surfacing_question = str(d.get("surfacing_question", "") or "").strip()
            if not surfacing_question.endswith("?"):
                raise RuntimeError(f"ApplicationAgent dimension '{dim_id}' surfacing_question must be a question.")
            hidden_terms = self._hidden_assumption_terms(surfacing_question, support_context)
            if hidden_terms:
                raise RuntimeError(
                    f"ApplicationAgent dimension '{dim_id}' contains unsupported hidden implementation assumptions: "
                    + ", ".join(hidden_terms[:5])
                )
            try:
                weight = float(d.get("weight", 1.5))
            except (TypeError, ValueError):
                raise RuntimeError(f"ApplicationAgent dimension '{dim_id}' has invalid weight.")
            weight = max(1.0, min(3.0, weight))
            raw_surface_kind = str(d.get("surface_kind") or "breadth").strip().lower()
            surface_kind = raw_surface_kind if raw_surface_kind in {"breadth", "depth"} else "breadth"
            depth_eligible = bool(d.get("depth_eligible", False)) or surface_kind == "depth"
            if depth_eligible:
                depth_eligible_count += 1
                if depth_eligible_count > 2:
                    depth_eligible = False
                    surface_kind = "breadth"
            dims.append(CoverageDimension(
                id=dim_id,
                label=label or dim_id,
                description=str(d.get("description", "")),
                expected_approaches=[str(item).strip() for item in expected_approaches_raw if str(item).strip()],
                surfacing_question=surfacing_question,
                weight=weight,
                depth_eligible=depth_eligible,
                surface_kind=surface_kind,
            ))

        if len(dims) < 2:
            raise RuntimeError("ApplicationAgent output missing coverage dimensions.")
        if len(dims) > 3:
            dims = dims[:3]
        if sum(1 for d in dims if d.depth_eligible) > 2:
            raise RuntimeError("ApplicationAgent output marked too many dimensions as depth_eligible.")

        try:
            coverage_confidence = float(result.get("coverage_confidence") or 0.5)
        except (TypeError, ValueError):
            raise RuntimeError("ApplicationAgent output has invalid coverage_confidence.")
        coverage_confidence = max(0.0, min(1.0, coverage_confidence))
        grounding_needed = bool(result.get("grounding_needed")) or self._anchor_depth_ambiguous(implementation_anchor)
        grounding_question = str(result.get("grounding_question") or "").strip()
        if grounding_needed:
            if not grounding_question.endswith("?") or self._hidden_assumption_terms(grounding_question, support_context):
                grounding_question = self._default_grounding_question(implementation_anchor, target_role)
        else:
            grounding_question = ""
        try:
            max_depth_level = int(float(result.get("max_depth_level") or 3))
        except (TypeError, ValueError):
            max_depth_level = 3
        max_depth_level = max(1, min(4, max_depth_level))
        depth_allowed_raw = result.get("depth_allowed_terms") or []
        depth_allowed_terms = [
            str(item).strip()
            for item in depth_allowed_raw
            if str(item).strip()
        ] if isinstance(depth_allowed_raw, list) else []

        return AnswerCoverageMap(
            application_question=app_question,
            implementation_anchor=implementation_anchor,
            dimensions=dims,
            total_weight=sum(d.weight for d in dims),
            coverage_confidence=coverage_confidence,
            grounding_question=grounding_question,
            grounding_needed=grounding_needed,
            max_depth_level=max_depth_level,
            depth_allowed_terms=depth_allowed_terms[:8],
        )

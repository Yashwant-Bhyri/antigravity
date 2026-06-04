from backend.services.interview_map import _focus_plan_user_prompt
from backend.services.surface_plan import (
    compact_surface_plan_for_prompt,
    normalize_surface_plan_v2,
    surface_plan_alignment_warnings,
)


def _sample_surface_plan() -> dict:
    return normalize_surface_plan_v2({
        "focus_areas": [
            {
                "focus_key": "seller_activation_attribution",
                "label": "Seller activation attribution",
                "why_high_signal": "Tests attribution, denominator design, and confound handling.",
                "role_relevance": 5,
                "profile_importance": 5,
                "evidence_strength": 4,
                "claim_risk": 5,
                "recommended_allocation_hint": 0.42,
                "source_snippets": ["Reported seller activation improved from 22% to 38%."],
                "sub_focuses": [
                    {
                        "sub_focus_key": "support_kyc_confound",
                        "label": "Support-call and KYC confound",
                        "surface_kind": "attribution",
                        "why_test": "Checks whether the candidate can separate overlapping interventions.",
                        "testable_surfaces": ["support-call split", "KYC UX split"],
                        "source_snippets": ["checklist, support-call, and KYC UX changes"],
                    }
                ],
            },
            {
                "focus_key": "marketplace_health_dashboard",
                "label": "Marketplace health dashboard",
                "why_high_signal": "Tests operating metrics and dashboard judgment.",
                "role_relevance": 5,
                "profile_importance": 4,
                "evidence_strength": 4,
                "claim_risk": 3,
                "recommended_allocation_hint": 0.24,
                "source_snippets": ["Built marketplace health dashboard for seller activation, buyer conversion, refunds, and support SLA."],
                "sub_focuses": [],
            },
        ],
        "demoted_or_off_role_surfaces": [
            {
                "label": "OCR invoice parser side project",
                "reason": "Not production deployed and not central to Product Analytics Engineer role.",
                "source_snippets": ["Side project: OCR invoice parser using Tesseract."],
            }
        ],
        "missing_or_risky_checks": ["Do not let OCR outrank marketplace analytics."],
    })


def test_surface_plan_prompt_is_first_class_but_advisory() -> None:
    prompt = _focus_plan_user_prompt(
        resume="QuickKart marketplace analytics resume",
        target_role="Product Analytics Engineer",
        surface_plan_v2=_sample_surface_plan(),
    )

    assert "SurfacePlanV2 typed recommendation" in prompt
    assert "Seller activation attribution" in prompt
    assert "recommended_allocation_hint" in prompt
    assert "advisory only" in prompt
    assert "never convert it directly into question counts" in prompt
    assert "Demoted/off-role surfaces should not become launch focus areas" in prompt


def test_compact_surface_plan_preserves_testable_surfaces() -> None:
    compact = compact_surface_plan_for_prompt(_sample_surface_plan())

    assert "support-call split" in compact
    assert "KYC UX split" in compact
    assert "OCR invoice parser side project" in compact


def test_alignment_warns_when_high_signal_surface_is_omitted() -> None:
    focus_plan = {
        "focus_areas": [
            {
                "focus_key": "onboarding_taxonomy",
                "label": "Seller onboarding taxonomy",
                "sub_focuses": [{"surface_kind": "taxonomy", "coverage_value": 2.5}],
            }
        ]
    }

    warnings = surface_plan_alignment_warnings(focus_plan, _sample_surface_plan())

    assert any("Seller activation attribution" in warning for warning in warnings)
    assert any("Marketplace health dashboard" in warning for warning in warnings)


def test_alignment_warns_when_demoted_surface_becomes_routable() -> None:
    focus_plan = {
        "focus_areas": [
            {
                "focus_key": "ocr_side_project",
                "label": "OCR side project credibility check",
                "coverage_value": 2.6,
                "sub_focuses": [],
            }
        ]
    }

    warnings = surface_plan_alignment_warnings(focus_plan, _sample_surface_plan())

    assert any("off-role" in warning.lower() or "credibility" in warning.lower() for warning in warnings)


def main() -> None:
    test_surface_plan_prompt_is_first_class_but_advisory()
    test_compact_surface_plan_preserves_testable_surfaces()
    test_alignment_warns_when_high_signal_surface_is_omitted()
    test_alignment_warns_when_demoted_surface_becomes_routable()
    print("surface plan contracts passed")


if __name__ == "__main__":
    main()

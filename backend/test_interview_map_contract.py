"""
Contract checks for deterministic interview-map quality on messy resume input.

Run with:
  python3 -m backend.test_interview_map_contract
"""

from backend.services.interview_map import build_deterministic_interview_map


MESSY_RESUME = """
(+86) 15914122353 | 123040005@link.cuhk.edu.cn| 2001 Longxiang Boulevard, Longgang District, Shenzhen :
TheChineseUniversityofHongKong,Shenzhen(B.Eng. in Computer Science and Engineering)
2024 Guangdong Government Outstanding International Student Scholarship
2025 Leading Academic Peer Advisor @ School of Data Science, CUHK-SZ
TECHNICAL SKILLS:
Top Skills: Python, C++, SQL Hybrid, RISC- V, Git, Docker, Google GCP, AWS Deployment, Linux, Deployment Testing
EXPERIENCE:
AI Agent Development Engineer [Intern] : AIGC Algorithms - Wondershare Filmora @ Shenzhen Jan 2026 – Present
Architected and prototyped an end-to-end Agent based AIGC video generation and editing pipeline on Google ADK by implementing a unified seed-based generation workflow.
Engineered a ML - feature-map control system that translates orthogonal control axes into pixel-level semantic generation instructions for Google Veo 3 seed-regeneration.
Built a semantic UI-to-latent translation interface that maps intuitive editing controls to diffusion conditioning vectors.
AI Engineer Intern : AI Model Developer - Optek Microelectronics @ Shenzhen, China 2025 July - Sept
Engineered a full-stack TinyML Audio Classification Pipeline, by integrating MediaPipe Audio for real-time feature extraction, TensorFlow Lite-Micro INT8 for quantized inference, and Edge Impulse for SDK deployment.
Optimized and delivered a custom classifier for a 700 MHz DSP + 16 MB NPU, accomplishing <10 ms latency and 4× model compression.
Research Assistant : HKU- COLUMBIA- ALIBABA- CUHKSZ@ BIRD Vision 2025 June - Sept
Reconstructed an advanced multi-modal benchmark framework that pioneered BIRD-SQL dataset.
Designed relational DB schemas, and created complex hybrid SQL queries.
"""


def main() -> None:
    interview_map = build_deterministic_interview_map(resume=MESSY_RESUME)
    focus_areas = interview_map.get("focus_areas", [])

    assert 3 <= len(focus_areas) <= 5, len(focus_areas)

    labels = [area["label"] for area in focus_areas]

    # Noise must never become a focus area
    banned = ("Scholarship", "Advisor", "University", "Longxiang", "Skills", "+86", "15914122353")
    for label in labels:
        assert not any(token.lower() in label.lower() for token in banned), (
            f"Noise label found: {label} — banned tokens: {banned}\nAll labels: {labels}"
        )

    # The three distinct work experiences must each be represented
    # (labels are generative — we check presence of key content words, not exact strings)
    combined = " ".join(labels).lower()
    assert "pipeline" in combined or "aigc" in combined or "video" in combined, (
        f"Filmora AIGC work missing from labels: {labels}"
    )
    assert "classifier" in combined or "audio" in combined or "tinyml" in combined, (
        f"Optek TinyML work missing from labels: {labels}"
    )
    assert "benchmark" in combined or "sql" in combined or "bird" in combined, (
        f"BIRD Vision work missing from labels: {labels}"
    )

    # Every area must have the required structure
    for area in focus_areas:
        if area.get("track_schema") == "dimension":
            assert str(area.get("opener", "")).strip(), area["label"]
            dims = area.get("dimensions", [])
            assert len(dims) >= 3, (area["label"], dims)
            for dim in dims:
                for key in ("surface", "mechanism", "boundary"):
                    assert str(dim.get(key, "")).strip(), (area["label"], dim.get("id"), key)
            recovery = area.get("recovery", {})
            for branch in (
                "short_answer",
                "honest_gap",
                "claim_conflict",
                "metric_risk",
                "overclaim_risk",
                "bridge",
            ):
                assert str(recovery.get(branch, "") or "").strip(), (area["label"], branch)
            continue

        for sprint_key in ("sprint_1", "sprint_2", "sprint_3"):
            sprint = area.get(sprint_key, {})
            for branch in (
                "if_strong",
                "if_vague",
                "if_honest_gap",
                "if_claim_conflict",
                "if_short_answer",
                "bridge_to_next_focus",
            ):
                value = str(sprint.get(branch, "") or "").strip()
                assert value, (area["label"], sprint_key, branch)

    print("deterministic interview-map contract checks passed")
    print(f"  focus areas: {labels}")


if __name__ == "__main__":
    main()

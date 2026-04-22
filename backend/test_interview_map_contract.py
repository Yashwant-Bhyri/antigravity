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
    banned = ("Scholarship", "Advisor", "University", "Longxiang", "Skills")
    for label in labels:
        assert not any(token.lower() in label.lower() for token in banned), labels

    expected = {
        "Agent Based AIGC Video Generation And Editing Pipeline",
        "Feature-Map Control System",
        "TinyML Audio Classification Pipeline",
        "Multi-Modal Benchmark Framework",
    }
    assert expected.issubset(set(labels)), labels

    for area in focus_areas:
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

    tinyml = next(area for area in focus_areas if area["label"] == "TinyML Audio Classification Pipeline")
    interface = next(area for area in focus_areas if area["label"] == "Feature-Map Control System")
    benchmark = next(area for area in focus_areas if area["label"] == "Multi-Modal Benchmark Framework")

    assert "TensorFlow Lite-Micro INT8" in tinyml["sprint_1"]["if_strong"], tinyml["sprint_1"]["if_strong"]
    assert "Google Veo 3" in interface["sprint_1"]["if_short_answer"] or "Google Veo 3" in interface["sprint_2"]["if_strong"], interface
    assert "evaluation" in benchmark["sprint_2"]["if_strong"].lower() or "benchmark" in benchmark["sprint_2"]["if_strong"].lower(), benchmark["sprint_2"]["if_strong"]

    print("deterministic interview-map contract checks passed")


if __name__ == "__main__":
    main()

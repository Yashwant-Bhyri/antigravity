"""
Focused regression checks for interview-map fallback extraction.

Run with:
  python3 -m backend.test_interview_map_fallback
"""

from backend.services.interview_map import _fallback_focus_seeds_from_resume, _fallback_track


SAMPLE_RESUME = """
AI Agent Development Engineer [Intern] : AIGC Algorithms - Wondershare Filmora @ Shenzhen Jan 2026 – Present
Architected and prototyped an end-to-end Agent based AIGC video generation and editing pipeline on Google ADK by implementing a unified seed-based generation workflow.
Engineered a ML - feature-map control system that translates orthogonal control axes into pixel-level semantic generation instructions.
Built a semantic UI-to-latent translation interface that maps intuitive editing controls to diffusion conditioning vectors.

AI Engineer Intern : AI Model Developer - Optek Microelectronics @ Shenzhen, China 2025 July - Sept
Engineered a full-stack TinyML Audio Classification Pipeline, by integrating MediaPipe Audio and TensorFlow Lite-Micro INT8.
Optimized and delivered a custom classifier for a 700 MHz DSP + 16 MB NPU.

Research Assistant : HKU- COLUMBIA- ALIBABA- CUHKSZ@ BIRD Vision 2025 June - Sept
Reconstructed an advanced multi-modal benchmark framework that pioneered BIRD-SQL dataset.
Designed relational DB schemas, and created complex hybrid SQL queries.
"""


def main() -> None:
    seeds = _fallback_focus_seeds_from_resume(SAMPLE_RESUME)
    labels = [seed["label"] for seed in seeds]

    assert "Feature-Map Control System" in labels, labels
    assert "TinyML Audio Classification Pipeline" in labels, labels
    assert "Multi-Modal Benchmark Framework" in labels, labels
    assert "Audio Classification Pipeline" not in labels, labels

    tinyml_seed = next(seed for seed in seeds if seed["label"] == "TinyML Audio Classification Pipeline")
    tinyml_track = _fallback_track(tinyml_seed, "Feature-Map Control System")

    sprint_1 = tinyml_track["sprint_1"]["if_strong"]
    sprint_2 = tinyml_track["sprint_2"]["if_strong"]
    assert "TensorFlow Lite-Micro INT8" in sprint_1, sprint_1
    assert (
        "inference" in sprint_2.lower()
        or "feature-extraction" in sprint_2.lower()
        or "accuracy" in sprint_2.lower()
    ), sprint_2

    print("fallback interview-map regression checks passed")


if __name__ == "__main__":
    main()

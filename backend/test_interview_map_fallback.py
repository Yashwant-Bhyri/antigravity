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

    # Noise must never become a focus area
    banned = ("Scholarship", "Advisor", "University", "Skills", "Contact")
    for label in labels:
        assert not any(token.lower() in label.lower() for token in banned), (
            f"Noise label found: {label} — banned tokens: {banned}\nAll labels: {labels}"
        )

    # The three distinct work experiences must each be represented
    combined = " ".join(labels).lower()
    assert any(token in combined for token in ("aigc", "video", "pipeline", "agent")), (
        f"Filmora AIGC work missing from labels: {labels}"
    )
    assert any(token in combined for token in ("audio", "classifier", "tinyml", "classification")), (
        f"Optek audio/classifier work missing from labels: {labels}"
    )
    assert any(token in combined for token in ("benchmark", "sql", "bird", "multi-modal")), (
        f"BIRD Vision work missing from labels: {labels}"
    )

    # Pick the audio/classifier seed and verify the fallback track has substantive content
    audio_seed = next(
        (s for s in seeds if any(t in s["label"].lower() for t in ("audio", "classifier", "tinyml", "classification"))),
        None,
    )
    assert audio_seed is not None, f"No audio/classifier seed found in labels: {labels}"

    next_label = next(
        (s["label"] for s in seeds if s["label"] != audio_seed["label"]),
        "Multi-Modal Benchmark Framework",
    )
    audio_track = _fallback_track(audio_seed, next_label)

    sprint_1 = audio_track["sprint_1"]["if_strong"]
    sprint_2 = audio_track["sprint_2"]["if_strong"]

    # Sprint 1 should name the artifact and a specific tech or inference framing
    assert audio_seed["label"] in sprint_1 or "inference" in sprint_1.lower() or "dsp" in sprint_1.lower(), sprint_1
    # Sprint 2 should probe inference/feature-extraction depth
    assert (
        "inference" in sprint_2.lower()
        or "feature-extraction" in sprint_2.lower()
        or "accuracy" in sprint_2.lower()
    ), sprint_2

    print("fallback interview-map regression checks passed")
    print(f"  labels: {labels}")


if __name__ == "__main__":
    main()

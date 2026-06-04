"""
Focused regression check: interview-map fallbacks are disabled.

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
    for fn, args in (
        (_fallback_focus_seeds_from_resume, (SAMPLE_RESUME,)),
        (_fallback_track, ({"label": "TinyML Audio Classifier", "focus_key": "tinyml_audio_classifier"}, "BIRD SQL")),
    ):
        try:
            fn(*args)
        except RuntimeError as exc:
            assert "disabled" in str(exc).lower(), exc
            continue
        raise AssertionError(f"{fn.__name__} unexpectedly succeeded")

    print("interview-map fallback helpers are disabled")


if __name__ == "__main__":
    main()

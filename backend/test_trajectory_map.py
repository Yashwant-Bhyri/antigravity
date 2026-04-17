"""
Simulation test for the resume-grounded interview map / trajectory bank.
Tests the 5 scenarios Codex specified.

Run with: python -m backend.test_trajectory_map
Backend must be running on localhost:8000.
"""

import asyncio
import json
import time
import httpx

BASE = "http://127.0.0.1:8000/api"

SAMPLE_RESUME = """
Name: Alex Chen
Target Role: AI/ML Engineer

Experience:
- AI Engineering Intern @ Wondershare Filmora (Jan 2026 – Present)
  Architected end-to-end AIGC pipeline for video generation with ML feature-map control system
  Built seed-to-video generation workflow, latency optimization for content preview

Projects:
- TinyML Audio Classification Pipeline
  Engineered full-stack TinyML pipeline: MediaPipe Audio feature extraction, custom MobileNet architecture
  Optimized model performance for custom 700 MHz DSP + 16 MB NPU: INT8 quantization, <10ms latency
  Delivered production-ready classifier with 94% F1 on-device

- Emotionally Intelligent Health Agent
  Multi-modal agent system (audio + vision) for emotional state recognition
  Audio: DSP feature extraction (MFCCs, spectral features), numerically stable softmax
  Deployed with <100ms audio processing pipeline

Skills: Python, C++, PyTorch, TensorFlow Lite, MediaPipe, WebGL, DSP, INT8 quantization, TinyML
"""

TURN1_SUBSTANTIVE = (
    "So I built the TinyML pipeline during my research project at CUHK. The main challenge was "
    "fitting a MobileNet variant into 16 MB of NPU memory. I used INT8 quantization and had to "
    "rewrite the softmax to avoid overflow at low precision. Got it down to under 10ms on the "
    "700 MHz DSP which was the target."
)


async def start_interview() -> tuple[str, str, dict]:
    async with httpx.AsyncClient(timeout=240) as c:
        r = await c.post(f"{BASE}/start_interview", json={
            "resume": SAMPLE_RESUME,
            "target_role": "AI/ML Engineer",
            "years_experience": "0-1",
        })
        r.raise_for_status()
        d = r.json()
        return d["session_id"], d["opening_question"], d


async def process_turn(session_id: str, transcript: str, turn_id: str = "") -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{BASE}/process_turn", json={
            "session_id": session_id,
            "transcript": transcript,
            "turn_id": turn_id or f"t_{int(time.time()*1000)}",
        })
        r.raise_for_status()
        return r.json()


def print_turn(label: str, answer: str, result: dict) -> None:
    q = result.get("response", "")
    route = result.get("route_kind", result.get("served_route_kind", "?"))
    print(f"\n  Answer: {answer[:80]!r}")
    print(f"  → Q: {q[:120]!r}")
    print(f"  → route_kind: {route}")


async def check_map_ready(session_id: str) -> None:
    """
    Verify the trajectory map is in state.
    start_interview now blocks until map is built, so this should
    always pass immediately. A failure here means generation broke.
    """
    deadline = time.time() + 180
    async with httpx.AsyncClient(timeout=30) as c:
        while time.time() < deadline:
            try:
                r = await c.get(f"{BASE}/state/{session_id}")
                if r.status_code == 200:
                    state = r.json()
                    tmap = state.get("interview_trajectory_map", {})
                    if tmap.get("focus_areas"):
                        areas = [a["label"] for a in tmap["focus_areas"]]
                        print(f"  [map ready] {len(areas)} focus areas: {areas}")
                        return
            except Exception as e:
                print(f"  [map poll retry] {type(e).__name__}")
            await asyncio.sleep(1.5)
    print("  [map] FAIL: map not in state before deadline")


# ─────────────────────────────────────────────
# TEST SCENARIOS
# ─────────────────────────────────────────────

async def scenario_1_vague_short():
    """Vague short answers after a substantive turn 1."""
    print("\n=== SCENARIO 1: Vague short answers ===")
    sid, opener, startup = await start_interview()
    print(f"  Session: {sid[:8]}")
    print(f"  Opening: {opener[:80]!r}")
    print(f"  Startup map preview: {json.dumps(startup.get('trajectory_focus_preview', []), indent=2)[:800]}")

    # Wait for map
    await check_map_ready(sid)

    # Turn 1: substantive
    r = await process_turn(sid, TURN1_SUBSTANTIVE)
    print_turn("T1 (substantive)", TURN1_SUBSTANTIVE, r)

    # Turn 2–4: vague short
    for ans in ["Mostly cost.", "Latency.", "Quality tradeoffs."]:
        r = await process_turn(sid, ans)
        print_turn(f"T(short)", ans, r)


async def scenario_2_honest_short():
    """Candidate admits they didn't write parts of the code."""
    print("\n=== SCENARIO 2: Honest short / admission ===")
    sid, opener, startup = await start_interview()
    print(f"  Session: {sid[:8]}")
    print(f"  Startup map preview: {json.dumps(startup.get('trajectory_focus_preview', []), indent=2)[:800]}")

    await check_map_ready(sid)

    r = await process_turn(sid, TURN1_SUBSTANTIVE)
    print_turn("T1 (substantive)", TURN1_SUBSTANTIVE, r)

    for ans in ["I didn't write the DSP from scratch.", "Mostly framework support."]:
        r = await process_turn(sid, ans)
        print_turn("T(honest)", ans, r)


async def scenario_3_topic_switch():
    """Candidate switches topics mid-interview."""
    print("\n=== SCENARIO 3: Topic-switch short ===")
    sid, opener, startup = await start_interview()
    print(f"  Session: {sid[:8]}")
    print(f"  Startup map preview: {json.dumps(startup.get('trajectory_focus_preview', []), indent=2)[:800]}")

    await check_map_ready(sid)

    filmora_t1 = (
        "At Filmora I was working on the AIGC video generation pipeline. "
        "We used a seed-based system where users pick a style and the model generates frames."
    )
    r = await process_turn(sid, filmora_t1)
    print_turn("T1 (Filmora)", filmora_t1, r)

    for ans in ["Also the audio classifier.", "Mostly embedded constraints.", "Memory budget."]:
        r = await process_turn(sid, ans)
        print_turn("T(switch)", ans, r)


async def scenario_4_short_but_specific():
    """Short but specific answers — should get deeper follow-ups, not generic fallback."""
    print("\n=== SCENARIO 4: Short but specific ===")
    sid, opener, startup = await start_interview()
    print(f"  Session: {sid[:8]}")
    print(f"  Startup map preview: {json.dumps(startup.get('trajectory_focus_preview', []), indent=2)[:800]}")

    await check_map_ready(sid)

    r = await process_turn(sid, TURN1_SUBSTANTIVE)
    print_turn("T1 (substantive)", TURN1_SUBSTANTIVE, r)

    for ans in ["Mostly user control.", "Seed drift.", "We logged regeneration failures."]:
        r = await process_turn(sid, ans)
        print_turn("T(specific-short)", ans, r)


async def scenario_5_delayed_turn1():
    """Verify map is populated and actually used before Turn 1 answer."""
    print("\n=== SCENARIO 5: Delayed Turn 1 — map must be ready ===")
    sid, opener, startup = await start_interview()
    print(f"  Session: {sid[:8]}")
    print(f"  Startup map preview: {json.dumps(startup.get('trajectory_focus_preview', []), indent=2)[:800]}")

    # Simulate candidate thinking for 5s before answering
    print("  Waiting 3s (simulating candidate reading question)...")
    await asyncio.sleep(3.0)
    await check_map_ready(sid)

    # Very short Turn 1 to force trajectory map path
    short_t1 = "I built the audio pipeline."
    r = await process_turn(sid, short_t1)
    print_turn("T1 (short)", short_t1, r)

    short_t2 = "Just the feature extraction part."
    r = await process_turn(sid, short_t2)
    print_turn("T2 (short)", short_t2, r)


async def main():
    print("=" * 60)
    print("Trajectory Bank Simulation Test")
    print("=" * 60)

    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.get(f"{BASE}/tts_health")
    except Exception:
        print("ERROR: Backend not reachable at localhost:8000")
        return

    await scenario_1_vague_short()
    await scenario_2_honest_short()
    await scenario_3_topic_switch()
    await scenario_4_short_but_specific()
    await scenario_5_delayed_turn1()

    print("\n" + "=" * 60)
    print("Done. Check route_kind values — should NOT see 'sprint_fallback' after Turn 1.")
    print("Trajectory map routes: trajectory_map_short_answer_rescue, trajectory_map_honesty_probe,")
    print("                       trajectory_map_followup, trajectory_map_bridge, trajectory_map_challenge")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

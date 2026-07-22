"""Regression contract for the production interview-room API boundary."""

import os
import subprocess
import sys
from pathlib import Path

from backend.main import _is_internal_api_path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert not _is_internal_api_path("/api/state/session-id", "GET")
    assert _is_internal_api_path("/api/telemetry/session-id", "GET")
    assert _is_internal_api_path("/api/replay/cases", "GET")

    env = dict(os.environ)
    env.pop("OPENROUTER_API_KEY", None)
    env.pop("CEREBRAS_API_KEY", None)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fastapi.testclient import TestClient; "
                "from backend.main import app; "
                "client=TestClient(app); "
                "response=client.get('/healthz'); "
                "assert response.status_code == 200, response.text"
            ),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert probe.returncode == 0, probe.stderr or probe.stdout
    print("Public interview route contract passed.")


if __name__ == "__main__":
    main()

"""Focused safety contracts for the bounded local credential loader."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.services.local_experiment_credentials import (
    EXPERIMENT_ENV_BASENAME,
    EXPERIMENT_ENV_OVERRIDE,
    LocalExperimentCredentialError,
    load_local_experiment_credentials,
    resolve_local_experiment_env,
)


TRACKED_ENV_NAMES = (
    "DASHSCOPE_API_KEY",
    "ALIBABA_WORKSPACE_ID",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY",
)


@contextmanager
def _without_tracked_environment():
    missing = object()
    previous = {name: os.environ.get(name, missing) for name in TRACKED_ENV_NAMES}
    for name in TRACKED_ENV_NAMES:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in previous.items():
            os.environ.pop(name, None)
            if value is not missing:
                os.environ[name] = value


def _git_common_dir_result(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git", "rev-parse", "--git-common-dir"],
        returncode=0,
        stdout=f"{path / '.git'}\n",
        stderr="",
    )


def _write_dedicated(path: Path, content: str = "OPENROUTER_API_KEY=file-secret\n", mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


class LocalExperimentCredentialTests(unittest.TestCase):
    def test_primary_checkout_resolution_uses_dedicated_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            primary = Path(temporary) / "primary"
            dedicated = _write_dedicated(primary / EXPERIMENT_ENV_BASENAME)
            with patch(
                "backend.services.local_experiment_credentials.subprocess.run",
                return_value=_git_common_dir_result(primary),
            ):
                self.assertEqual(resolve_local_experiment_env(worktree_root=primary), dedicated.resolve())

    def test_linked_worktree_resolution_uses_primary_common_dir(self):
        with tempfile.TemporaryDirectory() as temporary:
            primary = Path(temporary) / "primary"
            linked = Path(temporary) / "linked"
            primary.mkdir()
            linked.mkdir()
            dedicated = _write_dedicated(primary / EXPERIMENT_ENV_BASENAME)
            with patch(
                "backend.services.local_experiment_credentials.subprocess.run",
                return_value=_git_common_dir_result(primary),
            ):
                self.assertEqual(resolve_local_experiment_env(worktree_root=linked), dedicated.resolve())

    def test_missing_file_does_not_fall_back_to_generic_dotenv(self):
        with tempfile.TemporaryDirectory() as temporary:
            primary = Path(temporary) / "primary"
            linked = Path(temporary) / "linked"
            primary.mkdir()
            linked.mkdir()
            generic = primary / ".env"
            generic.write_text("OPENROUTER_API_KEY=generic-secret\n", encoding="utf-8")
            with _without_tracked_environment(), patch(
                "backend.services.local_experiment_credentials.subprocess.run",
                return_value=_git_common_dir_result(primary),
            ):
                metadata = load_local_experiment_credentials(worktree_root=linked)
            self.assertFalse(metadata["loaded"])
            self.assertEqual(metadata["reason"], "local_experiment_env_missing")
            self.assertEqual(metadata["path"], str((primary / EXPERIMENT_ENV_BASENAME).resolve()))
            self.assertNotIn("generic-secret", os.environ)
            self.assertTrue(generic.exists())

    def test_unsafe_permissions_are_rejected_before_dotenv_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            dedicated = _write_dedicated(Path(temporary) / EXPERIMENT_ENV_BASENAME, mode=0o644)
            with self.assertRaisesRegex(LocalExperimentCredentialError, "permissions_too_broad"):
                load_local_experiment_credentials(env_path=dedicated)

    def test_explicit_override_must_be_the_dedicated_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            generic = Path(temporary) / ".env"
            with self.assertRaisesRegex(LocalExperimentCredentialError, "must_be_dedicated_file"):
                resolve_local_experiment_env(worktree_root=Path(temporary), explicit_override=generic)
            with patch.dict(os.environ, {EXPERIMENT_ENV_OVERRIDE: str(generic)}, clear=False):
                with self.assertRaisesRegex(LocalExperimentCredentialError, "must_be_dedicated_file"):
                    resolve_local_experiment_env(worktree_root=Path(temporary))

    def test_metadata_is_redacted_and_native_environment_wins(self):
        with tempfile.TemporaryDirectory() as temporary:
            dedicated = _write_dedicated(Path(temporary) / EXPERIMENT_ENV_BASENAME)
            with _without_tracked_environment():
                os.environ["OPENROUTER_API_KEY"] = "native-secret"
                metadata = load_local_experiment_credentials(env_path=dedicated)
                serialized = json.dumps(metadata, sort_keys=True)
                self.assertTrue(metadata["loaded"])
                self.assertTrue(metadata["configured"]["OPENROUTER_API_KEY"])
                self.assertEqual(os.environ["OPENROUTER_API_KEY"], "native-secret")
                self.assertNotIn("native-secret", serialized)
                self.assertNotIn("file-secret", serialized)
                self.assertIn(EXPERIMENT_ENV_BASENAME, metadata["path"])


if __name__ == "__main__":
    unittest.main()

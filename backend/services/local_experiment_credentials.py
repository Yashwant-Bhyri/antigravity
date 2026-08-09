"""Explicit, local-only credential loading for bounded experiment runners.

This module is for isolated test harnesses only.  It loads only the dedicated
Git-ignored ``.env.qwen.local`` file through :mod:`python-dotenv`; it never
falls back to a generic ``.env`` file and never returns, logs, or serializes
credential values.  Production deployment continues to use native
process-environment injection.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Sequence


EXPERIMENT_ENV_BASENAME = ".env.qwen.local"
EXPERIMENT_ENV_OVERRIDE = "ANTIGRAVITY_LOCAL_EXPERIMENT_ENV"

# Kept as a compatibility constant for callers that only need the isolated
# checkout's local candidate.  ``load_local_experiment_credentials`` resolves
# the primary checkout dynamically for linked worktrees.
LOCAL_EXPERIMENT_ENV = Path(__file__).resolve().parents[2] / EXPERIMENT_ENV_BASENAME


class LocalExperimentCredentialError(RuntimeError):
    """Dedicated local credential file is invalid or has unsafe permissions."""


def _git_stdout(arguments: Sequence[str], *, cwd: Path) -> str:
    """Return non-secret Git metadata, or an empty string if unavailable."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _absolute_path(raw_path: str | Path, *, cwd: Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve(strict=False)


def resolve_primary_worktree_root(worktree_root: str | Path | None = None) -> Path:
    """Resolve the primary checkout root using Git metadata only.

    In a linked worktree, ``git rev-parse --git-common-dir`` points at the
    primary checkout's shared ``.git`` directory.  The porcelain worktree
    listing is a bounded fallback for Git implementations that do not expose
    that path.  No repository files, environment files, or credential values
    are read by this resolver.
    """

    current = Path(worktree_root or Path(__file__).resolve().parents[2]).resolve()
    common_dir_text = _git_stdout(("rev-parse", "--git-common-dir"), cwd=current)
    if common_dir_text:
        common_dir = _absolute_path(common_dir_text, cwd=current)
        if common_dir.name == ".git":
            return common_dir.parent

    worktree_listing = _git_stdout(("worktree", "list", "--porcelain"), cwd=current)
    for line in worktree_listing.splitlines():
        if line.startswith("worktree "):
            candidate = Path(line.removeprefix("worktree ").strip())
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
    return current


def resolve_local_experiment_env(
    *,
    worktree_root: str | Path | None = None,
    explicit_override: str | Path | None = None,
) -> Path:
    """Find the dedicated local experiment file without generic dotenv fallback.

    ``explicit_override`` (or ``ANTIGRAVITY_LOCAL_EXPERIMENT_ENV``) is allowed
    only when its final basename is exactly ``.env.qwen.local``.  Otherwise,
    the isolated checkout is checked first and the Git primary checkout second.
    A missing path is still returned so callers can emit redacted missing-file
    metadata without probing any other dotenv filename.
    """

    current = Path(worktree_root or Path(__file__).resolve().parents[2]).resolve()
    override = explicit_override
    if override is None:
        override = os.environ.get(EXPERIMENT_ENV_OVERRIDE, "").strip()
    if override:
        candidate = _absolute_path(override, cwd=current)
        if candidate.name != EXPERIMENT_ENV_BASENAME:
            raise LocalExperimentCredentialError("local_experiment_env_override_must_be_dedicated_file")
        return candidate

    primary = resolve_primary_worktree_root(current)
    candidates = [current / EXPERIMENT_ENV_BASENAME]
    if primary != current:
        candidates.append(primary / EXPERIMENT_ENV_BASENAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return (primary / EXPERIMENT_ENV_BASENAME).resolve()


def load_local_experiment_credentials(
    *,
    worktree_root: str | Path | None = None,
    env_path: str | Path | None = None,
) -> dict[str, object]:
    """Load the dedicated ignored file without exposing any values.

    Existing injected environment variables win because dotenv is called with
    ``override=False``.  Returned metadata contains only path/presence and
    boolean configured flags suitable for redacted experiment traces.
    """

    path = resolve_local_experiment_env(worktree_root=worktree_root, explicit_override=env_path)
    if not path.exists():
        return {
            "loaded": False,
            "reason": "local_experiment_env_missing",
            "path": str(path),
        }
    if path.is_symlink() or not path.is_file():
        raise LocalExperimentCredentialError("local_experiment_env_not_regular_file")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise LocalExperimentCredentialError("local_experiment_env_permissions_too_broad")
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - requirements pin python-dotenv.
        raise LocalExperimentCredentialError("python_dotenv_missing") from exc
    load_dotenv(path, override=False)
    tracked = (
        "DASHSCOPE_API_KEY",
        "ALIBABA_WORKSPACE_ID",
        "CEREBRAS_API_KEY",
        "OPENROUTER_API_KEY",
    )
    return {
        "loaded": True,
        "path": str(path),
        "configured": {name: bool(os.environ.get(name, "").strip()) for name in tracked},
    }


__all__ = [
    "EXPERIMENT_ENV_BASENAME",
    "EXPERIMENT_ENV_OVERRIDE",
    "LOCAL_EXPERIMENT_ENV",
    "LocalExperimentCredentialError",
    "load_local_experiment_credentials",
    "resolve_local_experiment_env",
    "resolve_primary_worktree_root",
]

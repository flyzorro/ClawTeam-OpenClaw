"""Helpers for making the current clawteam executable available to spawned agents."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


class ClawteamExecutableResolutionError(RuntimeError):
    """Raised when a tested repo requires a pinned same-source clawteam binary."""


def _looks_like_clawteam_entrypoint(value: str) -> bool:
    """Return True when argv0 plausibly points at the clawteam CLI."""

    name = Path(value).name.lower()
    return name == "clawteam" or name.startswith("clawteam.")


def _find_tested_repo_root(start: str | os.PathLike[str] | None) -> Path | None:
    if not start:
        return None
    current = Path(start).expanduser().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / 'pyproject.toml').is_file() and (candidate / 'clawteam' / '__init__.py').is_file():
            return candidate
    return None


def _repo_venv_clawteam(repo_root: Path | None) -> Path | None:
    if repo_root is None:
        return None
    candidate = repo_root / '.venv' / 'bin' / 'clawteam'
    if candidate.is_file():
        return candidate.resolve()
    return None


def resolve_clawteam_executable(*, cwd: str | os.PathLike[str] | None = None, require_same_source: bool = False) -> str:
    """Resolve the current clawteam executable.

    Prefer an explicitly pinned ``CLAWTEAM_BIN`` first so respawn/release flows
    stay on the same runtime binary as the original launcher. When spawning from
    a tested ClawTeam repo, prefer that repo's own ``.venv/bin/clawteam`` and
    optionally fail closed if same-source pinning is required. Fall back to the
    current process entrypoint when running from a venv or editable install via
    an absolute path. Then fall back to ``shutil.which("clawteam")`` and finally
    the bare command name.
    """

    repo_root = _find_tested_repo_root(cwd)
    repo_bin = _repo_venv_clawteam(repo_root)

    pinned = (os.environ.get("CLAWTEAM_BIN") or "").strip()
    if pinned:
        candidate = Path(pinned).expanduser()
        resolved_pinned = str(candidate.resolve()) if candidate.is_file() else (str(candidate) if candidate.is_absolute() else pinned)
        if repo_root is not None and repo_bin is not None and Path(resolved_pinned).is_absolute():
            try:
                if Path(resolved_pinned).resolve() != repo_bin:
                    raise ClawteamExecutableResolutionError(
                        f"tested repo at '{repo_root}' requires CLAWTEAM_BIN='{repo_bin}', got '{resolved_pinned}'"
                    )
            except OSError:
                pass
        return resolved_pinned

    if repo_bin is not None:
        return str(repo_bin)

    if require_same_source and repo_root is not None:
        raise ClawteamExecutableResolutionError(
            f"tested repo at '{repo_root}' requires pinned clawteam binary at '{repo_root / '.venv' / 'bin' / 'clawteam'}'; refusing to fall back to global clawteam"
        )

    argv0 = (sys.argv[0] or "").strip()
    if argv0 and _looks_like_clawteam_entrypoint(argv0):
        candidate = Path(argv0).expanduser()
        has_explicit_dir = candidate.parent != Path(".")
        if (candidate.is_absolute() or has_explicit_dir) and candidate.is_file():
            return str(candidate.resolve())

    resolved = shutil.which("clawteam")
    return resolved or "clawteam"


def build_spawn_path(base_path: str | None = None, *, cwd: str | os.PathLike[str] | None = None, require_same_source: bool = False) -> str:
    """Ensure the current clawteam executable directory is on PATH."""

    path_value = base_path if base_path is not None else os.environ.get("PATH", "")
    executable = resolve_clawteam_executable(cwd=cwd, require_same_source=require_same_source)
    if not os.path.isabs(executable):
        return path_value

    bin_dir = str(Path(executable).resolve().parent)
    path_parts = [part for part in path_value.split(os.pathsep) if part] if path_value else []
    if bin_dir in path_parts:
        return path_value
    if not path_parts:
        return bin_dir
    return os.pathsep.join([bin_dir, *path_parts])

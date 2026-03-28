"""Low-level git command wrappers — all subprocess calls centralized here."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """Raised when a git command fails."""


@dataclass(frozen=True)
class RemoteProbeResult:
    remote_status: str
    remote_head: str
    evidence: str


@dataclass(frozen=True)
class RemoteProbeTarget:
    remote: str
    branch: str
    evidence: str


def _run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_config_get(repo: Path, key: str) -> str:
    return _run(["config", "--get", key], cwd=repo, check=False).strip()


def is_git_repo(path: Path) -> bool:
    """Check if *path* is inside a git repository."""
    try:
        _run(["rev-parse", "--git-dir"], cwd=path)
        return True
    except (GitError, FileNotFoundError):
        return False


def repo_root(path: Path) -> Path:
    """Return the repository root for *path*."""
    return Path(_run(["rev-parse", "--show-toplevel"], cwd=path))


def current_branch(repo: Path) -> str:
    """Return the current branch name (or HEAD for detached)."""
    try:
        return _run(["symbolic-ref", "--short", "HEAD"], cwd=repo)
    except GitError:
        return _run(["rev-parse", "--short", "HEAD"], cwd=repo)


def create_worktree(
    repo: Path,
    worktree_path: Path,
    branch: str,
    base_ref: str = "HEAD",
) -> None:
    """Create a new worktree with a new branch based on *base_ref*."""
    _run(
        ["worktree", "add", "-b", branch, str(worktree_path), base_ref],
        cwd=repo,
    )


def remove_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove a worktree directory."""
    _run(["worktree", "remove", "--force", str(worktree_path)], cwd=repo)


def delete_branch(repo: Path, branch: str) -> None:
    """Force-delete a local branch."""
    _run(["branch", "-D", branch], cwd=repo)


def commit_all(worktree_path: Path, message: str) -> bool:
    """Stage everything and commit. Returns True if a commit was created."""
    _run(["add", "-A"], cwd=worktree_path)
    # Check if there is anything to commit
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=worktree_path,
        capture_output=True,
    )
    if result.returncode == 0:
        return False  # nothing staged
    _run(["commit", "-m", message], cwd=worktree_path)
    return True


def merge_branch(
    repo: Path,
    branch: str,
    target: str,
    no_ff: bool = True,
) -> tuple[bool, str]:
    """Merge *branch* into *target*. Returns (success, output)."""
    _run(["checkout", target], cwd=repo)
    args = ["merge"]
    if no_ff:
        args.append("--no-ff")
    args.append(branch)
    try:
        out = _run(args, cwd=repo)
        return True, out
    except GitError as e:
        # Abort on conflict
        subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
        return False, str(e)


def list_worktrees(repo: Path) -> list[dict[str, str]]:
    """Return list of worktrees as dicts with 'path' and 'branch' keys."""
    raw = _run(["worktree", "list", "--porcelain"], cwd=repo)
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
        elif line == "" and current:
            worktrees.append(current)
            current = {}
    if current:
        worktrees.append(current)
    return worktrees


def diff_stat(worktree_path: Path) -> str:
    """Return ``git diff --stat`` output for the worktree."""
    staged = _run(["diff", "--cached", "--stat"], cwd=worktree_path, check=False)
    unstaged = _run(["diff", "--stat"], cwd=worktree_path, check=False)
    parts = []
    if staged:
        parts.append(f"Staged:\n{staged}")
    if unstaged:
        parts.append(f"Unstaged:\n{unstaged}")
    return "\n".join(parts) if parts else "Clean — no changes."


def resolve_remote_probe_target(
    repo: Path,
    *,
    remote: str | None = None,
    branch: str | None = None,
) -> RemoteProbeTarget:
    """Resolve the authoritative target remote/branch for setup probing.

    Resolution order:
    1. Explicit arguments when both are supplied.
    2. Launch/runtime mapping persisted in git config: clawteam.targetRemote + clawteam.targetBranch.
    3. Current attached branch mapping: branch.<name>.remote + branch.<name>.merge.
    4. Fallback to branch.main.remote + branch.main.merge only when present.

    This intentionally does not treat `upstream` as default authority and fails closed
    when the target remote cannot be resolved unambiguously.
    """
    repo = repo_root(repo)
    explicit_remote = str(remote or "").strip()
    explicit_branch = str(branch or "").strip()
    if bool(explicit_remote) ^ bool(explicit_branch):
        raise GitError("remote probe target requires both remote and branch when either is supplied")
    if explicit_remote and explicit_branch:
        return RemoteProbeTarget(
            remote=explicit_remote,
            branch=explicit_branch,
            evidence=f"explicit target {explicit_remote}/{explicit_branch}",
        )

    mapped_remote = _git_config_get(repo, "clawteam.targetRemote")
    mapped_branch = _git_config_get(repo, "clawteam.targetBranch")
    if mapped_remote and mapped_branch:
        if mapped_remote == "upstream":
            raise GitError("clawteam.targetRemote=upstream is not allowed as default probe authority")
        return RemoteProbeTarget(
            remote=mapped_remote,
            branch=mapped_branch.removeprefix("refs/heads/"),
            evidence=f"git config clawteam.targetRemote/clawteam.targetBranch -> {mapped_remote}/{mapped_branch.removeprefix('refs/heads/')}",
        )

    current = _run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo, check=False).strip()
    if current:
        branch_remote = _git_config_get(repo, f"branch.{current}.remote")
        branch_merge = _git_config_get(repo, f"branch.{current}.merge")
        if branch_remote and branch_merge:
            if branch_remote == "upstream":
                raise GitError(f"branch.{current}.remote resolves to upstream; explicit target mapping required")
            return RemoteProbeTarget(
                remote=branch_remote,
                branch=branch_merge.removeprefix("refs/heads/"),
                evidence=(
                    f"current branch mapping branch.{current}.remote/merge -> "
                    f"{branch_remote}/{branch_merge.removeprefix('refs/heads/')}"
                ),
            )

    main_remote = _git_config_get(repo, "branch.main.remote")
    main_merge = _git_config_get(repo, "branch.main.merge")
    if main_remote and main_merge:
        if main_remote == "upstream":
            raise GitError("branch.main.remote resolves to upstream; explicit target mapping required")
        return RemoteProbeTarget(
            remote=main_remote,
            branch=main_merge.removeprefix("refs/heads/"),
            evidence=f"branch.main.remote/merge -> {main_remote}/{main_merge.removeprefix('refs/heads/')}",
        )

    remotes_raw = _run(["remote"], cwd=repo, check=False)
    remotes = [line.strip() for line in remotes_raw.splitlines() if line.strip() and line.strip() != "upstream"]
    if len(remotes) == 1:
        candidate = remotes[0]
        if _run(["rev-parse", "--verify", "refs/heads/main"], cwd=repo, check=False).strip():
            return RemoteProbeTarget(
                remote=candidate,
                branch="main",
                evidence=f"single non-upstream remote fallback with local refs/heads/main -> {candidate}/main",
            )

    if not remotes:
        raise GitError("no non-upstream git remotes available for setup probe target resolution")
    raise GitError(
        "unable to resolve setup probe target unambiguously; set clawteam.targetRemote/clawteam.targetBranch or use an attached branch mapping"
    )


def probe_remote_head(
    repo: Path,
    *,
    remote: str,
    branch: str,
    timeout_seconds: float = 30.0,
) -> RemoteProbeResult:
    """Probe a remote head with fail-closed classification.

    Returns:
    - confirmed_latest + sha when `git ls-remote --heads` succeeds with a parseable sha
    - cached_only + `none` when the probe times out
    - unreachable + `none` when the command fails or returns malformed output
    """
    command = ["git", "ls-remote", "--heads", remote, branch]
    quoted = " ".join(command)
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=True,
        )
    except subprocess.TimeoutExpired:
        return RemoteProbeResult(
            remote_status="cached_only",
            remote_head="none",
            evidence=f"{quoted} -> timed out after {timeout_seconds:g}s",
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip() or f"exit {exc.returncode}"
        return RemoteProbeResult(
            remote_status="unreachable",
            remote_head="none",
            evidence=f"{quoted} -> {stderr}",
        )

    stdout = (result.stdout or "").strip()
    if not stdout:
        return RemoteProbeResult(
            remote_status="unreachable",
            remote_head="none",
            evidence=f"{quoted} -> empty output",
        )

    line = stdout.splitlines()[0].strip()
    parts = line.split()
    sha = parts[0] if parts else ""
    if len(sha) >= 7 and all(ch in "0123456789abcdefABCDEF" for ch in sha):
        return RemoteProbeResult(
            remote_status="confirmed_latest",
            remote_head=sha.lower(),
            evidence=f"{quoted} -> {line}",
        )

    return RemoteProbeResult(
        remote_status="unreachable",
        remote_head="none",
        evidence=f"{quoted} -> malformed output: {line}",
    )

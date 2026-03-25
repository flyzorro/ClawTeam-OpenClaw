from __future__ import annotations

import shlex


def build_terminal_task_update_command(
    *,
    executable: str = "clawteam",
    team_name: str,
    task_id: str,
    status: str,
    execution_id: str = "",
    failure_kind: str = "",
    failure_note: str = "",
    failure_root_cause: str = "",
    failure_evidence: str = "",
    failure_recommended_next_owner: str = "",
    failure_recommended_action: str = "",
) -> str:
    parts = [
        executable,
        "task",
        "update",
        team_name,
        task_id,
        "--status",
        status,
    ]
    if execution_id:
        parts.extend(["--execution-id", execution_id])
    if failure_kind:
        parts.extend(["--failure-kind", failure_kind])
    if failure_note:
        parts.extend(["--failure-note", failure_note])
    if failure_root_cause:
        parts.extend(["--failure-root-cause", failure_root_cause])
    if failure_evidence:
        parts.extend(["--failure-evidence", failure_evidence])
    if failure_recommended_next_owner:
        parts.extend(["--failure-recommended-next-owner", failure_recommended_next_owner])
    if failure_recommended_action:
        parts.extend(["--failure-recommended-action", failure_recommended_action])
    return shlex.join(parts)

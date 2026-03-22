"""Task update state-machine and follow-up planning services."""

from __future__ import annotations

from typing import Any

from clawteam.team.models import TaskItem, TaskStatus


FAILURE_OPTION_FLAGS = {
    "--failure-kind": "failure_kind",
    "--failure-note": "failure_note",
    "--failure-root-cause": "failure_root_cause",
    "--failure-evidence": "failure_evidence",
    "--failure-recommended-next-owner": "failure_recommended_next_owner",
    "--failure-recommended-action": "failure_recommended_action",
}

COMPLEX_FAILURE_REQUIRED_FLAGS = {
    "--failure-root-cause": "failure_root_cause",
    "--failure-evidence": "failure_evidence",
    "--failure-recommended-next-owner": "failure_recommended_next_owner",
    "--failure-recommended-action": "failure_recommended_action",
}


class TaskUpdateValidationError(ValueError):
    """Raised when task update options violate workflow policy."""


def build_failure_metadata(
    *,
    status: TaskStatus | None,
    failure_kind: str | None,
    failure_note: str | None,
    failure_root_cause: str | None,
    failure_evidence: str | None,
    failure_recommended_next_owner: str | None,
    failure_recommended_action: str | None,
) -> dict[str, str] | None:
    """Validate failure options and normalize metadata payload."""
    option_values = {
        "failure_kind": failure_kind,
        "failure_note": failure_note,
        "failure_root_cause": failure_root_cause,
        "failure_evidence": failure_evidence,
        "failure_recommended_next_owner": failure_recommended_next_owner,
        "failure_recommended_action": failure_recommended_action,
    }

    if status != TaskStatus.failed:
        if any((value or "").strip() for value in option_values.values()):
            raise TaskUpdateValidationError("failure options require --status failed")
        return None

    kind = (failure_kind or "complex").strip().lower()
    if kind not in ("regular", "complex"):
        raise TaskUpdateValidationError("--failure-kind must be regular or complex")

    failure_metadata: dict[str, str] = {"failure_kind": kind}
    for key, value in option_values.items():
        if key == "failure_kind":
            continue
        if value and value.strip():
            failure_metadata[key] = value.strip()

    if kind == "complex":
        missing = [
            flag
            for flag, key in COMPLEX_FAILURE_REQUIRED_FLAGS.items()
            if not (option_values.get(key) or "").strip()
        ]
        if missing:
            raise TaskUpdateValidationError(f"complex fail requires: {', '.join(missing)}")

    return failure_metadata


def merge_update_metadata(
    existing: TaskItem,
    failure_metadata: dict[str, str] | None,
    add_on_fail_list: list[str] | None,
) -> dict[str, Any] | None:
    """Merge task-update metadata patches without duplicating on_fail targets."""
    merged_metadata: dict[str, Any] = dict(failure_metadata or {})
    if add_on_fail_list:
        current_on_fail = list(existing.metadata.get("on_fail", []))
        for target in add_on_fail_list:
            if target not in current_on_fail:
                current_on_fail.append(target)
        merged_metadata["on_fail"] = current_on_fail
    return merged_metadata or None


def plan_task_update_followups(
    *,
    existing: TaskItem,
    status: TaskStatus | None,
    all_tasks: list[TaskItem],
    failure_metadata: dict[str, str] | None,
) -> dict[str, list[str]]:
    """Plan transition follow-ups implied by a task status update."""
    dependent_ids_to_wake: list[str] = []
    failed_targets_to_wake: list[str] = []

    if status == TaskStatus.completed:
        dependent_ids_to_wake = [
            candidate.id
            for candidate in all_tasks
            if existing.id in candidate.blocked_by and candidate.status == TaskStatus.blocked
        ]
    elif status == TaskStatus.failed and failure_metadata:
        if failure_metadata.get("failure_kind") == "regular" and existing.started_at:
            failed_targets_to_wake = list(existing.metadata.get("on_fail", []))

    return {
        "dependent_ids_to_wake": dependent_ids_to_wake,
        "failed_targets_to_wake": failed_targets_to_wake,
    }

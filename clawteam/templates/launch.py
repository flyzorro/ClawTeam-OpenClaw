from __future__ import annotations

from pydantic import BaseModel, Field


class LaunchTemplateError(ValueError):
    """Base typed error for launch-boundary failures."""


class LaunchReferenceError(LaunchTemplateError):
    """Raised when a template references a task that is not launchable yet."""


class LaunchTaskBuildError(LaunchTemplateError):
    """Raised when launch task input construction fails."""


class LaunchBriefSections(BaseModel):
    version: str = "v1"
    source_request: str = ""
    scoped_brief: str = ""
    unknowns: list[str] = Field(default_factory=list)
    leader_assumptions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class NormalizedLaunchBrief(BaseModel):
    format: str = "prose_fallback"
    sections: LaunchBriefSections = Field(default_factory=LaunchBriefSections)


class PreparedTaskLaunchBrief(BaseModel):
    rendered_description: str
    normalized_brief: NormalizedLaunchBrief
    metadata_patch: dict[str, object] = Field(default_factory=dict)


class LaunchTaskInput(BaseModel):
    subject: str
    description: str
    owner: str
    blocked_by: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class LaunchExecutionResult(BaseModel):
    created_task_ids: dict[str, str] = Field(default_factory=dict)


NormalizedLaunchBrief.model_rebuild()
PreparedTaskLaunchBrief.model_rebuild()
LaunchTaskInput.model_rebuild()
LaunchExecutionResult.model_rebuild()


def _normalize_lines(value: str) -> list[str]:
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        lines.append(stripped)
    return lines


def normalize_launch_brief(*, source_request: str, leader_brief: str) -> NormalizedLaunchBrief:
    """Normalize launch input into an explicit brief contract.

    Structured format is intentionally minimal and section-labeled:
    ## Source Request
    ## Scoped Brief
    ## Unknowns
    ## Leader Assumptions
    ## Out of Scope
    """
    text = leader_brief.strip()
    if not text:
        return NormalizedLaunchBrief(
            format="empty",
            sections=LaunchBriefSections(source_request=source_request),
        )

    labels = {
        "source request": "source_request",
        "scoped brief": "scoped_brief",
        "unknowns": "unknowns",
        "leader assumptions": "leader_assumptions",
        "out of scope": "out_of_scope",
    }
    current: str | None = None
    sections: dict[str, list[str]] = {value: [] for value in labels.values()}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("## "):
            key = lowered[3:].strip()
            current = labels.get(key)
            continue
        if current is not None:
            sections[current].append(line)

    if any(sections.values()):
        return NormalizedLaunchBrief(
            format="structured_sections",
            sections=LaunchBriefSections(
                source_request="\n".join(sections["source_request"]).strip() or source_request,
                scoped_brief="\n".join(sections["scoped_brief"]).strip(),
                unknowns=_normalize_lines("\n".join(sections["unknowns"])),
                leader_assumptions=_normalize_lines("\n".join(sections["leader_assumptions"])),
                out_of_scope=_normalize_lines("\n".join(sections["out_of_scope"])),
            ),
        )

    return NormalizedLaunchBrief(
        format="prose_fallback",
        sections=LaunchBriefSections(
            source_request=source_request,
            scoped_brief=text,
        ),
    )


def parse_launch_brief(*, source_request: str, leader_brief: str) -> LaunchBriefSections:
    """Backward-compatible helper returning only the normalized sections."""
    return normalize_launch_brief(
        source_request=source_request,
        leader_brief=leader_brief,
    ).sections


def _render_normalized_launch_brief(normalized: NormalizedLaunchBrief) -> str:
    sections = normalized.sections

    def _bullet_lines(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) if values else "- none"

    return "\n\n".join(
        [
            f"## Source Request\n{sections.source_request or '- none'}",
            f"## Scoped Brief\n{sections.scoped_brief or '- none'}",
            f"## Unknowns\n{_bullet_lines(sections.unknowns)}",
            f"## Leader Assumptions\n{_bullet_lines(sections.leader_assumptions)}",
            f"## Out of Scope\n{_bullet_lines(sections.out_of_scope)}",
            f"## Brief Format\n{normalized.format}",
            "## Interpretation Rules\n"
            "- Treat Source Request as the original user intent.\n"
            "- Treat Scoped Brief as the current working scope.\n"
            "- Do not silently convert Unknowns into requirements.\n"
            "- Treat Leader Assumptions as provisional, not confirmed fact.\n"
            "- Do not implement Out of Scope items in the current task.",
        ]
    )


def prepare_task_launch_brief(task: str, *, render_task, **variables: str) -> PreparedTaskLaunchBrief:
    """Single launch-boundary entrypoint for task brief preparation.

    This keeps render/normalize/metadata logic out of the CLI composition root.
    """
    rendered = render_task(task, **variables).strip()
    normalized = normalize_launch_brief(
        source_request=variables.get("goal", ""),
        leader_brief=rendered,
    )
    return PreparedTaskLaunchBrief(
        rendered_description=_render_normalized_launch_brief(normalized),
        normalized_brief=normalized,
        metadata_patch={"launch_brief": normalized.model_dump(mode="json")},
    )


def render_task_brief(task: str, *, render_task, **variables: str) -> str:
    """Backward-compatible helper returning only rendered launch description."""
    return prepare_task_launch_brief(task, render_task=render_task, **variables).rendered_description


def build_launch_task_input(
    task_def,
    *,
    goal: str,
    team_name: str,
    created_task_ids: dict[str, str],
    render_task,
) -> LaunchTaskInput:
    """Canonical launch-task preparation entrypoint.

    Produces the task payload consumed by the CLI create path so description,
    reference validation, and metadata stay derived from one launch-boundary
    decision.
    """
    missing_dependencies = [name for name in task_def.blocked_by if name not in created_task_ids]
    if missing_dependencies:
        raise LaunchReferenceError(
            f"Template task '{task_def.subject}' references unknown or not-yet-created blocked_by tasks: {', '.join(missing_dependencies)}"
        )

    missing_fail_targets = [name for name in task_def.on_fail if name not in created_task_ids]
    if missing_fail_targets:
        raise LaunchReferenceError(
            f"Template task '{task_def.subject}' references unknown or not-yet-created on_fail tasks: {', '.join(missing_fail_targets)}"
        )

    metadata: dict[str, object] = {}
    if task_def.on_fail:
        metadata["on_fail"] = [created_task_ids[name] for name in task_def.on_fail]

    prepared_brief = prepare_task_launch_brief(
        task_def.description,
        goal=goal,
        team_name=team_name,
        agent_name=task_def.owner,
        render_task=render_task,
    )
    metadata.update(prepared_brief.metadata_patch)

    return LaunchTaskInput(
        subject=task_def.subject,
        description=prepared_brief.rendered_description,
        owner=task_def.owner,
        blocked_by=[created_task_ids[name] for name in task_def.blocked_by],
        metadata=metadata,
    )


def execute_template_launch(
    task_store,
    tasks,
    *,
    goal: str,
    team_name: str,
    render_task,
) -> LaunchExecutionResult:
    """Execute authored-order template task creation behind one launch boundary."""
    created_task_ids: dict[str, str] = {}

    for task_def in tasks:
        launch_task_input = build_launch_task_input(
            task_def,
            goal=goal,
            team_name=team_name,
            created_task_ids=created_task_ids,
            render_task=render_task,
        )
        task = task_store.create(
            subject=launch_task_input.subject,
            description=launch_task_input.description,
            owner=launch_task_input.owner,
            blocked_by=launch_task_input.blocked_by,
            metadata=launch_task_input.metadata,
        )
        created_task_ids[task_def.subject] = task.id

    return LaunchExecutionResult(created_task_ids=created_task_ids)

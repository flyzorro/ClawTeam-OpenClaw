"""Team template loader — load TOML templates for one-command team launch."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, Field

# TOML support: built-in on 3.11+, conditional dependency on 3.10
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentDef(BaseModel):
    name: str
    type: str = "general-purpose"
    task: str = ""
    command: list[str] | None = None


class TaskDef(BaseModel):
    subject: str
    description: str = ""
    owner: str = ""
    stage: str = ""
    blocked_by: list[str] = []
    on_fail: list[str] = []
    message_type: str = ""
    required_sections: list[str] = []


class TemplateDef(BaseModel):
    name: str
    description: str = ""
    command: list[str] = ["openclaw"]
    backend: str = "tmux"
    topology_mode: str = "explicit"
    leader: AgentDef
    agents: list[AgentDef] = []
    tasks: list[TaskDef] = []


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


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BUILTIN_DIR = Path(__file__).parent
_USER_DIR = Path.home() / ".clawteam" / "templates"


# ---------------------------------------------------------------------------
# Variable substitution helper
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    """dict subclass that keeps unknown {placeholders} intact."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_task(task: str, **variables: str) -> str:
    """Replace {goal}, {team_name}, {agent_name} etc. in task text."""
    return task.format_map(_SafeDict(**variables))


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


def prepare_task_launch_brief(task: str, **variables: str) -> PreparedTaskLaunchBrief:
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


def render_task_brief(task: str, **variables: str) -> str:
    """Backward-compatible helper returning only rendered launch description."""
    return prepare_task_launch_brief(task, **variables).rendered_description


def build_launch_task_input(
    task_def: TaskDef,
    *,
    goal: str,
    team_name: str,
    created_task_ids: dict[str, str],
) -> LaunchTaskInput:
    """Canonical launch-task preparation entrypoint.

    Produces the task payload consumed by the CLI create path so description,
    reference validation, and metadata stay derived from one launch-boundary
    decision.
    """
    missing_dependencies = [name for name in task_def.blocked_by if name not in created_task_ids]
    if missing_dependencies:
        raise ValueError(
            f"Template task '{task_def.subject}' references unknown or not-yet-created blocked_by tasks: {', '.join(missing_dependencies)}"
        )

    missing_fail_targets = [name for name in task_def.on_fail if name not in created_task_ids]
    if missing_fail_targets:
        raise ValueError(
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
    tasks: list[TaskDef],
    *,
    goal: str,
    team_name: str,
) -> LaunchExecutionResult:
    """Execute authored-order template task creation behind one launch boundary."""
    created_task_ids: dict[str, str] = {}

    for task_def in tasks:
        launch_task_input = build_launch_task_input(
            task_def,
            goal=goal,
            team_name=team_name,
            created_task_ids=created_task_ids,
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


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def resolve_template_topology(tmpl: TemplateDef) -> TemplateDef:
    """Resolve any template-level topology defaults before launch.

    Currently supported:
    - explicit: use blocked_by/on_fail exactly as authored
    - delivery-default: require staged tasks and auto-fill standard delivery edges
    """
    if tmpl.topology_mode == "explicit":
        return tmpl

    if tmpl.topology_mode != "delivery-default":
        raise ValueError(f"Unsupported template topology_mode: {tmpl.topology_mode}")

    by_stage: dict[str, list[TaskDef]] = {}
    for task in tmpl.tasks:
        stage = task.stage.strip().lower()
        if not stage:
            raise ValueError(
                f"Template '{tmpl.name}' uses topology_mode=delivery-default but task '{task.subject}' is missing stage"
            )
        by_stage.setdefault(stage, []).append(task)

    required = ["scope", "setup", "implement", "qa", "review", "deliver"]
    missing = [stage for stage in required if not by_stage.get(stage)]
    if missing:
        raise ValueError(
            f"Template '{tmpl.name}' uses topology_mode=delivery-default but is missing required stages: {', '.join(missing)}"
        )

    scope_subjects = [task.subject for task in by_stage["scope"]]
    setup_subjects = [task.subject for task in by_stage["setup"]]
    implement_subjects = [task.subject for task in by_stage["implement"]]
    qa_subjects = [task.subject for task in by_stage["qa"]]
    review_subjects = [task.subject for task in by_stage["review"]]

    resolved_tasks: list[TaskDef] = []
    for task in tmpl.tasks:
        stage = task.stage.strip().lower()
        updates: dict[str, object] = {}
        if stage == "setup" and not task.blocked_by:
            updates["blocked_by"] = list(scope_subjects)
        elif stage == "implement" and not task.blocked_by:
            updates["blocked_by"] = list(setup_subjects)
        elif stage == "qa":
            if not task.blocked_by:
                updates["blocked_by"] = list(implement_subjects)
            if not task.on_fail:
                updates["on_fail"] = list(implement_subjects)
        elif stage == "review":
            if not task.blocked_by:
                updates["blocked_by"] = list(qa_subjects)
            if not task.on_fail:
                updates["on_fail"] = list(implement_subjects)
        elif stage == "deliver" and not task.blocked_by:
            updates["blocked_by"] = list(review_subjects)

        resolved_tasks.append(task.model_copy(update=updates) if updates else task)

    return tmpl.model_copy(update={"tasks": resolved_tasks})


def _parse_toml(path: Path) -> TemplateDef:
    """Parse a TOML template file into a TemplateDef."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    tmpl = raw.get("template", {})

    # Parse leader
    leader_data = tmpl.get("leader", {})
    leader = AgentDef(**leader_data)

    # Parse agents
    agents = [AgentDef(**a) for a in tmpl.get("agents", [])]

    # Parse tasks
    tasks = [TaskDef(**t) for t in tmpl.get("tasks", [])]

    parsed = TemplateDef(
        name=tmpl.get("name", path.stem),
        description=tmpl.get("description", ""),
        command=tmpl.get("command", ["openclaw"]),
        backend=tmpl.get("backend", "tmux"),
        topology_mode=tmpl.get("topology_mode", "explicit"),
        leader=leader,
        agents=agents,
        tasks=tasks,
    )
    return resolve_template_topology(parsed)


def load_template(name: str) -> TemplateDef:
    """Load a template by name.

    Search order: user templates (~/.clawteam/templates/) first,
    then built-in templates (clawteam/templates/).
    """
    filename = f"{name}.toml"

    # User templates take priority
    user_path = _USER_DIR / filename
    if user_path.is_file():
        return _parse_toml(user_path)

    # Built-in templates
    builtin_path = _BUILTIN_DIR / filename
    if builtin_path.is_file():
        return _parse_toml(builtin_path)

    raise FileNotFoundError(
        f"Template '{name}' not found. "
        f"Searched: {_USER_DIR}, {_BUILTIN_DIR}"
    )


def list_templates() -> list[dict[str, str]]:
    """List all available templates (user + builtin, user overrides builtin)."""
    seen: dict[str, dict[str, str]] = {}

    # Built-in templates first (can be overridden)
    if _BUILTIN_DIR.is_dir():
        for p in sorted(_BUILTIN_DIR.glob("*.toml")):
            try:
                tmpl = _parse_toml(p)
                seen[tmpl.name] = {
                    "name": tmpl.name,
                    "description": tmpl.description,
                    "source": "builtin",
                }
            except Exception:
                continue

    # User templates override
    if _USER_DIR.is_dir():
        for p in sorted(_USER_DIR.glob("*.toml")):
            try:
                tmpl = _parse_toml(p)
                seen[tmpl.name] = {
                    "name": tmpl.name,
                    "description": tmpl.description,
                    "source": "user",
                }
            except Exception:
                continue

    return list(seen.values())

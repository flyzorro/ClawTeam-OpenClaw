"""Tests for clawteam.templates — loading, parsing, and variable substitution."""

import pytest

from clawteam.templates import (
    AgentDef,
    LaunchBriefSections,
    LaunchTaskInput,
    NormalizedLaunchBrief,
    PreparedTaskLaunchBrief,
    TaskDef,
    TemplateDef,
    _SafeDict,
    build_launch_task_input,
    list_templates,
    load_template,
    normalize_launch_brief,
    parse_launch_brief,
    prepare_task_launch_brief,
    render_task,
    render_task_brief,
    resolve_template_topology,
)


class TestRenderTask:
    def test_basic_substitution(self):
        result = render_task("Analyze {goal} for {team_name}", goal="AAPL", team_name="alpha")
        assert result == "Analyze AAPL for alpha"

    def test_unknown_placeholders_kept(self):
        """Variables we don't provide should stay as {placeholder}."""
        result = render_task("Hello {name}, team is {team_name}", name="bob")
        assert result == "Hello bob, team is {team_name}"

    def test_no_variables(self):
        result = render_task("plain text with no placeholders")
        assert result == "plain text with no placeholders"

    def test_empty_string(self):
        assert render_task("") == ""

    def test_multiple_same_variable(self):
        result = render_task("{x} and {x}", x="foo")
        assert result == "foo and foo"


class TestLaunchBrief:
    def test_normalize_launch_brief_marks_prose_fallback(self):
        normalized = normalize_launch_brief(
            source_request="Ship the feature safely",
            leader_brief="Clarify scope and acceptance criteria.",
        )

        assert normalized == NormalizedLaunchBrief(
            format="prose_fallback",
            sections=LaunchBriefSections(
                source_request="Ship the feature safely",
                scoped_brief="Clarify scope and acceptance criteria.",
                unknowns=[],
                leader_assumptions=[],
                out_of_scope=[],
            ),
        )

    def test_parse_launch_brief_falls_back_to_scoped_brief(self):
        parsed = parse_launch_brief(
            source_request="Ship the feature safely",
            leader_brief="Clarify scope and acceptance criteria.",
        )

        assert parsed == LaunchBriefSections(
            source_request="Ship the feature safely",
            scoped_brief="Clarify scope and acceptance criteria.",
            unknowns=[],
            leader_assumptions=[],
            out_of_scope=[],
        )

    def test_normalize_launch_brief_empty(self):
        normalized = normalize_launch_brief(
            source_request="Original request",
            leader_brief="   ",
        )

        assert normalized == NormalizedLaunchBrief(
            format="empty",
            sections=LaunchBriefSections(
                source_request="Original request",
                scoped_brief="",
                unknowns=[],
                leader_assumptions=[],
                out_of_scope=[],
            ),
        )

    def test_normalize_launch_brief_structured_sections(self):
        normalized = normalize_launch_brief(
            source_request="Original request",
            leader_brief="""
## Source Request
User asked for a safe rollout.

## Scoped Brief
Deliver the smallest safe change.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""".strip(),
        )

        assert normalized.format == "structured_sections"
        assert normalized.sections.source_request == "User asked for a safe rollout."
        assert normalized.sections.scoped_brief == "Deliver the smallest safe change."
        assert normalized.sections.unknowns == ["final prod env"]
        assert normalized.sections.leader_assumptions == ["existing tests are representative"]
        assert normalized.sections.out_of_scope == ["dashboard rewrite"]

    def test_parse_launch_brief_structured_sections(self):
        parsed = parse_launch_brief(
            source_request="Original request",
            leader_brief="""
## Source Request
User asked for a safe rollout.

## Scoped Brief
Deliver the smallest safe change.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""".strip(),
        )

        assert parsed.source_request == "User asked for a safe rollout."
        assert parsed.scoped_brief == "Deliver the smallest safe change."
        assert parsed.unknowns == ["final prod env"]
        assert parsed.leader_assumptions == ["existing tests are representative"]
        assert parsed.out_of_scope == ["dashboard rewrite"]

    def test_prepare_task_launch_brief_is_single_entrypoint(self):
        prepared = prepare_task_launch_brief(
            "Goal:\nClarify {goal} into a minimal deliverable.",
            goal="Ship the feature safely",
            team_name="delivery-demo",
            agent_name="leader",
        )

        assert prepared == PreparedTaskLaunchBrief(
            rendered_description=prepared.rendered_description,
            normalized_brief=NormalizedLaunchBrief(
                format="prose_fallback",
                sections=LaunchBriefSections(
                    source_request="Ship the feature safely",
                    scoped_brief="Goal:\nClarify Ship the feature safely into a minimal deliverable.",
                    unknowns=[],
                    leader_assumptions=[],
                    out_of_scope=[],
                ),
            ),
            metadata_patch={
                "launch_brief": {
                    "format": "prose_fallback",
                    "sections": {
                        "version": "v1",
                        "source_request": "Ship the feature safely",
                        "scoped_brief": "Goal:\nClarify Ship the feature safely into a minimal deliverable.",
                        "unknowns": [],
                        "leader_assumptions": [],
                        "out_of_scope": [],
                    },
                }
            },
        )
        assert "## Brief Format\nprose_fallback" in prepared.rendered_description

    def test_build_launch_task_input_keeps_description_and_metadata_same_source(self):
        task_input = build_launch_task_input(
            TaskDef(
                subject="Implement",
                description="Clarify {goal} into a minimal deliverable.",
                owner="dev1",
                blocked_by=["Scope"],
                on_fail=["Scope"],
            ),
            goal="Ship the feature safely",
            team_name="delivery-demo",
            created_task_ids={"Scope": "task-scope-1"},
        )

        assert task_input == LaunchTaskInput(
            subject="Implement",
            description=task_input.description,
            owner="dev1",
            blocked_by=["task-scope-1"],
            metadata={
                "on_fail": ["task-scope-1"],
                "launch_brief": {
                    "format": "prose_fallback",
                    "sections": {
                        "version": "v1",
                        "source_request": "Ship the feature safely",
                        "scoped_brief": "Clarify Ship the feature safely into a minimal deliverable.",
                        "unknowns": [],
                        "leader_assumptions": [],
                        "out_of_scope": [],
                    },
                },
            },
        )
        assert "## Source Request" in task_input.description
        assert "## Brief Format\nprose_fallback" in task_input.description

    def test_render_task_brief_wraps_old_prose_into_sections(self):
        rendered = render_task_brief(
            "Goal:\nClarify {goal} into a minimal deliverable.",
            goal="Ship the feature safely",
            team_name="delivery-demo",
            agent_name="leader",
        )

        assert "## Source Request" in rendered
        assert "Ship the feature safely" in rendered
        assert "## Scoped Brief" in rendered
        assert "Clarify Ship the feature safely into a minimal deliverable." in rendered
        assert "## Unknowns" in rendered
        assert "## Leader Assumptions" in rendered
        assert "## Out of Scope" in rendered
        assert "## Brief Format\nprose_fallback" in rendered
        assert "## Interpretation Rules" in rendered
        assert "Do not silently convert Unknowns into requirements." in rendered


class TestSafeDict:
    def test_missing_key_returns_placeholder(self):
        d = _SafeDict(a="1")
        assert d["a"] == "1"
        # missing key wrapped back into braces
        assert "{missing}".format_map(d) == "{missing}"


class TestModels:
    def test_agent_def_defaults(self):
        a = AgentDef(name="worker")
        assert a.type == "general-purpose"
        assert a.task == ""
        assert a.command is None

    def test_task_def(self):
        t = TaskDef(subject="Build feature", description="details", owner="alice")
        assert t.subject == "Build feature"

    def test_task_def_blocked_by(self):
        t = TaskDef(subject="Build feature", blocked_by=["Setup"])
        assert t.blocked_by == ["Setup"]

    def test_task_def_on_fail(self):
        t = TaskDef(subject="Run QA", on_fail=["Implement"])
        assert t.on_fail == ["Implement"]

    def test_task_def_stage(self):
        t = TaskDef(subject="Run QA", stage="qa")
        assert t.stage == "qa"

    def test_task_def_message_contract(self):
        t = TaskDef(
            subject="Run QA",
            message_type="QA_RESULT",
            required_sections=["status", "summary", "evidence"],
        )
        assert t.message_type == "QA_RESULT"
        assert t.required_sections == ["status", "summary", "evidence"]

    def test_template_def_defaults(self):
        leader = AgentDef(name="lead")
        t = TemplateDef(name="my-tmpl", leader=leader)
        assert t.description == ""
        assert t.command == ["openclaw"]
        assert t.backend == "tmux"
        assert t.topology_mode == "explicit"
        assert t.agents == []
        assert t.tasks == []


class TestTopologyResolver:
    def test_delivery_default_resolver_fills_missing_edges(self):
        tmpl = TemplateDef(
            name="delivery",
            topology_mode="delivery-default",
            leader=AgentDef(name="leader"),
            tasks=[
                TaskDef(subject="Scope", owner="leader", stage="scope"),
                TaskDef(subject="Setup", owner="config1", stage="setup"),
                TaskDef(subject="Implement backend", owner="dev1", stage="implement"),
                TaskDef(subject="Implement frontend", owner="dev2", stage="implement"),
                TaskDef(subject="QA", owner="qa1", stage="qa"),
                TaskDef(subject="Review", owner="review1", stage="review"),
                TaskDef(subject="Deliver", owner="leader", stage="deliver"),
            ],
        )

        resolved = resolve_template_topology(tmpl)
        by_subject = {task.subject: task for task in resolved.tasks}
        assert by_subject["Setup"].blocked_by == ["Scope"]
        assert by_subject["Implement backend"].blocked_by == ["Setup"]
        assert by_subject["Implement frontend"].blocked_by == ["Setup"]
        assert by_subject["QA"].blocked_by == ["Implement backend", "Implement frontend"]
        assert by_subject["QA"].on_fail == ["Implement backend", "Implement frontend"]
        assert by_subject["Review"].blocked_by == ["QA"]
        assert by_subject["Review"].on_fail == ["Implement backend", "Implement frontend"]
        assert by_subject["Deliver"].blocked_by == ["Review"]

    def test_delivery_default_resolver_fails_closed_without_stage(self):
        tmpl = TemplateDef(
            name="broken",
            topology_mode="delivery-default",
            leader=AgentDef(name="leader"),
            tasks=[TaskDef(subject="Scope", owner="leader")],
        )

        with pytest.raises(ValueError, match="missing stage"):
            resolve_template_topology(tmpl)


class TestLoadBuiltinTemplate:
    def test_load_hedge_fund(self):
        tmpl = load_template("hedge-fund")
        assert tmpl.name == "hedge-fund"
        assert tmpl.leader.name == "portfolio-manager"
        assert len(tmpl.agents) > 0
        assert len(tmpl.tasks) > 0

    def test_leader_type(self):
        tmpl = load_template("hedge-fund")
        assert tmpl.leader.type == "portfolio-manager"

    def test_agents_have_tasks(self):
        tmpl = load_template("hedge-fund")
        for agent in tmpl.agents:
            assert agent.task != "", f"Agent '{agent.name}' has no task text"

    def test_task_owners_match_agents(self):
        tmpl = load_template("hedge-fund")
        agent_names = {tmpl.leader.name} | {a.name for a in tmpl.agents}
        for task in tmpl.tasks:
            if task.owner:
                assert task.owner in agent_names, f"Task owner '{task.owner}' not in agents"

    def test_five_step_delivery_parallel_structure(self):
        tmpl = load_template("five-step-delivery")
        assert tmpl.topology_mode == "delivery-default"
        agent_names = {tmpl.leader.name} | {a.name for a in tmpl.agents}
        assert {"config1", "dev1", "dev2", "qa1", "qa2", "review1"}.issubset(agent_names)

        by_subject = {task.subject: task for task in tmpl.tasks}
        assert by_subject["Scope the task into a minimal deliverable"].stage == "scope"
        assert by_subject["Prepare repo, branch, env, and runnable baseline"].stage == "setup"
        assert by_subject["Review code quality, maintainability, and delivery readiness"].stage == "review"
        assert by_subject["Implement backend/data changes with real validation"].blocked_by == [
            "Prepare repo, branch, env, and runnable baseline"
        ]
        assert by_subject["Implement frontend/UI changes with real validation"].blocked_by == [
            "Prepare repo, branch, env, and runnable baseline"
        ]
        assert by_subject["Run main-flow QA on the real change"].blocked_by == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Run edge-case and regression QA on the real change"].blocked_by == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Review code quality, maintainability, and delivery readiness"].blocked_by == [
            "Run main-flow QA on the real change",
            "Run edge-case and regression QA on the real change",
        ]
        assert by_subject["Run main-flow QA on the real change"].on_fail == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Run edge-case and regression QA on the real change"].on_fail == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Review code quality, maintainability, and delivery readiness"].on_fail == [
            "Implement backend/data changes with real validation",
            "Implement frontend/UI changes with real validation",
        ]
        assert by_subject["Implement backend/data changes with real validation"].message_type == "DEV_RESULT"
        assert by_subject["Implement frontend/UI changes with real validation"].message_type == "DEV_RESULT"
        assert by_subject["Run main-flow QA on the real change"].message_type == "QA_RESULT"
        assert by_subject["Run edge-case and regression QA on the real change"].message_type == "QA_RESULT"
        assert by_subject["Review code quality, maintainability, and delivery readiness"].message_type == "REVIEW_RESULT"
        assert by_subject["Review code quality, maintainability, and delivery readiness"].required_sections == [
            "decision",
            "summary",
            "architecture_review",
            "required_fixes",
            "evidence",
            "validation",
            "next_action",
        ]


class TestLoadTemplateNotFound:
    def test_missing_template_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_template("this-does-not-exist-anywhere")


class TestUserTemplateOverride:
    def test_user_template_takes_priority(self, tmp_path, monkeypatch):
        """User templates in ~/.clawteam/templates/ override builtins."""
        user_tpl_dir = tmp_path / ".clawteam" / "templates"
        user_tpl_dir.mkdir(parents=True)

        toml_content = """\
[template]
name = "custom"
description = "User override"

[template.leader]
name = "my-leader"
type = "custom-leader"
"""
        (user_tpl_dir / "custom.toml").write_text(toml_content)

        # patch the module-level _USER_DIR
        import clawteam.templates as tmod

        monkeypatch.setattr(tmod, "_USER_DIR", user_tpl_dir)

        tmpl = load_template("custom")
        assert tmpl.name == "custom"
        assert tmpl.leader.name == "my-leader"
        assert tmpl.description == "User override"


class TestListTemplates:
    def test_list_includes_builtin(self):
        templates = list_templates()
        names = {t["name"] for t in templates}
        assert "hedge-fund" in names

    def test_list_entry_format(self):
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "source" in t
            assert t["source"] in ("builtin", "user")

from pathlib import Path

from clawteam.board.collector import BoardCollector
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


def test_collect_team_includes_failed_tasks(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))

    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )

    store = TaskStore("demo")
    failed = store.create("Investigate flaky dashboard", owner="leader")
    store.update(
        failed.id,
        status=TaskStatus.failed,
        metadata={"failure_note": "SSE handler crashed while grouping tasks"},
    )

    board = BoardCollector().collect_team("demo")

    assert board["taskSummary"]["failed"] == 1
    assert board["taskSummary"]["total"] == 1
    assert len(board["tasks"]["failed"]) == 1
    assert board["tasks"]["failed"][0]["id"] == failed.id


def test_collect_team_preserves_structured_qa_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))

    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )

    store = TaskStore("demo")
    task = store.create("Run QA", owner="qa1")
    completed = store.update(
        task.id,
        status=TaskStatus.completed,
        metadata={
            "qa_result_status": "pass_with_risk",
            "qa_result_risk": "- failed branch remains unvalidated",
            "qa_result": {
                "status": "pass_with_risk",
                "summary": "Main goal validated",
                "risk": "- failed branch remains unvalidated",
            },
        },
    )

    board = BoardCollector().collect_team("demo")
    assert board["tasks"]["completed"][0]["metadata"]["qa_result_status"] == "pass_with_risk"
    assert board["tasks"]["completed"][0]["metadata"]["qa_result_risk"] == "- failed branch remains unvalidated"
    assert completed is not None


def test_collect_overview_tolerates_team_with_failed_tasks(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))

    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )

    store = TaskStore("demo")
    task = store.create("Handle worker failure", owner="leader")
    store.update(task.id, status=TaskStatus.failed)

    overview = BoardCollector().collect_overview()

    assert overview == [
        {
            "name": "demo",
            "description": "",
            "leader": "leader",
            "members": 1,
            "tasks": 1,
            "pendingMessages": 0,
        }
    ]

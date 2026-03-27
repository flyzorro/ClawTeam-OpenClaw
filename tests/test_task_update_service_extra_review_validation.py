import pytest

from clawteam.services.task_update_service import (
    TaskUpdateRequest,
    TaskUpdateValidationError,
    _validate_review_completion,
    execute_task_update,
    TaskUpdateContext,
)
from clawteam.runtime.orchestrator import RuntimeOrchestrator
from clawteam.team import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


def _ctx(store: TaskStore):
    return TaskUpdateContext(store=store, team='demo', runtime=RuntimeOrchestrator(team='demo'), release_notifier=lambda *a, **k: None, failure_notifier=lambda *a, **k: None)


def test_rejects_completed_qa_without_structured_result(monkeypatch, tmp_path):
    monkeypatch.setenv('CLAWTEAM_DATA_DIR', str(tmp_path / 'data'))
    TeamManager.create_team(name='demo', leader_name='leader', leader_id='leader001')
    TeamManager.add_member('demo', 'qa1', 'qa1-id', agent_type='general-purpose')
    store = TaskStore('demo')
    task = store.create('Run scoped QA pass A on the real change', owner='qa1', metadata={'template_stage':'qa','message_type':'QA_RESULT','required_sections':['status','summary','evidence','validation','risk','next_action']})
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller='qa1')
    with pytest.raises(TaskUpdateValidationError, match='QA_RESULT header'):
        execute_task_update(task_id=task.id, caller='qa1', ctx=_ctx(store), request=TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description='looks good', add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=claimed.active_execution_id, wake_owner=False, message='', force=False))


def test_review_approve_requires_persisted_qa_results(monkeypatch, tmp_path):
    monkeypatch.setenv('CLAWTEAM_DATA_DIR', str(tmp_path / 'data'))
    TeamManager.create_team(name='demo', leader_name='leader', leader_id='leader001')
    TeamManager.add_member('demo', 'qa1', 'qa1-id', agent_type='general-purpose')
    TeamManager.add_member('demo', 'qa2', 'qa2-id', agent_type='general-purpose')
    TeamManager.add_member('demo', 'review1', 'review1-id', agent_type='general-purpose')
    store = TaskStore('demo')
    qa1 = store.create('Run scoped QA pass A on the real change', owner='qa1', metadata={'template_stage':'qa','message_type':'QA_RESULT'})
    qa2 = store.create('Run scoped QA pass B on the real change', owner='qa2', metadata={'template_stage':'qa','message_type':'QA_RESULT'})
    qa1.status = TaskStatus.completed
    qa2.status = TaskStatus.completed
    review = store.create('Review code quality, maintainability, and release readiness', owner='review1', metadata={'template_stage':'review','message_type':'REVIEW_RESULT','required_sections':['decision','summary','architecture_review','required_fixes','evidence','validation','next_action']})
    qa1.blocks.append(review.id)
    qa2.blocks.append(review.id)
    req = TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description="""REVIEW_RESULT
decision: approve
summary: reviewed the change
architecture_review:
- runtime + task update path inspected
required_fixes:
- none
evidence:
- clawteam/services/task_update_service.py: review acceptance path inspected
validation:
- git diff main..HEAD -> reviewed relevant files
next_action: move to deliver
""", add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=None, wake_owner=False, message='', force=False)
    with pytest.raises(TaskUpdateValidationError, match='persisted QA_RESULT metadata'):
        _validate_review_completion(review, req, all_tasks=[qa1, qa2, review])


def test_review_approve_accepts_with_persisted_qa_results(monkeypatch, tmp_path):
    monkeypatch.setenv('CLAWTEAM_DATA_DIR', str(tmp_path / 'data'))
    TeamManager.create_team(name='demo', leader_name='leader', leader_id='leader001')
    TeamManager.add_member('demo', 'qa1', 'qa1-id', agent_type='general-purpose')
    TeamManager.add_member('demo', 'qa2', 'qa2-id', agent_type='general-purpose')
    TeamManager.add_member('demo', 'review1', 'review1-id', agent_type='general-purpose')
    store = TaskStore('demo')
    qa1 = store.create('Run scoped QA pass A on the real change', owner='qa1', metadata={'template_stage':'qa','message_type':'QA_RESULT','qa_result':{'status':'pass'}})
    qa2 = store.create('Run scoped QA pass B on the real change', owner='qa2', metadata={'template_stage':'qa','message_type':'QA_RESULT','qa_result':{'status':'pass_with_risk'}})
    qa1.status = TaskStatus.completed
    qa2.status = TaskStatus.completed
    review = store.create('Review code quality, maintainability, and release readiness', owner='review1', metadata={'template_stage':'review','message_type':'REVIEW_RESULT','required_sections':['decision','summary','architecture_review','required_fixes','evidence','validation','next_action']})
    qa1.blocks.append(review.id)
    qa2.blocks.append(review.id)
    req = TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description="""REVIEW_RESULT
decision: approve
summary: reviewed the change
architecture_review:
- runtime + task update path inspected
required_fixes:
- none
evidence:
- clawteam/services/task_update_service.py: review acceptance path inspected
validation:
- git diff main..HEAD -> reviewed relevant files
next_action: move to deliver
""", add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=None, wake_owner=False, message='', force=False)
    _validate_review_completion(review, req, all_tasks=[qa1, qa2, review])

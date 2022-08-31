import os

import pytest

from dvc.exceptions import DvcException
from dvc.repo.experiments.executor.base import ExecutorInfo, TaskStatus
from dvc.repo.experiments.queue.tasks import collect_exp, setup_exp


def test_celery_queue_success_status(dvc, scm, test_queue, exp_stage):
    queue_entry = test_queue._stash_exp(
        params={"params.yaml": ["foo=1"]},
        targets=exp_stage.addressing,
        name="success",
    )
    infofile = test_queue.get_infofile_path(queue_entry.stash_rev)
    setup_exp.s(queue_entry.asdict())()
    executor_info = ExecutorInfo.load_json(infofile)
    assert executor_info.status == TaskStatus.PREPARING

    cmd = ["dvc", "exp", "exec-run", "--infofile", infofile]
    proc_dict = test_queue.proc.run_signature(
        cmd, name=queue_entry.stash_rev
    )()

    executor_info = ExecutorInfo.load_json(infofile)
    assert executor_info.status == TaskStatus.SUCCESS

    collect_exp.s(proc_dict, queue_entry.asdict())()
    executor_info = ExecutorInfo.load_json(infofile)
    assert executor_info.status == TaskStatus.FINISHED


def test_celery_queue_failure_status(dvc, scm, test_queue, failed_exp_stage):
    queue_entry = test_queue._stash_exp(
        params={"params.yaml": ["foo=1"]},
        targets=failed_exp_stage.addressing,
        name="failed",
    )
    infofile = test_queue.get_infofile_path(queue_entry.stash_rev)
    setup_exp.s(queue_entry.asdict())()
    cmd = ["dvc", "exp", "exec-run", "--infofile", infofile]
    test_queue.proc.run_signature(cmd, name=queue_entry.stash_rev)()
    executor_info = ExecutorInfo.load_json(infofile)
    assert executor_info.status == TaskStatus.FAILED


@pytest.mark.parametrize("queue_type", ["workspace_queue", "tempdir_queue"])
def test_workspace_executor_success_status(dvc, scm, exp_stage, queue_type):
    workspace_queue = getattr(dvc.experiments, queue_type)
    queue_entry = workspace_queue.put(
        params={"params.yaml": ["foo=1"]},
        targets=exp_stage.addressing,
        name="success",
    )
    name = workspace_queue._EXEC_NAME or queue_entry.stash_rev
    infofile = workspace_queue.get_infofile_path(name)
    entry, executor = workspace_queue.get()
    rev = entry.stash_rev
    exec_result = executor.reproduce(
        info=executor.info,
        rev=rev,
        infofile=infofile,
    )
    executor_info = ExecutorInfo.load_json(infofile)
    assert executor_info.status == TaskStatus.SUCCESS
    if exec_result.ref_info:
        workspace_queue.collect_executor(
            dvc.experiments, executor, exec_result, infofile
        )

    executor_info = ExecutorInfo.load_json(infofile)
    assert executor_info.status == TaskStatus.FINISHED


@pytest.mark.parametrize("queue_type", ["workspace_queue", "tempdir_queue"])
def test_workspace_executor_failed_status(
    dvc, scm, failed_exp_stage, queue_type
):
    workspace_queue = getattr(dvc.experiments, queue_type)
    queue_entry = workspace_queue.put(
        params={"params.yaml": ["foo=1"]},
        targets=failed_exp_stage.addressing,
        name="failed",
    )
    name = workspace_queue._EXEC_NAME or queue_entry.stash_rev

    infofile = workspace_queue.get_infofile_path(name)
    with pytest.raises(DvcException):
        workspace_queue.reproduce()
    if queue_type == "workspace_queue":
        assert not os.path.exists(infofile)
    else:
        executor_info = ExecutorInfo.load_json(infofile)
        assert executor_info.status == TaskStatus.FAILED
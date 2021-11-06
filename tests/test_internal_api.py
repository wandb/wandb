import pytest
import queue
import wandb
from wandb.apis import internal
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.sender import SendManager
from wandb.proto import wandb_internal_pb2 as pb


def test_agent_heartbeat_with_no_agent_id_fails(test_settings):
    a = internal.Api()
    with pytest.raises(ValueError):
        a.agent_heartbeat(None, {}, {})


def test_log_checkpoint(live_mock_server, test_settings):
    a = internal.Api()
    run = wandb.init()
    result = a.log_checkpoint(run.entity, run.project_name(), run.id, "test-checkpoint")
    assert result["name"] == "test-checkpoint"


def test_resume_from_checkpoint(live_mock_server, test_settings):
    a = internal.Api()
    run = wandb.init()
    checkpoint_name = "test-checkpoint"
    result = a.log_checkpoint(run.entity, run.project_name(), run.id, checkpoint_name)
    assert result["name"] == checkpoint_name
    chkpt, taskid = a.resume_from_checkpoint(
        run.entity, run.project_name(), checkpoint_name
    )
    assert chkpt["name"] == checkpoint_name
    assert taskid == 0
    finished, progress = a.check_task_progress(taskid)
    assert finished
    assert progress == 100


def test_maybe_setup_resume_checkpoint(live_mock_server, test_settings):
    a = internal.Api()
    run = wandb.init()
    checkpoint_name = "test-checkpoint"
    result = a.log_checkpoint(run.entity, run.project_name(), run.id, checkpoint_name)
    assert result["name"] == checkpoint_name

    live_mock_server.set_ctx({"resume": True})
    proto = pb.RunRecord()
    run._make_proto_run(proto)
    proto.checkpoint = checkpoint_name

    sm = SendManager(test_settings, queue.Queue(), queue.Queue(), InterfaceQueue())
    sm._maybe_setup_resume(proto)

    assert sm._resume_state.history == 15
    assert sm._resume_state.events == 0
    assert sm._resume_state.output == 14
    assert sm._resume_state.resumed

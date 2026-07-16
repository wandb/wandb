from wandb.proto import wandb_internal_pb2 as pb
from wandb.sync.sync import SyncThread


def test_legacy_sync_warns_for_resume_intent(mock_wandb_log):
    thread = SyncThread(
        sync_list=[],
        project=None,
        entity=None,
        run_id=None,
        job_type=None,
        view=False,
        verbose=False,
        mark_synced=False,
        app_url="https://wandb.test",
        sync_tensorboard=False,
        log_path=None,
        append=False,
        skip_console=False,
        replace_tags={},
    )
    record = pb.Record(
        run=pb.RunRecord(
            run_id="run-id",
            resume_mode=True,
        )
    )

    parsed, _, cont = thread._parse_pb(record.SerializeToString())

    assert not cont
    assert parsed.run.resume_mode is True
    mock_wandb_log.assert_warned(
        "Ignoring offline resume intent because legacy sync does not "
        "support offline resume."
    )

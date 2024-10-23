from __future__ import annotations

import pathlib

from wandb.proto import wandb_internal_pb2 as pb

from . import wandb_setup
from .lib.runid import generate_id


def _sync(
    path: str,
    run_id: str | None = None,
    project: str | None = None,
    entity: str | None = None,
    mark_synced: bool | None = None,
    append: bool | None = None,
    skip_console: bool | None = None,
) -> pb.SyncResponse:
    p = pathlib.Path(path)

    # ensure wandb-core is up and running
    wl = wandb_setup.setup()
    assert wl is not None
    service = wl.service
    assert service

    stream_id = generate_id()
    settings = wl.settings.to_proto()

    # indicate that we are in sync mode
    settings._sync.value = True

    if append:
        settings.resume.value = "allow"

    # set paths
    settings.sync_file.value = str(p.absolute())
    settings.sync_dir.value = str(p.parent.absolute())
    settings.files_dir.value = str(p.parent.absolute() / "files")

    # stream_id is only to initialize the stream.
    # the actual run id will either be extracted from the run record in
    # the transaction log or set to run_id if provided.
    settings.run_id.value = stream_id

    # we don't want to start the writer when syncing a run
    settings.disable_transaction_log.value = True
    # settings._file_stream_transmit_interval.value = 1

    # skip console output?
    if skip_console:
        settings.console.value = "off"

    # overwriting is reqested?
    overwrite = pb.SyncOverwrite()
    if run_id:
        overwrite.run_id = run_id
    if project:
        overwrite.project = project
    if entity:
        overwrite.entity = entity

    sync_request = pb.SyncRequest(overwrite=overwrite)

    # sync the run from the transaction log
    service.inform_sync(
        settings=settings,
        sync_request=sync_request,
        stream_id=stream_id,
    )

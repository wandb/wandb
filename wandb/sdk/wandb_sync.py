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

    # start a stream
    service.inform_init(settings=settings, run_id=stream_id)

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
    service.inform_sync(settings=settings, sync_request=sync_request)

    import time

    time.sleep(10)

    # service.inform_init(settings=settings, run_id=stream_id)

    # mailbox = Mailbox()
    # backend = Backend(
    #     settings=wl.settings,
    #     service=service,
    #     mailbox=mailbox,
    # )
    # backend.ensure_launched()

    # assert backend.interface
    # backend.interface._stream_id = stream_id  # type: ignore

    # mailbox.enable_keepalive()

    # # TODO: let's add extra sync messages here so we get the url in the beginning
    # handle = backend.interface.deliver_sync(
    #     start_offset=0,
    #     final_offset=-1,
    #     entity=entity,
    #     project=project,
    #     run_id=run_id,
    #     skip_output_raw=skip_console,
    # )
    # result = handle.wait(timeout=-1)
    # assert result and result.response
    # response = result.response.sync_response
    # if response.url:
    #     termlog(f"Synced {p} to {response.url}")
    #     # create a .synced file in the directory if mark_synced is true
    #     if mark_synced:
    #         with open(f"{p}.synced", "w"):
    #             pass
    # else:
    #     termerror(f"Failed to sync {p}")
    # if response.error and response.error.message:
    #     termerror(response.error.message)

    # return response

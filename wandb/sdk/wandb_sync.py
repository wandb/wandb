import pathlib
from typing import TYPE_CHECKING, Optional

from ..errors.term import termerror, termlog
from . import wandb_setup
from .backend.backend import Backend
from .lib.mailbox import Mailbox
from .lib.runid import generate_id

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2


def _sync(
    path: str,
    run_id: Optional[str] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    mark_synced: Optional[bool] = None,
    append: Optional[bool] = None,
    skip_console: Optional[bool] = None,
) -> "wandb_internal_pb2.SyncResponse":
    p = pathlib.Path(path)

    wl = wandb_setup.setup()
    assert wl is not None

    stream_id = generate_id()

    settings = wl.settings.to_proto()
    # update sync_file setting to point to the passed path
    settings.sync_file.value = str(p.absolute())
    settings.sync_dir.value = str(p.parent.absolute())
    settings.files_dir.value = str(p.parent.absolute() / "files")
    settings._sync.value = True
    settings.run_id.value = stream_id  # TODO: remove this
    if append:
        settings.resume.value = "allow"

    manager = wl._get_manager()
    manager._inform_init(settings=settings, run_id=stream_id)

    mailbox = Mailbox()
    backend = Backend(settings=wl.settings, manager=manager, mailbox=mailbox)
    backend.ensure_launched()

    assert backend.interface
    backend.interface._stream_id = stream_id  # type: ignore

    mailbox.enable_keepalive()

    # TODO: let's add extra sync messages here so we get the url in the beginning
    handle = backend.interface.deliver_sync(
        start_offset=0,
        final_offset=-1,
        entity=entity,
        project=project,
        run_id=run_id,
        skip_output_raw=skip_console,
    )
    result = handle.wait(timeout=-1)
    assert result and result.response
    response = result.response.sync_response
    if response.url:
        termlog(f"Synced {p} to {response.url}")
        # create a .synced file in the directory if mark_synced is true
        if mark_synced:
            with open(f"{p}.synced", "w"):
                pass
    else:
        termerror(f"Failed to sync {p}")
    if response.error and response.error.message:
        termerror(response.error.message)

    return response

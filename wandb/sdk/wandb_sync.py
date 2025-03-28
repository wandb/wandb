import pathlib
from typing import TYPE_CHECKING, Optional

from wandb import util
from wandb.errors.term import termerror, termlog

from . import wandb_setup
from .backend.backend import Backend
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
    wl = wandb_setup.setup()
    assert wl is not None

    stream_id = generate_id()

    settings = wl.settings.to_proto()
    p = pathlib.Path(path)

    # update sync_file setting to point to the passed path
    settings.sync_file.value = str(p.absolute())
    settings.sync_dir.value = str(p.parent.absolute())
    settings.files_dir.value = str(p.parent.absolute() / "files")
    settings.x_sync.value = True
    if run_id:
        settings.run_id.value = run_id
    if entity:
        settings.entity.value = entity
    if project:
        settings.project.value = project
    if skip_console:
        settings.console.value = "off"
    if append:
        settings.resume.value = "allow"

    service = wl.ensure_service()
    service.inform_init(settings=settings, run_id=stream_id)

    backend = Backend(settings=wl.settings, service=service)
    backend.ensure_launched()

    assert backend.interface
    backend.interface._stream_id = stream_id  # type: ignore

    handle = backend.interface.deliver_finish_sync()
    result = handle.wait_or(timeout=None)
    response = result.response.sync_response
    if response.url:
        termlog(f"Synced {p} to {util.app_url(response.url)}")
        # create a .synced file in the directory if mark_synced is true
        if mark_synced:
            with open(f"{p}.synced", "w"):
                pass
    else:
        termerror(f"Failed to sync {p}")
    if response.error and response.error.message:
        termerror(response.error.message)

    return response

import os
import pathlib
from typing import Optional

from ..errors.term import termerror, termlog
from . import wandb_setup
from .backend.backend import Backend
from .lib.mailbox import Mailbox
from .lib.runid import generate_id


def _sync(
    path: str,
    view=None,
    verbose=None,
    run_id: Optional[str] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    sync_tensorboard=None,
    include_globs=None,
    exclude_globs=None,
    include_online=None,
    include_offline=None,
    include_synced=None,
    mark_synced=None,
    sync_all=None,
    ignore=None,
    show=None,
    clean=None,
    clean_old_hours=24,
    clean_force=None,
    append: Optional[bool] = None,
    skip_console: Optional[bool] = None,
) -> None:
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
    # settings.console.value = "off" if console else "auto"

    # print([(e, os.environ[e]) for e in os.environ if e.startswith("WANDB")])
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
        termlog(f"Syncing {p} to {response.url}")
    else:
        termerror(f"Failed to sync {p}")
    if response.error and response.error.message:
        termerror(response.error.message)

    # TODO: create a .synced file in the directory if mark_synced is true

    return response

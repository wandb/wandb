import os
import pathlib

from ..errors.term import termerror, termlog
from . import wandb_setup
from .backend.backend import Backend
from .lib.mailbox import Mailbox
from .lib.runid import generate_id


def _sync(
    path,
    entity=None,
    project=None,
    run_id=None,
    console=None,
    append=None,
):
    p = pathlib.Path(path)

    wl = wandb_setup.setup()
    assert wl is not None

    stream_id = generate_id()

    settings = wl.settings.to_proto()
    # update sync_file setting to point to the passed path
    settings.sync_file.value = str(p.absolute())
    settings.sync_dir.value = str(p.parent.absolute())
    settings._sync.value = True
    settings.run_id.value = stream_id  # TODO: remove this
    settings.resume.value = "allow" if append else False
    # settings.console.value = "off" if console else "auto"

    print([(e, os.environ[e]) for e in os.environ if e.startswith("WANDB")])
    manager = wl._get_manager()
    manager._inform_init(settings=settings, run_id=stream_id)

    mailbox = Mailbox()
    backend = Backend(settings=wl.settings, manager=manager, mailbox=mailbox)
    backend.ensure_launched()

    assert backend.interface
    backend.interface._stream_id = stream_id

    mailbox.enable_keepalive()

    # TODO: let's add extra sync messages here so we get the url in the beginning
    handle = backend.interface.deliver_sync(
        start_offset=0,
        final_offset=-1,
        entity=entity,
        project=project,
        run_id=run_id,
        output_raw=console,
    )
    result = handle.wait(timeout=-1)
    response = result.response.sync_response
    if response.url:
        termlog(f"Syncing {p} to {response.url}")
    else:
        termerror(f"Failed to sync {p}")
    if response.error and response.error.message:
        termerror(response.error.message)

    # print(result)

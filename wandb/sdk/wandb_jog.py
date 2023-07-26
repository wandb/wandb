import os
from copy import copy
from typing import TYPE_CHECKING

from ..proto.wandb_internal_pb2 import (
    ConfigRecord,
    Record,
    Request,
    RunRecord,
    RunStartRequest,
)
from .interface.interface_sock import InterfaceSock
from .lib import filesystem, runid
from .lib.mailbox import Mailbox
from .lib.sock_client import SockClient

if TYPE_CHECKING:
    import wandb_settings


class Jog:
    settings: "wandb_settings.Settings"
    interface: InterfaceSock

    def setup_jog_dirs(self) -> None:
        settings = self.settings
        filesystem.mkdir_exists_ok(os.path.dirname(settings.log_user))
        filesystem.mkdir_exists_ok(os.path.dirname(settings.log_internal))
        filesystem.mkdir_exists_ok(os.path.dirname(settings.sync_file))
        filesystem.mkdir_exists_ok(settings.files_dir)
        filesystem.mkdir_exists_ok(settings._tmp_code_dir)

    def __init__(
        self,
        settings: "wandb_settings.Settings",
        socket_client: SockClient,
    ) -> None:
        self.settings = copy(settings)
        self.interface = InterfaceSock(socket_client, Mailbox())  # noqa

        jog_id = runid.generate_id()
        self.settings.update(run_id=jog_id)
        self.settings._set_run_start_time()

        self.interface._stream_id = jog_id

        self.setup_jog_dirs()

    def start(self):
        jog_id = self.settings.run_id
        config_pb = ConfigRecord()
        update = config_pb.update.add()
        update.key = "_wandb"
        update.value_json = '{"cli_version": "1.0.0"}'

        jog_pb = RunRecord(
            run_id=jog_id,
            config=config_pb,
        )
        record = Record(run=jog_pb)

        # print("jog_pb", jog_pb)
        handle = self.interface._deliver_record(record)
        result = handle.wait(timeout=self.settings.init_timeout)
        print("result", result)

        run_start_settings = {
            "entity": result.run_result.run.entity,
            "project": result.run_result.run.project,
            "display_name": result.run_result.run.display_name,
        }
        self.settings._apply_run_start(run_start_settings)

        print(self.settings)

        run_start_request = RunStartRequest(run=result.run_result.run)
        request = Request(run_start=run_start_request)
        record = Record(request=request)
        # All requests do not get persisted
        record.control.local = True
        handle = self.interface._deliver_record(record)
        result = handle.wait(timeout=self.settings.init_timeout)
        print("result", result)

    def log(self, data):
        pass

    def finish(self):
        pass

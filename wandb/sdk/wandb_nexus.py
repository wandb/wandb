import os
from copy import copy
from typing import TYPE_CHECKING, Dict

from ..proto.wandb_internal_pb2 import RunRecord
from . import wandb_manager, wandb_settings
from .lib import filesystem, runid

if TYPE_CHECKING:
    from interface.interface_sock import InterfaceSock


def init_settings():
    pid = os.getpid()
    s = wandb_settings.Settings()
    s._apply_base(pid=pid)
    s._apply_config_files()
    s._apply_env_vars(os.environ)

    s._infer_settings_from_environment()
    s._infer_run_settings_from_environment()

    return s


class Nexus:
    address: str
    settings: "wandb_settings.Settings"
    manager: "wandb_manager._Manager"
    interface: "InterfaceSock"
    jog_settings: Dict[str, "wandb_settings.Settings"]

    def __init__(self):
        self.jog_settings = {}

    def up(self):
        self.settings = init_settings()
        self.manager = wandb_manager._Manager(settings=self.settings)
        # print("manager", self.manager.__dict__)

        self.interface = self.manager._service._service_interface
        # print("interface", self.interface.__dict__)

    @staticmethod
    def setup_jog_dirs(settings: "wandb_settings.Settings"):
        filesystem.mkdir_exists_ok(os.path.dirname(settings.log_user))
        filesystem.mkdir_exists_ok(os.path.dirname(settings.log_internal))
        filesystem.mkdir_exists_ok(os.path.dirname(settings.sync_file))
        filesystem.mkdir_exists_ok(settings.files_dir)
        filesystem.mkdir_exists_ok(settings._tmp_code_dir)

    def init(self):
        # return Jog("sprint")
        jog_id = runid.generate_id()
        jog_settings = copy(self.settings)
        jog_settings.update(run_id=jog_id)
        jog_settings._set_run_start_time()

        self.setup_jog_dirs(jog_settings)

        self.manager._inform_init(settings=jog_settings, run_id=jog_id)
        self.jog_settings[jog_id] = jog_settings

        jog_pb = RunRecord(run_id=jog_id)

        print("jog_pb", jog_pb)

    def down(self):
        pass

import os
from typing import TYPE_CHECKING, Dict

from . import wandb_manager, wandb_settings
from .wandb_jog import Jog

if TYPE_CHECKING:
    from .service.service_sock import ServiceSockInterface


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
    command_interface: "ServiceSockInterface"
    jogs: Dict[str, "Jog"]

    def __init__(self):
        self.jogs = {}

    def up(self):
        self.settings = init_settings()
        self.manager = wandb_manager._Manager(settings=self.settings)
        # print("manager", self.manager.__dict__)

        self.command_interface = self.manager._service._service_interface
        # print("command_interface", self.command_interface.__dict__)

    def init(self):
        # return Jog("sprint")
        jog = Jog(self.settings, self.command_interface._sock_client)

        jog_id = jog.settings.run_id
        # send command to nexus to init stream for our jog
        self.manager._inform_init(settings=jog.settings, run_id=jog_id)
        self.jogs[jog_id] = jog

        jog.start()

    def down(self):
        pass

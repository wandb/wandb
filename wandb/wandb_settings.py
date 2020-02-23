"""
settings.
"""

order = ("org", "team", "project", "env", "sysdir", "dir", "settings", "code")

defaults = dict(
        team=None,
        entity=None,
        project=None,
        base_url="https://api.wandb.ai",
        api_key=None,
        anonymous=None,
        mode=None,
        # dynamic settings
        system_sample_seconds=2,
        system_samples=15,
        heartbeat_seconds=30,

        log_base_dir = "wandb",
        log_dir = "",
        log_user_spec = "wandb-debug-{timespec}-{pid}-user.txt",
        log_internal_spec = "wandb-debug-{timespec}-{pid}-internal.txt",
        log_user = False,
        log_internal = True,

        data_base_dir = "wandb",
        data_dir = "",
        data_spec = "data-{timespec}-{pid}.dat",

        run_base_dir = "wandb",
        run_dir_spec = "run-{timespec}-{pid}",
        )

move_mapping = dict(
        entity="team",
        )

deprecate_mapping = dict(
        entity=True,
        )

# env mapping?
env_mapping = dict(
        team="WANDB_TEAM",
        )


class Settings(object):
    def __init__(self):
        _settings_dict = defaults.copy()
        _forced_dict = dict()
        object.__setattr__(self, "_settings_dict", _settings_dict)
        object.__setattr__(self, "_forced_dict", _forced_dict)

    def __getattr__(self, k):
        try:
            v = self._settings_dict[k]
        except KeyError:
            raise AttributeError(k)
        return v
        
    def __setattr__(self, k, v):
        if k not in self._settings_dict:
            raise AttributeError(k)
        self._settings_dict[k] = v

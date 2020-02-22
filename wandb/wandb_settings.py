"""
settings.
"""

defaults = dict(
        team=None,
        entity=None,
        project=None,
        base_url="https://api.wandb.ai",
        # dynamic settings
        system_sample_seconds=2,
        system_samples=15,
        heartbeat_seconds=30,
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
        object.__setattr__(self, "_settings_dict", defaults.copy())

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

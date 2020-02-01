import numbers
import wandb
from ray import tune

# ray 0.8.1 reorganized ray.tune.util -> ray.tune.utils
try:
    from ray.tune.utils import flatten_dict
except ImportError:
    from ray.tune.util import flatten_dict


class WandbLogger(tune.logger.Logger):
    """Pass WandbLogger to the loggers argument of tune.run

       tune.run("PG", loggers=[WandbLogger], config={
           "monitor": True, "env_config": {
               "wandb": {"project": "my-project-name"}}})
    """

    def _init(self):
        self._config = None
        wandb.init(**self.config.get("env_config", {}).get("wandb", {}))

    def on_result(self, result):
        config = result.get("config")
        if config and self._config is None:
            for k in config.keys():
                if wandb.config.get(k) is None:
                    wandb.config[k] = config[k]
            self._config = config
        tmp = result.copy()
        for k in ["done", "config", "pid", "timestamp"]:
            if k in tmp:
                del tmp[k]
        metrics = {}
        for key, value in flatten_dict(tmp, delimiter="/").items():
            if not isinstance(value, numbers.Number):
                continue
            metrics[key] = value
        wandb.log(metrics)

    def close(self):
        wandb.join()

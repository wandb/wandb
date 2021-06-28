"""W&B callback for sb3

Really simple callback to get logging for each tree

Example usage:

```
import gym
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from wandb.integration.sb3 import WandbCallback

def make_env():
    env = gym.make("CartPole-v1")
    env = gym.wrappers.Monitor(env, f"videos", force=True)      # record videos
    env = gym.wrappers.RecordEpisodeStatistics(env) # record stats such as returns
    return env

config = {
    "policy_type": 'MlpPolicy',
    "total_timesteps": 25000
}

c = WandbCallback("sb3", config, "MyPPO")
env = DummyVecEnv([make_env])
model = PPO(config['policy_type'], env, verbose=1, tensorboard_log=f"runs/ppo")
model.learn(total_timesteps=config['total_timesteps'], callback=c)
```
"""

import wandb
from stable_baselines3.common.callbacks import BaseCallback


class WandbCallback(BaseCallback):
    """
    Callback for saving a model every ``save_freq`` calls
    to ``env.step()``.

    .. warning::

      When using multiple environments, each call to  ``env.step()``
      will effectively correspond to ``n_envs`` steps.
      To account for that, you can use ``save_freq = max(save_freq // n_envs, 1)``

    :param save_freq:
    :param save_path: Path to the folder where the model will be saved.
    :param name_prefix: Common prefix to the saved models
    :param verbose:
        , save_freq: int, save_path: str, name_prefix: str = "rl_model"
    """

    def __init__(
        self,
        project: str,
        config: dict,
        experiment_name: str = None,
        verbose: int = 0,
        save_freq: int = 1000,
        save_path="./models",
    ):
        super(WandbCallback, self).__init__(verbose)
        self.save_freq = save_freq
        self.save_path = save_path
        # self.name_prefix = name_prefix
        self.experiment_name = (
            experiment_name
            if experiment_name
            else f"{type(self.model).__name__}_{int(time.time())}"
        )
        wandb.init(
            project=project,
            config=config,
            sync_tensorboard=True,
            name=self.experiment_name,
            monitor_gym=True,
            save_code=True,
            allow_val_change=True,
        )
        # Create folder if needed
        if self.save_path is not None:
            os.makedirs(self.save_path, exist_ok=True)
        self.path = os.path.join(self.save_path, "model.pt")

    def _init_callback(self) -> None:

        d = {}
        for key in self.model.__dict__:
            if key in wandb.config:
                continue
            if type(self.model.__dict__[key]) in [float, int]:
                d[key] = self.model.__dict__[key]
            else:
                d[key] = str(self.model.__dict__[key])
        wandb.watch(self.model.policy, log_freq=100, log="all")
        wandb.config.update(d)

    def _on_step(self) -> bool:
        if self.n_calls % self.save_freq == 0:
            self.model.save(self.path)
            wandb.save(self.path)
            if self.verbose > 1:
                print(f"Saving model checkpoint to {self.path}")
        return True

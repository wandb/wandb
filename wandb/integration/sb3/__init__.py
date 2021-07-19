"""W&B callback for sb3

Really simple callback to get logging for each tree

Example usage:

```python
import gym
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv, VecVideoRecorder
import wandb
from wandb.integration.sb3 import WandbCallback


config = {"policy_type": "MlpPolicy", "total_timesteps": 25000}
run = wandb.init(
    project="sb3",
    config=config,
    sync_tensorboard=True,  # auto-upload sb3's tensorboard metrics
    monitor_gym=True,  # auto-upload the videos of agents playing the game
    save_code=True,  # optional
)


def make_env():
    env = gym.make("CartPole-v1")
    env = Monitor(env)  # record stats such as returns
    return env


env = DummyVecEnv([make_env])
env = VecVideoRecorder(env, "videos", record_video_trigger=lambda x: x % 2000 == 0, video_length=200)
model = PPO(config["policy_type"], env, verbose=1, tensorboard_log=f"runs")
model.learn(
    total_timesteps=config["total_timesteps"],
    callback=WandbCallback(
        gradient_save_freq=100,
        model_save_freq=1000,
    ),
)
```
"""

import os

from stable_baselines3.common.callbacks import BaseCallback
import wandb


class WandbCallback(BaseCallback):
    """ Log SB3 experiments to Weights and Biases
        - Added model tracking and uploading
        - Added complete hyperparameters recording
        - Added gradient logging
        - Note that `wandb.init(...)` must be called before the WandbCallback can be used

    Args:
        verbose: The verbosity of sb3 output
        model_save_path: Path to the folder where the model will be saved, The default value is `None` so the model is not logged
        model_save_freq: Frequency to save the model
        gradient_save_freq: Frequency to log gradient. The default value is 0 so the gradients are not logged
    """

    def __init__(
        self,
        verbose: int = 0,
        model_save_freq: int = 1000,
        gradient_save_freq: int = 0,
    ):
        super(WandbCallback, self).__init__(verbose)
        assert (
            wandb.run is not None
        ), "no wandb run detected; use `wandb.init()` to initialize a run"
        self.model_save_freq = model_save_freq
        self.gradient_save_freq = gradient_save_freq
        if self.model_save_freq > 0:
            self.path = os.path.join(wandb.run.dir, "model.zip")

    def _init_callback(self) -> None:
        d = {"algo": type(self.model).__name__}
        for key in self.model.__dict__:
            if key in wandb.config:
                continue
            if type(self.model.__dict__[key]) in [float, int, str]:
                d[key] = self.model.__dict__[key]
            else:
                d[key] = str(self.model.__dict__[key])
        if self.gradient_save_freq > 0:
            wandb.watch(self.model.policy, log_freq=self.gradient_save_freq, log="all")
        wandb.config.update(d)

    def _on_step(self) -> bool:
        if self.model_save_freq > 0:
            if self.n_calls % self.model_save_freq == 0:
                self.model.save(self.path)
                wandb.save(self.path)
                if self.verbose > 1:
                    print("Saving model checkpoint to", self.path)
        return True

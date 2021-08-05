#!/usr/bin/env python
"""Test stable_baselines3 integration

---
id: 0.0.4
check-ext-wandb: {}
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config][policy_type]: MlpPolicy
  - :wandb:runs[0][config][total_timesteps]: 200
  - :wandb:runs[0][config][policy_class]: "<class 'stable_baselines3.common.policies.ActorCriticPolicy'>"
  - :wandb:runs[0][config][action_space]: "Discrete(2)"
  - :wandb:runs[0][config][batch_size]: 64
  - :wandb:runs[0][config][n_epochs]: 10
  - :wandb:runs[0][exitcode]: 0
"""

import gym
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv
import wandb
from wandb.integration.sb3 import WandbCallback

config = {
    "policy_type": "MlpPolicy",
    "total_timesteps": 200,
    "env_name": "CartPole-v1",
}
run = wandb.init(
    project="sb3",
    config=config,
    sync_tensorboard=True,  # auto-upload sb3's tensorboard metrics
    save_code=True,  # optional
)


def make_env():
    env = gym.make(config["env_name"])
    env = Monitor(env)  # record stats such as returns
    return env


env = DummyVecEnv([make_env])
model = PPO(
    config["policy_type"], env, verbose=1, tensorboard_log=f"runs/{run.name}"
)

model.learn(
    total_timesteps=config["total_timesteps"],
    callback=WandbCallback(
        gradient_save_freq=100,
        model_save_path=f"models/{run.name}",
    ),
)

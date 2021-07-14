#!/usr/bin/env python
"""Test stable_baselines3 integration

---
id: 0.0.4
check-ext-wandb:
  run:
    - exit: 0
      config:
        policy_type: {desc: null, value: "MlpPolicy"}
        total_timesteps: {desc: null, value: 200}
        policy_class: {desc: null, value: "<class 'stable_baselines3.common.policies.ActorCriticPolicy'>"}
        action_space: {desc: null, value: "Discrete(2)"}
        batch_size: {desc: null, value: 64}
        n_epochs: {desc: null, value: 10}

      # we are not checking the summary for now, that is why it is {} with ignore_extra_summary_keys = True
      summary: {}
      ignore_extra_config_keys: true
      ignore_extra_summary_keys: true


"""

import time

import gym
import wandb

from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv
from wandb.integration.sb3 import WandbCallback


config = {"policy_type": "MlpPolicy", "total_timesteps": 200}
experiment_name = f"PPO_{int(time.time())}"
run = wandb.init(
    name=experiment_name,
    project="sb3",
    config=config,
    sync_tensorboard=True,  # auto-upload sb3's tensorboard metrics
    save_code=True,  # optional
)


def make_env():
    env = gym.make("CartPole-v1")
    env = Monitor(env)  # record stats such as returns
    return env


env = DummyVecEnv([make_env])
model = PPO(
    config["policy_type"], env, verbose=1, tensorboard_log=f"runs/{experiment_name}"
)

model.learn(
    total_timesteps=config["total_timesteps"],
    callback=WandbCallback(
        gradient_save_freq=100,
        model_save_freq=1000,
        model_save_path=f"models/{experiment_name}",
    ),
)

"""Test stable_baselines3 integration."""

from __future__ import annotations

import gymnasium as gym
import wandb
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv


def test_sb3_tensorboard(wandb_backend_spy):
    """Integration test for Stable Baselines 3 TensorBoard callback."""
    with wandb.init(sync_tensorboard=True) as run:
        PPO(
            "MlpPolicy",
            DummyVecEnv(
                [lambda: Monitor(gym.make("CartPole-v1", max_episode_steps=2))]
            ),
            verbose=1,
            tensorboard_log=f"runs/{run.name}",
            n_steps=21,
        ).learn(
            total_timesteps=4,
        )

    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.run_ids()) == 1

        summary = snapshot.summary(run_id=run.id)
        assert summary["global_step"] == 21
        for tag in ["time/fps", "rollout/ep_len_mean", "rollout/ep_rew_mean"]:
            assert tag in summary

        telemetry = snapshot.telemetry(run_id=run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

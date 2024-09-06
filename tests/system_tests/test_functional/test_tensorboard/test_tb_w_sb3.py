"""Test stable_baselines3 integration."""

import gymnasium as gym
import wandb
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv


def test_sb3_tensorboard(wandb_init, relay_server):
    """Integration test for Stable Baselines 3 TensorBoard callback."""
    with relay_server() as relay:
        with wandb_init(sync_tensorboard=True) as run:
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

        run_ids = relay.context.get_run_ids()
        assert len(run_ids) == 1
        assert run.id == run_ids[0]

        summary = relay.context.get_run_summary(run.id)
        assert summary["global_step"] == 21
        for tag in ["time/fps", "rollout/ep_len_mean", "rollout/ep_rew_mean"]:
            assert tag in summary

        telemetry = relay.context.get_run_telemetry(run.id)
        assert 35 in telemetry["3"]  # tensorboard_sync

    wandb.tensorboard.unpatch()

from __future__ import annotations

import dataclasses
from collections.abc import Mapping


@dataclasses.dataclass(frozen=True)
class LaunchIdentity:
    run_id: str
    rank: int
    local_rank: int
    node_rank: int
    world_size: int
    attempt: int
    scheduler: str


def launch_identity(env: Mapping[str, str]) -> LaunchIdentity | None:
    if "RANK" in env:
        keys = ("RANK", "LOCAL_RANK", "GROUP_RANK", "WORLD_SIZE")
        scheduler = "torchrun"
        elastic_id = env.get("TORCHELASTIC_RUN_ID")
        # torchrun's default rdzv id is the literal "none".
        scheduler_id = (elastic_id if elastic_id != "none" else None) or env.get(
            "K8S_JOB_UID"
        )
        attempt = env.get("TORCHELASTIC_RESTART_COUNT", "0")
    elif "SLURM_PROCID" in env:
        keys = ("SLURM_PROCID", "SLURM_LOCALID", "SLURM_NODEID", "SLURM_NTASKS")
        scheduler = "slurm"
        scheduler_id = env.get("SLURM_JOB_ID")
        attempt = env.get("SLURM_RESTART_COUNT", "0")
    elif "OMPI_COMM_WORLD_RANK" in env:
        keys = (
            "OMPI_COMM_WORLD_RANK",
            "OMPI_COMM_WORLD_LOCAL_RANK",
            "NODE_RANK",
            "OMPI_COMM_WORLD_SIZE",
        )
        scheduler = "mpi"
        scheduler_id = env.get("K8S_JOB_UID") or env.get("SLURM_JOB_ID")
        attempt = env.get("TORCHELASTIC_RESTART_COUNT", "0")
    else:
        return None
    run_id = env.get("WANDB_RUN_ID") or scheduler_id
    if not run_id or run_id == "none" or any(char in run_id for char in "/\\#?%:"):
        return None
    try:
        rank, local_rank, node_rank, world_size = (int(env[key]) for key in keys)
        restart = int(attempt)
    except (KeyError, TypeError, ValueError):
        return None
    if min(rank, local_rank, node_rank, restart) < 0 or world_size <= max(
        rank, local_rank, node_rank
    ):
        return None
    return LaunchIdentity(
        run_id, rank, local_rank, node_rank, world_size, restart, scheduler
    )

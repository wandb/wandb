import pytest
import sys
import torch
import wandb


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="PyTorch profiler table in 3.9? to verify"
)
def test_profiler_without_init():
    with pytest.raises(Exception):
        with torch.profiler.profile(
            schedule=torch.profiler.schedule(wait=1, warmup=1, active=3, repeat=1),
            on_trace_ready=wandb.profiler.trace(),
            record_shapes=True,
            with_stack=True,
        ) as prof:
            for step, batch_data in [(0, 0)]:
                if step >= (1 + 1 + 3) * 1:
                    break
                # train(batch_data)
                prof.step()

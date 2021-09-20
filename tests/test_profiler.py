import pytest
import sys
import wandb


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="PyTorch profiler table in 3.9? to verify"
)
def test_profiler_without_init():
    import torch

    with pytest.raises(Exception) as e_info:
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
        assert (
            str(e_info.value)
            == "Please call wandb.init() before wandb.profiler.trace()"
        )

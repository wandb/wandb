import numpy as np
import torch
import wandb


run = wandb.init(name=__file__)
run.log({"cuda_available": torch.cuda.is_available()})
x = np.random.random((32, 100)).astype("f")
t_cpu = torch.Tensor(x)
t_gpu = t_cpu.cuda()

run.log({"host_tensor": t_cpu})
run.log({"cuda_tensor": t_gpu})

run.finish()

public_run = wandb.Api().run(f"{run.project}/{run.id}")
cpu_hist = dict(public_run.summary["host_tensor"])
gpu_hist = dict(public_run.summary["cuda_tensor"])

assert wandb.Histogram(x, num_bins=32).to_json() == cpu_hist == gpu_hist

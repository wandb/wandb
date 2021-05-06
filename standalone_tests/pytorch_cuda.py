import numpy as np
import torch
import wandb

assert torch.cuda.is_available(), "CUDA not available!"


run = wandb.init()
x = np.random.random((32, 100)).astype("f")
t_cpu = torch.Tensor(x)
t_gpu = t_cpu.cuda()

run.log({"host_tensor": t_cpu})
run.log({"cuda_tensor": t_gpu})

run.finish()

public_run = wandb.Api().run("%s/%s" % (run.project, run.id))
cpu_hist = dict(public_run.summary["host_tensor"])
gpu_hist = dict(public_run.summary["cuda_tensor"])

assert wandb.Histogram(x, num_bins=32).to_json() == cpu_hist == gpu_hist

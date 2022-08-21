import pathlib

import numpy as np
import torch
import wandb

run = wandb.init(name=pathlib.Path(__file__).stem)
run.log({"cuda_available": torch.cuda.is_available()})
x = np.random.random((32, 100)).astype("f")
t_cpu = torch.Tensor(x)
t_gpu = t_cpu.cuda()

run.log({"host_tensor": t_cpu})
run.log({"cuda_tensor": t_gpu})

run.finish()

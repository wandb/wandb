# based on the following example: https://github.com/pytorch/examples/tree/main/mnist_hogwild
import torch
import torch.multiprocessing as mp

from torch_helper import MyDatatse, MyModel, train, transform, SEED
import wandb


if __name__ == "__main__":

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MyModel().to(device)
    # NOTE: this is required for the ``fork`` method to work
    model.share_memory()

    dataset = MyDatatse(transform=transform)

    torch.manual_seed(SEED)
    mp.set_start_method("spawn")

    wandb.require("service")
    run = wandb.init()

    processes = []
    for rank in range(2):
        p = mp.Process(target=train, args=(run, rank, model, device, dataset))
        # We first train the model across `num_processes` processes
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    run.finish()

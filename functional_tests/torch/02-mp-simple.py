# based on the following example: https://github.com/pytorch/examples/tree/main/mnist_hogwild
import torch
import torch.multiprocessing as mp

from helper import parser, MyDatatse, MyModel, train, transform
import wandb


if __name__ == "__main__":

    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MyModel().to(device)
    # NOTE: this is required for the ``fork`` method to work
    model.share_memory()

    dataset = MyDatatse(transform=transform)

    torch.manual_seed(args.seed)
    mp.set_start_method("spawn")

    wandb.require("service")
    run = wandb.init()

    processes = []
    for rank in range(args.num_processes):
        p = mp.Process(target=train, args=(run, rank, args, model, device, dataset))
        # We first train the model across `num_processes` processes
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    run.finish()

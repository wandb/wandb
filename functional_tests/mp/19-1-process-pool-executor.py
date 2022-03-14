from concurrent.futures import ProcessPoolExecutor
import wandb


def worker(initial: int):
    with wandb.init(config={"init": initial}) as run:
        for i in range(initial, initial + 10):
            run.log({"init": initial, "i": i})


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=4) as e:
        e.submit(worker, 12)
        e.submit(worker, 2)
        e.submit(worker, 40)
        e.submit(worker, 17)

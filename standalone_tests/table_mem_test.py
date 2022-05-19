import time

from memory_profiler import profile
import numpy as np
import wandb


@profile
def main(count, size=(32, 32, 3)):
    table = wandb.Table(columns=["img_1", "img_2", "img_3"])
    for _ in range(count):
        table.add_data(
            *[wandb.Image(np.random.randint(255, size=size)) for _ in range(3)]
        )


if __name__ == "__main__":
    for c in range(6):
        count = 2 * (10**c)
        start = time.time()
        print(f"Starting count {count}")
        main(10**c, (32, 32, 3))
        print(f"Completed count {count} in {time.time() - start} seconds")

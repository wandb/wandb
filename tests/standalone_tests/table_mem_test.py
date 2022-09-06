import pathlib
import time

import numpy as np
import wandb
from memory_profiler import profile


# todo: yea seems to swallow memory_profiler.profile's output
@profile
def main(count: int, size=(32, 32, 3)) -> wandb.Table:
    table = wandb.Table(columns=["img_1", "img_2", "img_3"])
    for _ in range(count):
        table.add_data(
            *[wandb.Image(np.random.randint(255, size=size)) for _ in range(3)]
        )
    return table


if __name__ == "__main__":
    run = wandb.init(name=pathlib.Path(__file__).stem)
    for c in range(4):
        cnt = 2 * (10**c)
        start = time.time()
        print(f"Starting count {cnt}")
        t = main(cnt, (32, 32, 3))
        run.log({f"table_{cnt}_rows": t})
        print(f"Completed count {cnt} in {time.time() - start} seconds")
    run.finish()

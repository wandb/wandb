from memory_profiler import profile
import wandb
import numpy as np

@profile
def main(count):
    table = wandb.Table(columns=["img"])
    for _ in range(count):
        table.add_data(wandb.Image(np.random.randint(255, size=(32,32))))

if __name__ == "__main__":
    for c in range(6):
        print(10**c)
        main(10**c)
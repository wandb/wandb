from math import sqrt
from joblib import Parallel, delayed
import wandb

def f(x):
    wandb.init(project="joblib", reinit=True)
    for i in range(10):
        loss = i
        # Log metrics with wandb
        # wandb.log({"Loss": loss})
    wandb.finish()
    return sqrt(x)

def main():
    res = Parallel(n_jobs=2)(delayed(f)(i**2) for i in range(4))
    print(res)

if __name__ == "__main__":
    main()

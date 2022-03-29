from joblib import Parallel, delayed
from math import sqrtx
import wandb

def f(x):
    with wandb.init(project="symppl", reinit=True) as run:
        for i in range(10):
            #Log metrics with wandb
            run.log({"Loss": i})
    return sqrt(x)

def main():
    res = Parallel(n_jobs=2)(delayed(f)(i**2) for i in range(4))
    print(res)

if __name__ == "__main__":
    wandb.require("service")
    main()
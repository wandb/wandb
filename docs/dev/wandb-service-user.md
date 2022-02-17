<p align="center">
  <img src="../../.github/wb-logo-lightbg.png#gh-light-mode-only" width="600" alt="Weights & Biases"/>
  <img src="../../.github/wb-logo-darkbg.png#gh-dark-mode-only" width="600" alt="Weights & Biases"/>
</p>

# `wandb` service

We are excited :tada: to share with you a new feature we call `service`. This feature is still in the experimental stage, but will be integrated by default in `wandb` in the near future.

## Why would you use this feature?

`service` improves `wandb`'s handling of multiprocessing and thus improves reliability in a distributed training setting.
If you are using `wandb` in a distributed training setup and experiencing hangs, please consider trying out this new feature.

## Usage

### General usage

`service` can be enabled by adding the following to your script:

```python
def __name__ == "__main__":
    wandb.require(experiment="service")
    # <rest-of-your-script-goes-here>
```

### Advanced usage example

If you are calling `wandb.init` in a spawned process you should add `wandb.setup()` in the main process:

```python
import multiprocessing as mp
import wandb

def do_work(n):
    run = wandb.init(config=dict(n=n))
    run.log(dict(this=n*n))

def main():
    wandb.require("service")
    wandb.setup()
    pool = mp.Pool(processes=4)
    pool.map(do_work, range(4))

if __name__ == "__main__":
    main()
```

If you are using threding instead of multi-processing, you should pass `thread` as the strting method to `wandb.init`:

```python
from threading import Thread
import wandb


def do_run(id):
    run = wandb.init(settings=wandb.Settings(start_method="thread"))
    run.config.id = n
    run.log(dict(this=n*n))


def main():
    wandb.require("service")
    wandb.setup()
    threads = []
    for i in range(2):
        thread = Thread(target=do_run, args=(i,))
        thread.start()
        threads.append(thread)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
```

### PyTorch Lightning

If you are using `PyTorch Lightning` please:

- Install the most recent version of `wandb` and update `PyTorch Lightning` from the master branch:

```bash
pip install --upgrade wandb
pip install --upgrade git+https://github.com/PytorchLightning/pytorch-lightning.git
```

The feature support will be part of `PyTorch Lightning`'s [1.6.0 release](https://github.com/PyTorchLightning/pytorch-lightning/pull/11650), at which point you will be able to simply install/update it from PyPI.

That's it... no need to add any further code...

## FAQs

### If your scrip is stuck in a restart loop

Please try adding:

```python
if __name__ == "__main__":
    # <your-script-goes-here>
```

## Reporting issues

We appreciate it that you gave this feature a try. If you are experiencing an issue that is not listed in the FAQs, please file a [GitHub Issue](https://github.com/wandb/client/issues).
To help us reproduce your issue, please provide the following:

- Minimal script to reproduce
- Python version
- Operating System
- Platform (for example: GPUs, TPUs etc.)
- Additional relevant packages installed (you can for example run `pip list` in your python environment)
- Traceback (if relevant)

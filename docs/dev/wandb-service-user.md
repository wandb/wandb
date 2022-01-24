# wandb service

The wandb service is still experimental. It can be enabled by adding the following to your script:

```python
wandb.require(experiment="service")
```

## Why would you use this feature?

`wandb-service` improves wandb's handling of multiprocessing and thus improves reliability in a distributed training setting.
If you are using `wandb` in a distributed training setup and experiencing hangs, please consider trying out this new feature.

## Installation

If you are using `Pytorch-Lightning` please also install this custom branch:

```bash
pip install --force git+https://github.com/wandb/pytorch-lightning.git@wandb-service-attach
```

(This branch will be upstreamed and be part of the regular Pytorch Lightning package.)

## FAQs

### If your scrip is stuck in a restart loop

Please try adding:

```python
if __name__ == "__main__":
    <your-script-goes-here>
```

## Reporting issues

If you are experiencing an issue which is not listed in the the FAQs, please file a ticket on [github issue](https://github.com/wandb/client/issues).
To help us reproduce your issue, please provide the following:

- Minimal script to reproduce
- Python version
- Operating System
- Platform (for example: GPUs, TPUs etc.)
- Additional relevant packages installed (you can run `pip list` in your python environment)
- Traceback (if relevant)

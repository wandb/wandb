# wandb service

The wandb service is still experimental. It can be enabled by adding this in your script:

```python
wandb.require(experiment="service")
```

## Why would you use this feature?

If you are training in a distributed setting and the current `wandb` solution seems to hang or does not scale as well as you would like.
Please consider trying out this new feature, it is hopefully should resolve many of these issues.

## Installation

The `service` feature is currently installed as an extra:

```bash
pip install --upgrade wandb[service]
```

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

### AssertionError: start method 'fork' is not supported yet

If the start method is not `fork` and you are running in a new enviroment try re-running your script to resolve this error message.

## Reporting issues

If your issues is not listed in the the FAQs, please file a ticket on [github issue](https://github.com/wandb/client/issues).
To help us reproduce your issue, it would be really helpful if you could provide the following things:

- Minimal script to reproduce
- Python version
- Your operating System
- Platform you are using (for example: GPUs, TPUs etc.)
- Additional relevant packages installed (you can run `pip list` in your python environment)

---
description: >-
  Run search and stopping algorithms locally, instead of using our cloud-hosted
  service
---

# Local Controller

By default the hyper-parameter controller is hosted by W&B as a cloud service. W&B agents communicate with the controller to determine the next set of parameters to use for training. The controller is also responsible for running early stopping algorithms to determine which runs can be stopped.

The local controller feature allows the user to run search and stopping algorithms locally. The local controller gives the user the ability to inspect and instrument the code in order to debug issues as well as develop new features which can be incorporated into the cloud service.

### Local controller configuration

To enable the local controller, add the following to the sweep configuration file:

```text
controller:
  type: local
```

### Running the local controller

The following command will launch a sweep controller:

```text
wandb controller SWEEP_ID
```

Alternatively you can launch a controller when you initialize the sweep:

```text
wandb --controller sweep.yaml
```


# Kubeflow

### Kubeflow Integration

Using certain features require additional dependencies. Install all kubeflow dependencies by running `pip install wandb[kubeflow]`.

#### Training Jobs

Currently W&B automatically reads the **TF\_CONFIG** environment variable to group distributed runs.

#### Arena

The wandb library integrates with [arena](https://github.com/kubeflow/arena) by automatically adding credentials to container environments. If you want to use the wandb wrapper locally, add the following to your `.bashrc`

```text
alias arena="python -m wandb.kubeflow.arena"
```

If you don't have arena installed locally, the above command will use the `wandb/arena` docker image and attempt to mount your kubectl configs.

#### Pipelines

wandb provides an `arena_launcher_op` that can be used in [pipelines](https://github.com/kubeflow/pipelines).

If you want to build your own custom launcher op, you can also use this [code](https://github.com/wandb/client/blob/master/wandb/kubeflow/__init__.py) to add pipeline\_metadata. For wandb to authenticate you should add the **WANDB\_API\_KEY** to the operation, then your launcher can add the same environment variable to the training container.

```text
import os
from kubernetes import client as k8s_client

op = dsl.ContainerOp( ... )
op.add_env_variable(k8s_client.V1EnvVar(
        name='WANDB_API_KEY',
        value=os.environ["WANDB_API_KEY"]))
```


import pickle

import wandb
from fastcore.all import typedispatch

from metaflow import Step, current, plugins
from metaflow.decorators import StepDecorator, _import_plugin_decorators

# I think importing here is more appropriate than importing in the func?
try:
    import pandas as pd
except ImportError:
    print(
        "Warning: `pandas` not installed >> @wandb_log(datasets=True) may not auto log your dataset!"
    )

try:
    import torch
    import torch.nn as nn
except ImportError:
    print(
        "Warning: `pytorch` not installed >> @wandb_log(models=True) may not auto log your dataset!"
    )

try:
    from sklearn.base import BaseEstimator
except ImportError:
    print(
        "Warning: `sklearn` not installed >> @wandb_log(models=True) may not auto log your dataset!"
    )


class WandbDecorator(StepDecorator):
    name = "wandb_log"
    defaults = {"datasets": False, "models": False, "wandb_init_kwargs": {}}

    def task_pre_step(
        self,
        step_name,
        datastore,
        metadata,
        run_id,
        task_id,
        flow,
        graph,
        retry_count,
        max_user_code_retries,
        ubf_context,
        inputs,
    ):
        if not self.attributes["wandb_init_kwargs"]:
            self.run = wandb.init(
                group=f"{current.flow_name}/{current.run_id}",
                job_type=step_name,
            )
        else:
            self.run = wandb.init(**self.attributes["wandb_init_kwargs"])

        self.inputs = [inp.to_dict() for inp in inputs][0]
        for name, data in self.inputs.items():
            self.wandb_use(name, data)

    def task_finished(
        self, step_name, flow, graph, is_task_ok, retry_count, max_user_code_retries
    ):
        step = Step(f"{current.flow_name}/{current.run_id}/{current.step_name}")
        params = {param: getattr(flow, param) for param in current.parameter_names}
        self.run.config.update(params)

        self.outputs = step.task.artifacts._asdict()
        self.delta = [
            artifact for var, artifact in self.outputs.items() if var not in self.inputs
        ]

        for artifact in self.delta:
            self.wandb_log(artifact.id, artifact.data)
        self.run.finish()

    @typedispatch
    def wandb_log(self, name: str, data: pd.DataFrame):
        if self.attributes["datasets"] is True:
            dataset = wandb.Artifact(name, type="dataset")
            with dataset.new_file(f"{name}.csv") as f:
                data.to_csv(f)
        self.run.log_artifact(dataset)
        print(f"wandb: logging artifact: {name} ({type(data)})")

    @typedispatch
    def wandb_log(self, name: str, data: nn.Module):
        if self.attributes["models"] is True:
            model = wandb.Artifact(name, type="model")
            with model.new_file(f"{name}.pkl", "wb") as f:
                torch.save(data, f)
            self.run.log_artifact(model)
            print(f"wandb: logging artifact: {name} ({type(data)})")

    @typedispatch
    def wandb_log(self, name: str, data: BaseEstimator):
        if self.attributes["models"] is True:
            model = wandb.Artifact(name, type="model")
            with model.new_file(f"{name}.pkl", "wb") as f:
                pickle.dump(data, f)
            self.run.log_artifact(model)
            print(f"wandb: logging artifact: {name} ({type(data)})")

    @typedispatch
    def wandb_log(self, name: str, data: (dict, str, int, float, bool)):  # type: ignore
        self.run.log({name: data})
        print(f"wandb: logging metric: {name} ({type(data)})")

    @typedispatch
    def wandb_use(self, name: str, data: (pd.DataFrame, nn.Module, BaseEstimator)):  # type: ignore
        artifact = self.run.use_artifact(f"{name}:latest")
        print(f"wandb: using artifact: {name} ({type(data)})")
        return artifact


plugins.STEP_DECORATORS.append(WandbDecorator)
_import_plugin_decorators(globals())

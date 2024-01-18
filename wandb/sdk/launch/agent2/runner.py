from wandb.apis.internal import Api
from wandb.sdk.launch import loader

def get_runner_for_job_set(resource: str, api: Api):
  # TODO
  config = { "SYNCHRONOUS": False }
  environment = None
  registry = None
  return loader.runner_from_config(
      resource,
      api,
      config,
      environment,
      registry,
  )
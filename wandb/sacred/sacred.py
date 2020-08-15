import collections
import warnings

import neptune
from neptunecontrib.monitoring.utils import pickle_and_send_artifact
from sacred.dependencies import get_digest
from sacred.observers import RunObserver
import numpy

class WandbObserver(RunObserver):
    """Logs sacred experiment data to Neptune.
    Sacred observer that logs experiment metadata to neptune.
    The experiment data can be accessed and shared via web UI or experiment API.
    Check Neptune docs for more information https://docs.neptune.ai.
    Args:
        project(str): project name in W&B Dashboard
        name(str): Experiment name
        api_key(str): API key for authentication

    Examples:
        Create sacred experiment::
    """

    def __init__(self, project=None, name=None):
        self.run =  wandb.init(project=project,name = name)

        self.resources = {}

    def started_event(self, ex_info, command, host_info, start_time, config, meta_info, _id):
        """ 
        TODO:
        * add the source code file 
        * add dependencies and metadata
        """
        self.__update_config(config)


    def completed_event(self, stop_time, result):
        if result:
            if not isinstance(result, tuple):
                result = (
                    result,)  # transform single result to tuple so that both single & multiple results use same code

            for i, r in enumerate(result):
                if isinstance(r, float) or isinstance(r, int):
                    wandb.log({"result_{}".format(i): float(r)})
                elif isinstance(r, object):
                    artifact = wandb.Artifact('result_{}.pkl'.format(i), type='result')
                    artifact.add_file(r)
                    self.run.log_artifact(artifact)
                
                elif isinstance(r,numpy.ndarray):
                    wandb.log({"result_{}".format(i):wandb.Image(r)})
                else:
                    warnings.warn(
                        "logging results does not support type '{}' results. Ignoring this result".format(type(r)))


    def interrupted_event(self, interrupt_time, status):

    def failed_event(self, fail_time, fail_trace):

    def artifact_event(self, name, filename, metadata=None, content_type=None):
        artifact = wandb.Artifact(name, type=content_type)
        artifact.add_file(filename)
        self.run.log_artifact(artifact)

    def resource_event(self, filename):
        """
        TODO: Maintain resources list
        """
        if filename not in self.resources:
            md5 = get_digest(filename)
            self.resources[filename] = md5

    def log_metrics(self, metrics_by_name, info):
        for metric_name, metric_ptr in metrics_by_name.items():
            for step, value in zip(metric_ptr["steps"], metric_ptr["values"]):
                wandb.log({metric_name:value},step=step)
    
    def __update_config(self,config):
        for k, v in d.items():
            self.run.config[k] = d
        self.run.config['resources'] = []        

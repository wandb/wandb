import collections
import warnings

from sacred.dependencies import get_digest
from sacred.observers import RunObserver
import numpy
import wandb
class WandbObserver(RunObserver):
    """Logs sacred experiment data to W&B.
    Args:
        project(str): project name in W&B Dashboard
        name(str): Experiment name

    Examples:
        Create sacred experiment::
        from numpy.random import permutation
        
        from sklearn import svm, datasets
        from sacred import Experiment
        ex = Experiment('iris_rbf_svm')
        from wandb.sacred import WandbObserver
        ex.observers.append(WandbObserver(project='sacred_test',
                                                name='test1'))
        @ex.config
        def cfg():
            C = 1.0
            gamma = 0.7
        @ex.automain
        def run(C, gamma, _run):
            iris = datasets.load_iris()
            per = permutation(iris.target.size)
            iris.data = iris.data[per]
            iris.target = iris.target[per]
            clf = svm.SVC(C, 'rbf', gamma=gamma)
            clf.fit(iris.data[:90],
                    iris.target[:90])
            return clf.score(iris.data[90:],
                                iris.target[90:])
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
                elif isinstance(r, dict):
                    wandb.log(r)

                elif isinstance(r, object):
                    artifact = wandb.Artifact('result_{}.pkl'.format(i), type='result')
                    artifact.add_file(r)
                    self.run.log_artifact(artifact)
                
                elif isinstance(r,numpy.ndarray):
                    wandb.log({"result_{}".format(i):wandb.Image(r)})
                else:
                    warnings.warn(
                        "logging results does not support type '{}' results. Ignoring this result".format(type(r)))

    def artifact_event(self, name, filename, metadata=None, content_type=None):
        if content_type is None:
            content_type = 'file'
        artifact = wandb.Artifact(name,type=content_type)
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
                if isinstance(value,numpy.ndarray):
                    wandb.log({metric_name:wandb.Image(value)})
                else:
                    wandb.log({metric_name:value})
    
    def __update_config(self,config):
        for k, v in config.items():
            self.run.config[k] = v
        self.run.config['resources'] = []        

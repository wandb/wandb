from collections import defaultdict

from sagemaker.analytics import ExperimentAnalytics

from .base import AbstractRun, Importer


class SageMakerRun(AbstractRun):
    def __init__(self, trial_component: dict):
        super().__init__()
        self.trial_component = trial_component

        source_detail = self.trial_component.get("SourceDetail")
        if source_detail:
            training_job = source_detail.get("TrainingJob")
            if training_job:
                experiment_config = training_job.get("ExperimentConfig")

        self.experiment_config = experiment_config

    def id(self):
        return self.trial_component.get("TrialComponentName", "")

    def name(self):
        return self.experiment_config.get("TrialName", "")

    def config(self):
        config_dict = {}

        parameters = self.trial_component.get("Parameters", [])
        for k, v in parameters.items():
            config_dict[k] = v.get("NumberValue", v.get("StringValue"))

        source = self.trial_component.get("Source", "")
        if source:
            config_dict["SourceArn"] = source["SourceArn"]
            config_dict["SourceType"] = source["SourceType"]

        return config_dict

    def summary(self):
        summary_dict = defaultdict(dict)
        metrics = self.trial_component.get("Metrics", [])
        stat_types = ["Min", "Max", "Avg", "StdDev", "Last", "Count"]
        for metric in metrics:
            name = metric["MetricName"]
            for stat_type in stat_types:
                summary_dict[name][stat_type] = metric.get(stat_type)

        summary_dict["Status"] = self.trial_component.get("Status")

        return summary_dict

    def start_time(self):
        return self.trial_component.get("StartTime")

    def finish_time(self):
        return self.trial_component.get("EndTime")

    def job_type(self):
        return self.experiment_config.get("TrialComponentDisplayName", "")

    def group(self):
        return self.experiment_config.get("ExperimentName", "")

    def metrics(self):
        for _ in range(2):  # not sure why I have to do this
            yield {}


class SageMakerImporter(Importer):
    def __init__(
        self,
        trial_component_analytics: ExperimentAnalytics,
        *,
        entity: str = None,
        project: str = None
    ):
        super().__init__(entity, project)
        self.trial_components = trial_component_analytics._get_trial_components()

    def process(self):
        for trial_component in self.trial_components:
            run = SageMakerRun(trial_component)
            self.add(run)
        super().process()

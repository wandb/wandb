This is a placeholder for creating an actual MLFlowClient

```python
from mlflow.entities import ViewType
from mlflow.tracking import SEARCH_MAX_RESULTS_DEFAULT

class WBMLFlowClient(object):
    def get_run(self, run_id):
        pass

    def get_metric_history(self, run_id, key):
        pass

    def create_run(self, experiment_id, start_time=None, tags=None):
        pass

    def list_run_infos(self, experiment_id, run_view_type=ViewType.ACTIVE_ONLY):
        pass

    def list_experiments(self, view_type=None):
        pass

    def get_experiment(self, experiment_id):
        pass

    def get_experiment_by_name(self, name):
        pass

    def create_experiment(self, name, artifact_location=None):
        pass

    def delete_experiment(self, experiment_id):
        pass

    def restore_experiment(self, experiment_id):
        pass

    def rename_experiment(self, experiment_id, new_name):
        pass

    def log_metric(self, run_id, key, value, timestamp=None, step=None):
        pass

    def log_param(self, run_id, key, value):
        pass

    def set_experiment_tag(self, experiment_id, key, value):
        pass

    def set_tag(self, run_id, key, value):
        pass

    def delete_tag(self, run_id, key):
        pass

    def log_batch(self, run_id, metrics=(), params=(), tags=()):
        pass

    def log_artifact(self, run_id, local_path, artifact_path=None):
        pass

    def log_artifacts(self, run_id, local_dir, artifact_path=None):
        pass

    def list_artifacts(self, run_id, path=None):
        pass

    def download_artifacts(self, run_id, path, dst_path=None):
        pass

    def set_terminated(self, run_id, status=None, end_time=None):
        pass

    def delete_run(self, run_id):
        pass

    def restore_run(self, run_id):
        pass

    def search_runs(self, experiment_ids, filter_string="", run_view_type=ViewType.ACTIVE_ONLY,
                    max_results=SEARCH_MAX_RESULTS_DEFAULT, order_by=None, page_token=None):
        pass
```

These are other methods we should likely implement:

```python
MlflowClient.orig_delete_run = MlflowClient.delete_run  # TODO
MlflowClient.orig_delete_tag = MlflowClient.delete_tag  # TODO
MlflowClient.orig_set_terminated = MlflowClient.set_terminated  # TODO
#MlflowClient.orig_active_run = MlflowClient.active_run
#MlflowClient.orig_search_runs = MlflowClient.search_runs
#MlflowClient.orig_get_artifact_uri = MlflowClient.get_artifact_uri
#MlflowClient.orig_set_tracking_uri = MlflowClient.set_tracking_uri
#MlflowClient.orig_get_tracking_uri = MlflowClient.get_tracking_uri
#fluent.orig_set_experiment = fluent.set_experiment
#MlflowClient.orig_create_experiment = MlflowClient.create_experiment
MlflowClient.orig_delete_experiment = MlflowClient.delete_experiment  # TODO
```

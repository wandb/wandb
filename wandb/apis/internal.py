from wandb.sdk.internal.internal_api import Api as InternalApi


class Api(object):
    """Internal proxy to the official internal API.  Eventually these methods
    should likely be moved to PublicApi"""

    def __init__(self, *args, **kwargs):
        self._api_args = args
        self._api_kwargs = kwargs
        self._api = None

    @property
    def api(self):
        # This is a property in order ot delay construction of Internal API
        # for as long as possible. If constructed in constructor, then the
        # whole InternalAPI is started when simply importing wandb.
        if self._api is None:
            self._api = InternalApi(*self._api_args, **self._api_kwargs)
        return self._api

    @property
    def api_key(self):
        return self.api.api_key

    @property
    def api_url(self):
        return self.api.api_url

    @property
    def app_url(self):
        return self.api.app_url

    @property
    def git(self):
        return self.api.git

    def file_current(self, *args):
        return self.api.file_current(*args)

    def download_file(self, *args, **kwargs):
        return self.api.download_file(*args, **kwargs)

    def set_current_run_id(self, run_id):
        return self.api.set_current_run_id(run_id)

    def viewer(self):
        return self.api.viewer()

    def viewer_server_info(self):
        return self.api.viewer_server_info()

    def list_projects(self, entity=None):
        return self.api.list_projects(entity=entity)

    def format_project(self, project):
        return self.api.format_project(project)

    def upsert_project(self, project, id=None, description=None, entity=None):
        return self.api.upsert_project(
            project, id=id, description=description, entity=entity
        )

    def settings(self, *args, **kwargs):
        return self.api.settings(*args, **kwargs)

    def clear_setting(self, *args, **kwargs):
        return self.api.clear_setting(*args, **kwargs)

    def set_setting(self, *args, **kwargs):
        return self.api.set_setting(*args, **kwargs)

    def parse_slug(self, *args, **kwargs):
        return self.api.parse_slug(*args, **kwargs)

    def download_url(self, *args, **kwargs):
        return self.api.download_url(*args, **kwargs)

    def download_urls(self, *args, **kwargs):
        return self.api.download_urls(*args, **kwargs)

    def create_anonymous_api_key(self):
        return self.api.create_anonymous_api_key()

    def push(self, *args, **kwargs):
        return self.api.push(*args, **kwargs)

    def sweep(self, *args, **kwargs):
        return self.api.sweep(*args, **kwargs)

    def upsert_sweep(self, *args, **kwargs):
        return self.api.upsert_sweep(*args, **kwargs)

    def set_sweep_state(self, *args, **kwargs):
        return self.api.set_sweep_state(*args, **kwargs)

    def get_sweep_state(self, *args, **kwargs):
        return self.api.get_sweep_state(*args, **kwargs)

    def stop_sweep(self, *args, **kwargs):
        return self.api.stop_sweep(*args, **kwargs)

    def cancel_sweep(self, *args, **kwargs):
        return self.api.cancel_sweep(*args, **kwargs)

    def pause_sweep(self, *args, **kwargs):
        return self.api.pause_sweep(*args, **kwargs)

    def resume_sweep(self, *args, **kwargs):
        return self.api.resume_sweep(*args, **kwargs)

    def register_agent(self, *args, **kwargs):
        return self.api.register_agent(*args, **kwargs)

    def agent_heartbeat(self, *args, **kwargs):
        return self.api.agent_heartbeat(*args, **kwargs)

    def use_artifact(self, *args, **kwargs):
        return self.api.use_artifact(*args, **kwargs)

    def create_artifact(self, *args, **kwargs):
        return self.api.create_artifact(*args, **kwargs)

    def run_config(self, *args, **kwargs):
        return self.api.run_config(*args, **kwargs)

    def upload_file_retry(self, *args, **kwargs):
        return self.api.upload_file_retry(*args, **kwargs)


__all__ = ["Api"]

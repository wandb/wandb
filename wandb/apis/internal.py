from wandb.internal.internal_api import Api as InternalApi


class Api(object):
    """Internal proxy to the official internal API.  Eventually these methods
    should likely be moved to PublicApi"""
    def __init__(self, *args, **kwargs):
        self.api = InternalApi(*args, **kwargs)

    @property
    def api_key(self):
        return self.api.api_key

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

    def settings(self, *args, **kwargs):
        return self.api.settings(*args, **kwargs)

    def set_setting(self, *args, **kwargs):
        return self.api.set_setting(*args, **kwargs)

    def parse_slug(self, *args, **kwargs):
        return self.api.parse_slug(*args, **kwargs)

    def download_urls(self, *args, **kwargs):
        return self.api.download_urls(*args, **kwargs)

    def sweep(self, *args, **kwargs):
        return self.api.sweep(*args, **kwargs)

    def upsert_sweep(self, *args, **kwargs):
        return self.api_upsert_sweep(*args, **kwargs)

    def register_agent(self, *args, **kwargs):
        return self.api.register_agent(*args, **kwargs)

    def agent_heartbeat(self, *args, **kwargs):
        return self.api.agent_heartbeat(*args, **kwargs)

    def use_artifact(self, *args, **kwargs):
        return self.api.use_artifact(*args, **kwargs)

    def create_artifact(self, *args, **kwargs):
        return self.api.create_artifact(*args, **kwargs)


__all__ = ["Api"]

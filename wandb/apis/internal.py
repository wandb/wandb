from typing import Any

from wandb.sdk.internal.internal_api import Api as InternalApi


class Api:
    """Internal proxy to the official internal API."""

    # TODO: Move these methods to PublicApi.

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._api_args = args
        self._api_kwargs = kwargs
        self._api = None

    def __getstate__(self):
        """Use for serializing.

        self._api is not serializable, so it's dropped
        """
        state = self.__dict__.copy()
        del state["_api"]
        return state

    def __setstate__(self, state):
        """Used for deserializing.

        Don't need to set self._api because it's constructed when needed.
        """
        self.__dict__.update(state)
        self._api = None

    @property
    def api(self) -> InternalApi:
        # This is a property in order to delay construction of Internal API
        # for as long as possible. If constructed in constructor, then the
        # whole InternalAPI is started when simply importing wandb.
        if self._api is None:
            self._api = InternalApi(*self._api_args, **self._api_kwargs)
        return self._api

    @property
    def api_key(self):
        return self.api.api_key

    @property
    def is_authenticated(self):
        return self.api.access_token is not None or self.api.api_key is not None

    @property
    def api_url(self):
        return self.api.api_url

    @property
    def app_url(self):
        return self.api.app_url

    @property
    def default_entity(self):
        return self.api.default_entity

    @property
    def git(self):
        return self.api.git

    def validate_api_key(self) -> bool:
        """Returns whether the API key stored on initialization is valid."""
        return self.api.validate_api_key()

    def file_current(self, *args):
        return self.api.file_current(*args)

    def download_file(self, *args, **kwargs):
        return self.api.download_file(*args, **kwargs)

    def download_write_file(self, *args, **kwargs):
        return self.api.download_write_file(*args, **kwargs)

    def set_current_run_id(self, run_id):
        return self.api.set_current_run_id(run_id)

    def viewer(self):
        return self.api.viewer()

    def max_cli_version(self):
        return self.api.max_cli_version()

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

    def upsert_run(self, *args, **kwargs):
        return self.api.upsert_run(*args, **kwargs)

    def settings(self, *args, **kwargs):
        return self.api.settings(*args, **kwargs)

    def clear_setting(
        self, key: str, globally: bool = False, persist: bool = False
    ) -> None:
        return self.api.clear_setting(key, globally, persist)

    def set_setting(
        self, key: str, value: Any, globally: bool = False, persist: bool = False
    ) -> None:
        return self.api.set_setting(key, value, globally, persist)

    def parse_slug(self, *args, **kwargs):
        return self.api.parse_slug(*args, **kwargs)

    def download_url(self, *args, **kwargs):
        return self.api.download_url(*args, **kwargs)

    def download_urls(self, *args, **kwargs):
        return self.api.download_urls(*args, **kwargs)

    def create_anonymous_api_key(self) -> str:
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

    def complete_multipart_upload_artifact(self, *args, **kwargs):
        return self.api.complete_multipart_upload_artifact(*args, **kwargs)

    def run_config(self, *args, **kwargs):
        return self.api.run_config(*args, **kwargs)

    def upload_file_retry(self, *args, **kwargs):
        return self.api.upload_file_retry(*args, **kwargs)

    def upload_multipart_file_chunk_retry(self, *args, **kwargs):
        return self.api.upload_multipart_file_chunk_retry(*args, **kwargs)

    def get_run_info(self, *args, **kwargs):
        return self.api.get_run_info(*args, **kwargs)

    def get_run_state(self, *args, **kwargs):
        return self.api.get_run_state(*args, **kwargs)

    def entity_is_team(self, *args, **kwargs):
        return self.api.entity_is_team(*args, **kwargs)

    def get_project_run_queues(self, *args, **kwargs):
        return self.api.get_project_run_queues(*args, **kwargs)

    def push_to_run_queue(self, *args, **kwargs):
        return self.api.push_to_run_queue(*args, **kwargs)

    def pop_from_run_queue(self, *args, **kwargs):
        return self.api.pop_from_run_queue(*args, **kwargs)

    def ack_run_queue_item(self, *args, **kwargs):
        return self.api.ack_run_queue_item(*args, **kwargs)

    def create_launch_agent(self, *args, **kwargs):
        return self.api.create_launch_agent(*args, **kwargs)

    def create_default_resource_config(self, *args, **kwargs):
        return self.api.create_default_resource_config(*args, **kwargs)

    def create_run_queue(self, *args, **kwargs):
        return self.api.create_run_queue(*args, **kwargs)

    def upsert_run_queue(self, *args, **kwargs):
        return self.api.upsert_run_queue(*args, **kwargs)

    def update_launch_agent_status(self, *args, **kwargs):
        return self.api.update_launch_agent_status(*args, **kwargs)

    def launch_agent_introspection(self, *args, **kwargs):
        return self.api.launch_agent_introspection(*args, **kwargs)

    def fail_run_queue_item_introspection(self, *args, **kwargs):
        return self.api.fail_run_queue_item_introspection(*args, **kwargs)

    def fail_run_queue_item(self, *args, **kwargs):
        return self.api.fail_run_queue_item(*args, **kwargs)

    def update_run_queue_item_warning(self, *args, **kwargs):
        return self.api.update_run_queue_item_warning(*args, **kwargs)

    def get_launch_agent(self, *args, **kwargs):
        return self.api.get_launch_agent(*args, **kwargs)

    def stop_run(self, *args, **kwargs):
        return self.api.stop_run(*args, **kwargs)


__all__ = ["Api"]

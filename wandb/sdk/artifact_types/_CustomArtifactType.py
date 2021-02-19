import wandb

from .. import wandb_artifacts

if wandb.TYPE_CHECKING:
    from typing import TYPE_CHECKING, Optional, List

    if TYPE_CHECKING:
        from wandb.apis.public import Artifact as PublicArtifact


class _CustomArtifact(wandb_artifacts.Artifact):
    def __init__(self, *args, **kwargs):
        super(_CustomArtifact, self).__init__(*args, **kwargs)
        self._project = None
        self._entity = None

    def set_preferred_destination(
        self, project: Optional[str] = None, entity: Optional[str] = None
    ) -> None:
        self._project = project
        self._entity = entity

    def save(self, aliases: Optional[List[str]] = None):
        # TODO: move this top level and fix circular imports
        from .. import wandb_setup, wandb_init

        setup = wandb_setup._setup()
        if len(setup._global_run_stack) > 0:
            run = setup._global_run_stack[-1]
            run.log_artifact(self)
        else:
            run = wandb_init.init(project=self._project, entity=self._entity)
            run.log_artifact(self)
            run.finish()


class _CustomArtifactType:
    def __init__(
        self, name: str, project: Optional[str] = None, entity: Optional[str] = None
    ) -> None:
        self._name = name
        self._project = project
        self._entity = entity

    @staticmethod
    def get_type_name() -> str:
        raise NotImplementedError()

    def _make_name(self, alias: str = "latest") -> str:
        name = "{}:{}".format(self._name, alias)
        return name

    def _make_qualified_name(self, alias: str = "latest") -> str:
        name = ""
        if self._entity is not None:
            name += "{}/".format(self._entity)
        if self._project is not None:
            name += "{}/".format(self._project)
        name += self._make_name(alias)
        return name

    def new(self) -> _CustomArtifact:
        art = _CustomArtifact(self._name, self.get_type_name())
        art.set_preferred_destination(self._project, self._entity)
        return art

    def use(self, alias: str = "latest") -> "PublicArtifact":
        from .. import wandb_setup, wandb_init

        setup = wandb_setup._setup()
        if len(setup._global_run_stack) > 0:
            run = setup._global_run_stack[-1]
            return run.use_artifact(self._make_qualified_name(alias))
        # else:
        #     from ...apis.public import Api
        #     wi = wandb_init._WandbInit()
        #     wi.setup({})
        #     print(wi.settings.entity)
        #     print(Api().settings)
        #     return Api().artifact(self._make_qualified_name(alias))
        else:
            run = wandb_init.init(project=self._project, entity=self._entity)
            art = run.use_artifact(self._make_qualified_name(alias))
            run.finish()
            return art

import pathlib
from typing import TYPE_CHECKING, Optional, Union

from wandb import util

from .media import Media

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


class Bokeh(Media):
    OBJ_TYPE = "bokeh-file"
    OBJ_ARTIFACT_TYPE = "bokeh-file"
    RELATIVE_PATH = pathlib.Path("media") / "bokeh"
    DEFAULT_FORMAT = ".BOKEH.JSON"

    def __init__(self, data_or_path) -> None:
        super().__init__()

        bokeh = util.get_module("bokeh", required=True)
        self._format = self.DEFAULT_FORMAT.lower()

        if isinstance(data_or_path, (str, pathlib.Path)):
            self.from_path(data_or_path)
        elif isinstance(data_or_path, bokeh.model.Model):
            self.from_bokeh(data_or_path)
        else:
            raise ValueError("data_or_path must be a path or bokeh model")

    def from_path(self, path: Union[str, pathlib.Path]) -> None:
        ...

    def from_bokeh(self, bokeh_model) -> None:
        ...

    def bind_to_run(
        self, run: "Run", *namespace: str, name: Optional[str] = None
    ) -> None:
        """Bind this bokeh object to a run.

        Args:
            run: The run to bind to.
            namespace: The namespace to use.
            name: The name of the bokeh object.
        """
        return super().bind_to_run(
            run,
            *namespace,
            name=name,
            suffix=f".{self._format}",
        )

    # def bind_to_artifact(self, artifact: "Artifact") -> Dict[str, Any]:
    #     super().bind_to_artifact(artifact)
    #     return {
    #         "_type": self.OBJ_ARTIFACT_TYPE,
    #     }

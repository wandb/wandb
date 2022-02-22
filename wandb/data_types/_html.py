import os
from typing import Sequence, Type, TYPE_CHECKING, Union

from wandb.sdk.interface import _dtypes
from wandb.util import generate_id, mkdir_exists_ok

from ._batched_media import BatchableMedia


if TYPE_CHECKING:
    import io

    from wandb.apis.public import Artifact as PublicArtifact
    from wandb.sdk.wandb_artifacts import Artifact
    from wandb.sdk.wandb_run import Run


class Html(BatchableMedia):
    """
    Wandb class for arbitrary html

    Arguments:
        data_or_path: (string or io object) HTML to display in wandb
        inject: (boolean) Add a stylesheet to the HTML object.  If set
            to False the HTML will pass through unchanged.
    """

    _log_type = "html-file"
    _STYLESHEET = '<base target="_blank"><link rel="stylesheet" type="text/css" href="https://app.wandb.ai/normalize.css" />'

    def __init__(
        self, data_or_path: Union[str, "io.TextIO"], inject: bool = True
    ) -> None:
        super().__init__()

        path = None
        if isinstance(data_or_path, str):
            if os.path.exists(data_or_path):
                path = data_or_path
                with open(path, "r") as file_handler:
                    html = file_handler.read()
            else:
                html = data_or_path
        elif hasattr(data_or_path, "read"):
            if hasattr(data_or_path, "seek"):
                data_or_path.seek(0)
            html = data_or_path.read()
        else:
            raise ValueError("`data_or_path` must be a string or an io object")

        self.html = html

        if inject:
            self._inject_stylesheet()

        if inject or path is None:
            path = os.path.join(self._MEDIA_TMP.name, generate_id() + ".html")
            with open(path, "w") as file_handler:
                file_handler.write(self.html)
            self._set_file(path, is_tmp=True)
        else:
            self._set_file(path)

    def _inject_stylesheet(self) -> None:

        if "<head>" in self.html:
            parts = list(self.html.partition("<head>"))
            parts.insert(2, self._STYLESHEET)
        elif "<html>" in self.html:
            parts = list(self.html.partition("<html>"))
            parts.insert(2, f"<head>{self._STYLESHEET}</head>")
        else:
            parts = [self._STYLESHEET, self.html]

        self.html = "".join(parts).strip()

    @classmethod
    def get_media_subdir(cls: Type["Html"]) -> str:
        return os.path.join("media", "html")

    def to_json(self, run_or_artifact: Union["Run", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        return json_dict

    @classmethod
    def from_json(
        cls: Type["Html"], json_obj: dict, source_artifact: "PublicArtifact"
    ) -> "Html":
        return cls(source_artifact.get_path(json_obj["path"]).download(), inject=False)

    @classmethod
    def seq_to_json(
        cls: Type["Html"],
        seq: Sequence["BatchableMedia"],
        run: "Run",
        key: str,
        step: Union[int, str],
    ) -> dict:
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        mkdir_exists_ok(base_path)

        meta = {
            "_type": "html",
            "count": len(seq),
            "html": [h.to_json(run) for h in seq],
        }
        return meta


class _HtmlFileType(_dtypes.Type):
    name = "html-file"
    types = [Html]


_dtypes.TypeRegistry.add(_HtmlFileType)

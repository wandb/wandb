import os
import pathlib
from typing import TYPE_CHECKING, Sequence, Type, Union

from wandb.sdk.lib import filesystem, runid

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia

if TYPE_CHECKING:  # pragma: no cover
    from typing import TextIO

    from wandb.sdk.artifacts.artifact import Artifact

    from ..wandb_run import Run as LocalRun


class Html(BatchableMedia):
    """W&B class for logging HTML content to W&B."""

    _log_type = "html-file"

    def __init__(
        self,
        data: Union[str, pathlib.Path, "TextIO"],
        inject: bool = True,
        data_is_not_path: bool = False,
    ) -> None:
        """Creates a W&B HTML object.

        Args:
            data:
                A string that is a path to a file with the extension ".html",
                or a string or IO object containing literal HTML.
            inject: Add a stylesheet to the HTML object. If set
                to False the HTML will pass through unchanged.
            data_is_not_path: If set to False, the data will be
                treated as a path to a file.

        Examples:
        It can be initialized by providing a path to a file:

        ```python
        with wandb.init() as run:
            run.log({"html": wandb.Html("./index.html")})
        ```

        Alternatively, it can be initialized by providing literal HTML,
        in either a string or IO object:

        ```python
        with wandb.init() as run:
            run.log({"html": wandb.Html("<h1>Hello, world!</h1>")})
        ```
        """
        super().__init__()
        data_is_path = (
            isinstance(data, (str, pathlib.Path))
            and os.path.isfile(data)
            and os.path.splitext(data)[1] == ".html"
        ) and not data_is_not_path
        data_path = ""
        if data_is_path:
            data_path = str(data)
            with open(data_path, encoding="utf-8") as file:
                self.html = file.read()
        elif isinstance(data, str):
            self.html = data
        elif hasattr(data, "read"):
            if hasattr(data, "seek"):
                data.seek(0)
            self.html = data.read()
        else:
            raise ValueError("data must be a string or an io object")

        if inject:
            self.inject_head()

        if inject or not data_is_path:
            tmp_path = os.path.join(MEDIA_TMP.name, runid.generate_id() + ".html")
            with open(tmp_path, "w", encoding="utf-8") as out:
                out.write(self.html)

            self._set_file(tmp_path, is_tmp=True)
        else:
            self._set_file(data_path, is_tmp=False)

    def inject_head(self) -> None:
        """Inject a <head> tag into the HTML.

        <!-- lazydoc-ignore: internal -->
        """
        join = ""
        if "<head>" in self.html:
            parts = self.html.split("<head>", 1)
            parts[0] = parts[0] + "<head>"
        elif "<html>" in self.html:
            parts = self.html.split("<html>", 1)
            parts[0] = parts[0] + "<html><head>"
            parts[1] = "</head>" + parts[1]
        else:
            parts = ["", self.html]
        parts.insert(
            1,
            '<base target="_blank"><link rel="stylesheet" type="text/css" href="https://app.wandb.ai/normalize.css" />',
        )
        self.html = join.join(parts).strip()

    @classmethod
    def get_media_subdir(cls: Type["Html"]) -> str:
        """Get media subdirectory.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        return os.path.join("media", "html")

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        """Returns the JSON representation expected by the backend.

        <!-- lazydoc-ignore: internal -->
        """
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self._log_type
        return json_dict

    @classmethod
    def from_json(
        cls: Type["Html"], json_obj: dict, source_artifact: "Artifact"
    ) -> "Html":
        """Deserialize a JSON object into it's class representation.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        return cls(source_artifact.get_entry(json_obj["path"]).download(), inject=False)

    @classmethod
    def seq_to_json(
        cls: Type["Html"],
        seq: Sequence["BatchableMedia"],
        run: "LocalRun",
        key: str,
        step: Union[int, str],
    ) -> dict:
        """Convert a sequence of HTML objects to a JSON representation.

        "<!-- lazydoc-ignore-classmethod: internal -->
        """
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        filesystem.mkdir_exists_ok(base_path)

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

import pathlib
from typing import Optional, TextIO, Union

from .media import Media


class HTML(Media):
    OBJ_TYPE = "html-file"
    RELATIVE_PATH = pathlib.Path("media") / "html"
    DEFAULT_FORMAT = "HTML"

    INJECTED_STYLESHEET = "<base target='_blank'><link rel='stylesheet' type='text/css' href='https://app.wandb.ai/normalize.css' />"

    def __init__(
        self, data_or_path: Union[str, pathlib.Path, TextIO], inject: bool = True
    ) -> None:
        if isinstance(data_or_path, pathlib.Path):
            self.from_path(data_or_path, inject=inject)
        elif isinstance(data_or_path, str) and pathlib.Path(data_or_path).exists():
            self.from_path(data_or_path, inject=inject)
        elif isinstance(data_or_path, str):
            self.from_string(data_or_path, inject=inject)
        elif hasattr(data_or_path, "read"):
            self.from_buffer(data_or_path, inject=inject)
        else:
            raise ValueError("data must be a string or an io object")

    def from_path(self, path: Union[str, pathlib.Path], inject: bool) -> None:
        with self.path.save(path) as path:
            if inject:
                with open(path) as f:
                    html = f.read()
                self.from_string(html, inject=inject)

    def from_string(self, html: str, inject: bool) -> None:
        self._format = self.DEFAULT_FORMAT.lower()
        with self.path.save(suffix=f".{self._format}") as path:
            if inject:
                html = self._inject_stylesheet(html)
            with open(path, "w") as f:
                f.write(html)

    def from_buffer(self, buffer: "TextIO", inject: bool) -> None:
        if hasattr(buffer, "seek"):
            buffer.seek(0)
        html = buffer.read()
        self.from_string(html, inject=inject)

    def _inject_stylesheet(self, html: str) -> str:
        if "<head>" in html:
            html_parts = list(html.partition("<head>"))
            html_parts.insert(2, self.INJECTED_STYLESHEET)
        elif "<html>" in html:
            html_parts = list(html.partition("<html>"))
            html_parts.insert(2, f"<head>{self.INJECTED_STYLESHEET}</head>")
        else:
            html_parts = [self.INJECTED_STYLESHEET, html]

        return "".join(html_parts).strip()

    def to_json(self) -> dict:
        return {
            "_type": self.OBJ_TYPE,
            **super().to_json(),
        }

    def bind_to_run(self, run, *namespace, name: Optional[str] = None) -> None:
        super().bind_to_run(
            run,
            *namespace,
            name=name,
            suffix=f".{self._format}",
        )

from .media import Media
import pathlib

from typing import Union, TextIO, Optional


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

        self._sha256 = self._compute_sha256(self._source_path)
        self._size = self._source_path.stat().st_size

    def from_path(self, path: Union[str, pathlib.Path], inject: bool) -> None:
        self._source_path = pathlib.Path(path).resolve()
        self._format = self._source_path.suffix[1:].lower()
        self._is_temp_path = False
        if inject:
            with open(self._source_path, "r") as f:
                html = f.read()
            self.from_string(html, inject=inject)

    def from_string(self, html: str, inject: bool) -> None:
        if inject:
            html = self._inject_stylesheet(html)
        self._format = self.DEFAULT_FORMAT.lower()
        self._source_path = self._generate_temp_path(suffix=f".{self._format}")
        self._is_temp_path = True

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
            "sha256": self._sha256,
            "size": self._size,
            "path": str(self._bind_path),
        }

    def bind_to_run(
        self, interface, start: pathlib.Path, *prefix, name: Optional[str] = None
    ) -> None:
        super().bind_to_run(
            interface,
            start,
            *prefix,
            name or self._sha256[:20],
            suffix=f".{self._format}",
        )

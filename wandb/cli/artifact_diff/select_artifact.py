"""Interactive selector for building an artifact path using Textual.

Run `run_selector(api)` to return a string like "project/artifact:vX" chosen by the user.
"""

from __future__ import annotations

from collections import deque
from enum import IntEnum, auto

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from wandb import Api


class PromptStep(IntEnum):
    """Steps for choosing an artifact."""

    PROJECT = auto()
    COLLECTION = auto()
    VERSION = auto()


class _Chooser(App):
    CSS = """
    Screen { background: $background; }
    ListView { border: round $primary; height: 80%; }
    """

    BINDINGS = [
        Binding(key="q", action="quit", description="Quit"),
    ]

    PROMPT_ID = "prompt"
    OPTIONS_ID = "options"

    def __init__(self, api: Api) -> None:
        super().__init__()
        self.api = api
        self.step = PromptStep.PROJECT
        self.project: str | None = None
        self.collection: str | None = None
        self.version: str | None = None

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header()
        yield Static(id=self.PROMPT_ID)
        yield ListView(id=self.OPTIONS_ID)
        yield Footer()

    def on_mount(self) -> None:  # type: ignore[override]
        self._show_projects()

    # ------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------
    def _set_prompt(self, text: str) -> None:
        self.query_one(f"#{self.PROMPT_ID}", Static).update(text)

    def _populate(self, items: list[str]) -> None:
        lv = self.query_one(f"#{self.OPTIONS_ID}", ListView)
        lv.clear()
        for t in items:
            lv.append(ListItem(Label(t)))
        if items:
            lv.index = 0

    # ------------------------------------------------------------
    # step builders
    # ------------------------------------------------------------
    def _show_projects(self) -> None:
        entity = (
            self.api.default_entity
            or self.api.settings().get("entity")
            or "<default entity>"
        )
        projects = sorted({p.name for p in self.api.projects()})
        self._set_prompt(f"Select project (entity: {entity!r})")
        self._populate(projects)
        self.step = PromptStep.PROJECT

    def _show_collections(self) -> None:
        if self.project is None:
            raise RuntimeError("Project is not set")

        collections = deque()
        for atype in self.api.artifact_types(self.project):
            collections.extend(
                c.name for c in self.api.artifact_collections(self.project, atype.name)
            )

        if not collections:
            self.exit("No collections found")
            return

        self._set_prompt(f"Select artifact collection from project: {self.project!r}")
        self._populate(sorted(collections))
        self.step = PromptStep.COLLECTION

    def _show_version_input(self) -> None:
        assert self.collection is not None
        self._set_prompt(
            f"Enter version/tag for {self.project}/{self.collection} (default: latest) and press Enter"
        )
        # replace listview with input
        lv = self.query_one(f"#{self.OPTIONS_ID}", ListView)
        lv.visible = False
        self.mount(Input(placeholder="version", id="ver_input"))
        self.query_one("#ver_input", Input).focus()
        self.step = PromptStep.VERSION

    # ------------------------------------------------------------
    # events
    # ------------------------------------------------------------
    async def on_list_view_selected(self, event: ListView.Selected) -> None:  # type: ignore
        lbl_widget = event.item.query_one(Label)
        # Textual 0.45+ stores text in `renderable`; else fallback
        renderable = lbl_widget.renderable
        label = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        if self.step is PromptStep.PROJECT:
            self.project = label
            self._show_collections()
        elif self.step is PromptStep.COLLECTION:
            self.collection = label
            self._show_version_input()

    async def on_input_submitted(self, event: Input.Submitted) -> None:  # type: ignore
        if self.step is PromptStep.VERSION:
            self.version = event.value.strip() or "latest"
            self.exit(f"{self.project}/{self.collection}:{self.version}")


def run_selector(api: Api) -> str | None:
    """Launch selector app; returns constructed artifact path or None if aborted."""
    return _Chooser(api).run()

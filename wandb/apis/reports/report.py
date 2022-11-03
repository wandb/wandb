import inspect
import json
import urllib
from copy import deepcopy
from typing import List as LList

from ... import __version__ as wandb_ver
from ... import termlog, termwarn
from ...sdk.lib import ipython
from ..public import Api, RetryingClient
from ._blocks import P, PanelGrid, UnknownBlock, block_mapping
from ._panels import ParallelCoordinatesPlot, ScatterPlot
from .mutations import UPSERT_VIEW
from .runset import Runset
from .util import Attr, Base, Block, coalesce, generate_name, nested_get, nested_set
from .validators import OneOf, TypeValidator


class Report(Base):
    project: str = Attr(json_path="viewspec.project.name")
    entity: str = Attr(json_path="viewspec.project.entityName")
    title: str = Attr(json_path="viewspec.displayName")
    description: str = Attr(json_path="viewspec.description")
    width: str = Attr(
        json_path="viewspec.spec.width",
        validators=[OneOf(["readable", "fixed", "fluid"])],
    )
    blocks: list = Attr(
        json_path="viewspec.spec.blocks",
        validators=[TypeValidator(Block, how="keys")],
    )

    def __init__(
        self,
        project,
        entity=None,
        title="Untitled Report",
        description="",
        width="readable",
        blocks=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._viewspec = self._default_viewspec()
        self._orig_viewspec = deepcopy(self._viewspec)

        self.project = project
        self.entity = coalesce(entity, Api().default_entity, "")
        self.title = title
        self.description = description
        self.width = width
        self.blocks = coalesce(blocks, [])

    @classmethod
    def from_url(self, url):
        return Api().load_report(url)

    @blocks.getter
    def blocks(self):
        json_path = self._get_path("blocks")
        block_specs = nested_get(self, json_path)
        blocks = []
        for bspec in block_specs:
            cls = block_mapping.get(bspec["type"], UnknownBlock)
            if cls is UnknownBlock:
                termwarn(
                    inspect.cleandoc(
                        f"""
                        UNKNOWN BLOCK DETECTED
                            This can happen if we have added new blocks, but you are using an older version of the SDK.
                            If your report is loading normally, you can safely ignore this message (but we recommend not touching UnknownBlock)
                            If you think this is an error, please file a bug report including your SDK version ({wandb_ver}) and this spec ({bspec})
                        """
                    )
                )
            blocks.append(cls.from_json(bspec))
        return blocks[1:-1]  # accounts for hidden p blocks

    @blocks.setter
    def blocks(self, new_blocks):
        json_path = self._get_path("blocks")
        new_block_specs = (
            [P("").spec] + [b.spec for b in new_blocks] + [P("").spec]
        )  # hidden p blocks
        nested_set(self, json_path, new_block_specs)

    @staticmethod
    def _default_viewspec():
        return {
            "id": None,
            "name": None,
            "spec": {
                "version": 5,
                "panelSettings": {},
                "blocks": [],
                "width": "readable",
                "authors": [],
                "discussionThreads": [],
                "ref": {},
            },
        }

    @classmethod
    def from_json(cls, viewspec):
        obj = cls(project=viewspec["project"]["name"])
        obj._viewspec = viewspec
        obj._orig_viewspec = deepcopy(obj._viewspec)
        return obj

    @property
    def viewspec(self):
        return self._viewspec

    @property
    def modified(self) -> bool:
        return self._viewspec != self._orig_viewspec

    @property
    def spec(self) -> dict:
        return self._viewspec["spec"]

    @property
    def client(self) -> "RetryingClient":
        return Api().client

    @property
    def id(self) -> str:
        return self._viewspec["id"]

    @property
    def name(self) -> str:
        return self._viewspec["name"]

    @property
    def panel_grids(self) -> "LList[PanelGrid]":
        return [b for b in self.blocks if isinstance(b, PanelGrid)]

    @property
    def runsets(self) -> "LList[Runset]":
        return [rs for pg in self.panel_grids for rs in pg.runsets]

    @property
    def url(self) -> str:
        title = urllib.parse.quote(self.title.replace(" ", "-"))
        id = self.id.replace("=", "")
        return (
            f"{self.client.app_url}/{self.entity}/{self.project}/reports/{title}--{id}"
        )

    def save(self, draft: bool = False, clone: bool = False) -> "Report":
        if not self.modified:
            termwarn("Report has not been modified")

        # create project if not exists
        Api().create_project(self.project, self.entity)

        # Check runsets with `None` for project and replace with the report's project.
        # We have to do this here because RunSets don't know about their report until they're added to it.
        for rs in self.runsets:
            if rs.project is None:
                rs.project = self.project

        # For PC and Scatter, we need to use slightly different values, so update if possible.
        # This only happens on set, and only when assigned to a panel grid because that is
        # the earliest time that we have a runset to check what kind of metric is being assigned.
        transform = self.runsets[0].pm_query_generator.pc_front_to_back
        for pg in self.panel_grids:
            for p in pg.panels:
                if isinstance(p, ParallelCoordinatesPlot) and p.columns:
                    for col in p.columns:
                        col.metric = transform(col.metric)
                if isinstance(p, ScatterPlot):
                    if p.x:
                        px = transform(p.x)
                    if p.y:
                        py = transform(p.y)
                    if p.z:
                        pz = transform(p.z)

        r = self.client.execute(
            UPSERT_VIEW,
            variable_values={
                "id": None if clone or not self.id else self.id,
                "name": generate_name() if clone or not self.name else self.name,
                "entityName": self.entity,
                "projectName": self.project,
                "description": self.description,
                "displayName": self.title,
                "type": "runs/draft" if draft else "runs",
                "spec": json.dumps(self.spec),
            },
        )

        viewspec = r["upsertView"]["view"]
        viewspec["spec"] = json.loads(viewspec["spec"])
        if clone:
            return Report.from_json(viewspec)
        else:
            self._viewspec = viewspec
            return self

    def to_html(self, height: int = 1024, hidden: bool = False) -> str:
        """Generate HTML containing an iframe displaying this report"""
        try:
            url = self.url + "?jupyter=true"
            style = f"border:none;width:100%;height:{height}px;"
            prefix = ""
            if hidden:
                style += "display:none;"
                prefix = ipython.toggle_button("report")
            return prefix + f'<iframe src="{url}" style="{style}"></iframe>'
        except AttributeError:
            termlog("HTML repr will be available after you save the report!")

    def _repr_html_(self) -> str:
        return self.to_html()

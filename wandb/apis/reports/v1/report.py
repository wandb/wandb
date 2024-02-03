import base64
import inspect
import json
import re
import urllib
from copy import deepcopy
from typing import List as LList

from .... import __version__ as wandb_ver
from .... import termlog, termwarn
from ....sdk.lib import ipython
from ...public import Api as PublicApi
from ...public import RetryingClient
from ._blocks import P, PanelGrid, UnknownBlock, WeaveBlock, block_mapping, weave_blocks
from .mutations import UPSERT_VIEW, VIEW_REPORT
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
        _api=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._viewspec = self._default_viewspec()
        self._orig_viewspec = deepcopy(self._viewspec)
        self._api = PublicApi() if _api is None else _api

        self.project = project
        self.entity = coalesce(entity, self._api.default_entity, "")
        self.title = title
        self.description = description
        self.width = width
        self.blocks = coalesce(blocks, [])

    @classmethod
    def from_url(cls, url, api=None):
        if api is None:
            api = PublicApi()
        report_id = cls._url_to_report_id(url)
        r = api.client.execute(VIEW_REPORT, variable_values={"reportId": report_id})
        viewspec = r["view"]
        viewspec["spec"] = json.loads(viewspec["spec"])
        return cls.from_json(viewspec)

    @staticmethod
    def _url_to_report_id(url):
        path_msg = "Path must be `entity/project/reports/report_title--report_id`"
        try:
            report_path, *_ = url.split("?")
            report_path = report_path.replace("---", "--")

            if "--" not in report_path:
                raise ValueError(path_msg)

            *_, report_id = report_path.split("--")
            if len(report_id) == 0:
                raise ValueError("Invalid report id")

            report_id = report_id.strip()

            """
                Server does not generate IDs with correct padding, so decode with default validate=False.
                Then re-encode it with correct padding.
                https://stackoverflow.com/questions/2941995/python-ignore-incorrect-padding-error-when-base64-decoding

                Corresponding core app logic that strips the padding in url
                https://github.com/wandb/core/blob/b563437c1f3237ec35b1fb388ac14abbab7b4279/frontends/app/src/util/url/shared.ts#L33-L78
            """
            report_id = base64.b64encode(base64.b64decode(report_id + "==")).decode(
                "utf-8"
            )

        except ValueError as e:
            raise ValueError(path_msg) from e
        else:
            return report_id

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
            if cls is WeaveBlock:
                for cls in weave_blocks:
                    try:
                        cls.from_json(bspec)
                    except Exception:
                        pass
                    else:
                        break
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
        return self._api.client

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
        title = re.sub(r"\W", "-", self.title)
        title = re.sub(r"-+", "-", title)
        title = urllib.parse.quote(title)
        id = self.id.replace("=", "")
        app_url = self._api.client.app_url
        if not app_url.endswith("/"):
            app_url = app_url + "/"
        return f"{app_url}{self.entity}/{self.project}/reports/{title}--{id}"

    def save(self, draft: bool = False, clone: bool = False) -> "Report":
        if not self.modified:
            termwarn("Report has not been modified")

        # create project if not exists
        projects = self._api.projects(self.entity)
        is_new_project = True
        for p in projects:
            if p.name == self.project:
                is_new_project = False
                break

        if is_new_project:
            self._api.create_project(self.project, self.entity)

        # All panel grids must have at least one runset
        for pg in self.panel_grids:
            if not pg.runsets:
                pg.runsets = PanelGrid._default_runsets()

        # Check runsets with `None` for project and replace with the report's project.
        # We have to do this here because RunSets don't know about their report until they're added to it.
        for rs in self.runsets:
            rs.entity = coalesce(rs.entity, self._api.default_entity)
            rs.project = coalesce(rs.project, self.project)

        r = self._api.client.execute(
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
            self._viewspec["id"] = viewspec["id"]
            self._viewspec["name"] = viewspec["name"]
            return self

    def to_html(self, height: int = 1024, hidden: bool = False) -> str:
        """Generate HTML containing an iframe displaying this report."""
        try:
            url = self.url + "?jupyter=true"
            style = f"border:none;width:100%;height:{height}px;"
            prefix = ""
            if hidden:
                style += "display:none;"
                prefix = ipython.toggle_button("report")
            return prefix + f"<iframe src={url!r} style={style!r}></iframe>"
        except AttributeError:
            termlog("HTML repr will be available after you save the report!")

    def _repr_html_(self) -> str:
        return self.to_html()

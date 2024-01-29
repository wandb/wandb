import inspect
import re
import urllib
from typing import List as LList
from typing import Optional, Union

from .... import __version__ as wandb_ver
from .... import termwarn
from ...public import Api as PublicApi
from ._panels import UnknownPanel, WeavePanel, panel_mapping, weave_panels
from .runset import Runset
from .util import (
    Attr,
    Base,
    Block,
    InlineCode,
    InlineLaTeX,
    Link,
    Panel,
    coalesce,
    fix_collisions,
    nested_get,
    nested_set,
    weave_inputs,
)
from .validators import OneOf, TypeValidator


class UnknownBlock(Block):
    pass


class PanelGrid(Block):
    runsets: list = Attr(
        json_path="spec.metadata.runSets",
        validators=[TypeValidator(Runset, how="keys")],
    )
    panels: list = Attr(
        json_path="spec.metadata.panelBankSectionConfig.panels",
        validators=[TypeValidator(Panel, how="keys")],
    )
    custom_run_colors: dict = Attr(
        json_path="spec.metadata.customRunColors",
        validators=[
            TypeValidator(Union[str, tuple], how="keys"),
            TypeValidator(str, how="values"),
        ],
    )
    active_runset: Union[str, None] = Attr(json_path="spec.metadata.openRunSet")

    def __init__(
        self,
        runsets=None,
        panels=None,
        custom_run_colors=None,
        active_runset=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._spec = self._default_panel_grid_spec()
        self.runsets = coalesce(runsets, self._default_runsets())
        self.panels = coalesce(panels, self._default_panels())
        self.custom_run_colors = coalesce(custom_run_colors, {})
        self.active_runset = active_runset

    @active_runset.getter
    def active_runset(self):
        json_path = self._get_path("active_runset")
        index = nested_get(self, json_path)
        if index is None:
            return None
        else:
            return self.runsets[index].name

    @active_runset.setter
    def active_runset(self, name):
        json_path = self._get_path("active_runset")
        index = None
        for i, rs in enumerate(self.runsets):
            if rs.name == name:
                index = i
                break
        nested_set(self, json_path, index)

    @panels.getter
    def panels(self):
        json_path = self._get_path("panels")
        specs = nested_get(self, json_path)
        panels = []
        for pspec in specs:
            cls = panel_mapping.get(pspec["viewType"], UnknownPanel)
            if cls is UnknownPanel:
                termwarn(
                    inspect.cleandoc(
                        f"""
                        UNKNOWN PANEL DETECTED
                            This can happen if we have added new panels, but you are using an older version of the SDK.
                            If your report is loading normally, you can safely ignore this message (but we recommend not touching UnknownPanel)
                            If you think this is an error, please file a bug report including your SDK version ({wandb_ver}) and this spec ({pspec})
                        """
                    )
                )
            if cls is WeavePanel:
                for cls in weave_panels:
                    try:
                        cls.from_json(pspec)
                    except Exception:
                        pass
                    else:
                        break
            panels.append(cls.from_json(pspec))
        return panels

    @panels.setter
    def panels(self, new_panels):
        json_path = self._get_path("panels")
        new_specs = [p.spec for p in fix_collisions(new_panels)]
        nested_set(self, json_path, new_specs)

    @runsets.getter
    def runsets(self):
        json_path = self._get_path("runsets")
        specs = nested_get(self, json_path)
        return [Runset.from_json(spec) for spec in specs]

    @runsets.setter
    def runsets(self, new_runsets):
        json_path = self._get_path("runsets")
        new_specs = [rs.spec for rs in new_runsets]
        nested_set(self, json_path, new_specs)

    @custom_run_colors.getter
    def custom_run_colors(self):
        json_path = self._get_path("custom_run_colors")
        id_colors = nested_get(self, json_path)

        def is_groupid(s):
            for rs in self.runsets:
                if rs.spec["id"] in s:
                    return True
            return False

        def groupid_to_ordertuple(groupid):
            rs = self.runsets[0]
            if "-run:" in groupid:
                id, rest = groupid.split("-run:", 1)
            else:
                id, rest = groupid.split("-", 1)
            kvs = rest.split("-")
            kvs = [rs.pm_query_generator.pc_back_to_front(v) for v in kvs]
            keys, ordertuple = zip(*[kv.split(":") for kv in kvs])
            rs_name = self._get_rs_by_id(id).name
            return (rs_name, *ordertuple)

        def run_id_to_name(id):
            for rs in self.runsets:
                try:
                    run = PublicApi().run(f"{rs.entity}/{rs.project}/{id}")
                except Exception:
                    pass
                else:
                    return run.name
            raise ValueError("Unable to find this run!")

        color_settings = {}
        for id, c in id_colors.items():
            if id == "ref":
                continue
            if is_groupid(id):
                key = groupid_to_ordertuple(id)
            else:
                key = run_id_to_name(id)
            color_settings[key] = c
        return color_settings

    @custom_run_colors.setter
    def custom_run_colors(self, new_custom_run_colors):
        json_path = self._get_path("custom_run_colors")
        color_settings = {}

        def ordertuple_to_groupid(ordertuple):
            rs_name, rest = ordertuple[0], ordertuple[1:]
            rs = self._get_rs_by_name(rs_name)
            id = rs.spec["id"]
            keys = [rs.pm_query_generator.pc_front_to_back(k) for k in rs.groupby]
            kvs = [f"{k}:{v}" for k, v in zip(keys, rest)]
            linked = "-".join(kvs)
            return f"{id}-{linked}"

        def run_name_to_id(name):
            for rs in self.runsets:
                runs = PublicApi().runs(
                    path=f"{rs.entity}/{rs.project}", filters={"display_name": name}
                )
                if len(runs) > 1:
                    termwarn(
                        "Multiple runs with the same name found! Using the first one."
                    )
                for run in runs:
                    if run.name == name:
                        return run.id
            raise ValueError("Unable to find this run!")

        for name, c in new_custom_run_colors.items():
            if isinstance(name, tuple):
                key = ordertuple_to_groupid(name)
            else:
                key = run_name_to_id(name)
            color_settings[key] = c
        nested_set(self, json_path, color_settings)

    def _get_rs_by_id(self, id):
        for rs in self.runsets:
            if rs.spec["id"] == id:
                return rs

    def _get_rs_by_name(self, name):
        for rs in self.runsets:
            if rs.name == name:
                return rs

    @staticmethod
    def _default_panel_grid_spec():
        return {
            "type": "panel-grid",
            "children": [{"text": ""}],
            "metadata": {
                "openViz": True,
                "panels": {
                    "views": {"0": {"name": "Panels", "defaults": [], "config": []}},
                    "tabs": ["0"],
                },
                "panelBankConfig": {
                    "state": 0,
                    "settings": {
                        "autoOrganizePrefix": 2,
                        "showEmptySections": False,
                        "sortAlphabetically": False,
                    },
                    "sections": [
                        {
                            "name": "Hidden Panels",
                            "isOpen": False,
                            "panels": [],
                            "type": "flow",
                            "flowConfig": {
                                "snapToColumns": True,
                                "columnsPerPage": 3,
                                "rowsPerPage": 2,
                                "gutterWidth": 16,
                                "boxWidth": 460,
                                "boxHeight": 300,
                            },
                            "sorted": 0,
                            "localPanelSettings": {
                                "xAxis": "_step",
                                "smoothingWeight": 0,
                                "smoothingType": "exponential",
                                "ignoreOutliers": False,
                                "xAxisActive": False,
                                "smoothingActive": False,
                            },
                        }
                    ],
                },
                "panelBankSectionConfig": {
                    "name": "Report Panels",
                    "isOpen": False,
                    "panels": [],
                    "type": "grid",
                    "flowConfig": {
                        "snapToColumns": True,
                        "columnsPerPage": 3,
                        "rowsPerPage": 2,
                        "gutterWidth": 16,
                        "boxWidth": 460,
                        "boxHeight": 300,
                    },
                    "sorted": 0,
                    "localPanelSettings": {
                        "xAxis": "_step",
                        "smoothingWeight": 0,
                        "smoothingType": "exponential",
                        "ignoreOutliers": False,
                        "xAxisActive": False,
                        "smoothingActive": False,
                    },
                },
                "customRunColors": {},
                "runSets": [],
                "openRunSet": 0,
                "name": "unused-name",
            },
        }

    @staticmethod
    def _default_runsets():
        return [Runset()]

    @staticmethod
    def _default_panels():
        return []


class List(Base):
    @classmethod
    def from_json(cls, spec: dict) -> "Union[CheckedList, OrderedList, UnorderedList]":
        items = []
        for item in spec["children"]:
            text = []
            for elem in item["children"][0]["children"]:
                if elem.get("type") == "latex":
                    text.append(InlineLaTeX(elem["content"]))
                elif elem.get("type") == "link":
                    text.append(Link(elem["children"][0]["text"], elem["url"]))
                elif elem.get("inlineCode"):
                    text.append(InlineCode(elem["text"]))
                elif elem.get("text"):
                    text.append(elem["text"])
            items.append(text)
        checked = [item.get("checked") for item in spec["children"]]
        ordered = spec.get("ordered")

        # NAND: Either checked or ordered or neither (unordered), never both
        if all(x is None for x in checked):
            checked = None
        if checked is not None and ordered is not None:
            raise ValueError(
                "Lists can be checked, ordered or neither (unordered), but not both!"
            )

        if checked:
            return CheckedList(items, checked)
        elif ordered:
            return OrderedList(items)
        else:
            return UnorderedList(items)


class CheckedList(Block, List):
    items: list = Attr()
    checked: list = Attr()

    def __init__(self, items=None, checked=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if items is not None and checked is not None and len(items) != len(checked):
            raise ValueError("Items and checked lists must be the same length!")

        self.items = coalesce(items, [""])
        self.checked = coalesce(checked, [False for _ in self.items])

    @property
    def spec(self) -> dict:
        children = []
        for item, check in zip(self.items, self.checked):
            if isinstance(item, list):
                content = [
                    t.spec if not isinstance(t, str) else {"text": t} for t in item
                ]
            else:
                content = [{"text": item}]
            children.append(
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": content}],
                    "checked": check,
                }
            )

        return {"type": "list", "children": children}


class OrderedList(Block, List):
    items: list = Attr()

    def __init__(self, items=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = coalesce(items, [""])

    @property
    def spec(self) -> dict:
        children = []
        for item in self.items:
            if isinstance(item, list):
                content = [
                    t.spec if not isinstance(t, str) else {"text": t} for t in item
                ]
            else:
                content = [{"text": item}]
            children.append(
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": content}],
                    "ordered": True,
                }
            )

        return {"type": "list", "ordered": True, "children": children}


class UnorderedList(Block, List):
    items: list = Attr()

    def __init__(self, items=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = coalesce(items, [""])

    @property
    def spec(self) -> dict:
        children = []
        for item in self.items:
            if isinstance(item, list):
                content = [
                    t.spec if not isinstance(t, str) else {"text": t} for t in item
                ]
            else:
                content = [{"text": item}]
            children.append(
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": content}],
                }
            )

        return {"type": "list", "children": children}


class Heading(Base):
    @classmethod
    def from_json(cls, spec: dict) -> "Union[H1,H2,H3]":
        level = spec["level"]
        level_mapping = {1: H1, 2: H2, 3: H3}
        if level not in level_mapping:
            raise ValueError(f"`level` must be one of {list(level_mapping.keys())}")

        if isinstance(spec["children"], str):
            text = spec["children"]
        else:
            text = []
            for elem in spec["children"]:
                if elem.get("type") == "latex":
                    text.append(InlineLaTeX(elem["content"]))
                elif elem.get("type") == "link":
                    text.append(Link(elem["children"][0]["text"], elem["url"]))
                elif elem.get("inlineCode"):
                    text.append(InlineCode(elem["text"]))
                elif elem.get("text"):
                    text.append(elem["text"])
        if not isinstance(text, list):
            text = [text]
        return level_mapping[level](text)


class H1(Block, Heading):
    text: Union[str, list, Link] = Attr()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @property
    def spec(self) -> dict:
        if isinstance(self.text, list):
            content = [
                t.spec if not isinstance(t, str) else {"text": t} for t in self.text
            ]
        else:
            content = [{"text": self.text}]
        return {
            "type": "heading",
            "children": content,
            "level": 1,
        }


class H2(Block, Heading):
    text: Union[str, list, Link] = Attr()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @property
    def spec(self) -> dict:
        if isinstance(self.text, list):
            content = [
                t.spec if not isinstance(t, str) else {"text": t} for t in self.text
            ]
        else:
            content = [{"text": self.text}]
        return {
            "type": "heading",
            "children": content,
            "level": 2,
        }


class H3(Block, Heading):
    text: Union[str, list, Link] = Attr()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @property
    def spec(self) -> dict:
        if isinstance(self.text, list):
            content = [
                t.spec if not isinstance(t, str) else {"text": t} for t in self.text
            ]
        else:
            content = [{"text": self.text}]
        return {
            "type": "heading",
            "children": content,
            "level": 3,
        }


class BlockQuote(Block):
    text: str = Attr()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @classmethod
    def from_json(cls, spec: dict) -> "BlockQuote":
        text = spec["children"][0]["text"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {"type": "block-quote", "children": [{"text": self.text}]}


class CalloutBlock(Block):
    text: Union[str, list] = Attr()

    def __init__(self, text=" ", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    def __post_init__(self) -> None:
        if isinstance(self.text, str):
            self.text = self.text.split("\n")

    @classmethod
    def from_json(cls, spec: dict) -> "CalloutBlock":
        text = [child["children"][0]["text"] for child in spec["children"]]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {
            "type": "callout-block",
            "children": [
                {"type": "callout-line", "children": [{"text": text}]}
                for text in self.text
            ],
        }


class CodeBlock(Block):
    code: Union[str, list] = Attr()
    language: str = Attr()

    def __init__(self, code=" ", language=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = code
        self.language = coalesce(language, "python")

    def __post_init__(self) -> None:
        if isinstance(self.code, str):
            self.code = self.code.split("\n")

    @classmethod
    def from_json(cls, spec: dict) -> "CodeBlock":
        code = [child["children"][0]["text"] for child in spec["children"]]
        language = spec.get("language", "python")
        return cls(code, language)

    @property
    def spec(self) -> dict:
        language = self.language.lower()
        return {
            "type": "code-block",
            "children": [
                {
                    "type": "code-line",
                    "children": [{"text": text}],
                    "language": language,
                }
                for text in self.code
            ],
            "language": language,
        }


class MarkdownBlock(Block):
    text: Union[str, list] = Attr()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

    @classmethod
    def from_json(cls, spec: dict) -> "MarkdownBlock":
        text = spec["content"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {
            "type": "markdown-block",
            "children": [{"text": ""}],
            "content": self.text,
        }


class LaTeXBlock(Block):
    text: Union[str, list] = Attr()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text
        if isinstance(self.text, list):
            self.text = "\n".join(self.text)

    @classmethod
    def from_json(cls, spec: dict) -> "LaTeXBlock":
        text = spec["content"]
        return cls(text)

    @property
    def spec(self) -> dict:
        return {
            "type": "latex",
            "children": [{"text": ""}],
            "content": self.text,
            "block": True,
        }


class Gallery(Block):
    ids: list = Attr(validators=[TypeValidator(str, how="keys")])

    def __init__(self, ids, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = ids

    @classmethod
    def from_json(cls, spec: dict) -> "Gallery":
        ids = spec["ids"]
        return cls(ids)

    @classmethod
    def from_report_urls(cls, urls: LList[str]) -> "Gallery":
        from .report import Report

        ids = [Report._url_to_report_id(url) for url in urls]
        return cls(ids)

    @property
    def spec(self) -> dict:
        return {"type": "gallery", "children": [{"text": ""}], "ids": self.ids}


class Image(Block):
    url: str = Attr()
    caption: Optional[str] = Attr()

    def __init__(self, url, caption=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url
        self.caption = caption

    @classmethod
    def from_json(cls, spec: dict) -> "Image":
        url = spec["url"]
        caption = spec["children"][0]["text"] if spec.get("hasCaption") else None
        return cls(url, caption)

    @property
    def spec(self) -> dict:
        if self.caption:
            return {
                "type": "image",
                "children": [{"text": self.caption}],
                "url": self.url,
                "hasCaption": True,
            }
        else:
            return {"type": "image", "children": [{"text": ""}], "url": self.url}


class WeaveBlockSummaryTable(Block):
    """This is a hacky solution to support the most common way of getting Weave tables for now..."""

    entity: str = Attr()
    project: str = Attr()
    table_name: str = Attr()

    def __init__(self, entity, project, table_name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entity = entity
        self.project = project
        self.table_name = table_name

    @classmethod
    def from_json(cls, spec: dict) -> "WeaveBlockSummaryTable":
        entity = spec["config"]["panelConfig"]["exp"]["fromOp"]["inputs"]["obj"][
            "fromOp"
        ]["inputs"]["run"]["fromOp"]["inputs"]["project"]["fromOp"]["inputs"][
            "entityName"
        ][
            "val"
        ]
        project = spec["config"]["panelConfig"]["exp"]["fromOp"]["inputs"]["obj"][
            "fromOp"
        ]["inputs"]["run"]["fromOp"]["inputs"]["project"]["fromOp"]["inputs"][
            "projectName"
        ][
            "val"
        ]
        table_name = spec["config"]["panelConfig"]["exp"]["fromOp"]["inputs"]["key"][
            "val"
        ]
        return cls(entity, project, table_name)

    @property
    def spec(self) -> dict:
        return {
            "type": "weave-panel",
            "children": [{"text": ""}],
            "config": {
                "panelConfig": {
                    "exp": {
                        "nodeType": "output",
                        "type": {
                            "type": "tagged",
                            "tag": {
                                "type": "tagged",
                                "tag": {
                                    "type": "typedDict",
                                    "propertyTypes": {
                                        "entityName": "string",
                                        "projectName": "string",
                                    },
                                },
                                "value": {
                                    "type": "typedDict",
                                    "propertyTypes": {"project": "project"},
                                },
                            },
                            "value": {
                                "type": "list",
                                "objectType": {
                                    "type": "tagged",
                                    "tag": {
                                        "type": "typedDict",
                                        "propertyTypes": {"run": "run"},
                                    },
                                    "value": {
                                        "type": "union",
                                        "members": [
                                            {
                                                "type": "file",
                                                "extension": "json",
                                                "wbObjectType": {
                                                    "type": "table",
                                                    "columnTypes": {},
                                                },
                                            },
                                            "none",
                                        ],
                                    },
                                },
                            },
                        },
                        "fromOp": {
                            "name": "pick",
                            "inputs": {
                                "obj": {
                                    "nodeType": "output",
                                    "type": {
                                        "type": "tagged",
                                        "tag": {
                                            "type": "tagged",
                                            "tag": {
                                                "type": "typedDict",
                                                "propertyTypes": {
                                                    "entityName": "string",
                                                    "projectName": "string",
                                                },
                                            },
                                            "value": {
                                                "type": "typedDict",
                                                "propertyTypes": {"project": "project"},
                                            },
                                        },
                                        "value": {
                                            "type": "list",
                                            "objectType": {
                                                "type": "tagged",
                                                "tag": {
                                                    "type": "typedDict",
                                                    "propertyTypes": {"run": "run"},
                                                },
                                                "value": {
                                                    "type": "union",
                                                    "members": [
                                                        {
                                                            "type": "typedDict",
                                                            "propertyTypes": {
                                                                "_wandb": {
                                                                    "type": "typedDict",
                                                                    "propertyTypes": {
                                                                        "runtime": "number"
                                                                    },
                                                                }
                                                            },
                                                        },
                                                        {
                                                            "type": "typedDict",
                                                            "propertyTypes": {
                                                                "_step": "number",
                                                                "table": {
                                                                    "type": "file",
                                                                    "extension": "json",
                                                                    "wbObjectType": {
                                                                        "type": "table",
                                                                        "columnTypes": {},
                                                                    },
                                                                },
                                                                "_wandb": {
                                                                    "type": "typedDict",
                                                                    "propertyTypes": {
                                                                        "runtime": "number"
                                                                    },
                                                                },
                                                                "_runtime": "number",
                                                                "_timestamp": "number",
                                                            },
                                                        },
                                                        {
                                                            "type": "typedDict",
                                                            "propertyTypes": {},
                                                        },
                                                    ],
                                                },
                                            },
                                        },
                                    },
                                    "fromOp": {
                                        "name": "run-summary",
                                        "inputs": {
                                            "run": {
                                                "nodeType": "output",
                                                "type": {
                                                    "type": "tagged",
                                                    "tag": {
                                                        "type": "tagged",
                                                        "tag": {
                                                            "type": "typedDict",
                                                            "propertyTypes": {
                                                                "entityName": "string",
                                                                "projectName": "string",
                                                            },
                                                        },
                                                        "value": {
                                                            "type": "typedDict",
                                                            "propertyTypes": {
                                                                "project": "project"
                                                            },
                                                        },
                                                    },
                                                    "value": {
                                                        "type": "list",
                                                        "objectType": "run",
                                                    },
                                                },
                                                "fromOp": {
                                                    "name": "project-runs",
                                                    "inputs": {
                                                        "project": {
                                                            "nodeType": "output",
                                                            "type": {
                                                                "type": "tagged",
                                                                "tag": {
                                                                    "type": "typedDict",
                                                                    "propertyTypes": {
                                                                        "entityName": "string",
                                                                        "projectName": "string",
                                                                    },
                                                                },
                                                                "value": "project",
                                                            },
                                                            "fromOp": {
                                                                "name": "root-project",
                                                                "inputs": {
                                                                    "entityName": {
                                                                        "nodeType": "const",
                                                                        "type": "string",
                                                                        "val": self.entity,
                                                                    },
                                                                    "projectName": {
                                                                        "nodeType": "const",
                                                                        "type": "string",
                                                                        "val": self.project,
                                                                    },
                                                                },
                                                            },
                                                        }
                                                    },
                                                },
                                            }
                                        },
                                    },
                                },
                                "key": {
                                    "nodeType": "const",
                                    "type": "string",
                                    "val": self.table_name,
                                },
                            },
                        },
                        "__userInput": True,
                    }
                }
            },
        }


class WeaveBlockArtifact(Block):
    """This is a hacky solution to support the most common way of getting Weave artifacts for now..."""

    entity: str = Attr()
    project: str = Attr()
    artifact: str = Attr()
    tab: str = Attr(
        validators=[OneOf(["overview", "metadata", "usage", "files", "lineage"])]
    )

    def __init__(self, entity, project, artifact, tab="overview", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entity = entity
        self.project = project
        self.artifact = artifact
        self.tab = tab

    @classmethod
    def from_json(cls, spec: dict) -> "WeaveBlockSummaryTable":
        inputs = weave_inputs(spec)
        entity = inputs["project"]["fromOp"]["inputs"]["entityName"]["val"]
        project = inputs["project"]["fromOp"]["inputs"]["projectName"]["val"]
        artifact = inputs["artifactName"]["val"]
        tab = spec["config"]["panelConfig"]["panelConfig"]["tabConfigs"]["overview"][
            "selectedTab"
        ]
        return cls(entity, project, artifact, tab)

    @property
    def spec(self) -> dict:
        return {
            "type": "weave-panel",
            "children": [{"text": ""}],
            "config": {
                "panelConfig": {
                    "exp": {
                        "nodeType": "output",
                        "type": {
                            "type": "tagged",
                            "tag": {
                                "type": "tagged",
                                "tag": {
                                    "type": "typedDict",
                                    "propertyTypes": {
                                        "entityName": "string",
                                        "projectName": "string",
                                    },
                                },
                                "value": {
                                    "type": "typedDict",
                                    "propertyTypes": {
                                        "project": "project",
                                        "artifactName": "string",
                                    },
                                },
                            },
                            "value": "artifact",
                        },
                        "fromOp": {
                            "name": "project-artifact",
                            "inputs": {
                                "project": {
                                    "nodeType": "output",
                                    "type": {
                                        "type": "tagged",
                                        "tag": {
                                            "type": "typedDict",
                                            "propertyTypes": {
                                                "entityName": "string",
                                                "projectName": "string",
                                            },
                                        },
                                        "value": "project",
                                    },
                                    "fromOp": {
                                        "name": "root-project",
                                        "inputs": {
                                            "entityName": {
                                                "nodeType": "const",
                                                "type": "string",
                                                "val": self.entity,
                                            },
                                            "projectName": {
                                                "nodeType": "const",
                                                "type": "string",
                                                "val": self.project,
                                            },
                                        },
                                    },
                                },
                                "artifactName": {
                                    "nodeType": "const",
                                    "type": "string",
                                    "val": self.artifact,
                                },
                            },
                        },
                        "__userInput": True,
                    },
                    "panelInputType": {
                        "type": "tagged",
                        "tag": {
                            "type": "tagged",
                            "tag": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "entityName": "string",
                                    "projectName": "string",
                                },
                            },
                            "value": {
                                "type": "typedDict",
                                "propertyTypes": {
                                    "project": "project",
                                    "artifactName": "string",
                                },
                            },
                        },
                        "value": "artifact",
                    },
                    "panelConfig": {
                        "tabConfigs": {"overview": {"selectedTab": self.tab}}
                    },
                }
            },
        }


class WeaveBlockArtifactVersionedFile(Block):
    """This is a hacky solution to support the most common way of getting Weave artifact verions for now..."""

    entity: str = Attr()
    project: str = Attr()
    artifact: str = Attr()
    version: str = Attr()
    file: str = Attr()

    def __init__(self, entity, project, artifact, version, file, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entity = entity
        self.project = project
        self.artifact = artifact
        self.version = version
        self.file = file

    @classmethod
    def from_json(cls, spec: dict) -> "WeaveBlockSummaryTable":
        inputs = weave_inputs(spec)
        entity = inputs["artifactVersion"]["fromOp"]["inputs"]["project"]["fromOp"][
            "inputs"
        ]["entityName"]["val"]
        project = inputs["artifactVersion"]["fromOp"]["inputs"]["project"]["fromOp"][
            "inputs"
        ]["projectName"]["val"]
        artifact = inputs["artifactVersion"]["fromOp"]["inputs"]["artifactName"]["val"]
        version = inputs["artifactVersion"]["fromOp"]["inputs"]["artifactVersionAlias"][
            "val"
        ]
        file = inputs["path"]["val"]
        return cls(entity, project, artifact, version, file)

    @property
    def spec(self) -> dict:
        return {
            "type": "weave-panel",
            "children": [{"text": ""}],
            "config": {
                "panelConfig": {
                    "exp": {
                        "nodeType": "output",
                        "type": {
                            "type": "tagged",
                            "tag": {
                                "type": "tagged",
                                "tag": {
                                    "type": "typedDict",
                                    "propertyTypes": {
                                        "entityName": "string",
                                        "projectName": "string",
                                    },
                                },
                                "value": {
                                    "type": "typedDict",
                                    "propertyTypes": {
                                        "project": "project",
                                        "artifactName": "string",
                                        "artifactVersionAlias": "string",
                                    },
                                },
                            },
                            "value": {
                                "type": "file",
                                "extension": "json",
                                "wbObjectType": {"type": "table", "columnTypes": {}},
                            },
                        },
                        "fromOp": {
                            "name": "artifactVersion-file",
                            "inputs": {
                                "artifactVersion": {
                                    "nodeType": "output",
                                    "type": {
                                        "type": "tagged",
                                        "tag": {
                                            "type": "tagged",
                                            "tag": {
                                                "type": "typedDict",
                                                "propertyTypes": {
                                                    "entityName": "string",
                                                    "projectName": "string",
                                                },
                                            },
                                            "value": {
                                                "type": "typedDict",
                                                "propertyTypes": {
                                                    "project": "project",
                                                    "artifactName": "string",
                                                    "artifactVersionAlias": "string",
                                                },
                                            },
                                        },
                                        "value": "artifactVersion",
                                    },
                                    "fromOp": {
                                        "name": "project-artifactVersion",
                                        "inputs": {
                                            "project": {
                                                "nodeType": "output",
                                                "type": {
                                                    "type": "tagged",
                                                    "tag": {
                                                        "type": "typedDict",
                                                        "propertyTypes": {
                                                            "entityName": "string",
                                                            "projectName": "string",
                                                        },
                                                    },
                                                    "value": "project",
                                                },
                                                "fromOp": {
                                                    "name": "root-project",
                                                    "inputs": {
                                                        "entityName": {
                                                            "nodeType": "const",
                                                            "type": "string",
                                                            "val": self.entity,
                                                        },
                                                        "projectName": {
                                                            "nodeType": "const",
                                                            "type": "string",
                                                            "val": self.project,
                                                        },
                                                    },
                                                },
                                            },
                                            "artifactName": {
                                                "nodeType": "const",
                                                "type": "string",
                                                "val": self.artifact,
                                            },
                                            "artifactVersionAlias": {
                                                "nodeType": "const",
                                                "type": "string",
                                                "val": self.version,
                                            },
                                        },
                                    },
                                },
                                "path": {
                                    "nodeType": "const",
                                    "type": "string",
                                    "val": self.file,
                                },
                            },
                        },
                        "__userInput": True,
                    }
                }
            },
        }


class HorizontalRule(Block):
    @classmethod
    def from_json(cls, spec: dict) -> "HorizontalRule":
        return cls()

    @property
    def spec(self):
        return {"type": "horizontal-rule", "children": [{"text": ""}]}


class TableOfContents(Block):
    @classmethod
    def from_json(cls, spec: dict) -> "TableOfContents":
        return cls()

    @property
    def spec(self) -> dict:
        return {"type": "table-of-contents", "children": [{"text": ""}]}


class SoundCloud(Block):
    url: str = Attr()

    def __init__(self, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url

    @classmethod
    def from_json(cls, spec: dict) -> "SoundCloud":
        quoted_url = spec["html"].split("url=")[-1].split("&show_artwork")[0]
        url = urllib.parse.unquote(quoted_url)
        return cls(url)

    @property
    def spec(self) -> dict:
        quoted_url = urllib.parse.quote(self.url)
        return {
            "type": "soundcloud",
            "html": f'<iframe width="100%" height="400" scrolling="no" frameborder="no" src="https://w.soundcloud.com/player/?visual=true&url={quoted_url}&show_artwork=true"></iframe>',
            "children": [{"text": ""}],
        }


class Twitter(Block):
    embed_html: str = Attr()

    def __init__(self, embed_html, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.embed_html = embed_html
        if self.embed_html:
            pattern = r" <script[\s\S]+?/script>"
            self.embed_html = re.sub(pattern, "\n", self.embed_html)

    @classmethod
    def from_json(cls, spec: dict) -> "Twitter":
        embed_html = spec["html"]
        return cls(embed_html)

    @property
    def spec(self) -> dict:
        return {"type": "twitter", "html": self.embed_html, "children": [{"text": ""}]}


class Spotify(Block):
    spotify_id: str = Attr()

    def __init__(self, spotify_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spotify_id = spotify_id

    @classmethod
    def from_json(cls, spec: dict) -> "Spotify":
        return cls(spec["spotifyID"])

    @classmethod
    def from_url(cls, url: str) -> "Spotify":
        spotify_id = url.split("/")[-1].split("?")[0]
        return cls(spotify_id)

    @property
    def spec(self) -> dict:
        return {
            "type": "spotify",
            "spotifyType": "track",
            "spotifyID": self.spotify_id,
            "children": [{"text": ""}],
        }


class Video(Block):
    url: str = Attr()

    def __init__(self, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url

    @classmethod
    def from_json(cls, spec: dict) -> "Video":
        return cls(spec["url"])

    @property
    def spec(self) -> dict:
        return {
            "type": "video",
            "url": self.url,
            "children": [{"text": ""}],
        }


class P(Block):
    text: Union[str, InlineLaTeX, InlineCode, Link, list] = Attr()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @classmethod
    def from_json(cls, spec):
        if isinstance(spec["children"], str):
            text = spec["children"]
        else:
            text = []
            for elem in spec["children"]:
                if elem.get("type") == "latex":
                    text.append(InlineLaTeX(elem["content"]))
                elif elem.get("type") == "link":
                    text.append(Link(elem["children"][0]["text"], elem["url"]))
                elif elem.get("inlineCode"):
                    text.append(InlineCode(elem["text"]))
                elif elem.get("text"):
                    text.append(elem["text"])

        if not isinstance(text, list):
            text = [text]
        return cls(text)

    @property
    def spec(self) -> dict:
        if isinstance(self.text, list):
            content = [
                t.spec if not isinstance(t, str) else {"text": t} for t in self.text
            ]
        else:
            content = [{"text": self.text}]

        return {"type": "paragraph", "children": content}


class WeaveBlock(Block):
    def __init__(self, spec, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spec = spec

    @classmethod
    def from_json(cls, spec):
        obj = cls(spec=spec)
        obj._spec = spec
        return obj

    @property
    def spec(self):
        return self._spec


block_mapping = {
    "block-quote": BlockQuote,
    "callout-block": CalloutBlock,
    "code-block": CodeBlock,
    "gallery": Gallery,
    "heading": Heading,
    "horizontal-rule": HorizontalRule,
    "image": Image,
    "latex": LaTeXBlock,
    "list": List,
    "markdown-block": MarkdownBlock,
    "panel-grid": PanelGrid,
    "paragraph": P,
    "table-of-contents": TableOfContents,
    "weave-panel": WeaveBlock,
    "video": Video,
    "spotify": Spotify,
    "twitter": Twitter,
    "soundcloud": SoundCloud,
}

weave_blocks = [
    WeaveBlockSummaryTable,
    WeaveBlockArtifactVersionedFile,
    WeaveBlockArtifact,
    WeaveBlock,
]

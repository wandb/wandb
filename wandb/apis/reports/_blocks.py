import inspect
import re
import urllib
from typing import List as LList
from typing import Union

from ... import __version__ as wandb_ver
from ... import termlog, termwarn
from ._panels import ParallelCoordinatesPlot, ScatterPlot, UnknownPanel, panel_mapping
from .runset import Runset
from .util import (
    Attr,
    Base,
    Block,
    Panel,
    TypeValidator,
    coalesce,
    fix_collisions,
    nested_get,
    nested_set,
)


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
    custom_run_colors: dict = Attr(json_path="spec.metadata.customRunColors")

    def __init__(
        self, runsets=None, panels=None, custom_run_colors=None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._spec = self._default_panel_grid_spec()
        self.runsets = coalesce(runsets, self._default_runsets())
        self.panels = coalesce(panels, self._default_panels())
        self.custom_run_colors = coalesce(custom_run_colors, {})

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
        if "ref" in id_colors:
            del id_colors["ref"]
        return {self._run_id_to_name(id): c for id, c in id_colors.items()}

    @custom_run_colors.setter
    def custom_run_colors(self, new_custom_run_colors):
        json_path = self._get_path("custom_run_colors")
        new_custom_run_colors = {
            self._run_name_to_id(name): c for name, c in new_custom_run_colors.items()
        }
        nested_set(self, json_path, new_custom_run_colors)

    def _run_id_to_name(self, id):
        for rs in self.runsets:
            for run in rs.runs:
                if run.id == id:
                    return run.name

    def _run_name_to_id(self, name):
        for rs in self.runsets:
            for run in rs.runs:
                if run.name == name:
                    return run.id

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

    def _get_specific_keys_for_certain_plots(self, panels, setting=False):
        """
        Helper function to map names for certain plots
        """
        gen = self.runsets[0].pm_query_generator
        for p in panels:
            if isinstance(p, ParallelCoordinatesPlot):
                termlog(
                    "INFO: PCColumn metrics will be have special naming applied -- no change from you is required."
                )
                transform = gen.pc_front_to_back if setting else gen.pc_back_to_front
                if p.columns:
                    for col in p.columns:
                        col.metric = transform(col.metric)
            if isinstance(p, ScatterPlot):
                termlog(
                    "INFO: Scatter metrics will be have special naming applied -- no change from you is required."
                )
                transform = gen.pc_front_to_back if setting else gen.pc_front_to_back
                if p.x:
                    p.x = transform(p.x)
                if p.y:
                    p.y = transform(p.y)
                if p.z:
                    p.z = transform(p.z)
        return panels


class List(Base):
    @classmethod
    def from_json(cls, spec: dict) -> "Union[CheckedList, OrderedList, UnorderedList]":
        items = [
            item["children"][0]["children"][0]["text"] for item in spec["children"]
        ]
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

    def __init__(self, items, checked, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items
        self.checked = checked

    @property
    def spec(self) -> dict:
        return {
            "type": "list",
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                    "checked": check,
                }
                for item, check in zip(self.items, self.checked)
            ],
        }


class OrderedList(Block, List):
    items: list = Attr()

    def __init__(self, items, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items

    @property
    def spec(self) -> dict:
        return {
            "type": "list",
            "ordered": True,
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                    "ordered": True,
                }
                for item in self.items
            ],
        }


class UnorderedList(Block, List):
    items: list = Attr()

    def __init__(self, items, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items

    @property
    def spec(self) -> dict:
        return {
            "type": "list",
            "children": [
                {
                    "type": "list-item",
                    "children": [{"type": "paragraph", "children": [{"text": item}]}],
                }
                for item in self.items
            ],
        }


class Heading(Base):
    @classmethod
    def from_json(cls, spec: dict) -> "Union[H1,H2,H3]":
        level = spec["level"]
        text = spec["children"][0]["text"]

        level_mapping = {1: H1, 2: H2, 3: H3}

        if level not in level_mapping:
            raise ValueError(f"`level` must be one of {list(level_mapping.keys())}")

        return level_mapping[level](text)


class H1(Block, Heading):
    text: str = Attr()

    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 1,
        }


class H2(Block, Heading):
    text: str = Attr()

    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 2,
        }


class H3(Block, Heading):
    text: str = Attr()

    def __init__(self, text, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = text

    @property
    def spec(self) -> dict:
        return {
            "type": "heading",
            "children": [{"text": self.text}],
            "level": 3,
        }


class BlockQuote(Block):
    text: str = Attr()

    def __init__(self, text, *args, **kwargs):
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

    def __init__(self, text, *args, **kwargs):
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

    def __init__(self, code, language=None, *args, **kwargs):
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

    def __init__(self, text, *args, **kwargs):
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

    def __init__(self, text, *args, **kwargs):
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
    ids: list = Attr()

    def __init__(self, ids, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = ids

    @classmethod
    def from_json(cls, spec: dict) -> "Gallery":
        ids = spec["ids"]
        return cls(ids)

    @classmethod
    def from_report_urls(cls, urls: LList[str]) -> "Gallery":
        ids = [url.split("--")[-1] for url in urls]
        return cls(ids)

    @property
    def spec(self) -> dict:
        return {"type": "gallery", "children": [{"text": ""}], "ids": self.ids}


class Image(Block):
    url: str = Attr()
    caption: str = Attr()

    def __init__(self, url, caption, *args, **kwargs):
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


# class WeaveBlock(Block):
#     def __init__(self, spec, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.spec = spec

#     spec: dict = Attr()

#     @classmethod
#     def from_json(cls, spec: dict) -> "WeaveBlock":
#         return cls(spec)


class WeaveTableBlock(Block):
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
    def from_json(cls, spec: dict) -> "WeaveTableBlock":
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


class InlineLaTeX(Base):
    latex: str = Attr()

    def __init__(self, latex, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.latex = latex

    @property
    def spec(self) -> dict:
        return {"type": "latex", "children": [{"text": ""}], "content": self.latex}


class InlineCode(Base):
    code: str = Attr()

    def __init__(self, code, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = code

    @property
    def spec(self) -> dict:
        return {"text": self.code, "inlineCode": True}


class P(Block):
    text: Union[str, InlineLaTeX, InlineCode, list] = Attr()

    def __init__(self, text, *args, **kwargs):
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
                elif elem.get("inlineCode"):
                    text.append(InlineCode(elem["text"]))
                else:
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
    "weave-panel": WeaveTableBlock,
    "video": Video,
    "spotify": Spotify,
    "twitter": Twitter,
    "soundcloud": SoundCloud,
}

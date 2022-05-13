import json
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.apis.reports as WB

from tests.conftest import DUMMY_API_KEY
from tests.utils.mock_server import mock_server


@pytest.fixture
def report():
    MOCK_ATTRS = {
        "id": "VmlldzoxOTk3OTcx",
        "type": "runs",
        "name": "75guz82nsr",
        "displayName": "Project about cool stuff",
        "description": "Look at how descriptive this is!",
        "project": {
            "id": "UHJvamVjdDp2MTpyZXBvcnQtZWRpdGluZzptZWdhdHJ1b25n",
            "name": "report-editing",
            "entityName": "megatruong",
        },
        "createdAt": "2022-05-12T22:17:56",
        "updatedAt": "2022-05-12T22:17:56",
        "spec": json.dumps(
            {
                "version": 5,
                "panelSettings": {},
                "blocks": [
                    {
                        "type": "heading",
                        "children": [{"text": "H1 Heading"}],
                        "level": 1,
                    },
                    {"type": "paragraph", "children": [{"text": "Some text"}]},
                    {
                        "type": "panel-grid",
                        "children": [{"text": ""}],
                        "metadata": {
                            "openViz": True,
                            "panels": {
                                "views": {
                                    "0": {
                                        "name": "Panels",
                                        "defaults": [],
                                        "config": [],
                                    }
                                },
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
                            "runSets": [
                                {
                                    "filters": {
                                        "op": "OR",
                                        "filters": [
                                            {
                                                "op": "AND",
                                                "filters": [
                                                    {
                                                        "key": {
                                                            "section": "run",
                                                            "name": "state",
                                                        },
                                                        "op": "=",
                                                        "value": "crashed",
                                                    },
                                                    {
                                                        "key": {
                                                            "section": "summary",
                                                            "name": "team",
                                                        },
                                                        "op": "=",
                                                        "value": "amazing team",
                                                    },
                                                ],
                                            }
                                        ],
                                    },
                                    "runFeed": {
                                        "version": 2,
                                        "columnVisible": {"run:name": False},
                                        "columnPinned": {},
                                        "columnWidths": {},
                                        "columnOrder": [],
                                        "pageSize": 10,
                                        "onlyShowSelected": False,
                                    },
                                    "sort": {
                                        "keys": [
                                            {
                                                "key": {
                                                    "section": "run",
                                                    "name": "createdAt",
                                                },
                                                "ascending": True,
                                            },
                                            {
                                                "key": {
                                                    "section": "run",
                                                    "name": "duration",
                                                },
                                                "ascending": False,
                                            },
                                        ]
                                    },
                                    "enabled": True,
                                    "name": "The report-editing run set",
                                    "search": {"query": ""},
                                    "grouping": [
                                        {"section": "run", "name": "username"},
                                        {"section": "summary", "name": "something"},
                                    ],
                                    "selections": {"root": 1, "bounds": [], "tree": []},
                                    "expandedRowAddresses": [],
                                    "project": {
                                        "id": "UHJvamVjdDp2MTpyZXBvcnQtZWRpdGluZzptZWdhdHJ1b25n",
                                        "name": "report-editing",
                                        "entityName": "megatruong",
                                    },
                                    "id": "abcdef123",
                                },
                                {
                                    "filters": {
                                        "op": "OR",
                                        "filters": [{"op": "AND", "filters": []}],
                                    },
                                    "runFeed": {
                                        "version": 2,
                                        "columnVisible": {"run:name": False},
                                        "columnPinned": {},
                                        "columnWidths": {},
                                        "columnOrder": [],
                                        "pageSize": 10,
                                        "onlyShowSelected": False,
                                    },
                                    "sort": {
                                        "keys": [
                                            {
                                                "key": {
                                                    "section": "run",
                                                    "name": "createdAt",
                                                },
                                                "ascending": False,
                                            }
                                        ]
                                    },
                                    "enabled": True,
                                    "name": "Financial data runs",
                                    "search": {"query": ""},
                                    "grouping": [],
                                    "selections": {"root": 1, "bounds": [], "tree": []},
                                    "expandedRowAddresses": [],
                                    "project": {
                                        "id": "UHJvamVjdDp2MTpyZXBvcnQtZWRpdGluZzptZWdhdHJ1b25n",
                                        "name": "finance-examples",
                                        "entityName": "megatruong",
                                    },
                                    "id": "ghijklm456",
                                },
                            ],
                            "openRunSet": 0,
                            "name": "unused-name",
                        },
                    },
                ],
                "width": "readable",
                "authors": [],
                "discussionThreads": [],
                "ref": {},
            }
        ),
        "previewUrl": None,
        "user": {
            "name": "Andrew Truong",
            "username": "megatruong",
            "userInfo": {
                "bio": "model-registry \ninstant replay\nweeave-plot\nweeave-report\nniight\n",
                "company": "Weights and Biases",
                "location": "San Francisco",
                "githubUrl": "",
                "twitterUrl": "",
                "websiteUrl": "wandb.com",
            },
        },
    }
    yield wandb.apis.public.BetaReport(client=MagicMock(), attrs=MOCK_ATTRS)


@pytest.fixture
def panel_grid(report):
    yield report.panel_grids[0]


@pytest.fixture
def run_set(panel_grid):
    yield panel_grid.run_sets[0]


@pytest.fixture
def run_set_modified(run_set):
    assert not run_set.modified
    yield
    assert run_set.modified


@pytest.fixture
def panel_grid_modified(panel_grid):
    assert not panel_grid.modified
    yield
    assert panel_grid.modified


@pytest.fixture
def report_modified(report):
    assert not report.modified
    yield
    assert report.modified


@pytest.fixture
def require_v5_reports(report):
    assert report.spec.get("version", -1) == 5
    yield


# @pytest.fixture(autouse=True)
# def require_report_editing():
#     # if requirement.param:
#     wandb.require("report-editing")
#     os.environ["WANDB_REQUIRE_REPORT_EDITING"] = "True"
#     yield
#     # else:
#     #     with pytest.raises(Exception):
#     #         yield


@pytest.fixture
def api():
    wandb.login(key=DUMMY_API_KEY)
    yield wandb.Api()


@pytest.mark.usefixtures("require_v5_reports", "mock_server")
class TestPublicAPIReportCreation:
    @pytest.mark.parametrize(
        "project,entity,result",
        [
            (None, None, ValueError),
            (None, "entity", ValueError),
            ("project", None, "valid"),
            ("project", "entity", "valid"),
        ],
    )
    def test_create_report(self, api, project, entity, result):
        if result == "valid":
            report = api.create_report(entity, project)
            assert isinstance(report, wandb.apis.public.BetaReport)
        else:
            with pytest.raises(result):
                report = api.create_report(entity, project)

    @pytest.mark.parametrize(
        "path,result",
        [
            ("entity/project/reports/name--VmlldzoxOTcxMzI2", "valid"),
            ("entity/project/name--VmlldzoxOTcxMzI2", "valid"),
            ("entity/name--VmlldzoxOTcxMzI2", ValueError),
            ("name--VmlldzoxOTcxMzI2", ValueError),
            ("VmlldzoxOTcxMzI2", ValueError),
        ],
    )
    def test_get_report(self, api, path, result):
        if result == "valid":
            report = api.report(path)
            assert isinstance(report, wandb.apis.public.BetaReport)
        else:
            with pytest.raises(result):
                report = api.report(path)

    def test_report_saving(self, report):
        # need to mock out the different cases
        result = report.save()
        assert isinstance(result, wandb.apis.public.BetaReport)


@pytest.mark.usefixtures("require_v5_reports")
class TestReportGetters:
    @pytest.mark.parametrize(
        "property,path",
        [
            ("updated_at", ["updatedAt"]),
            ("title", ["displayName"]),
            ("description", ["description"]),
            ("width", ["spec", "width"]),
        ],
    )
    def test_basic_property_getters(self, report, property, path):
        def value_getter(d, keys):
            if len(keys) == 0:
                return d
            return value_getter(d[keys[0]], keys[1:])

        assert getattr(report, property) == value_getter(report._attrs, path)

    def test_get_blocks(self, report):
        assert report.spec["blocks"] == [block.to_json() for block in report.blocks]

    def test_get_panel_grids(self, report):
        assert all([isinstance(panel, WB.PanelGrid) for panel in report.panel_grids])

    def test_get_run_sets(self, report):
        all([isinstance(rs, WB.RunSet) for pg in report.run_sets for rs in pg])


@pytest.mark.usefixtures("require_v5_reports", "report_modified")
class TestReportSetters:
    @pytest.mark.parametrize(
        "blocks,blockspec",
        [
            (
                [
                    WB.TableOfContents(),
                    WB.H1(text="An example of programmatic report editing"),
                    WB.P("Look at what we can do!"),
                ],
                [
                    {"type": "table-of-contents", "children": [{"text": ""}]},
                    {
                        "type": "heading",
                        "children": [
                            {"text": "An example of programmatic report editing"}
                        ],
                        "level": 1,
                    },
                    {
                        "type": "paragraph",
                        "children": [{"text": "Look at what we can do!"}],
                    },
                ],
            ),
            (
                [
                    WB.H1("Heading1"),
                    WB.H2("Heading2"),
                    WB.H3("Heading3"),
                    WB.P("Paragraph"),
                    WB.HorizontalRule(),
                    WB.Image(
                        "https://i.kym-cdn.com/entries/icons/original/000/006/428/637738.jpg"
                    ),
                ],
                [
                    {"type": "heading", "children": [{"text": "Heading1"}], "level": 1},
                    {"type": "heading", "children": [{"text": "Heading2"}], "level": 2},
                    {"type": "heading", "children": [{"text": "Heading3"}], "level": 3},
                    {"type": "paragraph", "children": [{"text": "Paragraph"}]},
                    {"type": "horizontal-rule", "children": [{"text": ""}]},
                    {
                        "type": "image",
                        "children": [{"text": ""}],
                        "url": "https://i.kym-cdn.com/entries/icons/original/000/006/428/637738.jpg",
                    },
                ],
            ),
            (
                [
                    WB.LaTeXBlock("e=mc^2"),
                    WB.OrderedList(["one", "two", "three"]),
                    WB.UnorderedList(["alpha", "beta", "gamma"]),
                    WB.CheckedList(["done", "not done"], checked=[True, False]),
                    WB.BlockQuote("Look at this amazing blockquote"),
                    WB.CalloutBlock("This is also an amazing callout"),
                    WB.CodeBlock("for x in range(10): pass"),
                ],
                [
                    {
                        "type": "latex",
                        "children": [{"text": ""}],
                        "content": "e=mc^2",
                        "block": True,
                    },
                    {
                        "type": "list",
                        "ordered": True,
                        "children": [
                            {
                                "type": "list-item",
                                "children": [
                                    {"type": "paragraph", "children": [{"text": "one"}]}
                                ],
                                "ordered": True,
                            },
                            {
                                "type": "list-item",
                                "children": [
                                    {"type": "paragraph", "children": [{"text": "two"}]}
                                ],
                                "ordered": True,
                            },
                            {
                                "type": "list-item",
                                "children": [
                                    {
                                        "type": "paragraph",
                                        "children": [{"text": "three"}],
                                    }
                                ],
                                "ordered": True,
                            },
                        ],
                    },
                    {
                        "type": "list",
                        "children": [
                            {
                                "type": "list-item",
                                "children": [
                                    {
                                        "type": "paragraph",
                                        "children": [{"text": "alpha"}],
                                    }
                                ],
                            },
                            {
                                "type": "list-item",
                                "children": [
                                    {
                                        "type": "paragraph",
                                        "children": [{"text": "beta"}],
                                    }
                                ],
                            },
                            {
                                "type": "list-item",
                                "children": [
                                    {
                                        "type": "paragraph",
                                        "children": [{"text": "gamma"}],
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "type": "list",
                        "children": [
                            {
                                "type": "list-item",
                                "children": [
                                    {
                                        "type": "paragraph",
                                        "children": [{"text": "done"}],
                                    }
                                ],
                                "checked": True,
                            },
                            {
                                "type": "list-item",
                                "children": [
                                    {
                                        "type": "paragraph",
                                        "children": [{"text": "not done"}],
                                    }
                                ],
                                "checked": False,
                            },
                        ],
                    },
                    {
                        "type": "block-quote",
                        "children": [{"text": "Look at this amazing blockquote"}],
                    },
                    {
                        "type": "callout-block",
                        "children": [
                            {
                                "type": "callout-line",
                                "children": [
                                    {"text": "This is also an amazing callout"}
                                ],
                            }
                        ],
                    },
                    {
                        "type": "code-block",
                        "children": [
                            {
                                "type": "code-line",
                                "children": [{"text": "for x in range(10): pass"}],
                                "language": "python",
                            }
                        ],
                        "language": "python",
                    },
                ],
            ),
            (
                [
                    WB.Gallery(["url1", "url2", "url3"]),
                    WB.LaTeXInline("before", "e=mc^2", "after"),
                    WB.MarkdownBlock("This is **MARKDOWN!**"),
                ],
                [
                    {
                        "type": "gallery",
                        "children": [{"text": ""}],
                        "ids": ["url1", "url2", "url3"],
                    },
                    {
                        "type": "paragraph",
                        "children": [
                            {"text": "before"},
                            {
                                "type": "latex",
                                "children": [{"text": ""}],
                                "content": "e=mc^2",
                            },
                            {"text": "after"},
                        ],
                    },
                    {
                        "type": "markdown-block",
                        "children": [{"text": ""}],
                        "content": "This is **MARKDOWN!**",
                    },
                ],
            ),
        ],
    )
    def test_set_blocks(self, report, blocks, blockspec):
        report.blocks = blocks
        assert report.spec["blocks"] == blockspec

    def test_set_blocks_with_panel_grid(self, report):
        report.blocks = [WB.PanelGrid(report)]
        assert report.spec["blocks"] == [
            {
                "type": "panel-grid",
                "children": [{"text": ""}],
                "metadata": {
                    "openViz": True,
                    "panels": {
                        "views": {
                            "0": {"name": "Panels", "defaults": [], "config": []}
                        },
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
                    "runSets": [
                        {
                            "filters": {
                                "op": "OR",
                                "filters": [{"op": "AND", "filters": []}],
                            },
                            "runFeed": {
                                "version": 2,
                                "columnVisible": {"run:name": False},
                                "columnPinned": {},
                                "columnWidths": {},
                                "columnOrder": [],
                                "pageSize": 10,
                                "onlyShowSelected": False,
                            },
                            "sort": {
                                "keys": [
                                    {
                                        "key": {"section": "run", "name": "createdAt"},
                                        "ascending": False,
                                    }
                                ]
                            },
                            "enabled": True,
                            "name": "Run set",
                            "search": {"query": ""},
                            "grouping": [],
                            "selections": {"root": 1, "bounds": [], "tree": []},
                            "expandedRowAddresses": [],
                            "project": {
                                "id": "UHJvamVjdDp2MTpyZXBvcnQtZWRpdGluZzptZWdhdHJ1b25n",
                                "name": "report-editing",
                                "entityName": "megatruong",
                            },
                        }
                    ],
                    "openRunSet": 0,
                    "name": "unused-name",
                },
            }
        ]

    def test_set_blocks_with_weave(self, report):
        report.blocks = [
            WB.Weave(
                {
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
                                                        "val": "megatruong",
                                                    },
                                                    "projectName": {
                                                        "nodeType": "const",
                                                        "type": "string",
                                                        "val": "nvda-ngc",
                                                    },
                                                },
                                            },
                                        },
                                        "artifactName": {
                                            "nodeType": "const",
                                            "type": "string",
                                            "val": "my-artifact",
                                        },
                                    },
                                },
                            }
                        }
                    },
                }
            )
        ]
        assert report.spec["blocks"] == [
            {
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
                                                    "val": "megatruong",
                                                },
                                                "projectName": {
                                                    "nodeType": "const",
                                                    "type": "string",
                                                    "val": "nvda-ngc",
                                                },
                                            },
                                        },
                                    },
                                    "artifactName": {
                                        "nodeType": "const",
                                        "type": "string",
                                        "val": "my-artifact",
                                    },
                                },
                            },
                        }
                    }
                },
            }
        ]


class TestPanelGridGetters:
    @pytest.mark.parametrize(
        "property,path", [("open_run_set", ["metadata", "openRunSet"])],
    )
    def test_basic_property_getters(self, panel_grid, property, path):
        def value_getter(d, keys):
            if len(keys) == 0:
                return d
            return value_getter(d[keys[0]], keys[1:])

        assert getattr(panel_grid, property) == value_getter(panel_grid.spec, path)


@pytest.mark.usefixtures("panel_grid_modified", "report_modified")
class TestPanelGridSetters:
    @pytest.mark.parametrize(
        "case,result",
        [(0, "success"), (1, "success"), (2, ValueError), ("abc", TypeError)],
    )
    def test_set_open_run_set(self, panel_grid, case, result):
        if result == "success":
            panel_grid.open_run_set = case
            assert panel_grid.spec["metadata"]["openRunSet"] == case
        else:
            with pytest.raises(result):
                panel_grid.open_run_set = case

    def test_set_run_sets(self, panel_grid):
        run_set1 = WB.RunSet(panel_grid)
        run_set2 = WB.RunSet(panel_grid)
        new_run_sets = [run_set1, run_set2]

        panel_grid.run_sets = new_run_sets
        assert panel_grid.spec["metadata"]["runSets"] == [
            rs.spec for rs in new_run_sets
        ]


class TestRunSetGetters:
    @pytest.mark.parametrize(
        "property,path",
        [
            ("enabled", ["enabled"]),
            ("entity", ["project", "entityName"]),
            ("id", ["id"]),
            ("name", ["name"]),
            ("only_show_selected", ["runFeed", "onlyShowSelected"]),
            ("project", ["project", "name"]),
            ("query", ["search", "query"]),
            ("show_all_runs", ["selections", "root"]),
            ("visible", ["selections", "tree"]),
        ],
    )
    def test_basic_property_getters(self, run_set, property, path):
        def value_getter(d, keys):
            if len(keys) == 0:
                return d
            return value_getter(d[keys[0]], keys[1:])

        assert getattr(run_set, property) == value_getter(run_set.spec, path)

    def test_get_filters(self, run_set):
        mongo_filters = run_set.query_generator.mongo_to_filter(run_set.filters)
        assert mongo_filters == run_set.spec["filters"]

    def test_get_order(self, run_set):
        assert run_set._cols_to_order(run_set.order) == run_set.spec["sort"]

    def test_get_groupby(self, run_set):
        assert run_set._cols_to_groupby(run_set.groupby) == run_set.spec["grouping"]


@pytest.mark.usefixtures("run_set_modified", "panel_grid_modified", "report_modified")
class TestRunSetSetters:
    @pytest.mark.parametrize(
        "cols,groupbyspec",
        [
            (
                ["State", "Group"],
                [
                    {"section": "run", "name": "state"},
                    {"section": "run", "name": "group"},
                ],
            ),
            (
                ["User", "something"],
                [
                    {"section": "run", "name": "username"},
                    {"section": "summary", "name": "something"},
                ],
            ),
        ],
    )
    def test_set_groupby(self, run_set, cols, groupbyspec):
        run_set.groupby = cols
        assert run_set.spec["grouping"] == groupbyspec

    @pytest.mark.parametrize(
        "cols,orderspec",
        [
            (
                ["+User", "-State", "+other_col"],
                {
                    "keys": [
                        {
                            "key": {"section": "run", "name": "username"},
                            "ascending": True,
                        },
                        {
                            "key": {"section": "run", "name": "state"},
                            "ascending": False,
                        },
                        {
                            "key": {
                                "section": "run",
                                "name": "summary_metrics.other_col",
                            },
                            "ascending": True,
                        },
                    ]
                },
            ),
            (
                ["+CreatedTimestamp", "-Runtime"],
                {
                    "keys": [
                        {
                            "key": {"section": "run", "name": "createdAt"},
                            "ascending": True,
                        },
                        {
                            "key": {"section": "run", "name": "duration"},
                            "ascending": False,
                        },
                    ]
                },
            ),
        ],
    )
    def test_set_order(self, run_set, cols, orderspec):
        run_set.order = cols
        assert run_set.spec["sort"] == orderspec

    @pytest.mark.parametrize(
        "expr,filtermongo,filterspec",
        [
            (
                "State == 'crashed' and team == 'amazing team'",
                {
                    "$or": [
                        {
                            "$and": [
                                {"state": "crashed"},
                                {"summary_metrics.team": "amazing team"},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "run", "name": "state"},
                                    "op": "=",
                                    "value": "crashed",
                                },
                                {
                                    "key": {"section": "summary", "name": "team"},
                                    "op": "=",
                                    "value": "amazing team",
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                "User != 'megatruong' and Runtime < 3600",
                {
                    "$or": [
                        {
                            "$and": [
                                {"username": {"$ne": "megatruong"}},
                                {"duration": {"$lt": 3600}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "run", "name": "username"},
                                    "op": "!=",
                                    "value": "megatruong",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": "<",
                                    "value": 3600,
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                """
                a > 123 and
                        c == "the cow"
                    and Runtime == "amazing"
                    and UsingArtifact ==
                    "other thing"
                    and Name in [123,456,789]
                """,
                {
                    "$or": [
                        {
                            "$and": [
                                {"summary_metrics.a": {"$gt": 123}},
                                {"summary_metrics.c": "the cow"},
                                {"duration": "amazing"},
                                {"inputArtifacts": "other thing"},
                                {"displayName": {"$in": [123, 456, 789]}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "summary", "name": "a"},
                                    "op": ">",
                                    "value": 123,
                                },
                                {
                                    "key": {"section": "summary", "name": "c"},
                                    "op": "=",
                                    "value": "the cow",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": "=",
                                    "value": "amazing",
                                },
                                {
                                    "key": {"section": "run", "name": "inputArtifacts"},
                                    "op": "=",
                                    "value": "other thing",
                                },
                                {
                                    "key": {"section": "run", "name": "displayName"},
                                    "op": "IN",
                                    "value": [123, 456, 789],
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                """
                person in ['a', 'b', 'c']
                and experiment_name == "amazing experiment"
                and JobType not in ['training', 'testing']
                """,
                {
                    "$or": [
                        {
                            "$and": [
                                {"summary_metrics.person": {"$in": ["a", "b", "c"]}},
                                {
                                    "summary_metrics.experiment_name": "amazing experiment"
                                },
                                {"jobType": {"$nin": ["training", "testing"]}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "summary", "name": "person"},
                                    "op": "IN",
                                    "value": ["a", "b", "c"],
                                },
                                {
                                    "key": {
                                        "section": "summary",
                                        "name": "experiment_name",
                                    },
                                    "op": "=",
                                    "value": "amazing experiment",
                                },
                                {
                                    "key": {"section": "run", "name": "jobType"},
                                    "op": "NIN",
                                    "value": ["training", "testing"],
                                },
                            ],
                        }
                    ],
                },
            ),
            (
                """
                Name in ['object_detection_2', 'pose_estimation_1', 'pose_estimation_2']
                and JobType == '<null>'
                and Runtime <= 6000
                and State != None
                and User != None
                and CreatedTimestamp <= '2022-05-06'
                and Runtime >= 0
                and team != None
                and _timestamp >= 0
                """,
                {
                    "$or": [
                        {
                            "$and": [
                                {
                                    "displayName": {
                                        "$in": [
                                            "object_detection_2",
                                            "pose_estimation_1",
                                            "pose_estimation_2",
                                        ]
                                    }
                                },
                                {"jobType": "<null>"},
                                {"duration": {"$lte": 6000}},
                                {"state": {"$ne": None}},
                                {"username": {"$ne": None}},
                                {"createdAt": {"$lte": "2022-05-06"}},
                                {"duration": {"$gte": 0}},
                                {"summary_metrics.team": {"$ne": None}},
                                {"summary_metrics._timestamp": {"$gte": 0}},
                            ]
                        }
                    ]
                },
                {
                    "op": "OR",
                    "filters": [
                        {
                            "op": "AND",
                            "filters": [
                                {
                                    "key": {"section": "run", "name": "displayName"},
                                    "op": "IN",
                                    "value": [
                                        "object_detection_2",
                                        "pose_estimation_1",
                                        "pose_estimation_2",
                                    ],
                                },
                                {
                                    "key": {"section": "run", "name": "jobType"},
                                    "op": "=",
                                    "value": "<null>",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": "<=",
                                    "value": 6000,
                                },
                                {
                                    "key": {"section": "run", "name": "state"},
                                    "op": "!=",
                                    "value": None,
                                },
                                {
                                    "key": {"section": "run", "name": "username"},
                                    "op": "!=",
                                    "value": None,
                                },
                                {
                                    "key": {"section": "run", "name": "createdAt"},
                                    "op": "<=",
                                    "value": "2022-05-06",
                                },
                                {
                                    "key": {"section": "run", "name": "duration"},
                                    "op": ">=",
                                    "value": 0,
                                },
                                {
                                    "key": {"section": "summary", "name": "team"},
                                    "op": "!=",
                                    "value": None,
                                },
                                {
                                    "key": {"section": "summary", "name": "_timestamp"},
                                    "op": ">=",
                                    "value": 0,
                                },
                            ],
                        }
                    ],
                },
            ),
        ],
    )
    def test_set_filters_with_python_expr(self, run_set, expr, filtermongo, filterspec):
        run_set.set_filters_with_python_expr(expr)
        assert (
            run_set.spec["filters"]
            == filterspec
            == run_set.query_generator.mongo_to_filter(run_set.filters)
        )
        assert run_set.query_generator.filter_to_mongo(filterspec) == filtermongo

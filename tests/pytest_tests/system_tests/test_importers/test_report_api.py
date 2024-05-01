import math
import os
import random
from itertools import product
from typing import Optional, Union

import pytest
import wandb
import wandb.apis.reports as wr
from wandb.apis.reports.util import (
    Attr,
    Base,
    Block,
    Panel,
    PanelMetricsHelper,
    collides,
)
from wandb.apis.reports.validators import (
    Between,
    LayoutDict,
    Length,
    OneOf,
    OrderString,
    TypeValidator,
)


@pytest.mark.usefixtures("user")
class WandbObject(Base):
    untyped = Attr(json_path="spec.untyped")
    typed: Optional[str] = Attr(json_path="spec.typed")
    nested_path: Optional[str] = Attr(
        json_path="spec.deeply.nested.example",
    )
    two_paths: list = Attr(
        json_path=["spec.two1", "spec.two2"],
        validators=[TypeValidator(Union[int, float, None], how="keys")],
    )
    two_nested_paths: list = Attr(
        json_path=["spec.nested.first", "spec.nested.second"],
        validators=[TypeValidator(Optional[str], how="keys")],
    )
    validated_scalar: int = Attr(
        json_path="spec.validated_scalar", validators=[Between(0, 3)]
    )
    validated_list: list = Attr(
        json_path="spec.validated_list", validators=[Between(0, 3, how="keys")]
    )
    validated_dict: dict = Attr(
        json_path="spec.validated_dict",
        validators=[OneOf(["a", "b"], how="keys"), Between(0, 3, how="values")],
    )
    objects_with_spec: list = Attr(
        json_path="spec.objects_with_spec",
        # validators=[TypeValidator("WandbObject", how="keys")],
    )

    def __init__(self):
        super().__init__()
        self.untyped = None
        self.typed = None
        self.nested_path = None
        self.two_paths = [None, None]
        self.two_nested_paths = [None, None]
        self.validated_scalar = 0
        self.validated_list = []
        self.validated_dict = {}
        self.objects_with_spec = []


# Self-referential -- must add post-hoc
WandbObject.objects_with_spec.validators = [TypeValidator(WandbObject, how="keys")]


@pytest.fixture
def log_example_runs(wandb_init):
    entity = os.getenv("WANDB_ENTITY")
    project = "example-project"

    run_names = [
        "adventurous-aardvark-1",
        "bountiful-badger-2",
        "clairvoyant-chipmunk-3",
        "dastardly-duck-4",
        "eloquent-elephant-5",
        "flippant-flamingo-6",
        "giddy-giraffe-7",
        "haughty-hippo-8",
        "ignorant-iguana-9",
        "jolly-jackal-10",
        "kind-koala-11",
        "laughing-lemur-12",
        "manic-mandrill-13",
        "neighbourly-narwhal-14",
        "oblivious-octopus-15",
        "philistine-platypus-16",
        "quant-quail-17",
        "rowdy-rhino-18",
        "solid-snake-19",
        "timid-tarantula-20",
        "understanding-unicorn-21",
        "voracious-vulture-22",
        "wu-tang-23",
        "xenic-xerneas-24",
        "yielding-yveltal-25",
        "zooming-zygarde-26",
    ]

    # opts = ["adam", "sgd"]
    # encoders = ["resnet18", "resnet50"]
    opts = ["adam"]
    encoders = ["resnet18"]
    learning_rates = [0.01]
    for run_name, (opt, encoder, lr) in zip(
        run_names, product(opts, encoders, learning_rates)
    ):
        config = {
            "optimizer": opt,
            "encoder": encoder,
            "learning_rate": lr,
            "momentum": 0.1 * random.random(),
        }
        displacement1 = random.random() * 2
        displacement2 = random.random() * 4
        with wandb_init(
            entity=entity,
            project=project,
            config=config,
            name=run_name,
        ) as run:
            for step in range(100):
                wandb.log(
                    {
                        "acc": 0.1
                        + 0.4
                        * (
                            math.log(1 + step + random.random())
                            + random.random() * run.config.learning_rate
                            + random.random()
                            + displacement1
                            + random.random() * run.config.momentum
                        ),
                        "val_acc": 0.1
                        + 0.4
                        * (
                            math.log(1 + step + random.random())
                            + random.random() * run.config.learning_rate
                            - random.random()
                            + displacement1
                        ),
                        "loss": 0.1
                        + 0.08
                        * (
                            3.5
                            - math.log(1 + step + random.random())
                            + random.random() * run.config.momentum
                            + random.random()
                            + displacement2
                        ),
                        "val_loss": 0.1
                        + 0.04
                        * (
                            4.5
                            - math.log(1 + step + random.random())
                            + random.random() * run.config.learning_rate
                            - random.random()
                            + displacement2
                        ),
                    }
                )
    yield entity, project


@pytest.fixture
def report():
    yield wr.Report(
        project="example-project",
        # entity="example-entity",
        title="example-title",
        description="example-description",
        width="readable",
        blocks=[wr.H1("Hello"), wr.P("World")],
    )


@pytest.fixture(
    params=[
        {
            "entity": "example-entity",
            "project": "example-project",
            "name": "example-names",
        },
        {"entity": "other-entity", "project": "other-project", "name": "other-name"},
        {"entity": "example-entity"},
        {},
    ]
)
def runset(request, user):
    return wr.Runset(**request.param)


@pytest.fixture
def panel_grid(log_example_runs):
    entity = os.getenv("WANDB_ENTITY")
    project = "example-project"

    return wr.PanelGrid(
        runsets=[
            wr.Runset(entity, project, "example-runset"),
            wr.Runset("test_entity", "test_project", "runset_name"),
        ],
        panels=[
            wr.LinePlot(x="Step", y=["val_loss"]),
            wr.ScatterPlot(x="layers", y="val_loss"),
            wr.BarPlot(metrics=["metrics"]),
        ],
    )


@pytest.fixture(params=["overview", "metadata", "usage", "files", "lineage"])
def weave_tab(request):
    yield request.param


PANEL_GRID_SENTINEL = object()

blocks = [
    wr.H1("test"),
    wr.H2("test"),
    wr.H3("test"),
    wr.BlockQuote("test"),
    wr.CalloutBlock("test"),
    wr.CheckedList(["not checked", "checked"], [False, True]),
    wr.CodeBlock(code="x = np.random.randn(size=100)", language="python"),
    wr.Gallery(["id1", "id2"]),
    wr.HorizontalRule(),
    wr.Image(url="https://www.wandb.com/img.png", caption="test"),
    wr.LaTeXBlock(["e=mc^2"]),
    wr.MarkdownBlock("# Hello\nWorld"),
    wr.OrderedList(["test", "test2"]),
    wr.P("test"),
    # wr.PanelGrid(),
    # panel_grid(),
    PANEL_GRID_SENTINEL,
    wr.SoundCloud("https://api.soundcloud.com/tracks/1076901103"),
    wr.Spotify("5cfUlsdrdUE4dLMK7R9CFd"),
    wr.TableOfContents(),
    wr.UnorderedList(["test", "test2"]),
    wr.Video("https://www.youtube.com/embed/6riDJMI-Y8U"),
    wr.WeaveBlockSummaryTable("example-entity", "example-project", "example-table"),
    wr.WeaveBlockArtifact("example-entity", "example-project", "example-artifact"),
    wr.WeaveBlockArtifactVersionedFile(
        "example-entity", "example-project", "example-artifact", "v0", "example-file"
    ),
]


@pytest.fixture(params=blocks)  # , ids=[b.__class__.__name__ for b in blocks])
def block(request, user):
    if request.param is not PANEL_GRID_SENTINEL:
        return request.param
    else:
        return wr.PanelGrid()


panels = [
    wr.BarPlot(),
    wr.CodeComparer(),
    wr.CustomChart(),
    wr.LinePlot(),
    wr.MarkdownPanel(),
    wr.MediaBrowser(),
    wr.ParallelCoordinatesPlot(),
    wr.ParameterImportancePlot(),
    wr.RunComparer(),
    wr.ScalarChart(),
    wr.ScatterPlot(),
    wr.WeavePanelSummaryTable("example-table"),
    wr.WeavePanelArtifact("example-artifact"),
    wr.WeavePanelArtifactVersionedFile("example-artifact", "v0", "example-file"),
]


@pytest.fixture(params=panels, ids=[p.__class__.__name__ for p in panels])
def panel(request):
    return request.param


@pytest.fixture
def save_new_report(user):
    report = wr.Report(project="example-project")
    report.save()
    yield report


_inline_content = [
    wr.Link("Hello", "https://url.com"),
    wr.InlineLaTeX("e=mc^2"),
    wr.InlineCode("print('Hello world!')"),
]


@pytest.fixture(
    params=_inline_content, ids=[x.__class__.__name__ for x in _inline_content]
)
def inline_content(request):
    return request.param


@pytest.mark.usefixtures("user")
class TestAttrSystem:
    def test_untyped(self):
        o = WandbObject()
        o.untyped = "untyped_value"
        assert o.spec["untyped"] == "untyped_value"
        assert o.untyped == "untyped_value"

    def test_typed(self):
        o = WandbObject()
        o.typed = "typed_value"
        assert o.spec["typed"] == "typed_value"
        with pytest.raises(TypeError):
            o.typed = 1
        assert o.spec["typed"] == "typed_value"
        assert o.typed == "typed_value"

    def test_two_paths(self):
        o = WandbObject()
        o.two_paths = [1, 2]
        assert "two_paths" not in o.spec
        assert o.spec["two1"] == 1
        assert o.spec["two2"] == 2
        assert o.two_paths == [1, 2]

    def test_nested_path(self):
        o = WandbObject()
        o.nested_path = "nested_value"
        assert o.spec["deeply"]["nested"]["example"] == "nested_value"
        assert o.nested_path == "nested_value"

    def test_two_nested_paths(self):
        o = WandbObject()
        o.two_nested_paths = ["first", "second"]
        assert "two_nested_paths" not in o.spec
        assert o.spec["nested"]["first"] == "first"
        assert o.spec["nested"]["second"] == "second"
        assert o.two_nested_paths == ["first", "second"]

    def test_validated_scalar(self):
        o = WandbObject()
        o.validated_scalar = 1
        assert o.spec["validated_scalar"] == 1

        with pytest.raises(ValueError):
            o.validated_scalar = -999
        assert o.spec["validated_scalar"] == 1
        assert o.validated_scalar == 1

    def test_validated_list(self):
        o = WandbObject()
        o.validated_list = [1, 2, 3]
        assert o.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            o.validated_list = [-1, -2, -3]
        assert o.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            o.validated_list = [1, 2, -999]
        assert o.spec["validated_list"] == [1, 2, 3]
        assert o.validated_list == [1, 2, 3]

    def test_validated_dict_keys(self):
        o = WandbObject()
        o.validated_dict = {"a": 1, "b": 2}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            o.validated_dict = {"a": 1, "invalid_key": 2}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}
        assert o.validated_dict == {"a": 1, "b": 2}

    def test_validated_dict_values(self):
        o = WandbObject()
        o.validated_dict = {"a": 1, "b": 2}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            o.validated_dict = {"a": 1, "b": -999}
        assert o.spec["validated_dict"] == {"a": 1, "b": 2}
        assert o.validated_dict == {"a": 1, "b": 2}

    def test_nested_objects_with_spec(self):
        o1 = WandbObject()
        o2 = WandbObject()
        o3 = WandbObject()
        o2.objects_with_spec = [o3]
        o1.objects_with_spec = [o2]

        o3.untyped = "a"
        assert o3.untyped == "a"
        assert o2.objects_with_spec[0].untyped == "a"
        assert o1.objects_with_spec[0].objects_with_spec[0].untyped == "a"

        o2.untyped = "b"
        assert o2.untyped == "b"
        assert o1.objects_with_spec[0].untyped == "b"


@pytest.mark.usefixtures("user")
class TestReports:
    def test_create_report(self):
        report = wr.Report(project="example-project")
        report.save()
        # check for upsert report mutation

    def test_load_report(self, save_new_report):
        saved_report = save_new_report
        report = wr.Report.from_url(saved_report.url)
        assert isinstance(report, wr.Report)

        for b in zip(report.blocks, saved_report.blocks):
            assert b[0].spec == b[1].spec

        for pg in zip(report.panel_grids, saved_report.panel_grids):
            assert pg[0].spec == pg[1].spec

        for rs in zip(report.runsets, saved_report.runsets):
            assert rs[0].spec == rs[1].spec

    def test_clone_report(self, report):
        report2 = report.save(clone=True)

        assert report is not report2
        assert report.id != report2.id
        assert report.name != report2.name

        assert report.spec == report2.spec

    def test_get_blocks(self, report):
        for b in report.blocks:
            assert isinstance(b, Block)

    def test_set_blocks(self, report, block):
        report.blocks = [block]
        assert len(report.blocks) == 1
        for b in report.blocks:
            assert isinstance(b, Block)

    def test_append_block(self, report, block):
        report.blocks += [block]
        assert len(report.blocks) == 3
        for b in report.blocks:
            assert isinstance(b, Block)

    def test_get_panel_grids(self, report):
        for pg in report.panel_grids:
            assert isinstance(pg, wr.PanelGrid)

    def test_get_runsets(self, report):
        for rs in report.runsets:
            assert isinstance(rs, wr.Runset)

    def test_blocks_can_be_reassigned(self, report):
        b = wr.H1(text=["Hello world!"])
        report.blocks = [b]
        b.text = ["Goodbye world!"]
        report.blocks = [b]
        assert report.blocks[0].text == b.text

    @pytest.mark.xfail
    def test_blocks_cannot_be_mutated(self, report):
        b = wr.H1(text=["Hello world!"])
        report.blocks = [b]
        b.text = ["Goodbye world!"]
        assert report.blocks[0].text == b.text

    def test_on_save_report_runsets_have_valid_project(self, report):
        pg = wr.PanelGrid()
        report.blocks = [pg]
        pg.runsets = [
            wr.Runset(),
            wr.Runset(project=None),
            wr.Runset(project="example-project"),
        ]
        report.save()
        for rs in report.runsets:
            assert rs.project is not None

    def test_on_save_report_panel_grids_have_at_least_one_runset(self, report):
        report.blocks = [wr.PanelGrid(runsets=[]), wr.PanelGrid(runsets=[])]
        report.save()
        for pg in report.panel_grids:
            assert len(pg.runsets) >= 1


@pytest.mark.usefixtures("user")
class TestBlocks:
    @pytest.mark.parametrize(
        "text", ["string", "string\nwith\nnewlines", ["list", "of", "strings"]]
    )
    @pytest.mark.parametrize("cls", [wr.H1, wr.H2, wr.H3])
    def test_headings(self, cls, text):
        b = cls(text)
        vars(b)

    @pytest.mark.parametrize(
        "items", [["one-item"], ["two", "items"], ["items\nwith", "new\nlines"]]
    )
    def test_ordered_list(self, items):
        b = wr.OrderedList(items)
        vars(b)

    @pytest.mark.parametrize(
        "items", [["one-item"], ["two", "items"], ["items\nwith", "new\nlines"]]
    )
    def test_unordered_list(self, items):
        b = wr.UnorderedList(items)
        vars(b)

    @pytest.mark.parametrize(
        "items,checked",
        [
            [["one-item"], [True]],
            [["two", "items"], [False, True]],
            [["items\nwith", "new\nlines"], [False, False]],
        ],
    )
    def test_checked_list(self, items, checked):
        b = wr.CheckedList(items, checked)
        vars(b)

    @pytest.mark.parametrize("text", ["string", "string\nwith\nnewlines"])
    def test_block_quote(self, text):
        b = wr.BlockQuote(text)
        vars(b)

    @pytest.mark.parametrize(
        "text", ["string", "string\nwith\nnewlines", ["list", "of", "strings"]]
    )
    def test_callout_block(self, text):
        b = wr.CalloutBlock(text)
        vars(b)

    @pytest.mark.xfail
    @pytest.mark.parametrize("text", [""])
    def test_callout_block_edge_cases(self, text):
        b = wr.CalloutBlock(text)
        vars(b)

    @pytest.mark.parametrize(
        "language,code",
        [
            ["python", "print('hello world')"],
            [None, "x = np.random.randint(0, 10, size=(10, 10))"],
            ["sql", "select * from table"],
            ["sql", ["select *", "from other_table"]],
            ["javascript", "console.log('hello world')"],
        ],
    )
    def test_code_block(self, language, code):
        b = wr.CodeBlock(code, language)
        vars(b)

    @pytest.mark.parametrize("ids", [["one-id"], ["two", "ids"]])
    def test_gallery(self, ids):
        b = wr.Gallery(ids)
        vars(b)

    @pytest.mark.parametrize(
        "ids",
        [
            ["test-title--VmlldzoxMjc5Njkz"],
            ["Code-Compare-Panel--VmlldzoxMjc5Njkz?query=hi"],
            [
                "https://wandb.ai/stacey/deep-drive/reports/Code-Compare-Panel--VmlldzoxMjc5Njkz"
            ],
        ],
    )
    def test_gallery_from_report_urls(self, ids):
        b = wr.Gallery.from_report_urls(ids)
        vars(b)

    def test_horizontal_rule(self):
        b = wr.HorizontalRule()
        vars(b)

    @pytest.mark.parametrize(
        "url,caption",
        [
            [
                "https://raw.githubusercontent.com/wandb/assets/main/wandb-logo-yellow-dots-black-wb.svg",
                "wandb logo",
            ],
            [
                "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRbi9aVFq2CV5UxsEhDk4L5Hk_u4nHnSTnsWhnOUNRg4mfdOfWZfJoPGLZL01QvgvIDT8Q&usqp=CAU",
                "penguin",
            ],
        ],
    )
    def test_image(self, url, caption):
        b = wr.Image(url, caption)
        vars(b)

    @pytest.mark.parametrize(
        "text",
        [
            r"Attention(Q, K, V) = softmax(\frac{QK^T}{\sqrt{d_k}})V",
            [r"\sigma(z) = \frac{1} {1 + e^{-z}}", r"\sum_{i=1}^{D}|x_i-y_i|"],
        ],
    )
    def test_latex_block(self, text):
        b = wr.LaTeXBlock(text)
        vars(b)

    @pytest.mark.parametrize(
        "text",
        [
            "# Heading",
            "# Heading\n## Subheading\nSome text",
            ["# Heading", "## Subheading", "Some text"],
        ],
    )
    def test_markdown(self, text):
        b = wr.MarkdownBlock(text)
        vars(b)

    @pytest.mark.parametrize(
        "text", ["string", "string\nwith\nnewlines", ["list", "of", "strings"]]
    )
    def test_p(self, text):
        b = wr.P(text)
        vars(b)

    @pytest.mark.parametrize("url", ["https://api.soundcloud.com/tracks/1076901103"])
    def test_soundcloud(self, url):
        b = wr.SoundCloud(url)
        vars(b)

    @pytest.mark.parametrize("url", ["5cfUlsdrdUE4dLMK7R9CFd"])
    def test_spotify(self, url):
        b = wr.Spotify(url)
        vars(b)

    def test_table_of_contents(self):
        b = wr.TableOfContents()
        vars(b)

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=krWjJcW80_A",
            "https://youtu.be/krWjJcW80_A",
            "https://youtu.be/krWjJcW80_A?t=123",
        ],
    )
    def test_video(self, url):
        b = wr.Video(url)
        vars(b)

    @pytest.mark.parametrize(
        "entity,project,table_name",
        [["example-entity", "example-project", "example-table"]],
    )
    def test_weave_block_summary_table(self, entity, project, table_name):
        b = wr.WeaveBlockSummaryTable(entity, project, table_name)
        vars(b)

    @pytest.mark.parametrize(
        "entity,project,artifact_name",
        [["example-entity", "example-project", "example-table"]],
    )
    def test_weave_block_artifact(self, entity, project, artifact_name, weave_tab):
        b = wr.WeaveBlockArtifact(entity, project, artifact_name, weave_tab)
        vars(b)

    @pytest.mark.parametrize(
        "entity,project,artifact_name,version,file",
        [["example-entity", "example-project", "example-table", "v0", "example-file"]],
    )
    def test_weave_block_artifact_versioned_file(
        self, entity, project, artifact_name, version, file
    ):
        b = wr.WeaveBlockArtifactVersionedFile(
            entity, project, artifact_name, version, file
        )
        vars(b)


@pytest.mark.usefixtures("user")
class TestPanelGrids:
    def test_get_runsets(self, panel_grid):
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_set_runsets(self, panel_grid, runset):
        panel_grid.runsets = [runset, runset]
        assert len(panel_grid.runsets) == 2
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_append_runsets(self, panel_grid):
        panel_grid.runsets += [wr.Runset(), wr.Runset()]
        assert len(panel_grid.runsets) == 4
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_get_panels(self, panel_grid):
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_set_panels(self, panel_grid, panel):
        panel_grid.panels = [panel, panel]
        assert len(panel_grid.panels) == 2
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_append_panels(self, panel_grid):
        panel_grid.panels += [wr.LinePlot(), wr.BarPlot()]
        assert len(panel_grid.panels) == 5
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_panels_dont_collide_after_assignment(self, panel_grid):
        panel_grid.panels = [wr.LinePlot() for _ in range(10)]
        for i, p1 in enumerate(panel_grid.panels):
            for p2 in panel_grid.panels[i:]:
                assert collides(p1, p2) is False

    def test_runset_colors(self, panel_grid):
        # This also requires an integration test to confirm if the colors actually show up in the UI.
        panel_grid.custom_run_colors = {
            "adventurous-aardvark-1": "red",
        }
        vars(panel_grid)

    def test_active_runset(self, panel_grid):
        panel_grid.active_runset = "example-runset"
        vars(panel_grid)


class TestRunsets:
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
    def test_set_filters_with_python_expr(
        self, log_example_runs, runset, expr, filtermongo, filterspec
    ):
        entity, project = log_example_runs
        runset.entity = entity
        runset.project = project
        runset.set_filters_with_python_expr(expr)
        assert runset.spec["filters"] == runset.query_generator.mongo_to_filter(
            runset.filters
        )
        assert runset.query_generator.filter_to_mongo(filterspec) == filtermongo


@pytest.mark.usefixtures("user")
class TestNameMappings:
    @pytest.mark.parametrize(
        "url,expected",
        [
            # No padding needed for `View:1290312` (base64 decoded), `VmlldzoxMjkwMzEy` (base64 encoded)
            (
                "sub.site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "http://sub.site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "https://sub.site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "http://site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "https://site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            ("this-is-a-title--VmlldzoxMjkwMzEy", "VmlldzoxMjkwMzEy"),
            ("another-one-with-=--VmlldzoxMjkwMzEy=", "VmlldzoxMjkwMzEy"),
            ("    another-one-with-whitespace--VmlldzoxMjkwMzEy", "VmlldzoxMjkwMzEy"),
            (" i-am-title --    VmlldzoxMjkwMzEy=     ", "VmlldzoxMjkwMzEy"),
            # three dashes too for some reason
            (
                "sub.site.tld/entity/project/reports/this-is-a-title---VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "http://sub.site.tld/entity/project/reports/this-is-a-title---VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "site.tld/entity/project/reports/this-is-a-title---VmlldzoxMjkwMzEy",
                "VmlldzoxMjkwMzEy",
            ),
            # sites with queries
            (
                "sub.site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy?query=something",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "http://sub.site.tld/entity/project/reports/this-is-a-title--VmlldzoxMjkwMzEy?query=something",
                "VmlldzoxMjkwMzEy",
            ),
            (
                "site.tld/entity/project/reports/this-is-a-title---VmlldzoxMjkwMzEy?query=something&query2=hi",
                "VmlldzoxMjkwMzEy",
            ),
            # Add "==" padding to `View:13` (base64 decoded), `VmlldzoxMw` (base64 encoded)
            ("imatitle--VmlldzoxMw", "VmlldzoxMw=="),
            ("entity/project/reports/this-is-a-title--VmlldzoxMw==", "VmlldzoxMw=="),
            # Add "=" padding to " `View:144` (base64 decoded), `VmlldzoxNDQ` (base64 encoded)
            ("imatitle--VmlldzoxNDQ", "VmlldzoxNDQ="),
        ],
    )
    def test_url_to_valid_report_id(self, url, expected):
        id = wr.Report._url_to_report_id(url)
        assert id == expected

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "--",
            "---",
            "=",
            "==",
            "===",
            "this-is-a-title--",
            "entity/project/reports/this-is-a-title",
            "this-is-a-title--",
            "https://site.tld/entity/project/reports/this-is-a-title--",
            "sub.site.tld/entity/project/reports",
            "http://sub.site.tld/entity/project/reports/",
            "https://sub.site.tld/entity/project/reports/this-is-a-",
            "site.tld/entity/project/reports/this-is-a-title---",
            # sites with queries
            "sub.site.tld/entity/project/reports/this-is-a-title?query=something",
            "http://sub.site.tld/entity/project/reports/this-is-a-title---?query=something",
            "https://sub.site.tld/entity/project/reports/this-is-a-title--?query=something&query2=hi",
            "site.tld/entity/project/reports/this-is-a-?query=something",
        ],
    )
    def test_url_with_invalid_report_id(self, url):
        with pytest.raises(ValueError):
            wr.Report._url_to_report_id(url)

    # For Scatter and ParallelCoords
    @pytest.mark.parametrize(
        "field,mapped",
        [
            ["c::metric", "config:metric.value"],
            ["c::metric.with.dots", "config:metric.value.with.dots"],
            pytest.param(
                "metric",
                "config:metric",
                marks=pytest.mark.xfail(reason="Unable to disambiguate"),
            ),
            pytest.param(
                "metric.with.dots",
                "config:metric.value.with.dots",
                marks=pytest.mark.xfail(reason="Unable to disambiguate"),
            ),
            ["s::metric", "summary:metric"],
            ["s::metric.with.dots", "summary:metric.with.dots"],
        ],
    )
    def test_special_mappings(self, field, mapped):
        mapper = PanelMetricsHelper()
        result = mapper.special_front_to_back(field)
        assert result == mapped

        result2 = mapper.special_back_to_front(mapped)
        assert result2 == field

    @pytest.mark.parametrize(
        "field,mapped,remapped",
        [
            ["metric", "summary:metric", "s::metric"],
            ["metric.with.dots", "summary:metric.with.dots", "s::metric.with.dots"],
        ],
    )
    def test_special_mappings_default(self, field, mapped, remapped):
        mapper = PanelMetricsHelper()
        result = mapper.special_front_to_back(field)
        assert result == mapped

        result2 = mapper.special_back_to_front(mapped)
        assert result2 == remapped


class TestPanels:
    def test_bar_plot(self):
        p = wr.BarPlot(metrics="metric", orientation="h")
        assert p.metrics == ["metric"]
        assert p.orientation == "h"
        vars(p)

    def test_custom_chart(self):
        p = wr.CustomChart()
        vars(p)

    def test_line_plot(self):
        p = wr.LinePlot(x="x", y=["y1", "y2"])
        vars(p)
        assert p.x == "x"
        assert p.y == ["y1", "y2"]

    def test_parallel_coordinates_plot(self):
        p = wr.ParallelCoordinatesPlot(
            columns=[wr.PCColumn("c::config1"), "c::config2"]
        )
        assert p.columns[0].metric == "c::config1"
        assert p.columns[1].metric == "c::config2"
        vars(p)

    def test_parameter_importance_plot(self):
        p = wr.ParameterImportancePlot(with_respect_to="metric")
        assert p.with_respect_to == "metric"
        vars(p)

    def test_scalar_chart(self):
        p = wr.ScalarChart(metric="metric")
        assert p.metric == "metric"
        vars(p)

    def test_scatter_plot(self):
        p = wr.ScatterPlot(x="x", y="y", z="z")
        assert p.x == "s::x"
        assert p.y == "s::y"
        assert p.z == "s::z"
        vars(p)


@pytest.mark.usefixtures("user")
class TestInlineContent:
    def test_paragraph(self, report, inline_content):
        b = wr.P(["Hello World", inline_content])
        report.blocks = [b]

    @pytest.mark.parametrize("cls", [wr.H1, wr.H2, wr.H3])
    def test_heading(self, cls, report, inline_content):
        b = cls(["Hello World", inline_content])
        report.blocks = [b]

    @pytest.mark.parametrize("cls", [wr.UnorderedList, wr.OrderedList, wr.CheckedList])
    def test_list(self, cls, report, inline_content):
        b = cls(["Hello World", inline_content])
        report.blocks = [b]


@pytest.mark.usefixtures("user")
class TestTemplates:
    @pytest.mark.parametrize(
        "f,kwargs",
        [
            pytest.param(
                wr.create_customer_landing_page,
                {},
                marks=pytest.mark.xfail(
                    reason="This func only works on the public cloud"
                ),
            ),
            [wr.create_enterprise_report, {}],
        ],
    )
    def test_report_templates(self, f, kwargs):
        report = f(**kwargs)
        assert isinstance(report, wr.Report)

    @pytest.mark.parametrize(
        "f,kwargs", [[wr.create_example_header, {}], [wr.create_example_footer, {}]]
    )
    def test_block_templates(self, f, kwargs):
        blocks = f(**kwargs)
        for b in blocks:
            assert isinstance(b, Block)


class TestValidators:
    @pytest.mark.parametrize(
        "typ,value,expect",
        [
            (int, 1, "pass"),
            (int, "a", "fail"),
            (str, "a", "pass"),
            (str, 1, "fail"),
            (bool, True, "pass"),
            (bool, "a", "fail"),
            (bool, "a", "fail"),
            (list, [], "pass"),
            (list, [1, 2, 3], "pass"),
            (list, 1, "fail"),
        ],
    )
    def test_type_validator(self, typ, value, expect):
        v = TypeValidator(typ)
        if expect == "pass":
            v.call("Validator", value)
        else:
            with pytest.raises(TypeError):
                v.call("Validator", value)

    @pytest.mark.parametrize(
        "options,value,expect",
        [
            ([1, 2, 3], 1, "pass"),
            ([1, 2, 3], 4, "fail"),
            ([1, 2, 3], "abc", "fail"),
            ([], "abc", "fail"),
            (["a"], "abc", "fail"),
            (["a"], "a", "pass"),
        ],
    )
    def test_one_of_validator(self, options, value, expect):
        v = OneOf(options)
        if expect == "pass":
            v.call("Validator", value)
        else:
            with pytest.raises(ValueError):
                v.call("Validator", value)

    @pytest.mark.parametrize(
        "k,value,expect",
        [
            (2, ("a", "b"), "pass"),
            (1, ("a", "b"), "fail"),
            (3, ("a", "b"), "fail"),
            (2, "a", "fail"),
        ],
    )
    def test_length_validator(self, k, value, expect):
        v = Length(k)
        if expect == "pass":
            v.call("Validator", value)
        else:
            with pytest.raises(ValueError):
                v.call("Validator", value)

    @pytest.mark.parametrize(
        "lb,ub,value,expect",
        [
            (0, 5, 3, "pass"),
            (0, 5, -1, "fail"),
            (0, 5, 6, "fail"),
        ],
    )
    def test_between_validator(self, lb, ub, value, expect):
        v = Between(lb, ub)
        if expect == "pass":
            v.call("Validator", value)
        else:
            with pytest.raises(ValueError):
                v.call("Validator", value)

    @pytest.mark.parametrize(
        "value,expect",
        [
            (
                "+metric",
                "pass",
            ),
            (
                "-metric",
                "pass",
            ),
            (
                "metric",
                "fail",
            ),
        ],
    )
    def test_orderstring_validator(self, value, expect):
        v = OrderString()
        if expect == "pass":
            v.call("Validator", value)
        else:
            with pytest.raises(ValueError):
                v.call("Validator", value)

    @pytest.mark.parametrize(
        "value,expect",
        [
            (
                {"x": 0, "y": 0, "w": 0, "h": 0},
                "pass",
            ),
            (
                {"x": 0, "y": 0, "z": 0, "h": 0},
                "fail",
            ),
            (
                {"x": 0, "y": 0},
                "fail",
            ),
            (
                {"z": 0, "h": 0},
                "fail",
            ),
        ],
    )
    def test_layoutdict_validator(self, value, expect):
        v = LayoutDict()
        if expect == "pass":
            v.call("Validator", value)
        else:
            with pytest.raises(ValueError):
                v.call("Validator", value)


class TestHelpers:
    def test_linekey(self):
        k = wr.LineKey("metric")
        vars(k)

    def test_linekey_from_panel_agg(self):
        pass

    def test_linekey_from_runset_agg(self):
        pass

    def test_pccolumn(self):
        c = wr.PCColumn("c::metric")
        vars(c)

    def test_pccolumn_from_json(self):
        pass

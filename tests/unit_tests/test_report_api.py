import inspect
from typing import Optional, Union
from unittest import mock

import pytest
import wandb
import wandb.apis.reports as wr
from wandb import Api
from wandb.apis.reports.testing import Attr, Base
from wandb.apis.reports.util import Block, Panel, generate_name, collides
from wandb.apis.reports.validators import Between, OneOf, TypeValidator


def test_create_and_load_report_from_public_api(user, wandb_init):
    # Not sure how to get a valid Api() object here.  It needs an API key to work I think
    run = wandb_init()
    run.finish()

    api = Api()
    runs = api.runs()
    for run in runs:
        print(run)
    # assert isinstance(report, wr.Report)

    # report2 = api.load_report(report.url)
    # assert isinstance(report2, wr.Report)

    # assert report is not report2
    # assert report.id == report2.id
    # assert report.name == report2.name
    # assert report.spec == report.spec


class ObjectWithSpec(Base):
    something = Attr(json_path="spec.something")
    another = Attr(json_path="spec.another")

    def __init__(self):
        self.something = "some thing"
        self.another = "another thing"


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
        validators=[TypeValidator(ObjectWithSpec, how="keys")],
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


def test_untyped():
    wandb_object = WandbObject()
    wandb_object.untyped = "untyped_value"
    assert wandb_object.spec["untyped"] == "untyped_value"
    assert wandb_object.untyped == "untyped_value"


# blocks = [obj for _, obj in inspect.getmembers(wr.blocks) if inspect.isclass(obj)]
# blocks = [wr.BlockQuote(), wr.CalloutBlock(), wr.CheckedList(), wr.CodeBlock(), ]
blocks = [
    wr.H1("Test"),
    wr.H2("Test"),
    wr.H3("Test"),
    wr.BlockQuote("Test"),
    wr.CalloutBlock("Test"),
    wr.CheckedList(["a", "b", "c"]),
    wr.CodeBlock("Test"),
    wr.Gallery([generate_name()]),
    wr.HorizontalRule(),
    wr.Image(
        "https://avatars.githubusercontent.com/u/26401354?s=200&v=4", "wandb logo"
    ),
    wr.LaTeXBlock("e=mc^2"),
    wr.MarkdownBlock("Test"),
    wr.OrderedList(["a", "b", "c"]),
    wr.P("Test"),
    wr.PanelGrid(),
    wr.SoundCloud("https://api.soundcloud.com/tracks/1076901103"),
    wr.Spotify(spotify_id="5cfUlsdrdUE4dLMK7R9CFd"),
    wr.TableOfContents(),
    wr.UnorderedList(["a", "b", "c"]),
    wr.Video("https://www.youtube.com/embed/6riDJMI-Y8U"),
    wr.WeaveTableBlock("my-entity", "my-project", "some-table"),
]
panels = [obj for _, obj in inspect.getmembers(wr.panels) if inspect.isclass(obj)]


@pytest.fixture(params=blocks, ids=[b.__class__.__name__ for b in blocks])
def block(request):
    return request.param


@pytest.fixture(params=panels)
def panel(request):
    return request.param()


@pytest.fixture(
    params=[
        wr.InlineLaTeX("e=mc^2"),
        wr.InlineCode("x,y,z = hello()"),
        wr.Link("This is a hyperlink", url="wandb.ai"),
    ],
    ids=["latex", "code", "link"],
)
def inline_content(request):
    return request.param


@pytest.fixture
def object_with_spec():
    return ObjectWithSpec()


@pytest.fixture
def wandb_object():
    return WandbObject()


@pytest.fixture
def runset():
    return wr.Runset(entity="test_entity", project="test_project", name="runset_name")


@pytest.fixture
def panel_grid():
    return wr.PanelGrid(
        runsets=[
            wr.Runset("test_entity", "test_project", "runset_name"),
            wr.Runset("another_entity", "another_project", "runset_name2"),
        ],
        panels=[
            wr.LinePlot(x="Step", y=["val_loss"]),
            wr.ScatterPlot(x="layers", y="val_loss"),
            wr.BarPlot(metrics=["metrics"]),
        ],
    )


@pytest.fixture
def report():
    return wr.Report(
        project="test_project",
        # entity="test_entity",
        title="test_title",
        description="test_description",
        width="readable",
        blocks=[wr.H1("Hello"), wr.P("World")],
    )


# create a project with some runs as part of setup
# this requires the relay server?


class TestReports:
    def test_valid_spec(self):
        raise

    def test_create_and_load_report(self):
        report = wr.Report(project="my-project")
        report.save()
        assert isinstance(report, wr.Report)

        report2 = wr.Report.from_url(report.url)
        assert isinstance(report2, wr.Report)

        assert report is not report2
        assert report.id == report2.id
        assert report.name == report2.name
        assert report.spec == report.spec

    def test_clone_report(self, report):
        report2 = report.save(clone=True)
        # should save it to the server, but the id should be different.

        assert report is not report2
        assert report.id != report2.id
        assert report.name != report2.name
        assert report.spec == report2.spec

    # def test_create_and_load_report_from_public_api(self, user):
    #     # Not sure how to get a valid Api() object here.  It needs an API key to work I think
    #     api = Api()
    #     report = api.create_report(project="my-project")
    #     assert isinstance(report, wr.Report)

    #     report2 = api.load_report(report.url)
    #     assert isinstance(report2, wr.Report)

    #     assert report is not report2
    #     assert report.id == report2.id
    #     assert report.name == report2.name
    #     assert report.spec == report.spec

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

    # @pytest.mark.parametrize(
    #     "block,setup,edited",
    #     [
    #         [wr.H1, {"text": "Hello World"}, {"text": "Edited"}],
    #         [
    #             wr.PanelGrid,
    #             {"panels": [wr.LinePlot(), wr.BarPlot()], "runsets": [wr.Runset()]},
    #             {
    #                 "panels": [wr.LinePlot(), wr.ScatterPlot()],
    #                 "runsets": [wr.Runset(project="new-project")],
    #             },
    #         ],
    #     ],
    # )
    # def test_blocks_can_be_edited_after_assignment(self, report, block, setup, edited):
    #     b = block(**setup)  # b = wr.H1("Hello World")
    #     report.blocks = [b]
    #     for k, v in edited.items():
    #         setattr(b, k, v)  # b.text = "Edited"
    #         # assert report.blocks[0].text == "Edited"
    #         assert getattr(report.blocks[0], k) == v

    #
    def test_save_report_keeps_same_spec_object(self):
        rs = wr.Runset()
        p = wr.LinePlot()
        pg = wr.PanelGrid(runsets=[rs], panels=[p])

        report = wr.Report(project="test", blocks=[pg])
        report.save()

        assert report.blocks[0].spec is pg.spec
        assert report.blocks[0].runsets[0].spec is rs.spec
        assert report.blocks[0].panels[0].spec is p.spec

    def test_on_save_report_runsets_have_valid_project(self, report, panel_grid):
        # Runsets should have valid entity and project names
        report.blocks = [panel_grid]
        panel_grid.runsets = [wr.Runset(project="test"), wr.Runset(project=None)]
        report = report.save()
        for rs in report.runsets:
            assert rs.project is not None

    def test_on_save_report_panel_grids_have_at_least_one_runset(self, report):
        # Panel grids should have at least one runset
        report.blocks = [wr.PanelGrid(runsets=[])]
        report = report.save()
        assert len(report.runsets) == 1


class TestPanelGrids:
    def test_get_runsets(self, panel_grid):
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_set_runsets(self, panel_grid):
        panel_grid.runsets = [wr.Runset(), wr.Runset()]
        assert len(panel_grid.runsets) == 2
        for rs in panel_grid.runsets:
            assert isinstance(rs, wr.Runset)

    def test_panel_grid_has_at_least_one_runset_on_save(self, report, panel_grid):
        panel_grid.runsets = []
        report.blocks = [panel_grid]

    def test_custom_run_colors_ungrouped(self, panel_grid):
        # should be an integration test?
        raise

    def test_custom_run_colors_grouped(self, panel_grid):
        # should be an integration test?
        raise

    def test_get_panels(self, panel_grid):
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_set_panels(self, panel_grid):
        panel_grid.panels = [wr.LinePlot(), wr.BarPlot()]
        assert len(panel_grid.panels) == 2
        for p in panel_grid.panels:
            assert isinstance(p, Panel)

    def test_panels_dont_collide_after_assignment(self, panel_grid):
        panel_grid.panels = [wr.LinePlot() for _ in range(10)]
        for i, p1 in enumerate(panel_grid.panels):
            for p2 in panel_grid.panels[i:]:
                assert collides(p1, p2) is False


class TestInlineContent:
    def test_paragraph(self, report, inline_content):
        b = wr.P(["Hello World", inline_content])
        report.blocks = [b]
        # report.save()

    @pytest.mark.parametrize("cls", [wr.H1, wr.H2, wr.H3])
    def test_heading(self, cls, report, inline_content):
        b = cls(["Hello World", inline_content])
        report.blocks = [b]
        # report.save()

    @pytest.mark.parametrize("cls", [wr.UnorderedList, wr.OrderedList, wr.CheckedList])
    def test_list(self, cls, report, inline_content):
        b = cls(["Hello World", inline_content])
        report.blocks = [b]
        # report.save()


class TestRunsets:
    def test_set_filters_with_python_expr(self, runset):
        # Could not find project.  What projects exist by default if any?
        runset.set_filters_with_python_expr("val_loss < 0.5 and category == 'cat'")


class TestAttrSystem:
    def test_untyped(self):
        wandb_object = WandbObject()
        wandb_object.untyped = "untyped_value"
        assert wandb_object.spec["untyped"] == "untyped_value"
        assert wandb_object.untyped == "untyped_value"

    def test_typed(self, wandb_object):
        wandb_object.typed = "typed_value"
        assert wandb_object.spec["typed"] == "typed_value"
        with pytest.raises(TypeError):
            wandb_object.typed = 1
        assert wandb_object.spec["typed"] == "typed_value"
        assert wandb_object.typed == "typed_value"

    def test_two_paths(self, wandb_object):
        wandb_object.two_paths = [1, 2]
        assert "two_paths" not in wandb_object.spec
        assert wandb_object.spec["two1"] == 1
        assert wandb_object.spec["two2"] == 2
        assert wandb_object.two_paths == [1, 2]

    def test_nested_path(self, wandb_object):
        wandb_object.nested_path = "nested_value"
        assert wandb_object.spec["deeply"]["nested"]["example"] == "nested_value"
        assert wandb_object.nested_path == "nested_value"

    def test_two_nested_paths(self, wandb_object):
        wandb_object.two_nested_paths = ["first", "second"]
        assert "two_nested_paths" not in wandb_object.spec
        assert wandb_object.spec["deeply"]["nested"]["first"] == "first"
        assert wandb_object.spec["deeply"]["nested"]["second"] == "second"
        assert wandb_object.two_nested_paths == ["first", "second"]

    def test_validated_scalar(self, wandb_object):
        wandb_object.validated_scalar = 1
        assert wandb_object.spec["validated_scalar"] == 1

        with pytest.raises(ValueError):
            wandb_object.validated_scalar = -999
        assert wandb_object.spec["validated_scalar"] == 1
        assert wandb_object.validated_scalar == 1

    def test_validated_list(self, wandb_object):
        wandb_object.validated_list = [1, 2, 3]
        assert wandb_object.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            wandb_object.validated_list = [-1, -2, -3]
        assert wandb_object.spec["validated_list"] == [1, 2, 3]

        with pytest.raises(ValueError):
            wandb_object.validated_list = [1, 2, -999]
        assert wandb_object.spec["validated_list"] == [1, 2, 3]
        assert wandb_object.validated_list == [1, 2, 3]

    def test_validated_dict_keys(self, wandb_object):
        wandb_object.validated_dict = {"a": 1, "b": 2}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            wandb_object.validated_dict = {"a": 1, "invalid_key": 2}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}
        assert wandb_object.validated_dict == {"a": 1, "b": 2}

    def test_validated_dict_values(self, wandb_object):
        wandb_object.validated_dict = {"a": 1, "b": 2}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}

        with pytest.raises(ValueError):
            wandb_object.validated_dict = {"a": 1, "b": -999}
        assert wandb_object.spec["validated_dict"] == {"a": 1, "b": 2}
        assert wandb_object.validated_dict == {"a": 1, "b": 2}

    def test_objects_with_spec(self, wandb_object, object_with_spec):
        wandb_object.objects_with_spec = [object_with_spec]
        assert wandb_object.spec["objects_with_spec"] == [object_with_spec.spec]
        assert wandb_object.objects_with_spec == [object_with_spec]


class TestTemplates:
    def test_customer_landing_page(self):
        report = wr.templates.create_customer_landing_page()
        report.save()

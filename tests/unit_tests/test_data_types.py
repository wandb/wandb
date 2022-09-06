import glob
import io
import os
import platform

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import pandas as pd
import pytest
import rdkit.Chem
import wandb
from bokeh.plotting import figure
from PIL import Image
from wandb import data_types
from wandb.sdk.data_types.base_types.media import _numpy_arrays_to_lists


def subdict(d, expected_dict):
    """Return a new dict with only the items from `d` whose keys occur in `expected_dict`."""
    return {k: v for k, v in d.items() if k in expected_dict}


def matplotlib_multiple_axes_figures(total_plot_count=3, data=(1, 2, 3)):
    """Helper generator which  create a figure containing up to `total_plot_count`
    axes and optionally adds `data` to each axes in a permutation-style loop.
    """
    for num_plots in range(1, total_plot_count + 1):
        for permutation in range(2**num_plots):
            has_data = [permutation & (1 << i) > 0 for i in range(num_plots)]
            fig, ax = plt.subplots(num_plots)
            if num_plots == 1:
                if has_data[0]:
                    ax.plot(data)
            else:
                for plot_id in range(num_plots):
                    if has_data[plot_id]:
                        ax[plot_id].plot(data)
            yield fig
            plt.close()


def matplotlib_with_image():
    """Creates a matplotlib figure with an image"""
    fig, ax = plt.subplots(3)
    ax[0].plot([1, 2, 3])
    ax[1].imshow(np.random.rand(200, 200, 3))
    ax[2].plot([1, 2, 3])
    return fig


def matplotlib_without_image():
    """Creates a matplotlib figure without an image"""
    fig, ax = plt.subplots(2)
    ax[0].plot([1, 2, 3])
    ax[1].plot([1, 2, 3])
    return fig


###############################################################################
# Test wandb.Histogram
###############################################################################


def test_raw_data():
    data = np.random.randint(255, size=(1000))

    wbhist = wandb.Histogram(data)
    assert len(wbhist.histogram) == 64


def test_np_histogram():
    data = np.random.randint(255, size=(1000))
    wbhist = wandb.Histogram(np_histogram=np.histogram(data))
    assert len(wbhist.histogram) == 10


def test_manual_histogram():
    wbhist = wandb.Histogram(
        np_histogram=(
            [1, 2, 4],
            [3, 10, 20, 0],
        )
    )
    assert len(wbhist.histogram) == 3


def test_invalid_histogram():
    with pytest.raises(ValueError):
        wandb.Histogram(
            np_histogram=(
                [1, 2, 3],
                [1],
            )
        )


###############################################################################
# Test wandb.Image
###############################################################################


@pytest.fixture
def image():
    yield np.zeros((28, 28))


@pytest.fixture
def full_box():
    yield {
        "position": {
            "middle": (0.5, 0.5),
            "width": 0.1,
            "height": 0.2,
        },
        "class_id": 2,
        "box_caption": "This is a big car",
        "scores": {"acc": 0.3},
    }


@pytest.fixture
def dissoc():
    # Helper function return a new dictionary with the key removed
    def dissoc_fn(d, key):
        new_d = d.copy()
        new_d.pop(key)
        return new_d

    yield dissoc_fn


@pytest.fixture
def standard_mask():
    yield {
        "mask_data": np.array(
            [
                [1, 2, 2, 2],
                [2, 3, 3, 4],
                [4, 4, 4, 4],
                [4, 4, 4, 2],
            ]
        ),
        "class_labels": {
            1: "car",
            2: "pedestrian",
            3: "tractor",
            4: "cthululu",
        },
    }


def test_captions(
    image,
):

    wbone = wandb.Image(image, caption="Cool")
    wbtwo = wandb.Image(image, caption="Nice")
    assert wandb.Image.all_captions([wbone, wbtwo]) == ["Cool", "Nice"]


def test_bind_image(
    mock_run,
    image,
):

    wb_image = wandb.Image(image)
    wb_image.bind_to_run(mock_run(), "stuff", 10)
    assert wb_image.is_bound()


def test_image_accepts_other_images():
    image_a = wandb.Image(np.random.random((300, 300, 3)))
    image_b = wandb.Image(image_a)
    assert image_a == image_b


def test_image_accepts_bounding_boxes(
    mock_run,
    image,
    full_box,
):

    run = mock_run()
    img = wandb.Image(
        image,
        boxes={
            "predictions": {
                "box_data": [full_box],
            },
        },
    )
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["boxes"]["predictions"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_accepts_bounding_boxes_optional_args(
    mock_run,
    image,
    full_box,
    dissoc,
):

    optional_keys = ["box_caption", "scores"]

    boxes_with_removed_optional_args = [dissoc(full_box, k) for k in optional_keys]

    img = data_types.Image(
        image,
        boxes={
            "predictions": {
                "box_data": boxes_with_removed_optional_args,
            },
        },
    )
    run = mock_run()
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["boxes"]["predictions"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_accepts_masks(
    mock_run,
    image,
    standard_mask,
):
    img = wandb.Image(
        image,
        masks={
            "overlay": standard_mask,
        },
    )
    run = mock_run()
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["masks"]["overlay"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_accepts_masks_without_class_labels(
    mock_run,
    image,
    dissoc,
    standard_mask,
):
    img = wandb.Image(
        image,
        masks={
            "overlay": dissoc(standard_mask, "class_labels"),
        },
    )
    run = mock_run()
    img.bind_to_run(run, "images", 0)
    img_json = img.to_json(run)
    path = img_json["masks"]["overlay"]["path"]
    assert os.path.exists(os.path.join(run.dir, path))


def test_image_seq_to_json(
    mock_run,
    image,
):
    run = mock_run()
    wb_image = wandb.Image(image)
    wb_image.bind_to_run(run, "test", 0, 0)
    _ = wandb.Image.seq_to_json([wb_image], run, "test", 0)
    assert os.path.exists(os.path.join(run.dir, "media", "images", "test_0_0.png"))


def test_max_images(mock_run):
    run = mock_run()
    large_image = np.random.randint(255, size=(10, 10))
    large_list = [wandb.Image(large_image)] * 200
    large_list[0].bind_to_run(run, "test2", 0, 0)
    meta = wandb.Image.seq_to_json(
        wandb.wandb_sdk.data_types.utils._prune_max_seq(large_list),
        run,
        "test2",
        0,
    )
    expected = {
        "_type": "images/separated",
        "count": data_types.Image.MAX_ITEMS,
        "height": 10,
        "width": 10,
    }
    path = os.path.join(run.dir, "media/images/test2_0_0.png")
    assert subdict(meta, expected) == expected
    assert os.path.exists(path)


def test_guess_mode():
    image = np.random.randint(255, size=(28, 28, 3))
    wbimg = wandb.Image(image)
    assert wbimg.image.mode == "RGB"


def test_pil():
    pil = Image.new("L", (28, 28))
    img = wandb.Image(pil)
    assert list(img.image.getdata()) == list(pil.getdata())


def test_matplotlib_image():
    plt.plot([1, 2, 2, 4])
    img = wandb.Image(plt)
    assert img.image.width == 640


def test_matplotlib_image_with_multiple_axes():
    """Ensures that wandb.Image constructor can accept a pyplot or figure
    reference in which the figure has multiple axes. Importantly, there is
    no requirement that any of the axes have plotted data.
    """
    for fig in matplotlib_multiple_axes_figures():
        wandb.Image(fig)  # this should not error.

    for _ in matplotlib_multiple_axes_figures():
        wandb.Image(plt)  # this should not error.


def test_image_from_matplotlib_with_image():
    """Ensures that wandb.Image constructor supports a pyplot with image is passed"""
    # try the figure version
    fig = matplotlib_with_image()
    wandb.Image(fig)  # this should not error.
    plt.close()

    # try the plt version
    fig = matplotlib_with_image()
    wandb.Image(plt)  # this should not error.
    plt.close()


@pytest.mark.skipif(
    platform.system() != "Windows", reason="Failure case is only happening on Windows"
)
def test_fail_to_make_file(
    mock_run,
    image,
):
    with pytest.raises(
        ValueError,
        match="is invalid. Please remove invalid filename characters",
    ):
        wb_image = wandb.Image(image)
        wb_image.bind_to_run(mock_run(), "my key: an identifier", 0)


# def test_cant_serialize_to_other_run(mock_run):
#     """This isn't implemented yet. Should work eventually."""
#     other_run = wandb.wandb_sdk.wandb_run.Run(settings=wandb_init)
#     other_run._set_backend(mock_run._backend)
#     wb_image = wandb.Image(image)

#     wb_image.bind_to_run(mock_run, "stuff", 10)

#     with pytest.raises(AssertionError):
#         wb_image.to_json(other_run)


#     meta_expected = {
#         "_type": "images/separated",
#         "count": 1,
#         "height": 28,
#         "width": 28,
#     }
#     assert utils.subdict(meta, meta_expected) == meta_expected


################################################################################
# Test wandb.Audio
################################################################################


def test_audio_sample_rates():
    audio1 = np.random.uniform(-1, 1, 44100)
    audio2 = np.random.uniform(-1, 1, 88200)
    wbaudio1 = wandb.Audio(audio1, sample_rate=44100)
    wbaudio2 = wandb.Audio(audio2, sample_rate=88200)
    assert wandb.Audio.sample_rates([wbaudio1, wbaudio2]) == [44100, 88200]
    # test with missing sample rate
    with pytest.raises(ValueError):
        wandb.Audio(audio1)


def test_audio_durations():
    audio1 = np.random.uniform(-1, 1, 44100)
    audio2 = np.random.uniform(-1, 1, 88200)
    wbaudio1 = wandb.Audio(audio1, sample_rate=44100)
    wbaudio2 = wandb.Audio(audio2, sample_rate=44100)
    assert wandb.Audio.durations([wbaudio1, wbaudio2]) == [1.0, 2.0]


def test_audio_captions():
    audio = np.random.uniform(-1, 1, 44100)
    sample_rate = 44100
    caption1 = "This is what a dog sounds like"
    caption2 = "This is what a chicken sounds like"
    # test with all captions
    wbaudio1 = wandb.Audio(audio, sample_rate=sample_rate, caption=caption1)
    wbaudio2 = wandb.Audio(audio, sample_rate=sample_rate, caption=caption2)
    assert wandb.Audio.captions([wbaudio1, wbaudio2]) == [caption1, caption2]
    # test with no captions
    wbaudio3 = wandb.Audio(audio, sample_rate=sample_rate)
    wbaudio4 = wandb.Audio(audio, sample_rate=sample_rate)
    assert wandb.Audio.captions([wbaudio3, wbaudio4]) is False
    # test with some captions
    wbaudio5 = wandb.Audio(audio, sample_rate=sample_rate)
    wbaudio6 = wandb.Audio(audio, sample_rate=sample_rate, caption=caption2)
    assert wandb.Audio.captions([wbaudio5, wbaudio6]) == ["", caption2]


def test_audio_to_json(mock_run):
    run = mock_run()
    audio = np.zeros(44100)
    audio_obj = wandb.Audio(audio, sample_rate=44100)
    audio_obj.bind_to_run(run, "test", 0)
    meta = wandb.Audio.seq_to_json([audio_obj], run, "test", 0)
    assert os.path.exists(os.path.join(run.dir, meta["audio"][0]["path"]))

    meta_expected = {
        "_type": "audio",
        "count": 1,
        "sampleRates": [44100],
        "durations": [1.0],
    }
    assert subdict(meta, meta_expected) == meta_expected

    audio_expected = {
        "_type": "audio-file",
        "caption": None,
        "size": 88244,
    }
    assert subdict(meta["audio"][0], audio_expected) == audio_expected


def test_audio_refs():
    audio_obj = wandb.Audio(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    art = wandb.Artifact("audio_ref_test", "dataset")
    art.add(audio_obj, "audio_ref")

    audio_expected = {
        "_type": "audio-file",
        "caption": None,
    }
    assert subdict(audio_obj.to_json(art), audio_expected) == audio_expected


################################################################################
# Test wandb.Plotly
################################################################################


def test_matplotlib_plotly_with_multiple_axes():
    """Ensures that wandb.Plotly constructor can accept a plotly figure
    reference in which the figure has multiple axes. Importantly, there is
    no requirement that any of the axes have plotted data.
    """
    for fig in matplotlib_multiple_axes_figures():
        wandb.Plotly(fig)  # this should not error.

    for _ in matplotlib_multiple_axes_figures():
        wandb.Plotly(plt)  # this should not error.


def test_plotly_from_matplotlib_with_image():
    """Ensures that wandb.Plotly constructor properly errors when
    a pyplot with image is passed
    """
    # try the figure version
    fig = matplotlib_with_image()
    with pytest.raises(ValueError):
        wandb.Plotly(fig)
    plt.close()

    # try the plt version
    fig = matplotlib_with_image()
    with pytest.raises(ValueError):
        wandb.Plotly(plt)
    plt.close()


def test_make_plot_media_from_matplotlib_without_image():
    """Ensures that wand.Plotly.make_plot_media() returns a Plotly object when
    there is no image
    """
    fig = matplotlib_without_image()
    assert type(wandb.Plotly.make_plot_media(fig)) == wandb.Plotly
    plt.close()

    fig = matplotlib_without_image()
    assert type(wandb.Plotly.make_plot_media(plt)) == wandb.Plotly
    plt.close()


def test_make_plot_media_from_matplotlib_with_image():
    """Ensures that wand.Plotly.make_plot_media() returns an Image object when
    there is an image in the matplotlib figure
    """
    fig = matplotlib_with_image()
    assert type(wandb.Plotly.make_plot_media(fig)) == wandb.Image
    plt.close()

    fig = matplotlib_with_image()
    assert type(wandb.Plotly.make_plot_media(plt)) == wandb.Image
    plt.close()


################################################################################
# Test wandb.Bokeh
################################################################################


@pytest.fixture
def bokeh_plot():
    def bokeh_plot_fn():
        # from https://docs.bokeh.org/en/latest/docs/user_guide/quickstart.html
        # prepare some data
        x = [1, 2, 3, 4, 5]
        y = [6, 7, 2, 4, 5]

        # create a new plot with a title and axis labels
        p = figure(title="simple line example", x_axis_label="x", y_axis_label="y")

        # add a line renderer with legend and line thickness
        p.line(x, y, legend_label="Temp.", line_width=2)

        return p

    yield bokeh_plot_fn


def test_create_bokeh_plot(
    mock_run,
    bokeh_plot,
):
    """Ensures that wandb.Bokeh constructor accepts a bokeh plot"""
    bp = bokeh_plot()
    bp = wandb.data_types.Bokeh(bp)
    bp.bind_to_run(mock_run(), "bokeh", 0)


################################################################################
# Test wandb.Video
################################################################################


def test_video_numpy_gif(mock_run):
    run = mock_run()
    video = np.random.randint(255, size=(10, 3, 28, 28))
    vid = wandb.Video(video, format="gif")
    vid.bind_to_run(run, "videos", 0)
    assert vid.to_json(run)["path"].endswith(".gif")


def test_video_numpy_mp4(mock_run):
    run = mock_run()
    video = np.random.randint(255, size=(10, 3, 28, 28))
    vid = wandb.Video(video, format="mp4")
    vid.bind_to_run(run, "videos", 0)
    assert vid.to_json(run)["path"].endswith(".mp4")


def test_video_numpy_multi(mock_run):
    run = mock_run()
    video = np.random.random(size=(2, 10, 3, 28, 28))
    vid = wandb.Video(video)
    vid.bind_to_run(run, "videos", 0)
    assert vid.to_json(run)["path"].endswith(".gif")


def test_video_numpy_invalid():
    video = np.random.random(size=(3, 28, 28))
    with pytest.raises(ValueError):
        wandb.Video(video)


def test_video_path(mock_run):
    run = mock_run()
    with open("video.mp4", "w") as f:
        f.write("00000")
    vid = wandb.Video("video.mp4")
    vid.bind_to_run(run, "videos", 0)
    assert vid.to_json(run)["path"].endswith(".mp4")


def test_video_path_invalid():
    with open("video.avi", "w") as f:
        f.write("00000")
    with pytest.raises(ValueError):
        wandb.Video("video.avi")


################################################################################
# Test wandb.Molecule
################################################################################


def test_molecule(mock_run):
    run = mock_run()
    with open("test.pdb", "w") as f:
        f.write("00000")
    mol = wandb.Molecule("test.pdb")
    mol.bind_to_run(run, "rad", "summary")
    wandb.Molecule.seq_to_json([mol], run, "rad", "summary")

    assert os.path.exists(mol._path)


def test_molecule_file(mock_run):
    run = mock_run()
    with open("test.pdb", "w") as f:
        f.write("00000")
    mol = wandb.Molecule(open("test.pdb"))
    mol.bind_to_run(run, "rad", "summary")
    wandb.Molecule.seq_to_json([mol], run, "rad", "summary")

    assert os.path.exists(mol._path)


def test_molecule_from_smiles(mock_run):
    """Ensures that wandb.Molecule.from_smiles supports valid SMILES molecule string representations"""
    run = mock_run()
    mol = wandb.Molecule.from_smiles("CC(=O)Nc1ccc(O)cc1")
    mol.bind_to_run(run, "rad", "summary")
    wandb.Molecule.seq_to_json([mol], run, "rad", "summary")

    assert os.path.exists(mol._path)


def test_molecule_from_invalid_smiles():
    """Ensures that wandb.Molecule.from_smiles errs if passed an invalid SMILES string"""
    with pytest.raises(ValueError):
        wandb.Molecule.from_smiles("TEST")


def test_molecule_from_rdkit_mol_object(mock_run):
    """Ensures that wandb.Molecule.from_rdkit supports rdkit.Chem.rdchem.Mol objects"""
    run = mock_run()
    mol = wandb.Molecule.from_rdkit(rdkit.Chem.MolFromSmiles("CC(=O)Nc1ccc(O)cc1"))
    mol.bind_to_run(run, "rad", "summary")
    wandb.Molecule.seq_to_json([mol], run, "rad", "summary")

    assert os.path.exists(mol._path)


def test_molecule_from_rdkit_mol_file(mock_run):
    """Ensures that wandb.Molecule.from_rdkit supports .mol files"""
    run = mock_run()
    substance = rdkit.Chem.MolFromSmiles("CC(=O)Nc1ccc(O)cc1")
    mol_file_name = "test.mol"
    rdkit.Chem.rdmolfiles.MolToMolFile(substance, mol_file_name)
    mol = wandb.Molecule.from_rdkit(mol_file_name)
    mol.bind_to_run(run, "rad", "summary")
    wandb.Molecule.seq_to_json([mol], run, "rad", "summary")

    assert os.path.exists(mol._path)


def test_molecule_from_rdkit_invalid_input():
    """Ensures that wandb.Molecule.from_rdkit errs on invalid input"""
    mol_file_name = "test"
    with pytest.raises(ValueError):
        wandb.Molecule.from_rdkit(mol_file_name)


################################################################################
# Test wandb.Html
################################################################################


def test_html_str(mock_run):
    run = mock_run()
    html_str = "<html><body><h1>Hello</h1></body></html>"
    html = wandb.Html(html_str)
    html.bind_to_run(run, "rad", "summary")
    wandb.Html.seq_to_json([html], run, "rad", "summary")
    assert os.path.exists(html._path)
    assert html == wandb.Html(html_str)


def test_html_styles():
    pre = (
        '<base target="_blank"><link rel="stylesheet" type="text/css" '
        'href="https://app.wandb.ai/normalize.css" />'
    )
    html = wandb.Html("<html><body><h1>Hello</h1></body></html>")
    assert (
        html.html == "<html><head>" + pre + "</head><body><h1>Hello</h1></body></html>"
    )
    html = wandb.Html("<html><head></head><body><h1>Hello</h1></body></html>")
    assert (
        html.html == "<html><head>" + pre + "</head><body><h1>Hello</h1></body></html>"
    )
    html = wandb.Html("<h1>Hello</h1>")
    assert html.html == pre + "<h1>Hello</h1>"
    html = wandb.Html("<h1>Hello</h1>", inject=False)
    assert html.html == "<h1>Hello</h1>"


def test_html_file(mock_run):
    run = mock_run()
    with open("test.html", "w") as f:
        f.write("<html><body><h1>Hello</h1></body></html>")
    html = wandb.Html(open("test.html"))
    html.bind_to_run(run, "rad", "summary")
    wandb.Html.seq_to_json([html, html], run, "rad", "summary")

    assert os.path.exists(html._path)


def test_html_file_path(mock_run):
    run = mock_run()
    with open("test.html", "w") as f:
        f.write("<html><body><h1>Hello</h1></body></html>")
    html = wandb.Html("test.html")
    html.bind_to_run(run, "rad", "summary")
    wandb.Html.seq_to_json([html, html], run, "rad", "summary")

    assert os.path.exists(html._path)


################################################################################
# Test wandb.Table
################################################################################


@pytest.fixture
def table_data():
    yield [
        ["a", 1, True],
        ["b", 2, False],
        ["c", 3, True],
    ]


def test_table_default():
    table = wandb.Table()
    table.add_data(
        "Some awesome text",
        "Positive",
        "Negative",
    )
    assert table._to_table_json() == {
        "data": [
            [
                "Some awesome text",
                "Positive",
                "Negative",
            ]
        ],
        "columns": [
            "Input",
            "Output",
            "Expected",
        ],
    }


@pytest.mark.parametrize(
    ["a", "b"],
    [
        (  # Invalid Type
            wandb.Table(
                data=[
                    [1, 2, 3],
                    [4, 5, 6],
                ]
            ),
            {},
        ),
        (  # Mismatch Rows
            wandb.Table(
                data=[
                    [1, 2, 3],
                    [4, 5, 6],
                ]
            ),
            wandb.Table(
                data=[
                    [1, 2, 3],
                ]
            ),
        ),
        (  # Mismatch Columns
            wandb.Table(
                data=[
                    [1, 2, 3],
                    [4, 5, 6],
                ]
            ),
            wandb.Table(
                data=[
                    [1, 2, 3],
                    [4, 5, 6],
                ],
                columns=["a", "b", "c"],
            ),
        ),
        (  # Mismatch Types
            wandb.Table(
                data=[
                    [1, 2, 3],
                ]
            ),
            wandb.Table(
                data=[
                    ["1", "2", "3"],
                ]
            ),
        ),
        (  # Mismatch Data
            wandb.Table(
                data=[
                    [1, 2, 3],
                    [4, 5, 6],
                ]
            ),
            wandb.Table(
                data=[
                    [1, 2, 3],
                    [4, 5, 100],
                ]
            ),
        ),
    ],
)
def test_table_eq_debug_mismatch(a, b):

    with pytest.raises(AssertionError):
        a._eq_debug(b, True)
    assert a != b


def test_table_eq_debug_match():
    a = wandb.Table(
        data=[
            [1, 2, 3],
            [4, 5, 6],
        ]
    )
    b = wandb.Table(
        data=[
            [1, 2, 3],
            [4, 5, 6],
        ]
    )
    a._eq_debug(b, True)
    assert a == b


def test_table_custom():

    table = wandb.Table(["Foo", "Bar"])
    table.add_data("So", "Cool")
    table.add_row("&", "Rad")
    assert table._to_table_json() == {
        "data": [["So", "Cool"], ["&", "Rad"]],
        "columns": ["Foo", "Bar"],
    }
    df = pd.DataFrame(columns=["Foo", "Bar"], data=[["So", "Cool"], ["&", "Rad"]])
    table_df = wandb.Table(dataframe=df)
    assert table._to_table_json() == table_df._to_table_json()


def test_table_init():
    table = wandb.Table(
        data=[
            ["Some awesome text", "Positive", "Negative"],
        ]
    )
    assert table._to_table_json() == {
        "data": [
            ["Some awesome text", "Positive", "Negative"],
        ],
        "columns": [
            "Input",
            "Output",
            "Expected",
        ],
    }


def test_table_from_list(table_data):
    table = wandb.Table(data=table_data)
    assert table.data == table_data

    with pytest.raises(AssertionError):
        # raises when user accidentally overrides columns
        table = wandb.Table(table_data)

    with pytest.raises(AssertionError):
        # raises when user uses list in "dataframe"
        table = wandb.Table(dataframe=table_data)

    # legacy
    table = wandb.Table(rows=table_data)
    assert table.data == table_data


def test_table_iterator(table_data):
    table = wandb.Table(data=table_data)
    for ndx, row in table.iterrows():
        assert row == table_data[ndx]

    table = wandb.Table(data=[])
    assert len([(ndx, row) for ndx, row in table.iterrows()]) == 0


def test_table_from_numpy(table_data):
    np_data = np.array(table_data)
    table = wandb.Table(data=np_data)
    assert table.data == np_data.tolist()

    with pytest.raises(AssertionError):
        # raises when user accidentally overrides columns
        table = wandb.Table(np_data)

    with pytest.raises(AssertionError):
        # raises when user uses list in "dataframe"
        table = wandb.Table(dataframe=np_data)


def test_table_from_pandas(table_data):

    pd_data = pd.DataFrame(table_data)
    table = wandb.Table(data=pd_data)
    assert table.data == table_data

    with pytest.raises(AssertionError):
        # raises when user accidentally overrides columns
        table = wandb.Table(pd_data)

    # legacy
    table = wandb.Table(dataframe=pd_data)
    assert table.data == table_data


def test_table_column_style():
    # Test Base Cases
    table1 = wandb.Table(columns=[], data=[])
    table1.add_column("number", [1, 2, 3])
    table1.add_data(4)
    with pytest.raises(AssertionError):
        table1.add_column("strings", ["a"])
    table1.add_column("strings", ["a", "b", "c", "d"])
    table1.set_pk("strings")
    table1.add_data(5, "e")
    table1.add_column("np_numbers", np.array([101, 102, 103, 104, 105]))

    assert table1.data == [
        [1, "a", 101],
        [2, "b", 102],
        [3, "c", 103],
        [4, "d", 104],
        [5, "e", 105],
    ]

    assert table1.get_column("number") == [1, 2, 3, 4, 5]
    assert table1.get_column("strings") == ["a", "b", "c", "d", "e"]
    assert table1.get_column("np_numbers") == [101, 102, 103, 104, 105]

    assert np.all(
        table1.get_column("number", convert_to="numpy") == np.array([1, 2, 3, 4, 5])
    )
    assert np.all(
        table1.get_column("strings", convert_to="numpy")
        == np.array(["a", "b", "c", "d", "e"])
    )
    assert np.all(
        table1.get_column("np_numbers", convert_to="numpy")
        == np.array([101, 102, 103, 104, 105])
    )

    ndxs = table1.get_index()
    assert ndxs == [0, 1, 2, 3, 4]
    assert [ndx._table == table1 for ndx in ndxs]

    # Test More Images and ndarrays
    rand_1 = np.random.randint(255, size=(32, 32))
    rand_2 = np.random.randint(255, size=(32, 32))
    rand_3 = np.random.randint(255, size=(32, 32))
    img_1 = wandb.Image(rand_1)
    img_2 = wandb.Image(rand_2)
    img_3 = wandb.Image(rand_3)

    table2 = wandb.Table(columns=[], data=[])
    table2.add_column("np_data", [rand_1, rand_2])
    table2.add_column("image", [img_1, img_2])
    table2.add_data(rand_3, img_3)

    assert table2.data == [[rand_1, img_1], [rand_2, img_2], [rand_3, img_3]]
    assert np.all(
        table2.get_column("np_data", convert_to="numpy")
        == np.array([rand_1, rand_2, rand_3])
    )
    assert table2.get_column("image") == [img_1, img_2, img_3]
    _ = table2.get_column("image", convert_to="numpy")
    _ = np.array([rand_1, rand_2, rand_3])
    assert np.all(
        table2.get_column("image", convert_to="numpy")
        == np.array([rand_1, rand_2, rand_3])
    )

    table3 = wandb.Table(columns=[], data=[])
    table3.add_column("table1_fk", table1.get_column("strings"))
    assert table3.get_column("table1_fk")[0]._table == table1


def test_ndarrays_in_tables():
    rows = 10
    d = 128
    c = 3
    nda_table = wandb.Table(
        columns=["ndarray"], data=np.random.randint(255, size=(rows, 1, d, d, c))
    )
    nda_table.add_data(np.random.randint(255, size=(d, d, c)))
    nda_table.add_data(np.random.randint(255, size=(d, d, c)).tolist())
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(d + 1, d, c)))
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(d + 1, d, c)).tolist())

    assert any(
        [
            isinstance(t, wandb.data_types._dtypes.NDArrayType)
            for t in nda_table._column_types.params["type_map"]["ndarray"].params[
                "allowed_types"
            ]
        ]
    )

    nda_table = wandb.Table(columns=[], data=[])
    nda_table.add_column(
        "odd_col",
        [[[i], [i]] for i in range(rows)] + [np.random.randint(255, size=(2, 1))],
    )

    assert isinstance(
        nda_table._column_types.params["type_map"]["odd_col"],
        wandb.data_types._dtypes.ListType,
    )

    nda_table.cast("odd_col", wandb.data_types._dtypes.NDArrayType(shape=(2, 1)))
    nda_table.add_data(np.random.randint(255, size=(2, 1)))
    nda_table.add_data(np.random.randint(255, size=(2, 1)).tolist())
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(2, 2)))
    with pytest.raises(TypeError):
        nda_table.add_data(np.random.randint(255, size=(2, 2)).tolist())

    assert isinstance(
        nda_table._column_types.params["type_map"]["odd_col"],
        wandb.data_types._dtypes.NDArrayType,
    )


################################################################################
# Test wandb.Object3D
################################################################################


@pytest.fixture
def point_cloud_1():
    yield np.array(
        [
            [0, 0, 0, 1],
            [0, 0, 1, 13],
            [0, 1, 0, 2],
            [0, 1, 0, 4],
        ]
    )


@pytest.fixture
def point_cloud_2():
    yield np.array(
        [
            [0, 0, 0],
            [0, 0, 1],
            [0, 1, 0],
            [0, 1, 0],
        ]
    )


@pytest.fixture
def point_cloud_3():
    yield np.array(
        [
            [0, 0, 0, 100, 100, 100],
            [0, 0, 1, 100, 100, 100],
            [0, 1, 0, 100, 100, 100],
            [0, 1, 0, 100, 100, 100],
        ]
    )


def test_object3d_numpy(
    mock_run,
    point_cloud_1,
    point_cloud_2,
    point_cloud_3,
):
    run = mock_run()
    obj1 = wandb.Object3D(point_cloud_1)
    obj2 = wandb.Object3D(point_cloud_2)
    obj3 = wandb.Object3D(point_cloud_3)
    obj1.bind_to_run(run, "object3d", 0)
    obj2.bind_to_run(run, "object3d", 1)
    obj3.bind_to_run(run, "object3d", 2)
    assert obj1.to_json(run)["_type"] == "object3D-file"
    assert obj2.to_json(run)["_type"] == "object3D-file"
    assert obj3.to_json(run)["_type"] == "object3D-file"


def test_object3d_dict(mock_run):
    run = mock_run()
    obj = wandb.Object3D(
        {
            "type": "lidar/beta",
        }
    )
    obj.bind_to_run(run, "object3D", 0)
    assert obj.to_json(run)["_type"] == "object3D-file"


def test_object3d_dict_invalid():
    with pytest.raises(ValueError):
        _ = wandb.Object3D(
            {
                "type": "INVALID",
            }
        )
    wandb.finish()


def test_object3d_dict_invalid_string():
    with pytest.raises(ValueError):
        _ = wandb.Object3D("INVALID")
    wandb.finish()


@pytest.mark.parametrize(
    "file_name",
    [
        "cube.obj",
        "Box.gltf",
    ],
)
def test_object3d_obj(mock_run, assets_path, file_name):
    run = mock_run()
    with open(assets_path(file_name)) as f:
        obj = wandb.Object3D(f)
    obj.bind_to_run(run, "object3D", 0)
    assert obj.to_json(run)["_type"] == "object3D-file"


def test_object3d_io(mock_run, assets_path):
    run = mock_run()
    with open(assets_path("Box.gltf")) as f:
        io_obj = io.StringIO(f.read())

    obj = wandb.Object3D(io_obj, file_type="obj")
    obj.bind_to_run(run, "object3D", 0)
    assert obj.to_json(run)["_type"] == "object3D-file"


@pytest.mark.parametrize(
    "object3d",
    [
        np.array([1]),
        np.array(
            [
                [1, 2],
                [3, 4],
                [1, 2],
            ]
        ),
        np.array([1, 3, 4, 5, 6, 7, 8, 8, 3]),
    ],
)
def test_object3d_unsupported_numpy(object3d):
    with pytest.raises(ValueError):
        wandb.Object3D(object3d)


def test_object3d_unsupported_io(assets_path):
    with open(assets_path("Box.gltf")) as f:
        io_obj = io.StringIO(f.read())
    with pytest.raises(ValueError):
        wandb.Object3D(io_obj)


def test_object3d_seq_to_json(mock_run, point_cloud_1, assets_path):
    run = mock_run()

    objects = [wandb.Object3D(point_cloud_1)]
    with open(assets_path("Box.gltf")) as f:
        objects.append(wandb.Object3D(f))
    with open(assets_path("cube.obj")) as f:
        objects.append(wandb.Object3D(f))

    for o in objects:
        o.bind_to_run(run, "pc", 1)

    obj = wandb.Object3D.seq_to_json(objects, run, "pc", 1)

    for i in range(3):
        assert os.path.exists(
            os.path.join(run.dir, "media", "object3D", obj["filenames"][i])
        )
    assert obj["_type"] == "object3D"
    assert obj["count"] == 3


################################################################################
# Test wandb.Graph
################################################################################


def test_graph():
    graph = wandb.Graph()
    node_a = data_types.Node("a", "Node A", size=(4,))
    node_b = data_types.Node("b", "Node B", size=(16,))
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_edge(node_a, node_b)
    assert graph._to_graph_json() == {
        "edges": [["a", "b"]],
        "format": "keras",
        "nodes": [
            {
                "id": "a",
                "name": "Node A",
                "size": (4,),
            },
            {
                "id": "b",
                "name": "Node B",
                "size": (16,),
            },
        ],
    }


################################################################################
# Test wandb.PartitionedTable
################################################################################


def test_partitioned_table():
    partition_table = wandb.data_types.PartitionedTable(parts_path="parts")
    assert len([(ndx, row) for ndx, row in partition_table.iterrows()]) == 0
    assert partition_table == wandb.data_types.PartitionedTable(parts_path="parts")
    assert partition_table != wandb.data_types.PartitionedTable(parts_path="parts2")


################################################################################
# Test various data types
################################################################################


@pytest.mark.parametrize(
    "media",
    [
        wandb.Image(
            np.zeros((28, 28)),
            masks={
                "overlay": {
                    "mask_data": np.array(
                        [
                            [1, 2, 2, 2],
                            [2, 3, 3, 4],
                            [4, 4, 4, 4],
                            [4, 4, 4, 2],
                        ]
                    ),
                    "class_labels": {
                        1: "car",
                        2: "pedestrian",
                        3: "tractor",
                        4: "cthululu",
                    },
                },
            },
        ),
        wandb.data_types.ImageMask(
            {
                "mask_data": np.random.randint(0, 10, (300, 300)),
            },
            key="test",
        ),
        wandb.Table(
            data=[
                [1, 2, 3],
                [4, 5, 6],
            ]
        ),
        wandb.Graph(),
        wandb.Audio(
            np.random.uniform(-1, 1, 44100),
            sample_rate=44100,
        ),
    ],
)
def test_media_keys_escaped_as_glob_for_publish(mock_run, media):
    run = mock_run(use_magic_mock=True)
    weird_key = "[weirdkey]"
    media.bind_to_run(run, weird_key, 0)
    published_globs = [
        g
        for (
            [files_dict],
            [],
        ) in run._backend.interface.publish_files.call_args_list
        for g, _ in files_dict["files"]
    ]
    assert not any(weird_key in g for g in published_globs), published_globs
    assert any(glob.escape(weird_key) in g for g in published_globs), published_globs


def test_numpy_arrays_to_list():
    conv = _numpy_arrays_to_lists
    assert conv(np.array(1)) == [1]
    assert conv(np.array((1, 2))) == [1, 2]
    assert conv([np.array((1, 2))]) == [[1, 2]]
    assert conv(np.array(({"a": [np.array((1, 2))]}, 3))) == [{"a": [[1, 2]]}, 3]

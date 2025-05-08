import json
import platform
import tempfile
from pathlib import Path
from unittest import mock

import moviepy.video.io.ImageSequenceClip
import numpy as np
import PIL.Image
import pytest
import soundfile as sf
import wandb
from bokeh.document import Document
from bokeh.plotting import figure


def create_image(temp_dir) -> Path:
    image_path = Path(temp_dir) / "image.png"
    PIL.Image.fromarray(np.random.randint(0, 255, (1, 1, 3), dtype=np.uint8)).save(
        image_path
    )
    return image_path


def create_video(temp_dir) -> Path:
    video_path = Path(temp_dir) / "video.mp4"
    moviepy.video.io.ImageSequenceClip.ImageSequenceClip(
        list(np.random.randint(0, 255, (1, 1, 3, 30), dtype=np.uint8)),
        fps=10,
    ).write_videofile(str(video_path))
    return video_path


def create_audio(temp_dir) -> Path:
    audio_path = Path(temp_dir) / "audio.wav"
    sf.write(audio_path, np.random.uniform(-1, 1, int(1 * 2)), 1)
    return audio_path


def create_bokeh(temp_dir) -> Path:
    bokeh_path = Path(temp_dir) / "bokeh.bokeh.json"
    doc = Document()
    doc.add_root(figure(title="test", x_axis_label="x", y_axis_label="y"))
    with open(bokeh_path, "w") as f:
        json.dump(doc.to_json(), f, indent=4)
    return bokeh_path


def create_object3d(temp_dir) -> Path:
    object3d_path = Path(temp_dir) / "mediaobj.pts.json"
    point_cloud = np.random.rand(100, 6)
    point_cloud[:, 3:] *= 255
    with open(object3d_path, "w") as f:
        json.dump(point_cloud.tolist(), f, indent=4)
    return object3d_path


def create_html(temp_dir) -> Path:
    html_path = Path(temp_dir) / "index.html"
    with open(html_path, "w") as f:
        f.write("<html><body><h1>Hello, World!</h1></body></html>")
    return html_path


def test_big_table_throws_error_that_can_be_overridden(user):
    with wandb.init(settings={"table_raise_on_max_row_limit_exceeded": True}) as run:
        # make this smaller just for this one test to make the runtime shorter
        with mock.patch("wandb.Table.MAX_ARTIFACT_ROWS", 10):
            table = wandb.Table(
                data=np.arange(wandb.Table.MAX_ARTIFACT_ROWS + 1)[:, None].tolist(),
                columns=["col1"],
            )

            with pytest.raises(ValueError):
                run.log({"table": table})

        with mock.patch(
            "wandb.Table.MAX_ARTIFACT_ROWS", wandb.Table.MAX_ARTIFACT_ROWS + 1
        ):
            # should no longer raise
            run.log({"table": table})


def test_table_logging(user):  # TODO: do we need this fixture? reinit_internal_api
    with wandb.init() as run:
        run.log(
            {
                "logged_table": wandb.Table(
                    columns=["a"],
                    data=[[wandb.Image(np.ones(shape=(32, 32)))]],
                )
            }
        )


def test_object3d_logging(wandb_backend_spy, assets_path):
    with wandb.init() as run:
        run.log(
            {
                "point_cloud": wandb.Object3D.from_file(
                    str(assets_path("point_cloud.pts.json"))
                )
            }
        )

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["point_cloud"]["_type"] == "object3D-file"
        assert summary["point_cloud"]["path"].endswith(".pts.json")


def test_partitioned_table_logging(user):
    with wandb.init() as run:
        run.log({"logged_table": wandb.data_types.PartitionedTable("parts")})


def test_joined_table_logging(user):
    with wandb.init() as run:
        art = wandb.Artifact("A", "dataset")
        t1 = wandb.Table(
            columns=["id", "a"],
            data=[[1, wandb.Image(np.ones(shape=(32, 32)))]],
        )
        t2 = wandb.Table(
            columns=["id", "a"],
            data=[[1, wandb.Image(np.ones(shape=(32, 32)))]],
        )
        art.add(t1, "t1")
        art.add(t2, "t2")
        jt = wandb.JoinedTable(t1, t2, "id")
        art.add(jt, "jt")
        run.log_artifact(art)
        run.log({"logged_table": jt})


def test_log_with_dir_sep_windows(user):
    image = np.zeros((28, 28))
    with wandb.init() as run:
        wb_image = wandb.Image(image)
        run.log({"train/image": wb_image})


def test_log_with_back_slash_windows(user):
    with wandb.init() as run:
        wb_image = wandb.Image(np.zeros((28, 28)))

        # Windows does not allow a backslash in media keys right now
        if platform.system() == "Windows":
            with pytest.raises(ValueError):
                run.log({r"train\image": wb_image})
        else:
            run.log({r"train\image": wb_image})


def test_image_array_old_wandb(
    wandb_backend_spy,
    monkeypatch,
    mock_wandb_log,
):
    monkeypatch.setattr(wandb.util, "_get_max_cli_version", lambda: "0.10.33")

    with wandb.init() as run:
        wb_image = [wandb.Image(np.zeros((28, 28))) for i in range(5)]
        run.log({"logged_images": wb_image})

    assert mock_wandb_log.warned("Unable to log image array filenames.")

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert "filenames" not in summary["logged_images"]


def test_image_array_old_wandb_mp_warning(
    user,
    monkeypatch,
    mock_wandb_log,
):
    monkeypatch.setattr(wandb.util, "_get_max_cli_version", lambda: "0.10.33")

    with wandb.init() as run:
        wb_image = [wandb.Image(np.zeros((28, 28))) for _ in range(5)]
        run._init_pid += 1
        run.log({"logged_images": wb_image})

    assert mock_wandb_log.warned(
        "Attempting to log a sequence of Image objects from multiple processes"
        " might result in data loss. Please upgrade your wandb server"
    )


@pytest.mark.parametrize(
    (
        "create_media",
        "file_ext",
        "wandb_class",
    ),
    [
        (
            create_image,
            "png",
            wandb.Image,
        ),
        (
            create_video,
            "mp4",
            wandb.Video,
        ),
        (
            create_audio,
            "wav",
            wandb.Audio,
        ),
        (
            create_bokeh,
            "bokeh.json",
            wandb.sdk.data_types.bokeh.Bokeh,
        ),
        (
            create_object3d,
            "pts.json",
            wandb.Object3D,
        ),
        (
            create_html,
            "html",
            wandb.Html,
        ),
    ],
)
def test_log_media_with_pathlib_path(
    user, wandb_backend_spy, create_media, file_ext, wandb_class
):
    temp_dir = tempfile.mkdtemp()
    media_path = create_media(temp_dir)
    with wandb.init() as run:
        run.log({"media": wandb_class(media_path)})

    with wandb_backend_spy.freeze() as snapshot:
        files = snapshot.uploaded_files(run_id=run.id)
        assert any(file.endswith(file_ext) for file in files)

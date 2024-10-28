from pathlib import Path

import numpy as np

data = np.random.randint(255, size=(1000))


def test_log_media_saves_to_run_directory(
    mock_run,
    audio_media,
    video_media,
    image_media,
    table_media,
    graph_media,
    bokeh_media,
    html_media,
    molecule_media,
    object3d_media,
    plotly_media,
):
    run = mock_run(use_magic_mock=True)

    media = {
        "/table/test_table": table_media,
        "/image/test_image": image_media,
        "/video/test_video": video_media,
        "/audio/test_audio": audio_media,
        "/graph/test_graph": graph_media,
        "/bokeh/test_bokeh": bokeh_media,
        "/html/test_html": html_media,
        "/molecule/test_molecule": molecule_media,
        "/object/test_object3d": object3d_media,
        "/plotly/test_plotly": plotly_media,
    }
    for key, media_object in media.items():
        media_object.bind_to_run(run, key, 0)

    # Assert all media objects are saved under the run directory
    for media_object in media.values():
        assert media_object._path.startswith(run.dir)


def test_log_media_with_path_traversal(mock_run, image_media):
    run = mock_run()
    image_media.bind_to_run(run, "../../../image", 0)

    # Resolve to path to verify no path traversals
    resolved_path = str(Path(image_media._path).resolve())
    assert resolved_path.startswith(run.dir)


def test_log_media_prefixed_with_multiple_slashes(mock_run, image_media):
    run = mock_run()
    image_media.bind_to_run(run, "////image", 0)

    resolved_path = str(Path(image_media._path).resolve())
    assert resolved_path.startswith(run.dir)

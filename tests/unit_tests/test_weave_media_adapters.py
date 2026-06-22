"""Unit tests for Weave media adapter helpers."""

from __future__ import annotations

import sys
import types
from io import BytesIO

import pytest
import wandb
from wandb.integration.weave.media_adapters import (
    handle_nested_wandb_values,
    unwrap_value,
)


def _install_fake_weave(monkeypatch, **attrs):
    module = types.ModuleType("weave")
    module.__path__ = []
    module.__version__ = "999.0.0"
    for name, value in attrs.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, "weave", module)
    return module


# Unsupported wandb values


def test_media_adapter_rejects_unsupported_wandb_media():
    html = wandb.Html("<p>hi</p>")

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(html, "html", unsupported_media_mode="raise")

    message = str(exc_info.value)
    assert "unsupported wandb media type 'Html'" in message
    assert "Only wandb.Image, wandb.Audio, and wandb.Video" in message


def test_media_adapter_rejects_unsupported_wandb_value():
    histogram = wandb.Histogram([1, 2, 3])

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(histogram, "histogram", unsupported_media_mode="raise")

    message = str(exc_info.value)
    assert "unsupported wandb value type 'Histogram'" in message
    assert "Only wandb.Image, wandb.Audio, and wandb.Video" in message


def test_media_adapter_stubs_unsupported_wandb_media(mock_wandb_log):
    html = wandb.Html("<p>hi</p>", inject=False)

    result = unwrap_value(
        html,
        "html",
        unsupported_media_mode="stub",
    )

    mock_wandb_log.assert_warned("wandb.Html values are not yet supported")
    assert result == "[wandb.Html not yet supported]"


def test_media_adapter_stubs_same_wandb_type_consistently(mock_wandb_log):
    html = wandb.Html("<p>hi</p>", inject=False)
    same_html = wandb.Html("<p>hi</p>", inject=False)
    different_html = wandb.Html("<p>bye</p>", inject=False)

    result = unwrap_value(
        html,
        "html",
        unsupported_media_mode="stub",
    )
    same_result = unwrap_value(
        same_html,
        "html",
        unsupported_media_mode="stub",
    )
    different_result = unwrap_value(
        different_html,
        "html",
        unsupported_media_mode="stub",
    )

    mock_wandb_log.assert_warned("wandb.Html values are not yet supported")
    assert result == same_result
    assert result == different_result


def test_media_adapter_stubs_unsupported_wandb_value_without_natural_hash(
    mock_wandb_log,
):
    histogram = wandb.Histogram([1, 2, 3])

    result = unwrap_value(
        histogram,
        "histogram",
        unsupported_media_mode="stub",
    )

    mock_wandb_log.assert_warned("wandb.Histogram values are not yet supported")
    assert result == "[wandb.Histogram not yet supported]"


def test_media_adapter_stubs_nested_wandb_value(mock_wandb_log):
    from PIL import Image as PILImage

    image = wandb.Image(PILImage.new("RGB", (2, 2), color="red"))

    result = handle_nested_wandb_values(
        {"images": ([image],)},
        "media",
        unsupported_media_mode="stub",
    )

    mock_wandb_log.assert_warned("Nested wandb.Image values are not yet supported")
    assert result == {"images": [["[wandb.Image nested value not yet supported]"]]}


def test_media_adapter_unwraps_wandb_image_in_dict_value(mock_wandb_log):
    from PIL import Image as PILImage

    image = wandb.Image(PILImage.new("RGB", (2, 2), color="red"))

    result = handle_nested_wandb_values(
        {"metadata": {"image": image}},
        "metadata",
        unsupported_media_mode="raise",
    )

    mock_wandb_log.assert_warned("wandb.Image values")
    assert isinstance(result["metadata"]["image"], PILImage.Image)
    assert result["metadata"]["image"].size == (2, 2)


def test_media_adapter_rejects_nested_wandb_value():
    from PIL import Image as PILImage

    image = wandb.Image(PILImage.new("RGB", (2, 2), color="red"))

    with pytest.raises(TypeError) as exc_info:
        handle_nested_wandb_values(
            {"images": [image]},
            "media",
            unsupported_media_mode="raise",
        )

    message = str(exc_info.value)
    assert "nested wandb value type 'Image'" in message
    assert "inside lists or tuples" in message
    assert "unsupported_media_mode='stub'" in message


def test_media_adapter_rejects_nested_table_even_in_stub_mode():
    table = wandb.Table(columns=["x"], data=[[1]])

    with pytest.raises(TypeError) as exc_info:
        handle_nested_wandb_values(
            [table],
            "media",
            unsupported_media_mode="stub",
        )

    assert "does not support nested Tables" in str(exc_info.value)


# Image


def test_media_adapter_image_value_unwrapped_to_pil(mock_wandb_log):
    from PIL import Image as PILImage

    pil_in = PILImage.new("RGB", (2, 2), color="red")
    image = wandb.Image(pil_in)

    result = unwrap_value(image, "img", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Image values")
    assert isinstance(result, PILImage.Image)
    assert result.size == (2, 2)


def test_media_adapter_image_path_unwrapped_to_pil(tmp_path, mock_wandb_log):
    from PIL import Image as PILImage

    image_path = tmp_path / "image.png"
    PILImage.new("RGB", (3, 4), color="red").save(image_path)
    image = wandb.Image(str(image_path))

    result = unwrap_value(image, "img", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Image values")
    assert isinstance(result, PILImage.Image)
    assert result.size == (3, 4)


def test_media_adapter_rejects_external_image_reference(mock_wandb_log):
    image = wandb.Image("https://example.com/image.png")

    with pytest.raises(
        TypeError,
        match="Unsupported external media reference",
    ):
        unwrap_value(image, "img", unsupported_media_mode="raise")


def test_media_adapter_stubs_external_image_reference(mock_wandb_log):
    image = wandb.Image("https://example.com/image.png")

    result = unwrap_value(image, "img", unsupported_media_mode="stub")

    mock_wandb_log.assert_warned(
        "External media references for wandb.Image are not yet supported"
    )
    assert result == "[wandb.Image external reference not yet supported]"


# Audio


def test_media_adapter_audio_path_uses_weave_audio_from_path(
    monkeypatch,
    mock_wandb_log,
    tmp_path,
):
    class FakeWeaveAudio:
        calls = []

        @classmethod
        def from_path(cls, path):
            cls.calls.append(("from_path", path))
            return {"kind": "audio-path", "path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake-wave")
    audio = wandb.Audio(str(audio_path))

    result = unwrap_value(audio, "audio", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Audio values")
    assert result == {"kind": "audio-path", "path": audio_path}
    assert FakeWeaveAudio.calls == [("from_path", audio_path)]


def test_media_adapter_audio_data_uses_weave_audio_from_path(
    monkeypatch,
    mock_wandb_log,
):
    from wandb.sdk.data_types import audio as audio_module

    class FakeSoundFile:
        @staticmethod
        def write(path, data, sample_rate):
            with open(path, "wb") as f:
                f.write(b"RIFFfake-wave")

    original_get_module = audio_module.util.get_module

    def fake_get_module(name, required=None):
        if name == "soundfile":
            return FakeSoundFile
        return original_get_module(name, required=required)

    class FakeWeaveAudio:
        calls = []

        @classmethod
        def from_path(cls, path):
            cls.calls.append(("from_path", path))
            return {"kind": "audio-path", "path": path}

    monkeypatch.setattr(audio_module.util, "get_module", fake_get_module)
    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = wandb.Audio([0.0, 0.1], sample_rate=2)

    result = unwrap_value(audio, "audio", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Audio values")
    assert result["kind"] == "audio-path"
    assert result["path"].suffix == ".wav"
    assert FakeWeaveAudio.calls == [("from_path", result["path"])]


def test_media_adapter_audio_numpy_array_uses_weave_audio_from_path(
    monkeypatch,
    mock_wandb_log,
):
    from wandb.sdk.data_types import audio as audio_module

    np = pytest.importorskip("numpy")

    class FakeSoundFile:
        @staticmethod
        def write(path, data, sample_rate):
            assert data.shape == (2,)
            assert sample_rate == 2
            with open(path, "wb") as f:
                f.write(b"RIFFfake-wave")

    original_get_module = audio_module.util.get_module

    def fake_get_module(name, required=None):
        if name == "soundfile":
            return FakeSoundFile
        return original_get_module(name, required=required)

    class FakeWeaveAudio:
        calls = []

        @classmethod
        def from_path(cls, path):
            cls.calls.append(("from_path", path))
            return {"kind": "audio-path", "path": path}

    monkeypatch.setattr(audio_module.util, "get_module", fake_get_module)
    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = wandb.Audio(np.array([0.0, 0.1]), sample_rate=2)

    result = unwrap_value(audio, "audio", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Audio values")
    assert result["kind"] == "audio-path"
    assert result["path"].suffix == ".wav"
    assert FakeWeaveAudio.calls == [("from_path", result["path"])]


def test_media_adapter_rejects_external_audio_reference(monkeypatch):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = wandb.Audio("https://example.com/audio.wav")

    with pytest.raises(
        TypeError,
        match="does not support external media references",
    ):
        unwrap_value(audio, "audio", unsupported_media_mode="raise")


def test_media_adapter_stubs_external_audio_reference(monkeypatch, mock_wandb_log):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = wandb.Audio("https://example.com/audio.wav")

    result = unwrap_value(audio, "audio", unsupported_media_mode="stub")

    mock_wandb_log.assert_warned(
        "External media references for wandb.Audio are not yet supported"
    )
    assert result == "[wandb.Audio external reference not yet supported]"


def test_media_adapter_rejects_media_without_local_path(monkeypatch):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = object.__new__(wandb.Audio)
    audio._path = None

    with pytest.raises(
        TypeError,
        match="does not have a local file path",
    ):
        unwrap_value(audio, "audio", unsupported_media_mode="raise")


def test_media_adapter_rejects_media_without_local_path_in_stub_mode(monkeypatch):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = object.__new__(wandb.Audio)
    audio._path = None

    with pytest.raises(
        TypeError,
        match="does not have a local file path",
    ):
        unwrap_value(audio, "audio", unsupported_media_mode="stub")


def test_media_adapter_rethrows_weave_audio_value_error(
    monkeypatch,
    mock_wandb_log,
    tmp_path,
):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            raise ValueError("unsupported audio")

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake-wave")
    audio = wandb.Audio(str(audio_path))

    with pytest.raises(
        TypeError,
        match="Cannot convert wandb.Audio in column 'audio' for Weave logging",
    ):
        unwrap_value(audio, "audio", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Audio values")


# Video


def _install_fake_moviepy_editor(monkeypatch, video_file_clip_cls):
    class FakeVideoClip:
        pass

    moviepy = types.ModuleType("moviepy")
    editor = types.ModuleType("moviepy.editor")
    editor.VideoClip = FakeVideoClip
    editor.VideoFileClip = video_file_clip_cls
    monkeypatch.setitem(sys.modules, "moviepy", moviepy)
    monkeypatch.setitem(sys.modules, "moviepy.editor", editor)


def test_media_adapter_video_path_uses_moviepy_video_file_clip(
    monkeypatch,
    mock_wandb_log,
    tmp_path,
):
    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    _install_fake_moviepy_editor(monkeypatch, FakeVideoFileClip)

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")
    video = wandb.Video(str(video_path))

    result = unwrap_value(video, "video", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Video values")
    assert isinstance(result, FakeVideoFileClip)
    assert result.path == str(video_path)


def test_media_adapter_video_path_requires_moviepy_editor(
    monkeypatch,
    mock_wandb_log,
    tmp_path,
):
    class FakeVideoFileClip:
        pass

    class FakeVideoClip:
        pass

    moviepy = types.ModuleType("moviepy")
    moviepy.VideoClip = FakeVideoClip
    moviepy.VideoFileClip = FakeVideoFileClip
    monkeypatch.setitem(sys.modules, "moviepy", moviepy)
    monkeypatch.delitem(sys.modules, "moviepy.editor", raising=False)

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")
    video = wandb.Video(str(video_path))

    with pytest.raises(ImportError) as exc_info:
        unwrap_value(video, "video", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Video values")
    message = str(exc_info.value)
    assert "moviepy.editor" in message
    assert 'wandb["eval-table-video-support"]' in message


def test_media_adapter_video_bytes_uses_moviepy_video_file_clip(
    monkeypatch,
    mock_wandb_log,
):
    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    _install_fake_moviepy_editor(monkeypatch, FakeVideoFileClip)

    video = wandb.Video(BytesIO(b"fake-video"), format="mp4")

    result = unwrap_value(video, "video", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Video values")
    assert isinstance(result, FakeVideoFileClip)
    assert result.path.endswith(".mp4")


def test_media_adapter_video_data_uses_moviepy_video_file_clip(
    monkeypatch,
    mock_wandb_log,
):
    from wandb.sdk.data_types import video as video_module

    np = pytest.importorskip("numpy")

    class FakeWandbImageSequenceClip:
        def __init__(self, frames, fps):
            self.frames = frames
            self.fps = fps

        def write_videofile(self, path, logger=None):
            with open(path, "wb") as f:
                f.write(b"fake-encoded-video")

    original_get_module = video_module.util.get_module

    def fake_get_module(name, required=None):
        if name == "moviepy.video.io.ImageSequenceClip":
            return types.SimpleNamespace(ImageSequenceClip=FakeWandbImageSequenceClip)
        return original_get_module(name, required=required)

    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    monkeypatch.setattr(video_module.util, "get_module", fake_get_module)
    _install_fake_moviepy_editor(monkeypatch, FakeVideoFileClip)

    frames = np.zeros((2, 3, 4, 4), dtype=np.uint8)
    video = wandb.Video(frames, format="mp4", fps=7)

    result = unwrap_value(video, "video", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Video values")
    assert isinstance(result, FakeVideoFileClip)
    assert result.path.endswith(".mp4")


def test_media_adapter_video_tensor_uses_moviepy_video_file_clip(
    monkeypatch,
    mock_wandb_log,
):
    from wandb.sdk.data_types import video as video_module

    np = pytest.importorskip("numpy")

    class FakeTensor:
        def __init__(self, data):
            self._data = data

        def numpy(self):
            return self._data

    class FakeWandbImageSequenceClip:
        def __init__(self, frames, fps):
            self.frames = frames
            self.fps = fps

        def write_videofile(self, path, logger=None):
            with open(path, "wb") as f:
                f.write(b"fake-encoded-video")

    original_get_module = video_module.util.get_module

    def fake_get_module(name, required=None):
        if name == "moviepy.video.io.ImageSequenceClip":
            return types.SimpleNamespace(ImageSequenceClip=FakeWandbImageSequenceClip)
        return original_get_module(name, required=required)

    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    monkeypatch.setattr(video_module.util, "get_module", fake_get_module)
    _install_fake_moviepy_editor(monkeypatch, FakeVideoFileClip)

    frames = np.zeros((2, 3, 4, 4), dtype=np.uint8)
    video = wandb.Video(FakeTensor(frames), format="mp4", fps=7)

    result = unwrap_value(video, "video", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Video values")
    assert isinstance(result, FakeVideoFileClip)
    assert result.path.endswith(".mp4")

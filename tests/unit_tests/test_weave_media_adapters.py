"""Unit tests for Weave media adapter helpers."""

from __future__ import annotations

import sys
import types
from io import BytesIO

import pytest
import wandb
from wandb.integration.weave.media_adapters import unwrap_value


def test_media_adapter_image_value_unwrapped_to_pil():
    from PIL import Image as PILImage

    pil_in = PILImage.new("RGB", (2, 2), color="red")
    image = wandb.Image(pil_in)

    with pytest.warns(UserWarning, match="wandb.Image values"):
        result = unwrap_value(image, "img", set())

    assert isinstance(result, PILImage.Image)
    assert result.size == (2, 2)


def test_media_adapter_rejects_external_image_reference():
    image = wandb.Image("https://example.com/image.png")

    with (
        pytest.warns(UserWarning, match="wandb.Image values"),
        pytest.raises(
            TypeError,
            match="Unsupported external media reference",
        ),
    ):
        unwrap_value(image, "img", set())


def test_media_adapter_rejects_unsupported_wandb_media():
    html = wandb.Html("<p>hi</p>")

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(html, "html", set())

    message = str(exc_info.value)
    assert "unsupported wandb media type 'Html'" in message
    assert "Only wandb.Image is currently supported" in message


def test_media_adapter_rejects_unsupported_wandb_value():
    histogram = wandb.Histogram([1, 2, 3])

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(histogram, "histogram", set())

    message = str(exc_info.value)
    assert "unsupported wandb value type 'Histogram'" in message
    assert "Only wandb.Image is currently supported" in message


def test_media_adapter_stubs_unsupported_wandb_media():
    html = wandb.Html("<p>hi</p>", inject=False)
    assert html._sha256 is not None
    expected_stub = f"[wandb.Html unsupported: {html._sha256[:8]}]"

    with pytest.warns(UserWarning, match="wandb.Html values are not supported"):
        result = unwrap_value(
            html,
            "html",
            set(),
            unsupported_media_mode="stub",
        )

    assert result == expected_stub


def test_media_adapter_stubs_unsupported_wandb_value_without_natural_hash():
    histogram = wandb.Histogram([1, 2, 3])

    with pytest.warns(UserWarning, match="wandb.Histogram values are not supported"):
        result = unwrap_value(
            histogram,
            "histogram",
            set(),
            unsupported_media_mode="stub",
        )

    assert result.startswith("[wandb.Histogram unsupported: ")
    assert result.endswith("]")
    digest = result.removeprefix("[wandb.Histogram unsupported: ").removesuffix("]")
    assert len(digest) == 8


def test_media_adapter_rejects_unknown_unsupported_media_mode():
    with pytest.raises(ValueError, match="unsupported_media_mode"):
        unwrap_value("plain text", "text", set(), unsupported_media_mode="ignore")


def test_media_adapter_rejects_external_audio_reference(monkeypatch):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = wandb.Audio("https://example.com/audio.wav")

    with (
        pytest.warns(UserWarning, match="wandb.Audio values"),
        pytest.raises(
            TypeError,
            match="Unsupported external media reference",
        ),
    ):
        unwrap_value(audio, "audio", set())


def test_media_adapter_rejects_media_without_local_path(monkeypatch):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = object.__new__(wandb.Audio)
    audio._path = None

    with (
        pytest.warns(UserWarning, match="wandb.Audio values"),
        pytest.raises(
            TypeError,
            match="does not have a local file path",
        ),
    ):
        unwrap_value(audio, "audio", set())


def test_media_adapter_rethrows_weave_audio_value_error(monkeypatch, tmp_path):
    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            raise ValueError("unsupported audio")

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake-wave")
    audio = wandb.Audio(str(audio_path))

    with (
        pytest.warns(UserWarning, match="wandb.Audio values"),
        pytest.raises(
            TypeError,
            match="Cannot convert wandb.Audio in column 'audio' for Weave logging",
        ),
    ):
        unwrap_value(audio, "audio", set())


def test_media_adapter_audio_path_uses_weave_audio_from_path(monkeypatch, tmp_path):
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

    with pytest.warns(UserWarning, match="wandb.Audio values"):
        result = unwrap_value(audio, "audio", set())

    assert result == {"kind": "audio-path", "path": audio_path}
    assert FakeWeaveAudio.calls == [("from_path", audio_path)]


def test_media_adapter_audio_data_uses_weave_audio_from_path(monkeypatch):
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

    with pytest.warns(UserWarning, match="wandb.Audio values"):
        result = unwrap_value(audio, "audio", set())

    assert result["kind"] == "audio-path"
    assert result["path"].suffix == ".wav"
    assert FakeWeaveAudio.calls == [("from_path", result["path"])]


def _install_fake_weave(monkeypatch, **attrs):
    module = types.ModuleType("weave")
    module.__path__ = []
    module.__version__ = "999.0.0"
    for name, value in attrs.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, "weave", module)
    return module


def _install_fake_weave_video_handler(monkeypatch):
    from unittest.mock import MagicMock

    ensure_registered = MagicMock()

    weave_module = _install_fake_weave(monkeypatch)
    type_handlers_module = types.ModuleType("weave.type_handlers")
    type_handlers_module.__path__ = []
    video_package = types.ModuleType("weave.type_handlers.Video")
    video_package.__path__ = []
    video_module = types.ModuleType("weave.type_handlers.Video.video")
    video_module._ensure_registered = ensure_registered

    weave_module.type_handlers = type_handlers_module
    type_handlers_module.Video = video_package
    video_package.video = video_module

    monkeypatch.setitem(sys.modules, "weave.type_handlers", type_handlers_module)
    monkeypatch.setitem(sys.modules, "weave.type_handlers.Video", video_package)
    monkeypatch.setitem(sys.modules, "weave.type_handlers.Video.video", video_module)

    return ensure_registered


def _install_fake_moviepy_editor(monkeypatch, video_file_clip_cls):
    class FakeVideoClip:
        pass

    moviepy = types.ModuleType("moviepy")
    editor = types.ModuleType("moviepy.editor")
    editor.VideoClip = FakeVideoClip
    editor.VideoFileClip = video_file_clip_cls
    monkeypatch.setitem(sys.modules, "moviepy", moviepy)
    monkeypatch.setitem(sys.modules, "moviepy.editor", editor)


def test_media_adapter_video_path_uses_moviepy_video_file_clip(monkeypatch, tmp_path):
    ensure_video_registered = _install_fake_weave_video_handler(monkeypatch)

    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    _install_fake_moviepy_editor(monkeypatch, FakeVideoFileClip)

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")
    video = wandb.Video(str(video_path))

    with pytest.warns(UserWarning, match="wandb.Video values"):
        result = unwrap_value(video, "video", set())

    assert isinstance(result, FakeVideoFileClip)
    assert result.path == str(video_path)
    ensure_video_registered.assert_called_once_with()


def test_media_adapter_video_path_requires_moviepy_editor(monkeypatch, tmp_path):
    _install_fake_weave_video_handler(monkeypatch)

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

    with (
        pytest.warns(UserWarning, match="wandb.Video values"),
        pytest.raises(ImportError, match="moviepy.editor"),
    ):
        unwrap_value(video, "video", set())


def test_media_adapter_video_bytes_uses_moviepy_video_file_clip(monkeypatch):
    ensure_video_registered = _install_fake_weave_video_handler(monkeypatch)

    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    _install_fake_moviepy_editor(monkeypatch, FakeVideoFileClip)

    video = wandb.Video(BytesIO(b"fake-video"), format="mp4")

    with pytest.warns(UserWarning, match="wandb.Video values"):
        result = unwrap_value(video, "video", set())

    assert isinstance(result, FakeVideoFileClip)
    assert result.path.endswith(".mp4")
    ensure_video_registered.assert_called_once_with()


def test_media_adapter_video_data_uses_moviepy_video_file_clip(monkeypatch):
    from wandb.sdk.data_types import video as video_module

    ensure_video_registered = _install_fake_weave_video_handler(monkeypatch)

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

    with pytest.warns(UserWarning, match="wandb.Video values"):
        result = unwrap_value(video, "video", set())

    assert isinstance(result, FakeVideoFileClip)
    assert result.path.endswith(".mp4")
    ensure_video_registered.assert_called_once_with()

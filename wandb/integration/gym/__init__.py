from __future__ import annotations

import os
import re
from typing import Literal

import wandb
import wandb.util

_gym_version_lt_0_26: bool | None = None
_gymnasium_version_lt_1_0_0: bool | None = None

_required_error_msg = (
    "Couldn't import the gymnasium python package, install with `pip install gymnasium`"
)
GymLib = Literal["gym", "gymnasium"]


def _patch_gymnasium_video_recorder(
    recorder, path: str, gym_lib: str, wrapper_name: str
) -> None:
    """Patch gymnasium.wrappers.monitoring.video_recorder.VideoRecorder (older gymnasium)."""
    recorder.orig_close = recorder.close

    def close(self):
        recorder.orig_close(self)
        if not self.enabled:
            return
        if wandb.run:
            video_path = getattr(self, path, None)
            if video_path is None and path == "path":
                video_path = getattr(self, "base_path", None)
                if video_path is not None:
                    video_path = video_path + ".mp4"
                    if not os.path.isfile(video_path):
                        video_path = None
            if video_path:
                m = re.match(r".+(video\.\d+).+", video_path)
                key = m.group(1) if m else "videos"
                wandb.log({key: wandb.Video(video_path)})

    def del_(self):
        self.orig_close()

    recorder.close = close
    if getattr(recorder, "__del__", None) is not None:
        recorder.__del__ = del_
    wandb.patched["gym"].append([f"{gym_lib}.wrappers.{wrapper_name}", "close"])


def _patch_gymnasium_record_video_rendering(record_video_class, gym_lib: str) -> None:
    """Patch gymnasium.wrappers.rendering.RecordVideo (gymnasium 1.2+). stop_recording writes the file; we capture path before orig clears _video_name, then upload after."""
    record_video_class.orig_stop_recording = record_video_class.stop_recording

    def stop_recording_wrapper(self):
        video_folder = getattr(self, "video_folder", None)
        video_name = getattr(self, "_video_name", None)
        record_video_class.orig_stop_recording(self)
        if wandb.run and video_folder and video_name:
            path = os.path.join(video_folder, f"{video_name}.mp4")
            if os.path.isfile(path):
                m = re.match(r".+(video\.\d+).+", path)
                key = m.group(1) if m else "videos"
                wandb.log({key: wandb.Video(path)})

    record_video_class.stop_recording = stop_recording_wrapper


def monitor():
    """Monitor a gym environment.

    Supports both gym and gymnasium.
    """
    gym_lib: GymLib | None = None

    # gym is not maintained anymore, gymnasium is the drop-in replacement - prefer it
    if wandb.util.get_module("gymnasium") is not None:
        gym_lib = "gymnasium"
    elif wandb.util.get_module("gym") is not None:
        gym_lib = "gym"

    if gym_lib is None:
        raise wandb.Error(_required_error_msg)

    global _gym_version_lt_0_26
    global _gymnasium_version_lt_1_0_0

    if _gym_version_lt_0_26 is None or _gymnasium_version_lt_1_0_0 is None:
        if gym_lib == "gym":
            import gym
        else:
            import gymnasium as gym  # type: ignore

        from packaging.version import parse

        gym_lib_version = parse(gym.__version__)
        _gym_version_lt_0_26 = gym_lib_version < parse("0.26.0")
        _gymnasium_version_lt_1_0_0 = gym_lib_version < parse("1.0.0a1")

    path = "path"  # Default path
    if gym_lib == "gymnasium" and not _gymnasium_version_lt_1_0_0:
        # Gymnasium >= 1.0: try monitoring.video_recorder (older) first; if missing (e.g. 1.2+),
        # patch RecordVideo in rendering and hook stop_recording to upload after save.
        vcr = wandb.util.get_module(
            f"{gym_lib}.wrappers.monitoring.video_recorder",
            required=None,
        )
        if vcr is not None:
            vcr_recorder_attribute = "VideoRecorder"
            recorder = getattr(vcr, vcr_recorder_attribute)
            wrapper_name = f"monitoring.video_recorder.{vcr_recorder_attribute}"
            _patch_gymnasium_video_recorder(
                recorder,
                path,
                gym_lib,
                wrapper_name,
            )
            return
        # No monitoring.video_recorder (e.g. gymnasium 1.2+): patch RecordVideo in rendering.
        rendering = wandb.util.get_module(
            f"{gym_lib}.wrappers.rendering",
            required=_required_error_msg,
        )
        record_video = rendering.RecordVideo
        _patch_gymnasium_record_video_rendering(record_video, gym_lib)
        wandb.patched["gym"].append(
            [f"{gym_lib}.wrappers.rendering.RecordVideo", "stop_recording"],
        )
        return
    else:
        vcr = wandb.util.get_module(
            f"{gym_lib}.wrappers.monitoring.video_recorder",
            required=_required_error_msg,
        )
        # Breaking change in gym 0.26.0
        if _gym_version_lt_0_26:
            vcr_recorder_attribute = "ImageEncoder"
            recorder = getattr(vcr, vcr_recorder_attribute)
            path = "output_path"  # Override path for older gym versions
        else:
            vcr_recorder_attribute = "VideoRecorder"
            recorder = getattr(vcr, vcr_recorder_attribute)
        wrapper_name = f"monitoring.video_recorder.{vcr_recorder_attribute}"

    recorder.orig_close = recorder.close

    def close(self):
        recorder.orig_close(self)
        if not self.enabled:
            return
        if wandb.run:
            video_path = getattr(self, path, None)
            if video_path is None and path == "path":
                # Gymnasium VideoRecorder may use base_path; output is base_path + ".mp4"
                video_path = getattr(self, "base_path", None)
                if video_path is not None:
                    video_path = video_path + ".mp4"
                    if not os.path.isfile(video_path):
                        video_path = None
            if video_path:
                m = re.match(r".+(video\.\d+).+", video_path)
                key = m.group(1) if m else "videos"
                wandb.log({key: wandb.Video(video_path)})

    def del_(self):
        self.orig_close()

    if not _gym_version_lt_0_26:
        recorder.__del__ = del_
    recorder.close = close

    wandb.patched["gym"].append(
        [
            f"{gym_lib}.wrappers.{wrapper_name}",
            "close",
        ]
    )

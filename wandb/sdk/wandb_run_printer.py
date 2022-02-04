import json
import logging
import numbers
import os
import time
from typing import Optional, TYPE_CHECKING

import wandb

from .lib import ipython, printer


if TYPE_CHECKING:
    from .wandb_settings import Settings
    from wandb.sdk.interface.interface import InterfaceBase
    from wandb.proto.wandb_internal_pb2 import (
        CheckVersionResponse,
        FilePusherStats,
        PollExitResponse,
    )
    from .lib.reporting import Reporter


logger = logging.getLogger("wandb")


class RunPrinter:
    _poll_exit_response: Optional["PollExitResponse"]
    _check_version: Optional["CheckVersionResponse"]
    _settings: "Settings"
    _reporter: Optional["Reporter"]

    def __init__(self, settings: "Settings") -> None:
        self._check_version = None
        self._poll_exit_response = None

        self._settings = settings
        self._printer = printer.get_printer(self._settings._jupyter)

        self._html = self._settings._jupyter and ipython.in_jupyter()
        self._reporter = None

    def __call__(self, settings: "Settings") -> None:
        self._settings = settings

    def _display_on_init(self, interface: "InterfaceBase") -> None:
        logger.info("communicating current version")
        check = interface.communicate_check_version(current_version=wandb.__version__)
        if check:
            self._check_version = check
            logger.info(f"got version response {check}")
        self._append_version_check_info()
        self._printer.display()

    def _display_on_start(self,) -> None:
        self._append_header_offline_sync_info()
        self._append_header_wandb_version_info()
        self._append_header_run_info()
        self._append_header_sync_dir_info()
        self._printer.display()
        print("")

    def _display_on_finish(
        self,
        exit_code: Optional[int],
        quiet: Optional[bool],
        interface: "InterfaceBase",
    ) -> None:

        self._display_footer_exit_status(exit_code, quiet)
        # Wait for data to be synced
        self._poll_exit_response = self._display_footer_file_upload_info(interface)

        self._append_footer_history_summary_info(interface, quiet)

    def _display_on_final(self, quiet: Optional[bool],) -> None:

        self._append_footer_reporter_warn_err(quiet)

        self._append_footer_file_sync_info()
        self._append_footer_run_sync_info()
        self._append_footer_offline_sync_info(quiet)
        self._append_footer_logging_dir_info(quiet)

        if not quiet and not self._settings._offline:
            self._append_version_check_info(footer=True)
            self._append_footer_local_warn()

        self._printer.display()

    def _append_version_check_info(self, footer: bool = None) -> None:
        if not self._check_version:
            return

        package_problem = False
        if self._check_version.delete_message:
            self._printer._errors.append(self._check_version.delete_message)
            package_problem = True
        elif self._check_version.yank_message:
            self._printer._warnings.append(self._check_version.yank_message)
            package_problem = True
        # only display upgrade message if packages are bad or in header
        if not footer or package_problem:
            if self._check_version.upgrade_message:
                self._printer._info.append(self._check_version.upgrade_message)

    def _append_header_wandb_version_info(self) -> None:

        if self._settings._quiet or self._settings._silent:
            return

        self._printer._info.append(
            f"Tracking run with wandb version {wandb.__version__}"
        )

    def _append_header_offline_sync_info(self) -> None:
        if self._settings._quiet or not self._settings._offline:
            return

        # TODO: make offline mode in jupyter use HTML
        self._printer._info.extend(
            [
                f"W&B syncing is set to {self._printer.code('`offline`')} in this directory.  ",
                f"Run {self._printer.code('`wandb online`')} or set {self._printer.code('WANDB_MODE=online')} to enable cloud syncing.",
            ]
        )

    def _append_footer_offline_sync_info(self, quiet: Optional[bool]) -> None:
        if quiet or not self._settings._offline:
            return

        self._printer._info.extend(
            [
                "You can sync this run to the cloud by running:",
                self._printer.code(f"wandb sync {self._settings['sync_dir']}"),
            ]
        )

    def _append_header_sync_dir_info(self) -> None:

        if self._settings._quiet or self._settings._silent:
            return

        self._printer._info.append(
            f"Run data is saved locally in {self._printer.files(self._settings.sync_dir)}"
        )
        if not self._settings._offline and not self._html:
            self._printer._info.append(
                f"Run {self._printer.code('`wandb offline`')} to turn off syncing."
            )

    def _append_footer_file_sync_info(self) -> None:

        if self._settings._silent or self._settings._offline:
            return

        if not self._poll_exit_response or not self._poll_exit_response.file_counts:
            return

        logger.info("logging synced files")
        file_counts = self._poll_exit_response.file_counts
        self._printer._info.append(
            f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), {file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)"
        )

    def _append_footer_run_sync_info(self) -> None:
        if not (self._settings.run_url and self._settings.run_name):
            return

        self._printer._info.append(
            f"Synced {self._printer.name(self._settings.run_name)}: {self._printer.link(self._settings.run_url)}"
        )

    def _append_header_run_info(self,) -> None:

        if self._settings._offline or self._settings._silent:
            return

        run_url = self._settings.run_url
        project_url = self._settings.project_url
        sweep_url = self._settings.sweep_url

        run_state_str = "Resuming run" if self._settings.resumed else "Syncing run"
        run_name = self._settings.run_name

        if self._html:
            if not wandb.jupyter.maybe_display():

                run_line = f"<strong>{self._printer.link(run_url, run_name)}</strong>"
                project_line, sweep_line = "", ""

                # TODO(settings): make settings the source of truth
                if not wandb.jupyter.quiet():

                    doc_html = self._printer.link("https://wandb.me/run", "docs")

                    project_html = self._printer.link(project_url, "Weights & Biases")
                    project_line = f"to {project_html} ({doc_html})"

                    if sweep_url:
                        sweep_line = (
                            f"Sweep page:  {self._printer.link(sweep_url, sweep_url)}"
                        )

                self._printer._info.extend(
                    [f"{run_state_str} {run_line} {project_line}", sweep_line]
                )

        else:
            self._printer._info.append(
                f"{run_state_str} {self._printer.name(run_name)}"
            )
            if not self._settings._quiet:
                self._printer._info.append(
                    f'{self._printer.emoji("star")} View project at {self._printer.link(project_url)}'
                )
                if sweep_url:
                    self._printer._info.append(
                        f'{self._printer.emoji("broom")} View sweep at {self._printer.link(sweep_url)}'
                    )
            self._printer._info.append(
                f'{self._printer.emoji("rocket")} View run at {self._printer.link(run_url)}'
            )

            if self._settings.anonymous == "true":
                self._printer._warnings.append(
                    "Do NOT share these links with anyone. They can be used to claim your runs."
                )

    def _display_footer_exit_status(
        self, exit_code: Optional[int], quiet: Optional[bool]
    ) -> None:
        if self._settings._silent:
            return

        info = ["Waiting for W&B process to finish..."]
        status = "(success)." if not exit_code else f"(failed {exit_code})."
        info.append(self._printer.status(status, bool(exit_code)))

        if not self._settings._offline and exit_code:
            info.append("Press ctrl-c to abort syncing.")

        self._printer._info.append(f'{" ".join(info)}')
        self._printer.display()

    def _dispaly_file_pusher_status_info(
        self, progress: "FilePusherStats", done: Optional[bool] = False,
    ) -> None:

        if self._settings._offline:
            return

        megabyte = wandb.util.POW_2_BYTES[2][1]
        line = f"{progress.uploaded_bytes/megabyte :.2f} MB of {progress.total_bytes/megabyte:.2f} MB uploaded ({progress.deduped_bytes/megabyte:.2f} MB deduped)\r"

        percent_done = (
            1.0
            if progress.total_bytes == 0
            else progress.uploaded_bytes / progress.total_bytes
        )

        self._printer.progress_update(line, percent_done)
        if done:
            self._printer.progress_close()

            dedupe_fraction = (
                progress.deduped_bytes / float(progress.total_bytes)
                if progress.total_bytes > 0
                else 0
            )
            if dedupe_fraction > 0.01:
                self._printer._info.append(
                    f"W&B sync reduced upload amount by {dedupe_fraction * 100:.1f}%             "
                )
            self._printer.display()

    def _display_footer_file_upload_info(
        self, interface: "InterfaceBase"
    ) -> "PollExitResponse":
        while True:
            if interface:
                poll_exit_resp = interface.communicate_poll_exit()
            logger.info(f"got exit ret: {poll_exit_resp}")

            if poll_exit_resp:
                done = poll_exit_resp.done
                pusher_stats = poll_exit_resp.pusher_stats
                if pusher_stats:
                    self._dispaly_file_pusher_status_info(pusher_stats, done=done)
                if done:
                    return poll_exit_resp
            time.sleep(0.1)

    def _render_history_info(self, interface: "InterfaceBase") -> Optional[str]:

        history = interface.communicate_sampled_history()

        if not history:
            return None

        sampled_history = {
            item.key: item.values_float or item.values_int for item in history.item
        }

        logger.info("rendering history")
        history_rows = []
        for key, values in sorted(sampled_history.items()):
            if key.startswith("_"):
                continue
            downsampled_values = wandb.util.downsample(values, 40)
            if any(
                (not isinstance(value, numbers.Number) for value in downsampled_values)
            ):
                continue
            sparkline = self._printer.sparklines(downsampled_values)
            if sparkline:
                history_rows.append([key, sparkline])
        if not history_rows:
            return None
        return self._printer.grid(history_rows, "Run history:")

    def _render_summary_info(self, interface: "InterfaceBase") -> Optional[str]:

        summary = interface.communicate_get_summary()

        if not summary:
            return None

        final_summary = {item.key: json.loads(item.value_json) for item in summary.item}

        logger.info("rendering summary")
        summary_rows = []
        for key, value in sorted(final_summary.items()):
            # arrays etc. might be too large. for now we just don't print them
            if key.startswith("_"):
                continue
            if isinstance(value, str):
                value = value[:20] + "..." * (len(value) >= 20)
                summary_rows.append([key, value])
            elif isinstance(value, numbers.Number):
                value = round(value, 5) if isinstance(value, float) else value
                summary_rows.append([key, str(value)])
            else:
                continue
        if not summary_rows:
            return None

        return self._printer.grid(summary_rows, "Run summary:")

    def _append_footer_history_summary_info(
        self, interface: "InterfaceBase", quiet: Optional[bool]
    ) -> None:

        if quiet or not interface:
            return

        panel = []
        history = self._render_history_info(interface)
        if history:
            panel.append(history)

        summary = self._render_summary_info(interface)
        if summary:
            panel.append(summary)

        if not panel:
            return

        self._printer._info.append(self._printer.panel(panel))

    def _append_footer_local_warn(self) -> None:
        if not self._poll_exit_response or not self._poll_exit_response.local_info:
            return

        if self._settings.is_local:
            local_info = self._poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                self._printer._warnings.append(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: {self._printer.link('http://wandb.me/local-upgrade')}"
                )

    def _append_footer_reporter_warn_err(self, quiet: Optional[bool]) -> None:

        if quiet or not self._reporter:
            return

        warning_lines = self._reporter.warning_lines
        if warning_lines:
            self._printer._warnings.append("Warnings:")
            self._printer._warnings.extend([f"{line}" for line in warning_lines])
            if len(warning_lines) < self._reporter.warning_count:
                self._printer._warnings.append("More warnings...")

        error_lines = self._reporter.error_lines
        if error_lines:
            self._printer._errors.append("Errors:")
            self._printer._errors.extend([f"{line}" for line in error_lines])
            if len(error_lines) < self._reporter.error_count:
                self._printer._errors.append("More errors...")

    def _append_footer_logging_dir_info(self, quiet: Optional[bool]) -> None:

        log_dir = self._settings.log_user or self._settings.log_internal

        if quiet or not log_dir:
            return

        log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))

        self._printer._info.append(f"Find logs at: {self._printer.files(log_dir)}")

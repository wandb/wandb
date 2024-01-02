import filecmp
import itertools
import json
import numbers
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime as dt
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from unittest.mock import patch

import filelock
import numpy as np
import polars as pl
import requests
import urllib3
import yaml
from wandb_gql import gql

import wandb
from wandb.apis.public import Run
from wandb.sdk.artifacts.artifacts_cache import get_artifacts_cache
from wandb.util import coalesce, remove_keys_with_none_values

from . import internal, progress, protocols
from .config import Namespace
from .logs import _thread_local_settings, import_logger, wandb_logger
from .protocols import ArtifactSequence, parallelize
from .utils import _merge_dfs

with patch("click.echo"):
    import wandb.apis.reports as wr
    from wandb.apis.reports import Report


Artifact = wandb.Artifact
Api = wandb.Api
Project = wandb.apis.public.Project

ARTIFACTS_ERRORS_JSONL_FNAME = "import_artifact_errors.jsonl"
ARTIFACTS_PREVIOUSLY_CHECKED_JSONL_FNAME = "import_artifact_validation_success.jsonl"
RUNS_ERRORS_JSONL_FNAME = "import_run_errors.jsonl"
RUNS_PREVIOUSLY_CHECKED_JSONL_FNAME = "import_run_validation_success.jsonl"

ART_SEQUENCE_DUMMY_PLACEHOLDER = "__ART_SEQUENCE_DUMMY_PLACEHOLDER__"
RUN_DUMMY_PLACEHOLDER = "__RUN_DUMMY_PLACEHOLDER__"

target_size = 80 * 1024**3  # 80GB


class WandbRun:
    def __init__(self, run: Run) -> None:
        self.run = run
        self.api = wandb.Api(
            api_key=_thread_local_settings.src_api_key,
            overrides={"base_url": _thread_local_settings.src_base_url},
        )
        self.dst_api = wandb.Api(
            api_key=_thread_local_settings.dst_api_key,
            overrides={"base_url": _thread_local_settings.dst_base_url},
        )

        _thread_local_settings.src_entity = self.entity()
        _thread_local_settings.src_project = self.project()
        _thread_local_settings.src_run_id = self.run_id()

        # For caching
        self._files: Optional[Iterable[Tuple[str, str]]] = None
        self._artifacts: Optional[Iterable[Artifact]] = None
        self._used_artifacts: Optional[Iterable[Artifact]] = None
        self._parquet_history_paths: Optional[Iterable[str]] = None

    def run_id(self) -> str:
        return self.run.id

    def entity(self) -> str:
        return self.run.entity

    def project(self) -> str:
        return self.run.project

    def config(self) -> Dict[str, Any]:
        return self.run.config

    def summary(self) -> Dict[str, float]:
        s = self.run.summary
        s = self._modify_table_artifact_paths(s)
        return s

    def metrics(self) -> Iterable[Dict[str, float]]:
        if self._parquet_history_paths is None:
            self._parquet_history_paths = list(self._get_parquet_history_paths())

        if self._parquet_history_paths:
            yield from self._get_metrics_from_parquet_history_paths()
        else:
            yield from self._get_metrics_from_scan_history_fallback()

    def run_group(self) -> Optional[str]:
        return self.run.group

    def job_type(self) -> Optional[str]:
        return self.run.job_type

    def display_name(self) -> str:
        return self.run.display_name

    def notes(self) -> Optional[str]:
        # Notes includes the previous notes and serves as a catch-all for things we missed or can't add back
        previous_link = f"Imported from: {self.run.url}"
        previous_author = f"Author: {self.run.user.username}"

        header = [previous_link, previous_author]
        previous_notes = self.run.notes or ""

        return "\n".join(header) + "\n---\n" + previous_notes

    def tags(self) -> Optional[List[str]]:
        return self.run.tags

    def artifacts(self) -> Optional[Iterable[Artifact]]:
        if self._artifacts is not None:
            yield from self._artifacts
            return

        try:
            self._artifacts = list(self.run.logged_artifacts())
        except Exception as e:
            self._log_error(f"Error downloading artifacts -- {e}")
            return []

        new_arts = []
        for art in self._artifacts:
            new_art = self._download_and_process_artifact(art)
            if new_art:
                new_arts.append(new_art)
                yield new_art

        self._artifacts = new_arts

    def used_artifacts(self) -> Optional[Iterable[Artifact]]:
        if self._used_artifacts is not None:
            yield from self._used_artifacts
            return

        try:
            self._used_artifacts = list(self.run.used_artifacts())
        except Exception as e:
            self._log_error(f"Error downloading used artifacts -- {e}")
            return []

        new_arts = []
        for art in self._used_artifacts:
            new_art = self._download_and_process_artifact(art)
            if new_art:
                new_arts.append(new_art)
                yield new_art

        self._used_artifacts = new_arts

    def os_version(self) -> Optional[str]:
        ...

    def python_version(self) -> Optional[str]:
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())
            return result.get("python")

    def cuda_version(self) -> Optional[str]:
        ...

    def program(self) -> Optional[str]:
        ...

    def host(self) -> Optional[str]:
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())
            return result.get("host")

    def username(self) -> Optional[str]:
        ...

    def executable(self) -> Optional[str]:
        ...

    def gpus_used(self) -> Optional[str]:
        ...

    def cpus_used(self) -> Optional[int]:  # can we get the model?
        ...

    def memory_used(self) -> Optional[int]:
        ...

    def runtime(self) -> Optional[int]:
        wandb_runtime = self.run.summary.get("_wandb", {}).get("runtime")
        base_runtime = self.run.summary.get("_runtime")

        t = coalesce(wandb_runtime, base_runtime)
        if t is None:
            return t
        return int(t)

    def start_time(self) -> Optional[int]:
        t = dt.fromisoformat(self.run.created_at).timestamp() * 1000
        return int(t)

    def code_path(self) -> Optional[str]:
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())
            return "code/" + result.get("codePath", "")

    def cli_version(self) -> Optional[str]:
        fname = self._find_in_files("config.yaml")
        if fname is None:
            return None

        with open(fname) as f:
            result = yaml.safe_load(f)
            if result is None:
                return ""

            return result.get("_wandb", {}).get("value", {}).get("cli_version")

    def files(self) -> Optional[Iterable[Tuple[str, str]]]:
        if self._files is not None:
            yield from self._files
            return

        files_dir = f"./wandb-importer/{self.run_id()}/files"

        self._files = []
        for f in self.run.files():
            if self._should_skip_file(f):
                continue

            file_and_policy = self._download_and_log_file(f, files_dir)
            if file_and_policy:
                self._files.append(file_and_policy)
                yield file_and_policy

    def _should_skip_file(self, f) -> bool:
        # Don't carry over empty files
        if f.size == 0:
            return True

        # Skip deadlist to avoid overloading S3
        if "wandb_manifest.json.deadlist" in f.name:
            return True

        return False

    def logs(self) -> Optional[Iterable[str]]:
        fname = self._find_in_files("output.log")
        if fname is None:
            return

        with open(fname) as f:
            yield from f.readlines()

    def _get_metrics_df_from_parquet_history_paths(self) -> None:
        if self._parquet_history_paths is None:
            self._parquet_history_paths = list(self._get_parquet_history_paths())

        if not self._parquet_history_paths:
            # unfortunately, it's not feasible to validate non-parquet history
            return pl.DataFrame()

        dfs = []
        for path in self._parquet_history_paths:
            for p in Path(path).glob("*.parquet"):
                df = pl.read_parquet(p)
                dfs.append(df)

        return _merge_dfs(dfs).sort("_step")

    def _get_metrics_from_parquet_history_paths(self) -> Iterable[Dict[str, Any]]:
        df = self._get_metrics_df_from_parquet_history_paths()
        if "_step" in df:
            df = df.with_columns(pl.col("_step").cast(pl.Int64))
        for row in df.iter_rows(named=True):
            row = remove_keys_with_none_values(row)
            row = self._modify_table_artifact_paths(row)
            yield row

    def _get_metrics_from_scan_history_fallback(self) -> Iterable[Dict[str, Any]]:
        self._log_warning("No parquet files detected; using scan history")

        hist = list(self.run.scan_history())
        try:
            df = pl.DataFrame(hist).sort("_step")
        except Exception as e:
            import_logger.error(f"problem with scan history {e=}")
            rows = hist
        else:
            rows = df.iter_rows(named=True)

        for row in rows:
            row = remove_keys_with_none_values(row)
            row = self._modify_table_artifact_paths(row)
            yield row

    def _get_parquet_history_paths(self) -> List[str]:
        paths = []
        if not self._artifacts:
            try:
                self._artifacts = list(self.run.logged_artifacts())
            except Exception as e:
                import_logger.error(f"exeception downloading metrics artifacts {e=}")
                wandb_logger.error(
                    f"Error downloading metrics artifacts -- {e}",
                    extra={
                        "entity": self.entity(),
                        "project": self.project(),
                        "run_id": self.run_id(),
                    },
                )
                return []

        for art in self._artifacts:
            if art.type != "wandb-history":
                continue
            with patch("click.echo"):
                try:
                    cleanup_cache()
                    path = art.download(root=f"./artifacts/src/{art.name}", cache=False)
                except Exception as e:
                    import_logger.error(
                        f"exeception downloading metrics artifacts {e=}"
                    )
                    wandb_logger.error(
                        f"Error downloading metrics artifact ({art}) -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                    continue
                paths.append(path)
        return paths

    def _modify_table_artifact_paths(self, row: Dict[str, Any]) -> Dict[str, Any]:
        # Modify artifact paths because they are different between systems
        table_keys = []
        for k, v in row.items():
            if isinstance(v, (dict)) and v.get("_type") == "table-file":
                table_keys.append(k)

        for table_key in table_keys:
            obj = row[table_key]["artifact_path"]
            obj_name = obj.split("/")[-1]

            new_table_key = table_key.replace("/", "")
            art_path = f"{self.entity()}/{self.project()}/run-{self.run_id()}-{new_table_key}:latest"
            art = None
            # Try to pick up the artifact within 6 seconds
            for _ in range(3):
                try:
                    art = self.dst_api.artifact(art_path, type="run_table")
                except wandb.errors.CommError:
                    wandb.termwarn(f"Waiting for artifact {art_path}...")
                    time.sleep(2)
                except Exception as e:
                    wandb_logger.error(
                        f"Error getting back artifact -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                    import_logger.error(f"Error getting table artifact {e=}")
                else:
                    break

            # If we can't find after timeout, just skip it.
            if art is None:
                wandb_logger.error(
                    "Error getting back artifact -- Timeout exceeded",
                    extra={
                        "entity": self.entity(),
                        "project": self.project(),
                        "run_id": self.run_id(),
                    },
                )
                continue

            url = art.get_path(obj_name).ref_url()
            base, name = url.rsplit("/", 1)
            latest_art_path = f"{base}:latest/{name}"

            # replace the old url which points to an artifact on the old system
            # with a new url which points to an artifact on the new system.
            row[table_key]["artifact_path"] = url
            row[table_key]["_latest_artifact_path"] = latest_art_path

        return row

    def _find_in_files(self, name: str) -> Optional[str]:
        files = self.files()
        if files is None:
            return None

        for path, _ in files:
            if name in path:
                return path

        return None

    def _log_error(self, msg: str):
        wandb_logger.error(
            msg,
            extra={
                "entity": self.entity(),
                "project": self.project(),
                "run_id": self.run_id(),
            },
        )

    def _log_warning(self, msg: str):
        wandb_logger.warn(
            msg,
            extra={
                "entity": self.entity(),
                "project": self.project(),
                "run_id": self.run_id(),
            },
        )

    def _download_and_process_artifact(self, art: Artifact) -> Optional[Artifact]:
        with patch("click.echo"):
            try:
                cleanup_cache()
                path = art.download(root=f"./artifacts/src/{art.name}", cache=False)
            except Exception as e:
                self._log_error(f"Error downloading artifact ({art}) -- {e}")
                return None

            new_art = _make_new_art(art)
            if Path(path).is_dir():
                new_art.add_dir(path)

        return new_art

    def _download_and_log_file(self, f, files_dir) -> Optional[Tuple[str, str]]:
        try:
            result = f.download(files_dir, exist_ok=True, timeout=60)
        except Exception as e:
            self.log_error(f"Error downloading file ({f}) -- {e}")
            return None

        return (result.name, "now")


class WandbImporter:
    """Import runs, reports, and artifact sequences from a source instance at `src_base_url` to a destination instance at `dst_base_url`."""

    def __init__(
        self,
        src_base_url: str,
        src_api_key: str,
        dst_base_url: str,
        dst_api_key: str,
        *,
        custom_api_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.src_base_url = src_base_url
        self.src_api_key = src_api_key
        self.dst_base_url = dst_base_url
        self.dst_api_key = dst_api_key

        # this login is neccessary for files because they assume you are logged in to download them.
        wandb.login(key=src_api_key, host=src_base_url)

        if custom_api_kwargs is None:
            custom_api_kwargs = {}

        self.src_api = wandb.Api(
            api_key=src_api_key,
            overrides={"base_url": src_base_url},
            timeout=600,
            **custom_api_kwargs,
        )
        self.dst_api = wandb.Api(
            api_key=dst_api_key,
            overrides={"base_url": dst_base_url},
            timeout=600,
            **custom_api_kwargs,
        )

        # There is probably a better way of doing this
        _thread_local_settings.src_api_key = src_api_key
        _thread_local_settings.src_base_url = src_base_url
        _thread_local_settings.dst_api_key = dst_api_key
        _thread_local_settings.dst_base_url = dst_base_url

    def __repr__(self):
        return "W&B Importer"

    import_runs = protocols.import_runs

    def _import_run(
        self,
        run: WandbRun,
        *,
        namespace: Optional[Namespace] = None,
        metadata: bool = True,
        files: bool = True,
        media: bool = True,
        code: bool = True,
        history: bool = True,
        summary: bool = True,
        terminal_output: bool = True,
    ) -> None:
        """Import one WandbRun.

        Use `namespace` to specify alternate settings like where the run should be uploaded
        """
        if namespace is None:
            namespace = Namespace(run.entity(), run.project())

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
        }

        sm_config = internal.SendManagerConfig(
            metadata=metadata,
            files=files,
            media=media,
            code=code,
            history=history,
            summary=summary,
            terminal_output=terminal_output,
        )

        run_str = f"{run.entity()}/{run.project()}/{run.run_id()}"
        t = progress.subsubtask_pbar.add_task(f"Upload history ({run_str})", total=None)
        internal.send_run_with_send_manager(
            run,
            overrides=namespace.send_manager_overrides,
            settings_override=settings_override,
            config=sm_config,
        )
        import_logger.info(f"W&B Importer: Finished uploading history ({run_str})")
        progress.subsubtask_pbar.remove_task(t)

        if history:
            t = progress.subsubtask_pbar.add_task(
                f"Collect history artifacts ({run_str})", total=None
            )
            history_arts = []
            for a in run.artifacts():
                if a.type == "wandb-history":
                    with patch("click.echo"):
                        try:
                            cleanup_cache()
                            path = a.download(
                                root=f"./artifacts/src/{a.name}", cache=False
                            )
                        except Exception as e:
                            wandb_logger.error(
                                f"Error downloading history artifact ({a}) -- {e}",
                                extra={
                                    "entity": self.entity(),
                                    "project": self.project(),
                                    "run_id": self.run_id(),
                                },
                            )
                            continue

                    new_art = _make_new_art(a)

                    # empty artifact paths are not dirs
                    if Path(path).is_dir():
                        new_art.add_dir(path)

                    history_arts.append(new_art)
            import_logger.info(
                f"W&B Importer: Finished collecting history artifacts ({run_str})"
            )
            progress.subsubtask_pbar.remove_task(t)

            t = progress.subsubtask_pbar.add_task(
                f"Upload history artifacts ({run_str})",
                total=None,
            )
            internal.send_artifacts_with_send_manager(
                history_arts,
                run,
                overrides=namespace.send_manager_overrides,
                settings_override={**settings_override, "resumed": True},
                config=internal.SendManagerConfig(log_artifacts=True),
            )
            import_logger.info(
                f"W&B Importer: Finished uploading history artifacts ({run_str})"
            )
            progress.subsubtask_pbar.remove_task(t)

    def _delete_collection_in_dst(
        self,
        src_art: Artifact,
        namespace: Optional[Namespace] = None,
    ):
        entity = coalesce(namespace.entity, src_art.entity)
        project = coalesce(namespace.project, src_art.project)

        try:
            dst_type = self.dst_api.artifact_type(src_art.type, f"{entity}/{project}")
            dst_collection = dst_type.collection(src_art.collection.name)
        except wandb.CommError:
            return  # it didn't exist

        try:
            dst_collection.delete()
        except wandb.CommError:
            return  # it's not allowed to be deleted

    def _get_run_from_art(self, art: Artifact):
        run = None

        try:
            run = art.logged_by()
        except ValueError as e:
            import_logger.warning(
                f"Trying to log {art=}, but {run=} doesn't exist! {e=}"
            )

        if run is None:
            run = special_logged_by(self.src_api.client, art)

        return run

    def _import_artifact_sequence_new(
        self,
        artifact_sequence: ArtifactSequence,
        *,
        namespace: Optional[Namespace] = None,
    ) -> None:
        """Import one artifact sequence.

        Use `namespace` to specify alternate settings like where the artifact sequence should be uploaded
        """
        if not artifact_sequence.artifacts:
            # The artifact sequence has no versions.  This usually means all artifacts versions were deleted intentionally,
            # but it can also happen if the sequence represents run history and that run was deleted.
            return

        if namespace is None:
            namespace = Namespace(artifact_sequence.entity, artifact_sequence.project)

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(log_artifacts=True)

        # Get a placeholder run for dummy artifacts we'll upload later
        art = artifact_sequence.artifacts[0]
        try:
            placeholder_run: Optional[Run] = self._get_run_from_art(art)
        except requests.exceptions.HTTPError as e:
            # If we had an http error, then just skip for now.
            import_logger.warning(
                f"Import Artifact Sequence http error: {art.entity=}, {art.project=}, {art.name=}, {e=}"
            )
            return

        # Delete any existing artifact sequence, otherwise versions will be out of order
        # Unfortunately, you can't delete only part of the sequence because versions are "remembered" even after deletion
        self._delete_collection_in_dst(art, namespace)

        # Instead of uploading placeholders one run at a time, upload an entire batch of placeholders at once
        # The placeholders cannot be uploaded at the same time as the actual artifact, otherwise we can run into
        # version collisions.
        groups_of_artifacts = list(_fill_with_dummy_arts(artifact_sequence))
        art = groups_of_artifacts[0][0]
        _type = art.type

        # can't use get_art_name_ver -- artifact naming is inconsistent between logged and not-yet-logged arts
        name, *_ = art.name.split(":v")
        entity = placeholder_run.entity
        project = placeholder_run.project

        base_descr = f"Artifact Sequence ({entity}/{project}/{_type}/{name})"

        total = len(groups_of_artifacts)
        i = 0
        for group in progress.subtask_progress(
            groups_of_artifacts, description=base_descr, total=total
        ):
            i += 1
            art = group[0]
            if art.description == ART_SEQUENCE_DUMMY_PLACEHOLDER:
                run = WandbRun(placeholder_run)
            else:
                try:
                    wandb_run = art.logged_by()
                except ValueError:
                    # Possible that the run that created this artifact was deleted, so we'll use a placeholder
                    import_logger.error(f"{placeholder_run=}, {type(placeholder_run)=}")
                    wandb_run = placeholder_run

                if wandb_run is None:
                    wandb_run = placeholder_run

                try:
                    cleanup_cache()
                    path = art.download(root=f"./artifacts/src/{art.name}", cache=False)
                except Exception as e:
                    import_logger.error(f"Error downloading artifact {art=} {e=}")
                    wandb_logger.error(
                        f"Error downloading artifact {art} -- {e}",
                        extra={
                            "entity": wandb_run.entity,
                            "project": wandb_run.project,
                            "run_id": wandb_run.id,
                        },
                    )
                    continue

                new_art = _make_new_art(art)
                if Path(path).is_dir():
                    new_art.add_dir(path)

                group = [new_art]
                run = WandbRun(wandb_run)

            internal.send_artifacts_with_send_manager(
                group,
                run,
                overrides=namespace.send_manager_overrides,
                settings_override=settings_override,
                config=send_manager_config,
            )
            import_logger.info(
                f"W&B Importer: Finished uploading partial artifact sequence ({entity}/{project}/{_type}/{name}) ({i=}/{total=})"
            )

        import_logger.info(
            f"W&B Importer: Finished uploading artifact sequences ({entity}/{project}/{_type}/{name})"
        )

        # query it back and remove placeholders
        self._remove_placeholders(art)

    def _remove_placeholders(self, art: Artifact) -> None:
        try:
            dst_versions = list(
                self.dst_api.artifact_versions(
                    art.type, _strip_version(art.qualified_name)
                )
            )
        except wandb.CommError:
            # the artifact did not upload for some reason
            import_logger.warning(f"This artifact doesn't seem to exist in dst, {art=}")
            return

        task = progress.subtask_pbar.add_task(
            f"Cleaning up placeholders for {art.entity}/{art.project}/{_strip_version(art.name)}",
            total=len(dst_versions),
        )
        for version in dst_versions:
            if version.description != ART_SEQUENCE_DUMMY_PLACEHOLDER:
                continue

            if version.type in ("wandb-history", "job"):
                continue

            try:
                version.delete(delete_aliases=True)
            except wandb.CommError as e:
                if "cannot delete system managed artifact" not in str(e):
                    raise e
            finally:
                progress.subtask_pbar.advance(task)

        import_logger.info(
            f"W&B Importer: Finished removing placeholders ({art.entity}/{art.project})"
        )
        progress.subtask_pbar.remove_task(task)

    def _compare_artifact_dirs(self, src_dir, dst_dir):
        def compare(src_dir, dst_dir):
            comparison = filecmp.dircmp(src_dir, dst_dir)
            differences = {
                "left_only": comparison.left_only,  # Items only in dir1
                "right_only": comparison.right_only,  # Items only in dir2
                "diff_files": comparison.diff_files,  # Different files
                "subdir_differences": {},  # Differences in subdirectories
            }

            # Recursively find differences in subdirectories
            for subdir in comparison.subdirs:
                subdir_differences = compare(
                    os.path.join(src_dir, subdir), os.path.join(dst_dir, subdir)
                )
                if any(
                    subdir_differences.values()
                ):  # If there are differences, add them to the result
                    differences["subdir_differences"][subdir] = subdir_differences

            if all(not diff for diff in differences.values()):
                return None

            return differences

        return compare(src_dir, dst_dir)

    # @progress.subsubtask_progress_deco(
    #     "Validate artifact manifests: {dst_art.entity}/{dst_art.project}/{dst_art.name}"
    # )
    def _compare_artifact_manifests(self, src_art: Artifact, dst_art: Artifact):
        problems = []
        if isinstance(dst_art, wandb.CommError):
            return ["commError"]

        if src_art.digest != dst_art.digest:
            problems.append(f"digest mismatch {src_art.digest=}, {dst_art.digest=}")

        for name, src_entry in src_art.manifest.entries.items():
            dst_entry = dst_art.manifest.entries.get(name)
            if dst_entry is None:
                problems.append(f"missing manifest entry {name=}, {src_entry=}")
                continue

            for attr in ["path", "digest", "size"]:
                if getattr(src_entry, attr) != getattr(dst_entry, attr):
                    problems.append(
                        f"manifest entry {attr=} mismatch, {getattr(src_entry, attr)=}, {getattr(dst_entry, attr)=}"
                    )

        return problems

    def _get_dst_art(
        self, src_art: Run, entity: Optional[str] = None, project: Optional[str] = None
    ):
        entity = coalesce(entity, src_art.entity)
        project = coalesce(project, src_art.project)
        name = src_art.name

        return self.dst_api.artifact(f"{entity}/{project}/{name}")

    def _get_src_artifacts(self, entity: str, project: str):
        for t in self.src_api.artifact_types(f"{entity}/{project}"):
            for c in t.collections():
                yield from c.versions()

    def _get_dst_run(self, src_run: Run) -> Run:
        entity = src_run.entity
        project = src_run.project
        run_id = src_run.id

        return self.dst_api.run(f"{entity}/{project}/{run_id}")

    def _clear_artifact_errors(self):
        src = "./" + ARTIFACTS_ERRORS_JSONL_FNAME
        dst = "./prev_" + ARTIFACTS_ERRORS_JSONL_FNAME

        try:
            shutil.copy2(src, dst)
        except FileNotFoundError:
            # this is just to make a copy of the last iteration, so its ok if the src doesn't exist
            pass

        with open(ARTIFACTS_ERRORS_JSONL_FNAME, "w"):
            pass

    def _clear_run_errors(self):
        src = "./" + RUNS_ERRORS_JSONL_FNAME
        dst = "./prev_" + RUNS_ERRORS_JSONL_FNAME

        try:
            shutil.copy2(src, dst)
        except FileNotFoundError:
            # this is just to make a copy of the last iteration, so its ok if the src doesn't exist
            pass

        with open(RUNS_ERRORS_JSONL_FNAME, "w"):
            pass

    def _get_run_problems(self, src_run, dst_run, force_retry=False):
        problems = []

        if force_retry:
            problems.append("__force_retry__")

        if non_matching_metadata := self._compare_run_metadata(src_run, dst_run):
            problems.append("metadata:" + str(non_matching_metadata))

        if non_matching_summary := self._compare_run_summary(src_run, dst_run):
            problems.append("summary:" + str(non_matching_summary))

        # Compare run metrics is not interesting because it just compares the artifacts.
        # We can do this a lot faster in the artifact comparison stage
        # if non_matching_metrics := self._compare_run_metrics(src_run, dst_run):
        #     problems.append("metrics:" + str(non_matching_metrics))

        if non_matching_files := self._compare_run_files(src_run, dst_run):
            problems.append("files" + str(non_matching_files))

        return problems

    @progress.subsubtask_progress_deco(
        "Validate run metadata: {dst_run.entity}/{dst_run.project}/{dst_run.id}"
    )
    def _compare_run_metadata(self, src_run: Run, dst_run: Run):
        fname = "wandb-metadata.json"

        src_f = src_run.file(fname)
        if src_f.size == 0:
            # the src was corrupted so no comparisons here will ever work
            return {}

        dst_f = dst_run.file(fname)
        try:
            contents = wandb.util.download_file_into_memory(
                dst_f.url, self.dst_api.api_key, timeout=60
            )
        except urllib3.exceptions.ReadTimeoutError:
            return {"Error checking": "Timeout"}
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return {"Bad upload": f"File not found: {fname}"}
            return {"http problem": f"{fname}: ({e})"}

        dst_meta = wandb.wandb_sdk.lib.json_util.loads(contents)

        non_matching = {}
        if src_run.metadata:
            for k, src_v in src_run.metadata.items():
                if k not in dst_meta:
                    non_matching[k] = {"src": src_v, "dst": "KEY NOT FOUND"}
                    continue
                dst_v = dst_meta[k]
                if src_v != dst_v:
                    non_matching[k] = {"src": src_v, "dst": dst_v}

        return non_matching

    @progress.subsubtask_progress_deco(
        "Validate run summary: {dst_run.entity}/{dst_run.project}/{dst_run.id}"
    )
    def _compare_run_summary(self, src_run: Run, dst_run: Run):
        non_matching = {}
        for k, src_v in src_run.summary.items():
            # These won't match between systems and that's ok
            if isinstance(src_v, str) and src_v.startswith("wandb-client-artifact://"):
                continue

            if k in ("_wandb", "_runtime"):
                continue

            dst_v = dst_run.summary.get(k)

            src_v = recursive_cast_to_dict(src_v)
            dst_v = recursive_cast_to_dict(dst_v)

            if isinstance(src_v, dict) and isinstance(dst_v, dict):
                for kk, sv in src_v.items():
                    # These won't match between systems and that's ok
                    if isinstance(sv, str) and sv.startswith(
                        "wandb-client-artifact://"
                    ):
                        continue
                    dv = dst_v.get(kk)
                    if not almost_equal(sv, dv):
                        non_matching[f"{k}-{kk}"] = {"src": sv, "dst": dv}
            else:
                if not almost_equal(src_v, dst_v):
                    non_matching[k] = {"src": src_v, "dst": dst_v}

        return non_matching

    # @progress.subsubtask_progress_deco(
    #     "Validate run metrics: {dst_run.entity}/{dst_run.project}/{dst_run.id}"
    # )
    # def _compare_run_metrics(self, src_run: Run, dst_run: Run):
    #     # NOTE: compare run metrics depend on artifacts, so if artifacts haven't uploaded yet
    #     # this will always say the runs don't match (even though they might)

    #     src_df = WandbRun(src_run)._get_metrics_df_from_parquet_history_paths()
    #     dst_df = WandbRun(dst_run)._get_metrics_df_from_parquet_history_paths()

    #     # NA never equals NA, so fill for easier comparison
    #     src_df = src_df.fill_nan(None)
    #     dst_df = dst_df.fill_nan(None)

    #     non_matching = []
    #     for col in src_df.columns:
    #         src = src_df[col]
    #         try:
    #             dst = dst_df[col]
    #         except pl.ColumnNotFoundError:
    #             non_matching.append(f"{col} does not exist in dst")
    #             continue

    #         # # handle case where NaN is a string
    #         # src = standardize_series(src)
    #         # dst = standardize_series(dst)

    #         if not src.series_equal(dst):
    #             non_matching.append(col)

    #     if non_matching:
    #         return f"Non-matching metrics {non_matching=}"
    #     else:
    #         return None

    @progress.subsubtask_progress_deco(
        "Validate run metrics: {dst_run.entity}/{dst_run.project}/{dst_run.id}"
    )
    def _compare_run_metrics(self, src_run: Run, dst_run: Run):
        # This version uses scan history which is a lot slower but will catch UI bugs.
        src_metrics = list(WandbRun(src_run)._get_metrics_from_scan_history_fallback())
        dst_metrics = list(WandbRun(dst_run)._get_metrics_from_scan_history_fallback())

        non_matching = []
        for src, dst in zip(src_metrics, dst_metrics):
            for k, src_v in src.items():
                dst_v = dst.get(k)

                if not almost_equal(src_v, dst_v):
                    non_matching.append(f"{k=}, {src_v=}, {dst_v=}")

        if non_matching:
            return f"Non-matching metrics {non_matching=}"
        else:
            return None

    @progress.subsubtask_progress_deco(
        "Validate run files: {dst_run.entity}/{dst_run.project}/{dst_run.id}"
    )
    def _compare_run_files(self, src_run: Run, dst_run: Run):
        # TODO
        return None

    def _filter_for_failed_sequences_only(self, seqs):
        df = _read_ndjson(ARTIFACTS_ERRORS_JSONL_FNAME)

        if df is None:
            return

        unique_failed_sequences = df[["entity", "project", "name", "type"]].unique()

        def filtered():
            for seq in seqs:
                entity = seq.entity
                project = seq.project
                name = seq.name
                _type = seq._type

                filtered_df = unique_failed_sequences.filter(
                    (pl.col("entity") == entity)
                    & (pl.col("project") == project)
                    & (pl.col("name") == name)
                    & (pl.col("type") == _type)
                )

                if len(filtered_df) > 0:
                    yield seq

        yield from filtered()

    def _collect_failed_artifact_sequences(self):
        df = _read_ndjson(ARTIFACTS_ERRORS_JSONL_FNAME)

        if df is None:
            return

        unique_failed_sequences = df[["entity", "project", "name", "type"]].unique()

        for row in unique_failed_sequences.iter_rows(named=True):
            entity = row["entity"]
            project = row["project"]
            name = row["name"]
            _type = row["type"]

            art_name = f"{entity}/{project}/{name}"
            arts = self.src_api.artifact_versions(_type, art_name)
            arts = sorted(arts, key=lambda a: int(a.version.lstrip("v")))
            arts = sorted(arts, key=lambda a: a.type)
            yield ArtifactSequence(arts, entity, project, _type, name)

    def _filter_for_failed_runs_only(self, runs):
        df = _read_ndjson(RUNS_ERRORS_JSONL_FNAME)

        if df is None:
            return

        unique_runs = df[["entity", "project", "run_id"]].unique()
        for run in runs:
            if self._is_failed_run(run, unique_runs):
                yield run

    def _is_failed_run(self, run, unique_runs: pl.DataFrame) -> bool:
        entity = run.entity()
        project = run.project()
        run_id = run.run_id()

        filtered_df = unique_runs.filter(
            (pl.col("entity") == entity)
            & (pl.col("project") == project)
            & (pl.col("run_id") == run_id)
        )

        return len(filtered_df) > 0

    def _cleanup_placeholder_runs_new(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.dst_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        for ns in progress.subtask_progress(
            namespaces, description="iterate namespaces"
        ):
            try:
                runs = api.runs(
                    f"{ns.entity}/{ns.project}",
                    filters={"config.experiment_name": RUN_DUMMY_PLACEHOLDER},
                )
                for run in progress.subsubtask_progress(
                    runs, description="cleanup runs"
                ):
                    if run.name == RUN_DUMMY_PLACEHOLDER:
                        run.delete(delete_artifacts=False)
            except ValueError as e:
                if "Could not find project" in str(e):
                    import_logger.warning(
                        f"Could not get runs for {ns.entity}/{ns.project} (is it empty?) {e=}"
                    )
                    continue
            except Exception as e:
                import_logger.error(f"problem cleanup {e=}")
                continue

    def collect_reports(
        self, entity: str, project: Optional[str] = None, limit: Optional[int] = None
    ) -> Iterable[Report]:
        """Collect all of the reports from `entity`/`project`.

        - If `project` is not specified, this will collect all runs from all projects

        Optionally set:
        - `limit` to get up to `limit` runs.
        """
        api = self.src_api
        projects = self._projects(entity, project)

        def reports():
            for project in projects:
                for report in api.reports(f"{project.entity}/{project.name}"):
                    yield wr.Report.from_url(report.url, api=api)

        yield from itertools.islice(reports(), limit)

    def import_report(
        self, report: Report, namespace: Optional[Namespace] = None
    ) -> None:
        """Import one wandb.Report.

        Use `namespace` to specify alternate settings like where the report should be uploaded
        """
        if namespace is None:
            namespace = Namespace(report.entity, report.project)

        entity = coalesce(namespace.entity, report.entity)
        project = coalesce(namespace.project, report.project)
        name = report.name
        title = report.title
        description = report.description

        api = self.dst_api

        # Testing Hack: To support multithreading import_report
        # We shouldn't need to upsert the project for every report
        try:
            api.create_project(project, entity)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 409:
                wandb.termwarn(f"{e}")

        api.client.execute(
            wr.report.UPSERT_VIEW,
            variable_values={
                "id": None,  # Is there any benefit for this to be the same as default report?
                "name": name,
                "entityName": entity,
                "projectName": project,
                "description": description,
                "displayName": title,
                "type": "runs",
                "spec": json.dumps(report.spec),
            },
        )

    def _projects(
        self,
        entity: str,
        project: Optional[str] = None,
        api: Optional[Api] = None,
    ) -> List[Project]:
        if api is None:
            api = self.src_api

        if project is None:
            return api.projects(entity)
        return [api.project(project, entity)]

    def _use_artifact_sequence(
        self, sequence: ArtifactSequence, namespace: Optional[Namespace] = None
    ):
        if namespace is None:
            namespace = Namespace(sequence.entity, sequence.project)

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "true",
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(use_artifacts=True)

        for art in sequence:
            used_by = art.used_by()
            if used_by is None:
                continue

            for wandb_run in used_by:
                run = WandbRun(wandb_run)

                internal.send_run_with_send_manager(
                    run,
                    overrides=namespace.send_manager_overrides,
                    settings_override=settings_override,
                    config=send_manager_config,
                )

    def _use_artifact_sequences(
        self,
        sequences: Iterable[ArtifactSequence],
        namespace: Optional[Namespace] = None,
        max_workers: Optional[int] = None,
    ):
        parallelize(
            self._use_artifact_sequence,
            sequences,
            namespace=namespace,
            max_workers=max_workers,
            description="Use artifact sequences",
        )

    @progress.with_progress
    def true_import_runs(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        incremental: bool = True,
        max_workers: Optional[int] = None,
        limit: Optional[int] = None,
        metadata: bool = True,
        files: bool = True,
        media: bool = True,
        code: bool = True,
        history: bool = True,
        summary: bool = True,
        terminal_output: bool = True,
        namespace_remapping: Optional[dict] = None,
    ):
        import_logger.debug(f"Starting to import runs for {namespaces=}")
        self._clear_run_errors()

        # Collect runs from source and validate against destination
        import_logger.debug(f"Starting to collect runs for {namespaces=}")
        runs = self._collect_runs(namespaces=namespaces, limit=limit)
        runs = list(runs)
        import_logger.debug(
            f"Starting to validate runs for {namespaces=}, {len(runs)=}"
        )
        self._validate_runs(
            runs,
            skip_previously_validated=incremental,
        )

        # (Re)-upload differences
        import_logger.debug(f"Starting to filter runs for {namespaces=}")
        incremental_runs = self._filter_for_failed_runs_only(runs)
        import_logger.debug(f"Starting to import runs for {namespaces=}")
        self._import_runs(
            incremental_runs,
            max_workers=max_workers,
            metadata=metadata,
            files=files,
            media=media,
            code=code,
            history=history,
            summary=summary,
            terminal_output=terminal_output,
            namespace_remapping=namespace_remapping,
        )
        import_logger.debug(f"Finished runs {namespaces=}")

    @progress.with_progress
    def true_import_reports(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
    ):
        import_logger.debug(f"Starting to import reports for {namespaces=}")
        reports = self._true_collect_reports(namespaces=namespaces, limit=limit)
        self.import_reports(reports)
        import_logger.debug(f"Finished reports {namespaces=}")

    @progress.with_progress
    def true_import_artifact_sequences(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        incremental: bool = True,
        max_workers: Optional[int] = None,
    ):
        import_logger.debug(f"Starting to import artifact sequences for {namespaces=}")
        self._clear_artifact_errors()

        # Collect artifacts from source and validate against destination
        import_logger.debug(f"Starting to collect artifact sequences for {namespaces=}")
        seqs = self._true_collect_artifact_sequences(namespaces=namespaces)
        seqs = list(seqs)
        import_logger.debug(
            f"Starting to validate artifact sequences for {namespaces=} {len(seqs)=}"
        )
        self._validate_artifact_sequences_new(
            seqs,
            skip_previously_checked=incremental,
        )

        # (Re)-upload differences
        # incremental_seqs = self._collect_failed_artifact_sequences()
        import_logger.debug(f"Starting to filter artifact sequences for {namespaces=}")
        incremental_seqs = self._filter_for_failed_sequences_only(seqs)
        incremental_seqs = list(incremental_seqs)
        import_logger.debug(
            f"Starting to import artifact sequences for {namespaces=} {len(incremental_seqs)=}"
        )
        self._import_artifact_sequences_new(incremental_seqs, max_workers=max_workers)

        # it's safer to just use artifact on all seqs to make sure we don't miss anything
        # For seqs that have already been used, this is a no-op.
        import_logger.debug(f"Starting to use artifact sequences for {namespaces=}")
        self._use_artifact_sequences(seqs)

        # Artifacts whose parent runs have been deleted should have that run deleted in the
        # destination as well
        import_logger.debug(
            f"Starting to use cleanup placeholder runs for {namespaces=}"
        )
        self._cleanup_placeholder_runs_new(namespaces=namespaces)
        import_logger.debug(f"Finished artifact sequences{namespaces=}")

    @progress.with_progress
    def import_all(
        self,
        *,
        repeat_if_error: bool = False,
        runs: bool = True,
        artifacts: bool = True,
        reports: bool = True,
        namespaces: Optional[Iterable[Namespace]] = None,
        incremental: bool = True,
        max_workers: Optional[int] = None,
    ):
        progress.task_pbar.update(progress.overall_time, description=repr(self))

        # errors = None
        while True:
            if runs:
                self.true_import_runs(
                    namespaces=namespaces,
                    incremental=incremental,
                    max_workers=max_workers,
                )

            if reports:
                self.true_import_reports(namespaces=namespaces)

            if artifacts:
                self.true_import_artifact_sequences(
                    namespaces=namespaces,
                    incremental=incremental,
                    max_workers=max_workers,
                )

            if not repeat_if_error:
                break

            # if not errors:
            #     break

    def _true_validate_run(self, src_run: Run) -> None:
        entity = src_run.entity
        project = src_run.project
        run_id = src_run.id

        run_str = f"{entity}/{project}/{run_id}"

        task = progress.subtask_pbar.add_task(f"Validate run: {run_str}", total=None)
        try:
            dst_run = self._get_dst_run(src_run)
        except wandb.CommError:
            problems = ["run does not exist"]
        except Exception as e:
            import_logger.error(f"Problem collecting run {src_run=}, {e=}")
        else:
            problems = self._get_run_problems(src_run, dst_run)
        finally:
            progress.subtask_pbar.remove_task(task)

        with filelock.FileLock("runs.lock"):
            with open(RUNS_ERRORS_JSONL_FNAME, "a") as f:
                with open(RUNS_PREVIOUSLY_CHECKED_JSONL_FNAME, "a") as f2:
                    d = {
                        "entity": src_run.entity,
                        "project": src_run.project,
                        "run_id": src_run.id,
                    }
                    if problems:
                        d["problems"] = problems
                        f.write(json.dumps(d) + "\n")
                    else:
                        f2.write(json.dumps(d) + "\n")
        import_logger.info(f"W&B Importer: Finished validating run ({run_str})")

    def _filter_previously_checked_runs(self, runs: Iterable[Run]) -> Iterable[Run]:
        df = _read_ndjson(RUNS_PREVIOUSLY_CHECKED_JSONL_FNAME)

        if df is None:
            yield from runs
            return

        data = [
            {"entity": r.entity, "project": r.project, "run_id": r.id, "data": r}
            for r in runs
        ]

        df2 = pl.DataFrame(data)
        results = df2.join(df, how="anti", on=["entity", "project", "run_id"])
        if not results.is_empty():
            results = results.filter(~results["run_id"].is_null())
            results = results.unique(["entity", "project", "run_id"])

        for r in results.iter_rows(named=True):
            yield r["data"]

    @progress.subsubtask_progress_deco("Filter previously checked artifacts")
    def _filter_previously_checked_artifacts(self, arts: Iterable[Artifact]):
        df = _read_ndjson(ARTIFACTS_PREVIOUSLY_CHECKED_JSONL_FNAME)

        if df is None:
            yield from arts
            return

        tracker = {}  # hack to get around polars converting the artifact to bytes
        data = []
        for i, art in enumerate(arts):
            name, ver = _get_art_name_ver(art)
            d = {
                "entity": art.entity,
                "project": art.project,
                "name": name,
                "version": ver,
                "type": art.type,
                "data": i,
            }
            data.append(d)
            tracker[i] = art

        df2 = pl.DataFrame(data)
        if not df2.is_empty():
            results = df2.join(
                df, how="anti", on=["entity", "project", "name", "version", "type"]
            )
        else:
            results = pl.DataFrame()

        if not results.is_empty():
            results = results.filter(~results["name"].is_null())
            results = results.unique(["entity", "project", "name", "version", "type"])

        for r in results.iter_rows(named=True):
            yield tracker[r["data"]]

    def _validate_artifact(
        self,
        src_art: Artifact,
        dst_entity: str,
        dst_project: str,
        download_files_and_compare: bool = False,
        check_entries_are_downloadable: bool = True,
    ):
        # These patterns of artifacts are special and should not be validated
        ignore_patterns = [
            r"^job-(.*?)\.py(:v\d+)?$",
            # r"^run-.*-history(?:\:v\d+)?$$",
        ]
        for pattern in ignore_patterns:
            if re.search(pattern, src_art.name):
                problems = []
                return (src_art, problems)

        try:
            dst_art = self._get_dst_art(src_art, dst_entity, dst_project)
        except Exception:
            problems = ["destination artifact not found"]
            return (src_art, problems)

        try:
            with progress.track_subsubtask("Validate artifact: Compare manifests"):
                problems = self._compare_artifact_manifests(src_art, dst_art)
        except Exception as e:
            problems = [
                f"Problem getting problems! problem with {src_art.entity=}, {src_art.project=}, {src_art.name=} {e=}"
            ]

        if check_entries_are_downloadable:
            # self._check_entries_are_downloadable(src_art)
            self._check_entries_are_downloadable(dst_art)

        if download_files_and_compare:
            with progress.track_subsubtask(
                f"Validate artifact: Downloading src {src_art=}"
            ):
                cleanup_cache()
                src_dir = src_art.download(
                    root=f"./artifacts/src/{src_art.name}", cache=False
                )

            try:
                with progress.track_subsubtask(
                    f"Validate artifact: Downloading dst {dst_art=}"
                ):
                    cleanup_cache()
                    dst_dir = dst_art.download(
                        root=f"./artifacts/dst/{dst_art.name}", cache=False
                    )

                with progress.track_subsubtask(
                    f"Validate artifact: Compare artifact dirs {src_dir=}, {dst_dir=}"
                ):
                    if problem := self._compare_artifact_dirs(src_dir, dst_dir):
                        problems.append(problem)

            except requests.HTTPError as e:
                problems.append(
                    f"Invalid download link for dst {dst_art.entity=}, {dst_art.project=}, {dst_art.name=}, {e}"
                )

        import_logger.info(
            f"W&B Importer: Finished validating artifact ({src_art.entity=}, {src_art.project=}, {src_art.name=})"
        )

        return (src_art, problems)

    def _validate_runs(
        self,
        runs: Iterable[WandbRun],
        *,
        skip_previously_validated: bool = True,
    ):
        # should probably rewrite this to put the writing inside _validate_run
        # and use a queue or lock

        base_runs = [r.run for r in runs]
        if skip_previously_validated:
            base_runs = self._filter_previously_checked_runs(base_runs)

        base_runs = list(base_runs)

        parallelize(
            self._true_validate_run,
            base_runs,
            description="Validate runs",
        )
        import_logger.info("W&B Importer: Finished validating runs")

    def _cleanup_runs_in_dst_but_not_in_src(self, entity, project):
        src_runs = [r for r in self.src_api.runs(f"{entity}/{project}")]
        dst_runs = [r for r in self.dst_api.runs(f"{entity}/{project}")]

        src_ids = set(r.id for r in src_runs)
        dst_ids = set(r.id for r in dst_runs)

        diff = dst_ids - src_ids

        for run in dst_runs:
            if run.id in diff:
                run.delete(delete_artifacts=False)

    def _import_runs(
        self,
        runs: Iterable[WandbRun],
        *,
        max_workers: Optional[int] = None,
        metadata: bool = True,
        files: bool = True,
        media: bool = True,
        code: bool = True,
        history: bool = True,
        summary: bool = True,
        terminal_output: bool = True,
        namespace_remapping: Optional[dict] = None,
    ):
        def _import_run_wrapped(run):
            namespace = Namespace(run.entity(), run.project())
            if namespace_remapping and namespace in namespace_remapping:
                namespace = namespace_remapping[namespace]

            return self._import_run(
                run,
                namespace=namespace,
                metadata=metadata,
                files=files,
                media=media,
                code=code,
                history=history,
                summary=summary,
                terminal_output=terminal_output,
            )

        desc = "Import runs"
        parallelize(
            _import_run_wrapped,
            runs,
            max_workers=max_workers,
            description=desc,
        )

    def _filter_previously_checked_artifacts_new(
        self, seqs: Iterable[ArtifactSequence]
    ):
        df = _read_ndjson(ARTIFACTS_PREVIOUSLY_CHECKED_JSONL_FNAME)

        if df is None:
            for seq in seqs:
                yield from seq.artifacts
            return

        for seq in seqs:
            for art in seq:
                try:
                    logged_by = self._get_run_from_art(art)
                except requests.HTTPError as e:
                    import_logger.error(
                        f"Validate Artifact http error: {art.entity=}, {art.project=}, {art.name=}, {e=}"
                    )
                    continue

                if art.type == "wandb-history" and isinstance(
                    logged_by, _PlaceholderRun
                ):
                    # We can never upload valid history for a deleted run, so skip it
                    continue

                entity = art.entity
                project = art.project
                _type = art.type
                name, ver = _get_art_name_ver(art)

                filtered_df = df.filter(
                    (df["entity"] == entity)
                    & (df["project"] == project)
                    & (df["name"] == name)
                    & (df["version"] == ver)
                    & (df["type"] == _type)
                )

                # not in file, so not verified yet, don't filter out
                if len(filtered_df) == 0:
                    yield art

    def _validate_artifact_sequences_new(
        self,
        seqs: Iterable[ArtifactSequence],
        *,
        skip_previously_checked: bool = True,
        download_files_and_compare: bool = False,
        check_entries_are_downloadable: bool = True,
    ):
        # args = []
        descr = "Validate artifacts"

        def filtered_sequences():
            for seq in progress.subsubtask_progress(
                seqs, description="iterate sequences"
            ):
                if not seq.artifacts:
                    continue

                art = seq.artifacts[0]

                try:
                    logged_by = self._get_run_from_art(art)
                except requests.HTTPError as e:
                    import_logger.error(
                        f"Validate Artifact http error: {art.entity=}, {art.project=}, {art.name=}, {e=}"
                    )
                    continue

                if art.type == "wandb-history" and isinstance(
                    logged_by, _PlaceholderRun
                ):
                    # We can never upload valid history for a deleted run, so skip it
                    continue

                yield seq

        if skip_previously_checked:
            artifacts = self._filter_previously_checked_artifacts_new(
                filtered_sequences()
            )
            descr = "Incrementally validate artifacts"

        args = ((art, art.entity, art.project) for art in artifacts)

        art_problems = parallelize(
            lambda args: self._validate_artifact(
                *args,
                download_files_and_compare=download_files_and_compare,
                check_entries_are_downloadable=check_entries_are_downloadable,
            ),
            args,
            description=descr,
        )

        with open(ARTIFACTS_ERRORS_JSONL_FNAME, "a") as f:
            with open(ARTIFACTS_PREVIOUSLY_CHECKED_JSONL_FNAME, "a") as f2:
                for art, problems in art_problems:
                    name, ver = _get_art_name_ver(art)
                    d = {
                        "entity": art.entity,
                        "project": art.project,
                        "name": name,
                        "version": ver,
                        "type": art.type,
                    }
                    if problems:
                        d["problems"] = problems
                        f.write(json.dumps(d) + "\n")
                    else:
                        f2.write(json.dumps(d) + "\n")
        import_logger.info("W&B Importer: Finished validating artifact sequences")

    def _collect_runs(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
        skip_ids: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        filters: Dict[str, Any] = {}
        if skip_ids is not None:
            filters["name"] = {"$nin": skip_ids}
        if start_date is not None:
            filters["createdAt"] = {"$gte": start_date}

        def _runs():
            for ns in namespaces:
                try:
                    for run in api.runs(f"{ns.entity}/{ns.project}", filters=filters):
                        yield WandbRun(run)
                except Exception as e:
                    import_logger.error(f"Error collecting runs {e=}")

        runs = itertools.islice(_runs(), limit)
        yield from progress.task_progress(runs, description="Collect runs")

    def _collect_run(
        self,
        entity: str,
        project: str,
        run_id: str,
        *,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)
        run = api.run(f"{entity}/{project}/{run_id}")
        return WandbRun(run)

    def _all_namespaces(
        self, *, entity: Optional[str] = None, api: Optional[Api] = None
    ):
        api = coalesce(api, self.src_api)
        entity = coalesce(entity, api.default_entity)

        projects = api.projects(entity)
        for p in projects:
            yield Namespace(p.entity, p.name)

    def _true_collect_reports(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        def reports():
            for ns in namespaces:
                for r in api.reports(f"{ns.entity}/{ns.project}"):
                    yield wr.Report.from_url(r.url, api=api)

        yield from itertools.islice(reports(), limit)

    def _collect_reports(
        self,
        entity: str,
        project: str,
        *,
        limit: Optional[int] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)

        def reports():
            for r in api.reports(f"{entity}/{project}"):
                yield wr.Report.from_url(r.url, api=api)

        yield from itertools.islice(reports(), limit)

    def _collect_artifact_sequence(
        self,
        entity,
        project,
        type,
        name,
        *,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)
        art_type = api.artifact_type(type_name=type, project=f"{entity}/{project}")

        c = art_type.collection(name)
        arts = [a for a in c.versions()]
        return ArtifactSequence(arts, entity, project, type, name)

    def _true_collect_artifact_sequences(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        def artifact_sequences():
            for ns in progress.subsubtask_progress(
                namespaces, description="iterate namespaces"
            ):
                namespace_str = f"{ns.entity}/{ns.project}"
                types = []
                try:
                    types = [t for t in api.artifact_types(namespace_str)]
                except Exception as e:
                    import_logger.error(f"problem getting types {e=}")

                for t in progress.subsubtask_progress(
                    types, description=f"iterate types ({namespace_str})"
                ):
                    collections = []

                    # Skip history because it's really for run history
                    if t.name == "wandb-history":
                        continue

                    try:
                        collections = t.collections()
                    except Exception as e:
                        import_logger.error(f"problem getting collections {e=}")

                    for c in progress.subsubtask_progress(
                        collections,
                        description=f"iterate collections ({namespace_str}/{t.name})",
                    ):
                        if c.is_sequence():
                            seq = self._sequence_from_collection(c)
                            if seq:
                                yield seq

        seqs = itertools.islice(artifact_sequences(), limit)
        unique_sequences = {
            seq.identifier: seq
            for seq in progress.task_progress(
                seqs, description="Collect artifact sequences"
            )
        }
        yield from unique_sequences.values()

    def _sequence_from_collection(self, collection):
        try:
            arts = collection.versions()
            arts = sorted(arts, key=lambda a: int(a.version.lstrip("v")))
        except Exception as e:
            import_logger.error(f"problem at sequence from collection {e=}")
            return

        if arts:
            art = arts[0]
            entity = art.entity
            project = art.project
            name, _ = _get_art_name_ver(art)
            _type = art.type

            return ArtifactSequence(arts, entity, project, _type, name)

    def _import_artifact_sequences_new(
        self,
        sequences: Iterable[ArtifactSequence],
        *,
        namespace: Optional[Namespace] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        """Import a collection of artifact sequences.

        Use `namespace` to specify alternate settings like where the report should be uploaded

        Optional:
        - `max_workers` -- set number of worker threads
        """
        parallelize(
            self._import_artifact_sequence_new,
            sequences,
            namespace=namespace,
            max_workers=max_workers,
            description="Import artifact sequences",
        )

    def import_reports(
        self,
        reports: Iterable[Report],
        namespace: Optional[Namespace] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        """Import a collection of wandb.Reports.

        Use `namespace` to specify alternate settings like where the report should be uploaded

        Optional:
        - `max_workers` -- set number of worker threads
        """
        parallelize(
            self.import_report,
            reports,
            namespace=namespace,
            max_workers=max_workers,
            description="Reports",
        )

    def _wipe_artifacts(self, entity: str, project: Optional[str] = None) -> None:
        def artifacts(project_name):
            for _type in self.dst_api.artifact_types(project_name):
                for collection in _type.collections():
                    yield from collection.versions()

        projects = self._projects(entity, project, api=self.dst_api)
        proj_names = [f"{entity}/{p.name}" for p in projects]
        proj_arts = {p: artifacts(p) for p in proj_names}

        for proj_path, arts in progress.task_pbar.track(
            proj_arts.items(),
            description=f"Wiping artifacts from destination: {entity}",
            total=len(proj_arts),
        ):
            task = progress.subtask_pbar.add_task(
                f"Wiping artifacts from {proj_path}", total=None
            )
            for art in arts:
                try:
                    art.delete(delete_aliases=True)
                except Exception as e:
                    if "cannot delete system managed artifact" not in str(e):
                        raise e
                finally:
                    progress.subtask_pbar.advance(task, 1)
            progress.subtask_pbar.remove_task(task)

    def _check_entries_are_downloadable(self, art):
        def _collect_entries(art):
            has_next_page = True
            cursor = None
            entries = []
            while has_next_page:
                attrs = art._fetch_file_urls(cursor)
                has_next_page = attrs["pageInfo"]["hasNextPage"]
                cursor = attrs["pageInfo"]["endCursor"]
                for edge in attrs["edges"]:
                    entry = art.get_path(edge["node"]["name"])
                    entry._download_url = edge["node"]["directUrl"]
                    entries.append(entry)
            return entries

        def _check_entry_is_downloable(entry):
            url = entry._download_url
            expected_size = entry.size

            try:
                resp = requests.head(url, allow_redirects=True)
            except Exception:
                import_logger.error(f"Problem validating {entry=}")

            if resp.status_code != 200:
                return False

            actual_size = resp.headers.get("content-length", -1)
            actual_size = int(actual_size)

            if expected_size == actual_size:
                return True

            return False

        entries = _collect_entries(art)
        for entry in entries:
            if not _check_entry_is_downloable(entry):
                return False
        return True


def _get_art_name_ver(art: Artifact) -> Tuple[str, int]:
    name, ver = art.name.split(":v")
    return name, int(ver)


def _make_new_art(art: Artifact) -> Artifact:
    name, _ = art.name.split(":v")

    # Hack: skip naming validation check for wandb-* types
    new_art = Artifact(name, "temp")
    new_art._type = art.type

    new_art._created_at = art.created_at
    new_art._aliases = art.aliases
    new_art._description = art.description

    return new_art


def _make_dummy_art(name: str, _type: str, ver: int):
    art = Artifact(name, "temp")
    art._type = _type
    art._description = ART_SEQUENCE_DUMMY_PLACEHOLDER

    p = Path("importer_temp")
    p.mkdir(parents=True, exist_ok=True)
    fname = p / str(ver)
    with open(fname, "w"):
        pass
    art.add_file(fname)
    return art


def _fill_with_dummy_arts(arts, start=0):
    prev_ver, first = None, True

    for a in arts:
        name, ver = _get_art_name_ver(a)
        if first:
            if ver > start:
                yield [_make_dummy_art(name, a.type, v) for v in range(start, ver)]
            first = False
        else:
            if ver - prev_ver > 1:
                yield [
                    _make_dummy_art(name, a.type, v) for v in range(prev_ver + 1, ver)
                ]
        yield [a]
        prev_ver = ver


def _strip_version(s):
    parts = s.split(":v", 1)
    return parts[0]


def recursive_cast_to_dict(obj):
    if isinstance(obj, list):
        return [recursive_cast_to_dict(item) for item in obj]
    elif isinstance(obj, dict) or hasattr(obj, "items"):
        new_dict = {}
        for key, value in obj.items():
            new_dict[key] = recursive_cast_to_dict(value)
        return new_dict
    else:
        return obj


def almost_equal(x, y, eps=1e-6):
    if isinstance(x, dict) and isinstance(y, dict):
        if x.keys() != y.keys():
            return False
        return all(almost_equal(x[k], y[k], eps) for k in x)

    if isinstance(x, numbers.Number) and isinstance(y, numbers.Number):
        return abs(x - y) < eps

    if type(x) is not type(y):
        return False

    return x == y


def special_logged_by(client, art):
    """Get the run that first logged this artifact.

    Raises:
        ArtifactNotLoggedError: if the artifact has not been logged
    """
    query = gql(
        """
        query ArtifactCreatedBy(
            $id: ID!
        ) {
            artifact(id: $id) {
                createdBy {
                    ... on Run {
                        name
                        project {
                            name
                            entityName
                        }
                    }
                }
            }
        }
    """
    )
    response = client.execute(
        query,
        variable_values={"id": art.id},
    )
    creator = response.get("artifact", {}).get("createdBy", {})

    placeholder_run = _PlaceholderRun(
        entity=art.entity,
        project=art.project,
        run_id=creator.get("name", RUN_DUMMY_PLACEHOLDER),
        id=creator.get("name", RUN_DUMMY_PLACEHOLDER),
    )

    return placeholder_run


@dataclass
class _PlaceholderUser:
    username: str = ""


@dataclass
class _PlaceholderRun:
    entity: str = ""
    project: str = ""
    run_id: str = RUN_DUMMY_PLACEHOLDER
    id: str = RUN_DUMMY_PLACEHOLDER
    display_name: str = RUN_DUMMY_PLACEHOLDER
    notes: str = ""
    url: str = ""
    group: str = ""
    created_at: str = "2000-01-01"
    user: _PlaceholderUser = field(default_factory=_PlaceholderUser)
    tags: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def files(self):
        return []


def standardize_series(series: pl.Series) -> pl.Series:
    df = pl.DataFrame({"col": series})

    if series.dtype in [
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    ]:
        series = series.cast(pl.Float64)

    df = df.select(
        pl.when(pl.col("col").str.lower().eq("nan"))
        .then(np.nan)
        .otherwise(pl.col("col"))
        .alias("col")
    )

    return df["col"]


def _read_ndjson(fname: str) -> Optional[pl.DataFrame]:
    try:
        df = pl.read_ndjson(fname)
    except FileNotFoundError:
        return None
    except RuntimeError as e:
        # No runs previously checked
        if "empty string is not a valid JSON value" in str(e):
            return None
        if "error parsing ndjson" in str(e):
            return None
        raise e

    return df


def cleanup_cache():
    cache = get_artifacts_cache()
    cache.cleanup(target_size=target_size)

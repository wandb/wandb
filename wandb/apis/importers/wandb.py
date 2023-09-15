import itertools
import json
import numbers
import re
import time
from datetime import datetime as dt
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from unittest.mock import patch

import polars as pl
import requests
import yaml

import wandb
from wandb.apis.public import Run
from wandb.util import coalesce, remove_keys_with_none_values

from . import internal, progress, protocols
from .config import Namespace
from .logs import _thread_local_settings, wandb_logger
from .protocols import ArtifactSequence, parallelize

with patch("click.echo"):
    import wandb.apis.reports as wr
    from wandb.apis.reports import Report


Artifact = wandb.Artifact
Api = wandb.Api

ARTIFACT_ERRORS_JSONL_FNAME = "import_artifact_errors.jsonl"
RUN_ERRORS_JSONL_FNAME = "import_run_errors.jsonl"


ART_SEQUENCE_DUMMY_DESCRIPTION = "__ART_SEQUENCE_DUMMY_DESCRIPTION__"


class WandbRun:
    def __init__(self, run: Run):
        self.run = run
        self.api = wandb.Api(
            api_key=_thread_local_settings.api_key,
            overrides={"base_url": _thread_local_settings.base_url},
        )

        _thread_local_settings.entity = self.entity()
        _thread_local_settings.project = self.project()
        _thread_local_settings.run_id = self.run_id()

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

        # Modify artifact paths because they are different between systems
        s = self._modify_table_artifact_paths(s)
        return s

    def _get_metrics_df_from_parquet_history_paths(self):
        if self._parquet_history_paths is None:
            self._parquet_history_paths = self._get_parquet_history_paths()

        if not self._parquet_history_paths:
            # unfortunately, it's not feasible to validate non-parquet history
            return pl.DataFrame()

        dfs = []
        for path in self._parquet_history_paths:
            for p in Path(path).glob("*.parquet"):
                df = pl.read_parquet(p)
                dfs.append(df)
        return pl.concat(dfs)

    def _get_metrics_from_parquet_history_paths(self) -> Iterable[Dict[str, Any]]:
        df = self._get_metrics_df_from_parquet_history_paths()
        for row in df.iter_rows(named=True):
            row = remove_keys_with_none_values(row)
            yield row

    def _get_metrics_from_scan_history_fallback(self) -> Iterable[Dict[str, Any]]:
        wandb_logger.warn(
            "No parquet files detected; using scan history",
            extra={
                "entity": self.entity(),
                "project": self.project(),
                "run_id": self.run_id(),
            },
        )
        yield from self.run.scan_history()

    def _get_parquet_history_paths(self) -> List[str]:
        paths = []
        try:
            self._artifacts = list(self.run.logged_artifacts())
        except Exception as e:
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
                    path = art.download()
                except Exception as e:
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

    def metrics(self) -> Iterable[Dict[str, float]]:
        if self._parquet_history_paths:
            yield from self._get_metrics_from_parquet_history_paths()
            return

        self._parquet_history_paths = self._get_parquet_history_paths()

        if not self._parquet_history_paths:
            yield from self._get_metrics_from_scan_history_fallback()
            return

        yield from self._get_metrics_from_parquet_history_paths()

    def run_group(self) -> Optional[str]:
        return self.run.group

    def job_type(self) -> Optional[str]:
        return self.run.job_type

    def display_name(self) -> str:
        return self.run.display_name

    def notes(self) -> Optional[str]:
        return self.run.notes

    def tags(self) -> Optional[List[str]]:
        return self.run.tags

    def artifacts(self) -> Optional[Iterable[Artifact]]:
        if self._artifacts is not None:
            yield from self._artifacts
            return

        try:
            self._artifacts = list(self.run.logged_artifacts())
        except Exception as e:
            wandb_logger.error(
                f"Error downloading artifacts -- {e}",
                extra={
                    "entity": self.entity(),
                    "project": self.project(),
                    "run_id": self.run_id(),
                },
            )
            return []

        new_arts = []
        for art in self._artifacts:
            with patch("click.echo"):
                try:
                    path = art.download()
                except Exception as e:
                    wandb_logger.error(
                        f"Error downloading artifact ({art}) -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                    continue

                new_art = _make_new_art(art)

                # empty artifact paths are not dirs
                if Path(path).is_dir():
                    new_art.add_dir(path)

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
            wandb_logger.error(
                f"Error downloading used artifacts -- {e}",
                extra={
                    "entity": self.entity(),
                    "project": self.project(),
                    "run_id": self.run_id(),
                },
            )
            return []

        new_arts = []
        for art in self._used_artifacts:
            with patch("click.echo"):
                try:
                    path = art.download()
                except Exception as e:
                    wandb_logger.error(
                        f"Error downloading used artifact ({art}) -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                    continue

                new_art = _make_new_art(art)

                # empty artifact paths are not dirs
                new_art.add_dir(path)

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
        t = dt.fromisoformat(self.run.created_at).timestamp()
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
        files_dir = f"./wandb-importer/{self.run_id()}/files"
        if self._files is not None:
            yield from self._files
            return

        self._files = []
        for f in self.run.files():
            # Don't carry over empty files
            if f.size == 0:
                continue
            # Skip deadlist to avoid overloading S3
            # if "wandb_manifest.json.deadlist" in f.name:
            #     continue

            try:
                result = f.download(files_dir, exist_ok=True)
            except Exception as e:
                wandb_logger.error(
                    f"Error downloading file ({f}) -- {e}",
                    extra={
                        "entity": self.entity(),
                        "project": self.project(),
                        "run_id": self.run_id(),
                    },
                )
                continue
            else:
                file_and_policy = (result.name, "now")
                self._files.append(file_and_policy)
                yield file_and_policy

    def logs(self) -> Optional[Iterable[str]]:
        fname = self._find_in_files("output.log")
        if fname is None:
            return

        with open(fname) as f:
            yield from f.readlines()

    def _modify_table_artifact_paths(self, row: Dict[str, Any]) -> Dict[str, Any]:
        table_keys = []
        for k, v in row.items():
            if (
                isinstance(v, (dict, wandb.old.summary.SummarySubDict))
                and v.get("_type") == "table-file"
            ):
                table_keys.append(k)

        for table_key in table_keys:
            obj = row[table_key]["artifact_path"]
            obj_name = obj.split("/")[-1]
            art_path = f"{self.entity()}/{self.project()}/run-{self.run_id()}-{table_key}:latest"
            art = None

            # Try to pick up the artifact within 20 seconds
            for _ in range(10):
                try:
                    art = self.api.artifact(art_path, type="run_table")
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
            # wandb.termlog(f"{row[table_key]}")
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


class WandbImporter:
    """Import runs, reports, and artifact sequences from a source instance at `src_base_url` to a destination instance at `dst_base_url`."""

    def __init__(
        self,
        src_base_url: str,
        src_api_key: str,
        dst_base_url: str,
        dst_api_key: str,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.src_base_url = src_base_url
        self.src_api_key = src_api_key
        self.dst_base_url = dst_base_url
        self.dst_api_key = dst_api_key

        # this login is neccessary for files because they assume you are logged in to download them.
        wandb.login(key=src_api_key, host=src_base_url)

        if api_kwargs is None:
            api_kwargs = {}

        self.src_api = wandb.Api(
            api_key=src_api_key,
            overrides={"base_url": src_base_url},
            timeout=600,
            **api_kwargs,
        )
        self.dst_api = wandb.Api(
            api_key=dst_api_key,
            overrides={"base_url": dst_base_url},
            timeout=600,
            **api_kwargs,
        )

        # There is probably a less redundant way of doing this
        _thread_local_settings.api_key = src_api_key
        _thread_local_settings.base_url = src_base_url

    import_runs = protocols.import_runs

    def _import_run(self, run: WandbRun, namespace: Optional[Namespace] = None) -> None:
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
            metadata=True,
            files=True,
            media=True,
            code=True,
            history=True,
            summary=True,
            terminal_output=True,
        )

        internal.send_run_with_send_manager(
            run,
            overrides=namespace.send_manager_overrides,
            settings_override=settings_override,
            config=sm_config,
        )

    def _delete_collection_in_dst(self, src_art, entity=None, project=None):
        entity = coalesce(entity, src_art.entity)
        project = coalesce(project, src_art.project)

        try:
            dst_type = self.dst_api.artifact_type(src_art.type, f"{entity}/{project}")
            dst_collection = dst_type.collection(src_art.collection.name)
        except wandb.CommError:
            return  # it didn't exist

        try:
            dst_collection.delete()
        except wandb.CommError:
            return  # it's not allowed to be deleted

    def _import_artifact_sequence(
        self, artifact_sequence: ArtifactSequence, namespace: Optional[Namespace] = None
    ) -> None:
        """Import one artifact sequence.

        Use `namespace` to specify alternate settings like where the artifact sequence should be uploaded
        """
        if not artifact_sequence.artifacts:
            # The artifact sequence has no versions.  This usually means all artifacts versions were deleted intentionally,
            # but it can also happen if the sequence represents run history and that run was deleted.
            print("No artifacts in sequence")
            return

        if namespace is None:
            namespace = Namespace(artifact_sequence.entity, artifact_sequence.project)

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(log_artifacts=True)

        placeholder_run = None
        for art in artifact_sequence:
            try:
                placeholder_run = art.logged_by()
            except ValueError:
                print("This run does not exist!")
                continue

            if placeholder_run is not None:
                break

        if placeholder_run is None:
            # If the run doesn't exist, history is not a relevant artifact
            if art.name.endswith("history:v0"):
                return

            # If the run doesn't exist, job is not a relevant artifact
            pattern = r"job-(.*?)\.py:v(\d+)"
            if re.search(pattern, art.name):
                return

            wandb_logger.error(
                f"Error finding placeholder run {art.entity=}, {art.project=}, {art.name=}, {art=}",
                extra={
                    "entity": "",
                    "project": "",
                    "run_id": "",
                },
            )
            return

        # Delete any existing artifact sequence, otherwise versions will be out of order
        self._delete_collection_in_dst(art, namespace.entity, namespace.project)

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

        task = progress.subtask_pbar.add_task(
            f"Artifact Sequence ({entity}/{project}/{_type}/{name})",
            total=len(groups_of_artifacts),
        )
        for group in groups_of_artifacts:
            art = group[0]
            if art.description == ART_SEQUENCE_DUMMY_DESCRIPTION:
                run = WandbRun(placeholder_run)
            else:
                wandb_run = art.logged_by()
                if wandb_run is None:
                    # Possible that the run that created this artifact was deleted, so we'll use a placeholder
                    wandb_run = placeholder_run

                try:
                    path = art.download()
                except Exception as e:
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
            progress.subtask_pbar.update(task, advance=1)

        # query it back and remove placeholders
        self._remove_placeholders(art)
        progress.subtask_pbar.remove_task(task)

    def _remove_placeholders(self, art: Artifact) -> None:
        dst_versions = list(
            self.dst_api.artifact_versions(art.type, _strip_version(art.qualified_name))
        )
        task = progress.subtask_pbar.add_task(
            f"Cleaning up placeholders for {art.entity}/{art.project}/{_strip_version(art.name)}",
            total=len(dst_versions),
        )
        for version in dst_versions:
            if version.description != ART_SEQUENCE_DUMMY_DESCRIPTION:
                continue
            try:
                version.delete(delete_aliases=True)
            except Exception as e:
                if "cannot delete system managed artifact" not in str(e):
                    raise e
            finally:
                progress.subtask_pbar.advance(task)
        progress.subtask_pbar.remove_task(task)

    def _compare_projects(self):
        ...

    def _compare_artifact(self, src_art: Artifact, dst_art: Artifact):
        problems = []
        if isinstance(dst_art, wandb.CommError):
            return ["commError"]

        if src_art.digest != dst_art.digest:
            problems.append(f"digest mismatch {src_art.digest=}, {dst_art.digest=}")

        for name, src_entry in src_art.manifest.entries.items():
            if name not in dst_art.manifest.entries:
                problems.append(f"missing manifest entry {name=}, {src_entry=}")

            dst_entry = dst_art.manifest.entries[name]
            for attr in ["path", "digest", "size"]:
                if getattr(src_entry, attr) != getattr(dst_entry, attr):
                    problems.append(
                        f"manifest entry {attr} mismatch, {getattr(src_entry, attr)=}, {getattr(dst_entry, attr)=}"
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

    def _clear_errors(self):
        with open(ARTIFACT_ERRORS_JSONL_FNAME, "w"):
            pass

        with open(RUN_ERRORS_JSONL_FNAME, "w"):
            pass

    def _get_run_problems(self, src_run, dst_run):
        problems = []

        non_matching_metadata = self._compare_run_metadata(src_run, dst_run)
        if non_matching_metadata:
            problems.append(str(non_matching_metadata))

        non_matching_summary = self._compare_run_summary(src_run, dst_run)
        if non_matching_summary:
            problems.append(str(non_matching_summary))

        non_matching_metrics = self._compare_run_metrics(src_run, dst_run)
        if non_matching_metrics:
            problems.append(str(non_matching_metrics))

        return problems

    def _compare_run(self, src_run, dst_run):
        problems = []

        non_matching_metadata = self._compare_run_metadata(src_run, dst_run)
        if non_matching_metadata:
            problems.append(non_matching_metadata)

        non_matching_summary = self._compare_run_summary(src_run, dst_run)
        if non_matching_summary:
            problems.append(non_matching_summary)

        return problems

    def _compare_run_metadata(self, src_run, dst_run):
        f = dst_run.file("wandb-metadata.json")
        try:
            contents = wandb.util.download_file_into_memory(f.url, self.dst_api.api_key)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return {"Bad upload": "File not found"}

        dst_meta = wandb.wandb_sdk.lib.json_util.loads(contents)

        non_matching = {}
        if src_run.metadata:
            for k, src_v in src_run.metadata.items():
                dst_v = dst_meta[k]
                if src_v != dst_v:
                    non_matching[k] = {"src": src_v, "dst": dst_v}

        return non_matching

    def _compare_run_summary(self, src_run, dst_run):
        non_matching = {}
        for k, src_v in src_run.summary.items():
            if k in ("_wandb", "_runtime"):
                continue

            dst_v = dst_run.summary[k]

            src_v = recursive_cast_to_dict(src_v)
            dst_v = recursive_cast_to_dict(dst_v)

            if isinstance(src_v, dict):
                for kk, sv in src_v.items():
                    dv = dst_v[kk]
                    if not almost_equal(sv, dv):
                        non_matching[f"{k}-{kk}"] = {"src": sv, "dst": dv}
            else:
                if not almost_equal(src_v, dst_v):
                    non_matching[k] = {"src": src_v, "dst": dst_v}

        return non_matching

    def _compare_run_metrics(self, src_run, dst_run):
        src_df = WandbRun(src_run)._get_metrics_df_from_parquet_history_paths()
        dst_df = WandbRun(dst_run)._get_metrics_df_from_parquet_history_paths()

        # NA never equals NA, so fill for easier comparison
        src_df = src_df.fill_nan(None)
        dst_df = dst_df.fill_nan(None)

        if not src_df.frame_equal(dst_df):
            return "Non matching metrics"

        return None

    def _collect_failed_artifact_sequences(self):
        try:
            df = pl.read_ndjson(ARTIFACT_ERRORS_JSONL_FNAME)
        except RuntimeError as e:
            # No errors found, good to go!
            if "empty string is not a valid JSON value" in str(e):
                return

        unique_failed_sequences = df.filter(~df["success"])[
            ["entity", "project", "name", "type"]
        ].unique()

        for seq in unique_failed_sequences.iter_rows(named=True):
            entity = seq["entity"]
            project = seq["project"]
            name = seq["name"]

            art_name = f"{entity}/{project}/{name}"
            arts = self.src_api.artifact_versions(seq["type"], art_name)
            arts = sorted(arts, key=lambda a: int(a.version.lstrip("v")))
            yield ArtifactSequence(arts, entity, project)

    def _collect_failed_runs(self):
        try:
            df = pl.read_ndjson(RUN_ERRORS_JSONL_FNAME)
        except RuntimeError as e:
            if "empty string is not a valid JSON value" not in str(e):
                raise e
            # No errors found, good to go!

        unique_runs = df[["entity", "project", "run_id"]].unique()

        for run in unique_runs.iter_rows(named=True):
            entity = run["entity"]
            project = run["project"]
            run_id = run["run_id"]

            r = Run(self.src_api.client, entity, project, run_id)
            yield WandbRun(r)

    def use_artifact_sequence(
        self, sequence: ArtifactSequence, config: Optional[Namespace] = None
    ) -> None:
        """Do the equivalent of `run.use_artifact(art)` for each artifact in the artifact sequence.

        Use `namespace` to specify alternate settings like where the artifact sequence should be used
        """
        if config is None:
            config = Namespace()

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "true",
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(
            use_artifacts=True,
        )

        sequence = list(sequence)
        s = sequence[0]
        _type = s.type
        name, _ = s.name.split(":")

        task = progress.subtask_pbar.add_task(
            f"Use Artifact Sequence ({_type}/{name})", total=len(sequence)
        )
        for art in sequence:
            if art.type == "job":
                # Job is a special type that can't be used yet
                continue

            wandb_runs = art.used_by()
            if wandb_runs == []:
                # Don't try to download an artifact that doesn't exist
                continue

            try:
                path = art.download()
            except Exception as e:
                wandb_logger.error(
                    f"Error downloading artifact {art} -- {e}",
                    extra={
                        "entity": wandb_runs[0].entity,
                        "project": wandb_runs[0].project,
                        "run_id": wandb_runs[0].id,
                    },
                )
                continue

            new_art = _make_new_art(art)

            if Path(path).is_dir():
                new_art.add_dir(path)

            for wandb_run in wandb_runs:
                run = WandbRun(wandb_run)
                internal.send_artifacts_with_send_manager(
                    new_art,
                    run,
                    overrides=config.send_manager_overrides,
                    settings_override=settings_override,
                    config=send_manager_config,
                )
            progress.subtask_pbar.update(task, advance=1)
        progress.subtask_pbar.remove_task(task)

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
        api: Optional[wandb.Api] = None,
    ) -> List[wandb.apis.public.Project]:
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
            wandb_run = art.used_by()
            if wandb_run is None:
                continue
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
            description="Use Artifact Sequences",
        )

    def _collect_reports_from_namespaces(self, namespaces) -> Iterable[Report]:
        for ns in namespaces:
            yield from self._collect_reports(ns.entity, ns.project)

    def _collect_runs_from_namespaces(self, namespaces) -> Iterable[WandbRun]:
        for ns in progress.task_pbar.track(
            namespaces,
            description="Collecting runs from namespaces",
            total=len(namespaces),
        ):
            yield from self._collect_runs(ns.entity, ns.project)

    def _collect_artifact_sequences_from_namespaces(
        self, namespaces
    ) -> Iterable[ArtifactSequence]:
        # for ns in namespaces:
        #     yield from self._collect_artifact_sequences(ns.entity, ns.project)

        for ns in progress.task_pbar.track(
            namespaces,
            description="Collecting artifact sequences from namespaces",
            total=len(namespaces),
        ):
            yield from self._collect_artifact_sequences(ns.entity, ns.project)

    def _add_aliases(
        self,
    ):
        ...

    def _import_all_from_namespaces(self, namespaces: Iterable[Namespace]) -> None:
        reports = self._collect_reports_from_namespaces(namespaces)
        self.import_reports(reports)

        runs = self._collect_runs_from_namespaces(namespaces)
        self.import_runs(runs)

        artifact_sequences = self._collect_artifact_sequences_from_namespaces(
            namespaces
        )

        # import the largest artifact sequences first becuase they will take the longest
        artifact_sequences = sorted(
            artifact_sequences,
            key=lambda s: sum(a.size for a in s.artifacts),
            reverse=True,
        )
        self.import_artifact_sequences(artifact_sequences)

        self._validate_and_reimport_failed(namespaces)

        self._use_artifact_sequences(artifact_sequences)

        progress.live.refresh()

    def _validate_run(self, src_run: Run) -> Tuple[Run, List[str]]:
        entity = src_run.entity
        project = src_run.project
        run_id = src_run.id
        task = progress.subtask_pbar.add_task(
            f"Validating {entity}/{project}/{run_id}", total=None
        )
        try:
            dst_run = self._get_dst_run(src_run)
        except wandb.CommError:
            problems = ["run does not exist"]
        else:
            problems = self._get_run_problems(src_run, dst_run)

        progress.subtask_pbar.remove_task(task)
        return (src_run, problems)

    def _validate_runs_from_namespaces(self, namespaces: Iterable[Namespace]) -> None:
        src_runs = [r.run for r in self._collect_runs_from_namespaces(namespaces)]
        problems = parallelize(
            self._validate_run, src_runs, description="Validate runs"
        )

        with open(RUN_ERRORS_JSONL_FNAME, "a") as f:
            for src_run, problem in problems:
                if problem:
                    d = {
                        "entity": src_run.entity,
                        "project": src_run.project,
                        "run_id": src_run.id,
                        "problems": problem,
                    }
                    f.write(json.dumps(d) + "\n")

    def _validate_artifact(self, src_art, dst_entity, dst_project):
        # try:
        #     src_art.logged_by()
        # except ValueError as e:
        #     if "Could not find run" not in str(e):
        #         print(
        #             f"problem with {src_art.entity=}, {src_art.project=}, {src_art.name=} {e=}"
        #         )
        #     return

        # These patterns of artifacts are special and should not be validated
        ignore_patterns = [r"^job-(.*?)\.py(:v\d+)?$", r"^run-.*-history$"]
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
            problems = self._compare_artifact(src_art, dst_art)
            return (src_art, problems)
        except Exception as e:
            problems = [
                f"Problem getting problems! problem with {src_art.entity=}, {src_art.project=}, {src_art.name=} {e=}"
            ]
            return (src_art, problems)

    def _validate_artifact_sequences_from_namespaces(self, namespaces):
        artifact_sequences = self._collect_artifact_sequences_from_namespaces(
            namespaces
        )
        tuples = []
        for seq in artifact_sequences:
            for art in seq:
                tup = (art, seq.entity, seq.project)
                tuples.append(tup)

        problems = parallelize(
            lambda args: self._validate_artifact(*args),
            tuples,
            description="Validate artifacts",
        )

        with open(ARTIFACT_ERRORS_JSONL_FNAME, "a") as f:
            for art, problem in problems:
                name, ver = _get_art_name_ver(art)
                d = {
                    "entity": art.entity,
                    "project": art.project,
                    "name": name,
                    "version": ver,
                    "type": art.type,
                    "problems": problem,
                    "success": True if not problem else False,
                }
                f.write(json.dumps(d) + "\n")

    def _validate_and_reimport_failed(self, namespaces):
        self._clear_errors()

        self._validate_runs_from_namespaces(namespaces)
        failed_runs = self._collect_failed_runs()
        self._import_failed_runs(failed_runs)

        self._validate_artifact_sequences_from_namespaces(namespaces)
        failed_artifact_sequences = self._collect_failed_artifact_sequences()

        # import the largest artifact sequences first becuase they will take the longest
        failed_artifact_sequences = sorted(
            failed_artifact_sequences,
            key=lambda s: sum(a.size for a in s.artifacts),
            reverse=True,
        )
        self._import_failed_artifact_sequences(failed_artifact_sequences)

    def _import_failed_artifact_sequences(
        self, failed_artifact_sequences, max_workers: Optional[int] = None
    ):
        parallelize(
            self._import_artifact_sequence,
            failed_artifact_sequences,
            namespace=None,
            max_workers=max_workers,
            description="Retry Failed Artifact Sequences",
        )

    def _import_failed_runs(self, failed_runs, max_workers: Optional[int] = None):
        parallelize(
            self._import_run,
            failed_runs,
            namespace=None,
            max_workers=max_workers,
            description="Retry Failed Runs",
        )

    def _collect_runs(
        self,
        entity: str,
        project: str,
        *,
        limit: Optional[int] = None,
        skip_ids: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)

        filters: Dict[str, Any] = {}
        if skip_ids is not None:
            filters["name"] = {"$nin": skip_ids}
        if start_date is not None:
            filters["createdAt"] = {"$gte": start_date}

        def runs():
            for run in api.runs(f"{entity}/{project}", filters=filters):
                yield WandbRun(run)

        yield from itertools.islice(runs(), limit)

    def _collect_reports(
        self,
        entity: str,
        project: str,
        *,
        limit: Optional[int] = None,
        api: Optional[Api] = None,
    ):
        api = self.src_api

        def reports():
            for r in api.reports(f"{entity}/{project}"):
                yield wr.Report.from_url(r.url, api=api)

        yield from itertools.islice(reports(), limit)

    def _collect_artifact_sequences(
        self,
        entity: str,
        project: str,
        *,
        limit: Optional[int] = None,
        api: Optional[Api] = None,
    ):
        api = self.src_api
        task = progress.subtask_pbar.add_task(
            f"Collecting artifact sequences ({entity}/{project})", total=None
        )

        def artifact_sequences():
            for _type in api.artifact_types(f"{entity}/{project}"):
                for collection in _type.collections():
                    if collection.is_sequence():
                        yield collection

        unique_sequences_map = {}
        for seq in itertools.islice(artifact_sequences(), limit):
            unique_sequences_map[(seq.entity, seq.project, seq.name, seq.type)] = seq

        unique_sequences = unique_sequences_map.values()
        for seq in unique_sequences:
            arts = seq.versions()
            # Reverse sort to simplify uploading placeholders
            arts = sorted(arts, key=lambda a: int(a.version.lstrip("v")))
            yield ArtifactSequence(arts, entity, project)

        progress.subtask_pbar.remove_task(task)

    def import_artifact_sequences(
        self,
        sequences: Iterable[ArtifactSequence],
        namespace: Optional[Namespace] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        """Import a collection of artifact sequences.

        Use `namespace` to specify alternate settings like where the report should be uploaded

        Optional:
        - `max_workers` -- set number of worker threads
        """
        parallelize(
            self._import_artifact_sequence,
            sequences,
            namespace=namespace,
            max_workers=max_workers,
            description="Artifact Sequences",
        )

    def use_artifact_sequences(
        self,
        sequences: Iterable[ArtifactSequence],
        namespace: Optional[Namespace] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        parallelize(
            self._use_artifact_sequence,
            sequences,
            namespace=namespace,
            max_workers=max_workers,
            description="Use Artifact Sequences",
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

    # def _validate_run(self):
    #     ...

    # def _validate_artifact_sequence(self, sequence):
    #     ...

    # def _validate_report(self):
    #     ...


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
    art._description = ART_SEQUENCE_DUMMY_DESCRIPTION

    p = Path("importer_temp")
    p.mkdir(parents=True, exist_ok=True)
    fname = p / str(ver)
    with open(fname, "w"):
        pass
    art.add_file(fname)
    return art


def _fill_with_dummy_arts(arts):
    prev_ver, first = None, True

    for a in arts:
        name, ver = _get_art_name_ver(a)
        if first:
            if ver > 0:
                yield [_make_dummy_art(name, a.type, v) for v in range(0, ver)]
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


def almost_equal(x, y, eps=1e-12):
    if type(x) != type(y):
        return False

    if isinstance(x, numbers.Number) and isinstance(y, numbers.Number):
        return abs(x - y) < eps

    return x == y

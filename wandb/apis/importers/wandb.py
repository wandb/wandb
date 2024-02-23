"""Tooling for the W&B Importer."""
import filecmp
import itertools
import json
import logging
import numbers
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime as dt
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from unittest.mock import patch

import filelock
import polars as pl
import requests
import urllib3
import yaml
from wandb_gql import gql

import wandb
import wandb.apis.reports as wr
from wandb.apis.public import ArtifactCollection, Run
from wandb.apis.public.artifacts import ArtifactType
from wandb.apis.public.files import File
from wandb.apis.reports import Report
from wandb.util import coalesce, remove_keys_with_none_values

from .internals import internal
from .internals.util import Namespace, for_each

Artifact = wandb.Artifact
Api = wandb.Api
Project = wandb.apis.public.Project

ARTIFACT_ERRORS_FNAME = "artifact_errors.jsonl"
ARTIFACT_SUCCESSES_FNAME = "artifact_successes.jsonl"
RUN_ERRORS_FNAME = "run_errors.jsonl"
RUN_SUCCESSES_FNAME = "run_successes.jsonl"

ART_SEQUENCE_DUMMY_PLACEHOLDER = "__ART_SEQUENCE_DUMMY_PLACEHOLDER__"
RUN_DUMMY_PLACEHOLDER = "__RUN_DUMMY_PLACEHOLDER__"
ART_DUMMY_PLACEHOLDER_PATH = "__importer_temp__"
ART_DUMMY_PLACEHOLDER_TYPE = "__temp__"

logger = logging.getLogger("import_logger")
# target_size = 80 * 1024**3  # 80GB


@dataclass
class ArtifactSequence:
    artifacts: Iterable[wandb.Artifact]
    entity: str
    project: str
    _type: str
    name: str

    def __iter__(self) -> Iterator:
        return iter(self.artifacts)

    def __repr__(self) -> str:
        return f"ArtifactSequence({self.identifier})"

    @property
    def identifier(self):
        return "/".join([self.entity, self.project, self._type, self.name])

    @classmethod
    def from_collection(cls, collection: ArtifactCollection):
        arts = collection.artifacts()
        arts = sorted(arts, key=lambda a: int(a.version.lstrip("v")))
        return ArtifactSequence(
            arts,
            collection.entity,
            collection.project,
            collection.type,
            collection.name,
        )


class WandbRun:
    def __init__(
        self,
        run: Run,
        *,
        src_base_url: str,
        src_api_key: str,
        dst_base_url: str,
        dst_api_key: str,
    ) -> None:
        self.run = run
        self.api = wandb.Api(
            api_key=src_api_key,
            overrides={"base_url": src_base_url},
        )
        self.dst_api = wandb.Api(
            api_key=dst_api_key,
            overrides={"base_url": dst_base_url},
        )

        # For caching
        self._files: Optional[Iterable[Tuple[str, str]]] = None
        self._artifacts: Optional[Iterable[Artifact]] = None
        self._used_artifacts: Optional[Iterable[Artifact]] = None
        self._parquet_history_paths: Optional[Iterable[str]] = None

    def __repr__(self) -> str:
        s = os.path.join(self.entity(), self.project(), self.run_id())
        return f"WandbRun({s})"

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
            rows = self._get_rows_from_parquet_history_paths()
        else:
            logger.warn(
                "No parquet files detected; using scan history (this may not be reliable)"
            )
            rows = self.run.scan_history()

        for row in rows:
            row = remove_keys_with_none_values(row)
            row = self._modify_table_artifact_paths(row)
            yield row

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
        if self._artifacts is None:
            self._artifacts = list(self.run.logged_artifacts())

        new_arts = []
        for art in self._artifacts:
            new_art = _clone_art(art)
            new_arts.append(new_art)
            yield new_art

        self._artifacts = new_arts

    def used_artifacts(self) -> Optional[Iterable[Artifact]]:
        if self._used_artifacts is None:
            self._used_artifacts = list(self.run.used_artifacts())

        new_arts = []
        for art in self._used_artifacts:
            new_art = _clone_art(art)
            new_arts.append(new_art)
            yield new_art

        self._used_artifacts = new_arts

    def os_version(self) -> Optional[str]:
        ...  # pragma: no cover

    def python_version(self) -> Optional[str]:
        return self._metadata_file().get("python")

    def cuda_version(self) -> Optional[str]:
        ...  # pragma: no cover

    def program(self) -> Optional[str]:
        ...  # pragma: no cover

    def host(self) -> Optional[str]:
        return self._metadata_file().get("host")

    def username(self) -> Optional[str]:
        ...  # pragma: no cover

    def executable(self) -> Optional[str]:
        ...  # pragma: no cover

    def gpus_used(self) -> Optional[str]:
        ...  # pragma: no cover

    def cpus_used(self) -> Optional[int]:  # can we get the model?
        ...  # pragma: no cover

    def memory_used(self) -> Optional[int]:
        ...  # pragma: no cover

    def runtime(self) -> Optional[int]:
        wandb_runtime = self.run.summary.get("_wandb", {}).get("runtime")
        base_runtime = self.run.summary.get("_runtime")

        if (t := coalesce(wandb_runtime, base_runtime)) is None:
            return t
        return int(t)

    def start_time(self) -> Optional[int]:
        t = dt.fromisoformat(self.run.created_at).timestamp() * 1000
        return int(t)

    def code_path(self) -> Optional[str]:
        path = self._metadata_file().get("codePath", "")
        return f"code/{path}"

    def cli_version(self) -> Optional[str]:
        return self._config_file().get("_wandb", {}).get("value", {}).get("cli_version")

    def files(self) -> Optional[Iterable[Tuple[str, str]]]:
        if self._files is not None:
            yield from self._files
            return

        files_dir = f"./wandb-importer/{self.run_id()}/files"

        self._files = []
        for f in self.run.files():
            f: File
            # These optimizations are intended to avoid rate limiting when importing many runs in parallel
            # Don't carry over empty files
            if f.size == 0:
                continue
            # Skip deadlist to avoid overloading S3
            if "wandb_manifest.json.deadlist" in f.name:
                continue

            # Download and log file (is this the right wording?)
            file_and_policy = None
            result = f.download(files_dir, exist_ok=True, api=self.api)
            file_and_policy = (result.name, "end")
            self._files.append(file_and_policy)
            yield file_and_policy

    def logs(self) -> Optional[Iterable[str]]:
        if (fname := self._find_in_files("output.log")) is None:
            return

        with open(fname) as f:
            yield from f.readlines()

    def _metadata_file(self) -> Dict[str, Any]:
        if (fname := self._find_in_files("wandb-metadata.json")) is None:
            return {}

        with open(fname) as f:
            return json.loads(f.read())

    def _config_file(self) -> Dict[str, Any]:
        if (fname := self._find_in_files("config.yaml")) is None:
            return {}

        with open(fname) as f:
            return yaml.safe_load(f) or {}

    def _get_rows_from_parquet_history_paths(self) -> None:
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

        df = _merge_dfs(dfs).sort("_step")
        if "_step" in df:
            df = df.with_columns(pl.col("_step").cast(pl.Int64))
        rows = df.iter_rows(named=True)
        yield from rows

    def _get_parquet_history_paths(self) -> List[str]:
        for art in self.artifacts():
            if art.type != "wandb-history":
                continue
            if (path := _download_art(art, root=f"./artifacts/src/{art.name}")) is None:
                continue
            yield path

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

            try:
                art = self.dst_api.artifact(art_path, type="run_table")
            except Exception as e:
                # Not the end of the world if we can't get the run table, so continue
                logger.error(f"Error getting run table artifact: {art_path=}, {e=}")
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
        if (files := self.files()) is None:
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
        *,
        custom_api_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.src_base_url = src_base_url
        self.src_api_key = src_api_key
        self.dst_base_url = dst_base_url
        self.dst_api_key = dst_api_key

        if custom_api_kwargs is None:
            custom_api_kwargs = {"timeout": 600}

        self.src_api = wandb.Api(
            api_key=src_api_key,
            overrides={"base_url": src_base_url},
            **custom_api_kwargs,
        )
        self.dst_api = wandb.Api(
            api_key=dst_api_key,
            overrides={"base_url": dst_base_url},
            **custom_api_kwargs,
        )

        self.run_api_kwargs = {
            "src_base_url": src_base_url,
            "src_api_key": src_api_key,
            "dst_base_url": dst_base_url,
            "dst_api_key": dst_api_key,
        }

    def __repr__(self):
        return f"<WandbImporter src={self.src_base_url}, dst={self.dst_base_url}>"  # pragma: no cover

    def _import_run(
        self,
        run: WandbRun,
        *,
        namespace: Optional[Namespace] = None,
        config: Optional[internal.SendManagerConfig] = None,
    ) -> None:
        """Import one WandbRun.

        Use `namespace` to specify alternate settings like where the run should be uploaded
        """
        if namespace is None:
            namespace = Namespace(run.entity(), run.project())

        if config is None:
            config = internal.SendManagerConfig(
                metadata=True,
                files=True,
                media=True,
                code=True,
                history=True,
                summary=True,
                terminal_output=True,
            )

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "true",
            "resumed": True,
        }

        logger.debug(f"Importing history, {run=}")
        internal.send_run_with_send_manager(
            run,
            overrides=namespace.send_manager_overrides,
            settings_override=settings_override,
            config=config,
        )

        logger.debug(f"Collecting history artifacts, {run=}")
        history_arts = []
        for art in run.artifacts():
            logger.debug(f"Collecting history artifact {art.name=}")
            if art.type != "wandb-history":
                continue
            new_art = _clone_art(art)
            history_arts.append(new_art)

        logger.debug(f"Importing history artifacts, {run=}")
        internal.send_artifacts_with_send_manager(
            history_arts,
            run,
            overrides=namespace.send_manager_overrides,
            settings_override=settings_override,
            config=internal.SendManagerConfig(log_artifacts=True),
        )

    def _delete_collection_in_dst(
        self,
        src_art: Artifact,
        namespace: Optional[Namespace] = None,
    ):
        """Deletes the equivalent artifact collection in destination.  Intended to clear the destination when an uploaded artifact does not pass validation."""
        entity = coalesce(namespace.entity, src_art.entity)
        project = coalesce(namespace.project, src_art.project)

        try:
            dst_type = self.dst_api.artifact_type(src_art.type, f"{entity}/{project}")
            dst_collection = dst_type.collection(src_art.collection.name)
        except (wandb.CommError, ValueError):
            return  # it didn't exist

        try:
            dst_collection.delete()
        except (wandb.CommError, ValueError):
            return  # it's not allowed to be deleted

    def _import_artifact_sequence(
        self,
        seq: ArtifactSequence,
        *,
        namespace: Optional[Namespace] = None,
    ) -> None:
        """Import one artifact sequence.

        Use `namespace` to specify alternate settings like where the artifact sequence should be uploaded
        """
        if not seq.artifacts:
            # The artifact sequence has no versions.  This usually means all artifacts versions were deleted intentionally,
            # but it can also happen if the sequence represents run history and that run was deleted.
            return

        if namespace is None:
            namespace = Namespace(seq.entity, seq.project)

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "true",
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(log_artifacts=True)

        # Get a placeholder run for dummy artifacts we'll upload later
        art = seq.artifacts[0]
        try:
            run_or_dummy: Optional[Run] = _get_run_or_dummy_from_art(art, self.src_api)
        except requests.exceptions.HTTPError as e:
            # If we had an http error, then just skip for now.
            logger.warn(f"Failed to get run (try again later): {seq=}, {art=}, {e=}")
            return

        # Delete any existing artifact sequence, otherwise versions will be out of order
        # Unfortunately, you can't delete only part of the sequence because versions are "remembered" even after deletion
        self._delete_collection_in_dst(art, namespace)

        # Each "group of artifacts" is either (1) a single "real" artifact in a list, or (2) a list of dummy artifacts
        # that are uploaded together.  This guarantees the real artifacts have the correct version numbers and allows
        # for parallel upload of dummies.
        groups_of_artifacts = list(_make_groups_of_artifacts(seq))
        for i, group in enumerate(groups_of_artifacts, 1):
            art = group[0]
            if art.description == ART_SEQUENCE_DUMMY_PLACEHOLDER:
                run = WandbRun(run_or_dummy, **self.run_api_kwargs)
            else:
                try:
                    wandb_run = art.logged_by()
                except ValueError:
                    pass  # see next line

                if wandb_run is None:
                    logger.warn(
                        f"Artifact run does not exist (deleted?), using {run_or_dummy=}"
                    )
                    wandb_run = run_or_dummy

                new_art = _clone_art(art)
                group = [new_art]
                run = WandbRun(wandb_run, **self.run_api_kwargs)

            internal.send_artifacts_with_send_manager(
                group,
                run,
                overrides=namespace.send_manager_overrides,
                settings_override=settings_override,
                config=send_manager_config,
            )
            logger.info(
                f"Uploaded partial artifact {seq=}, {i}/{len(groups_of_artifacts)}"
            )
        logger.info(f"Finished uploading {seq=}")

        # query it back and remove placeholders
        self._remove_placeholders(art)

    def _remove_placeholders(self, art: Artifact) -> None:
        name, _ = _get_art_name_ver(art)
        try:
            dst_versions = list(self.dst_api.artifacts(art.type, name))
        except wandb.CommError:
            # the artifact did not upload for some reason
            logger.warn(f"Art doesn't exist in dst (already deleted?), {art=}")
            return
        except TypeError:
            logger.error("Problem getting dst versions (try again later)")
            return

        for version in dst_versions:
            if version.description != ART_SEQUENCE_DUMMY_PLACEHOLDER:
                continue
            if version.type in ("wandb-history", "job"):
                continue

            try:
                version.delete(delete_aliases=True)
            except wandb.CommError as e:
                if "cannot delete system managed artifact" in str(e):
                    logger.warn("Cannot delete system managed artifact")
                else:
                    raise e

    @staticmethod
    def _compare_artifact_dirs(src_dir, dst_dir):
        def compare(src_dir, dst_dir):
            comparison = filecmp.dircmp(src_dir, dst_dir)
            differences = {
                "left_only": comparison.left_only,
                "right_only": comparison.right_only,
                "diff_files": comparison.diff_files,
                "subdir_differences": {},
            }

            # Recursively find differences in subdirectories
            for subdir in comparison.subdirs:
                subdir_src = os.path.join(src_dir, subdir)
                subdir_dst = os.path.join(dst_dir, subdir)
                subdir_differences = compare(subdir_src, subdir_dst)
                # If there are differences, add them to the result
                if subdir_differences and any(subdir_differences.values()):
                    differences["subdir_differences"][subdir] = subdir_differences

            if all(not diff for diff in differences.values()):
                return None

            return differences

        return compare(src_dir, dst_dir)

    @staticmethod
    def _compare_artifact_manifests(src_art: Artifact, dst_art: Artifact):
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
                        f"manifest entry mismatch {attr=}, {getattr(src_entry, attr)=}, {getattr(dst_entry, attr)=}"
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
            t: ArtifactType
            for c in t.collections():
                c: ArtifactCollection
                yield from c.artifacts()

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

    def _compare_run_metadata(self, src_run: Run, dst_run: Run):
        fname = "wandb-metadata.json"
        # problems = {}

        src_f = src_run.file(fname)
        if src_f.size == 0:
            # the src was corrupted so no comparisons here will ever work
            return {}

        dst_f = dst_run.file(fname)
        try:
            contents = wandb.util.download_file_into_memory(
                dst_f.url, self.dst_api.api_key
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

    def _compare_run_summary(self, src_run: Run, dst_run: Run):
        non_matching = {}
        for k, src_v in src_run.summary.items():
            # These won't match between systems and that's ok
            if isinstance(src_v, str) and src_v.startswith("wandb-client-artifact://"):
                continue
            if k in ("_wandb", "_runtime"):
                continue

            src_v = _recursive_cast_to_dict(src_v)

            dst_v = dst_run.summary.get(k)
            dst_v = _recursive_cast_to_dict(dst_v)

            if isinstance(src_v, dict) and isinstance(dst_v, dict):
                for kk, sv in src_v.items():
                    # These won't match between systems and that's ok
                    if isinstance(sv, str) and sv.startswith(
                        "wandb-client-artifact://"
                    ):
                        continue
                    dv = dst_v.get(kk)
                    if not _almost_equal(sv, dv):
                        non_matching[f"{k}-{kk}"] = {"src": sv, "dst": dv}
            else:
                if not _almost_equal(src_v, dst_v):
                    non_matching[k] = {"src": src_v, "dst": dst_v}

        return non_matching

    def _compare_run_files(self, src_run: Run, dst_run: Run):
        # TODO
        return None

    def _collect_failed_artifact_sequences2(self):
        if (df := _read_ndjson(ARTIFACT_ERRORS_FNAME)) is None:
            logger.debug(f"{ARTIFACT_ERRORS_FNAME=} is empty, returning nothing")
            return

        unique_failed_sequences = df[
            ["src_entity", "src_project", "name", "type"]
        ].unique()

        for row in unique_failed_sequences.iter_rows(named=True):
            entity = row["src_entity"]
            project = row["src_project"]
            name = row["name"]
            _type = row["type"]

            art_name = f"{entity}/{project}/{name}"
            arts = self.src_api.artifacts(_type, art_name)
            arts = sorted(arts, key=lambda a: int(a.version.lstrip("v")))
            arts = sorted(arts, key=lambda a: a.type)

            yield ArtifactSequence(arts, entity, project, _type, name)

    def _cleanup_dummy_runs(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        api: Optional[Api] = None,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ):
        api = coalesce(api, self.dst_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        for ns in namespaces:
            if remapping and ns in remapping:
                ns = remapping[ns]

            logger.debug(f"Cleaning up, {ns=}")
            try:
                runs = list(
                    api.runs(ns.path, filters={"displayName": RUN_DUMMY_PLACEHOLDER})
                )
            except ValueError as e:
                if "Could not find project" in str(e):
                    logger.error("Could not find project, does it exist?")
                    continue

            for run in runs:
                logger.debug(f"Deleting dummy {run=}")
                run.delete(delete_artifacts=False)

    def _import_report(
        self, report: Report, *, namespace: Optional[Namespace] = None
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

        # We shouldn't need to upsert the project for every report
        logger.debug(f"Upserting {entity=}/{project=}")
        try:
            api.create_project(project, entity)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 409:
                logger.warn(f"Issue upserting {entity=}/{project=}, {e=}")

        logger.debug(f"Upserting report {entity=}, {project=}, {name=}, {title=}")
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

    def _use_artifact_sequence(
        self,
        sequence: ArtifactSequence,
        *,
        namespace: Optional[Namespace] = None,
    ):
        if namespace is None:
            namespace = Namespace(sequence.entity, sequence.project)

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "true",
            "resumed": True,
        }
        logger.debug(f"Using artifact sequence with {settings_override=}, {namespace=}")

        send_manager_config = internal.SendManagerConfig(use_artifacts=True)

        for art in sequence:
            if (used_by := art.used_by()) is None:
                continue

            for wandb_run in used_by:
                run = WandbRun(wandb_run, **self.run_api_kwargs)

                internal.send_run_with_send_manager(
                    run,
                    overrides=namespace.send_manager_overrides,
                    settings_override=settings_override,
                    config=send_manager_config,
                )

    def import_runs(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        parallel: bool = True,
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
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ):
        os.environ["WANDB_IMPORTER_MODE_ENABLED"] = "true"
        logger.info("START: Import runs")

        logger.info("Setting up for import")
        _create_files_if_not_exists()
        _clear_fname(RUN_ERRORS_FNAME)

        logger.info("Collecting runs")
        runs = list(self._collect_runs(namespaces=namespaces, limit=limit))

        logger.info(f"Validating runs, {len(runs)=}")
        self._validate_runs(
            runs,
            skip_previously_validated=incremental,
            remapping=remapping,
        )

        logger.info("Collecting failed runs")
        # runs = list(self._filter_for_failed_runs_only(runs))
        runs = list(self._collect_failed_runs())

        logger.info(f"Importing runs, {len(runs)=}")

        def _import_run_wrapped(run):
            namespace = Namespace(run.entity(), run.project())
            if remapping is not None and namespace in remapping:
                namespace = remapping[namespace]

            config = internal.SendManagerConfig(
                metadata=metadata,
                files=files,
                media=media,
                code=code,
                history=history,
                summary=summary,
                terminal_output=terminal_output,
            )

            logger.debug(f"Importing {run=}, {namespace=}, {config=}")
            self._import_run(run, namespace=namespace, config=config)
            logger.debug(f"Finished importing {run=}, {namespace=}, {config=}")

        for_each(_import_run_wrapped, runs, max_workers=max_workers, parallel=parallel)
        logger.info("END: Importing runs")

        del os.environ["WANDB_IMPORTER_MODE_ENABLED"]

    def import_reports(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ):
        logger.info("START: Importing reports")

        logger.info("Collecting reports")
        reports = self._collect_reports(namespaces=namespaces, limit=limit)

        logger.info("Importing reports")

        def _import_report_wrapped(report):
            namespace = Namespace(report.entity, report.project)
            if remapping is not None and namespace in remapping:
                namespace = remapping[namespace]

            logger.debug(f"Importing {report=}, {namespace=}")
            self._import_report(report, namespace=namespace)
            logger.debug(f"Finished importing {report=}, {namespace=}")

        for_each(_import_report_wrapped, reports)

        logger.info("END: Importing reports")

    def import_artifact_sequences(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        incremental: bool = True,
        max_workers: Optional[int] = None,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ):
        """Import all artifact sequences from `namespaces`.

        Note: There is a known bug with the AWS backend where artifacts > 2048MB will fail to upload.  This seems to be related to multipart uploads, but we don't have a fix yet.
        """
        logger.info("START: Importing artifact sequences")
        _clear_fname(ARTIFACT_ERRORS_FNAME)

        logger.info("Collecting artifact sequences")
        seqs = list(self._collect_artifact_sequences(namespaces=namespaces))

        logger.info("Validating artifact sequences")
        self._validate_artifact_sequences(
            seqs,
            incremental=incremental,
            remapping=remapping,
        )

        logger.info("Collecting failed artifact sequences")
        seqs = list(self._collect_failed_artifact_sequences2())

        logger.info(f"Importing artifact sequences, {len(seqs)=}")

        def _import_artifact_sequence_wrapped(seq):
            namespace = Namespace(seq.entity, seq.project)
            if remapping is not None and namespace in remapping:
                namespace = remapping[namespace]

            logger.debug(f"Importing artifact sequence {seq=}, {namespace=}")
            self._import_artifact_sequence(seq, namespace=namespace)
            logger.debug(f"Finished importing artifact sequence {seq=}, {namespace=}")

        for_each(_import_artifact_sequence_wrapped, seqs, max_workers=max_workers)

        # it's safer to just use artifact on all seqs to make sure we don't miss anything
        # For seqs that have already been used, this is a no-op.
        logger.debug(f"Using artifact sequences, {len(seqs)=}")

        def _use_artifact_sequence_wrapped(seq):
            namespace = Namespace(seq.entity, seq.project)
            if remapping is not None and namespace in remapping:
                namespace = remapping[namespace]

            logger.debug(f"Using artifact sequence {seq=}, {namespace=}")
            self._use_artifact_sequence(seq, namespace=namespace)
            logger.debug(f"Finished using artifact sequence {seq=}, {namespace=}")

        for_each(_use_artifact_sequence_wrapped, seqs, max_workers=max_workers)

        # Artifacts whose parent runs have been deleted should have that run deleted in the
        # destination as well

        logger.info("Cleaning up dummy runs")
        self._cleanup_dummy_runs(
            namespaces=namespaces,
            remapping=remapping,
        )

        logger.info("END: Importing artifact sequences")

    def import_all(
        self,
        *,
        runs: bool = True,
        artifacts: bool = True,
        reports: bool = True,
        namespaces: Optional[Iterable[Namespace]] = None,
        incremental: bool = True,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ):
        logger.info(f"START: Importing all, {runs=}, {artifacts=}, {reports=}")
        if runs:
            self.import_runs(
                namespaces=namespaces,
                incremental=incremental,
                remapping=remapping,
            )

        if reports:
            self.import_reports(
                namespaces=namespaces,
                remapping=remapping,
            )

        if artifacts:
            self.import_artifact_sequences(
                namespaces=namespaces,
                incremental=incremental,
                remapping=remapping,
            )

        logger.info("END: Importing all")

    def _validate_run(
        self,
        src_run: Run,
        *,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ) -> None:
        namespace = Namespace(src_run.entity, src_run.project)
        if remapping is not None and namespace in remapping:
            namespace = remapping[namespace]

        dst_entity = namespace.entity
        dst_project = namespace.project
        run_id = src_run.id

        try:
            dst_run = self.dst_api.run(f"{dst_entity}/{dst_project}/{run_id}")
        except wandb.CommError:
            problems = [f"run does not exist in dst at {dst_entity=}/{dst_project=}"]
        else:
            problems = self._get_run_problems(src_run, dst_run)

        d = {
            "src_entity": src_run.entity,
            "src_project": src_run.project,
            "dst_entity": dst_entity,
            "dst_project": dst_project,
            "run_id": run_id,
        }
        if problems:
            d["problems"] = problems
            fname = RUN_ERRORS_FNAME
        else:
            fname = RUN_SUCCESSES_FNAME

        with filelock.FileLock("runs.lock"):
            with open(fname, "a") as f:
                f.write(json.dumps(d) + "\n")

    def _filter_previously_checked_runs(
        self,
        runs: Iterable[Run],
        *,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ) -> Iterable[Run]:
        if (df := _read_ndjson(RUN_SUCCESSES_FNAME)) is None:
            logger.debug(f"{RUN_SUCCESSES_FNAME=} is empty, yielding all runs")
            yield from runs
            return

        data = []
        for r in runs:
            namespace = Namespace(r.entity, r.project)
            if remapping is not None and namespace in remapping:
                namespace = remapping[namespace]

            data.append(
                {
                    "src_entity": r.entity,
                    "src_project": r.project,
                    "dst_entity": namespace.entity,
                    "dst_project": namespace.project,
                    "run_id": r.id,
                    "data": r,
                }
            )
        df2 = pl.DataFrame(data)
        logger.debug(f"Starting with {len(runs)=} in namespaces")

        results = df2.join(
            df,
            how="anti",
            on=["src_entity", "src_project", "dst_entity", "dst_project", "run_id"],
        )
        logger.debug(f"After filtering out already successful runs, {len(results)=}")

        if not results.is_empty():
            results = results.filter(~results["run_id"].is_null())
            results = results.unique(
                ["src_entity", "src_project", "dst_entity", "dst_project", "run_id"]
            )

        for r in results.iter_rows(named=True):
            yield r["data"]

    def _validate_artifact(
        self,
        src_art: Artifact,
        dst_entity: str,
        dst_project: str,
        download_files_and_compare: bool = False,
        check_entries_are_downloadable: bool = True,
    ):
        problems = []

        # These patterns of artifacts are special and should not be validated
        ignore_patterns = [
            r"^job-(.*?)\.py(:v\d+)?$",
            # r"^run-.*-history(?:\:v\d+)?$$",
        ]
        for pattern in ignore_patterns:
            if re.search(pattern, src_art.name):
                return (src_art, dst_entity, dst_project, problems)

        try:
            dst_art = self._get_dst_art(src_art, dst_entity, dst_project)
        except Exception:
            problems.append("destination artifact not found")
            return (src_art, dst_entity, dst_project, problems)

        try:
            logger.debug("Comparing artifact manifests")
        except Exception as e:
            problems.append(
                f"Problem getting problems! problem with {src_art.entity=}, {src_art.project=}, {src_art.name=} {e=}"
            )
        else:
            problems += self._compare_artifact_manifests(src_art, dst_art)

        if check_entries_are_downloadable:
            # _check_entries_are_downloadable(src_art)
            _check_entries_are_downloadable(dst_art)

        if download_files_and_compare:
            logger.debug(f"Downloading {src_art=}")
            try:
                src_dir = _download_art(src_art, root=f"./artifacts/src/{src_art.name}")
            except requests.HTTPError as e:
                problems.append(
                    f"Invalid download link for src {src_art.entity=}, {src_art.project=}, {src_art.name=}, {e}"
                )

            logger.debug(f"Downloading {dst_art=}")
            try:
                dst_dir = _download_art(dst_art, root=f"./artifacts/dst/{dst_art.name}")
            except requests.HTTPError as e:
                problems.append(
                    f"Invalid download link for dst {dst_art.entity=}, {dst_art.project=}, {dst_art.name=}, {e}"
                )
            else:
                logger.debug(f"Comparing artifact dirs {src_dir=}, {dst_dir=}")
                if problem := self._compare_artifact_dirs(src_dir, dst_dir):
                    problems.append(problem)

        return (src_art, dst_entity, dst_project, problems)

    def _validate_runs(
        self,
        runs: Iterable[WandbRun],
        *,
        skip_previously_validated: bool = True,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ):
        base_runs = [r.run for r in runs]
        if skip_previously_validated:
            base_runs = list(
                self._filter_previously_checked_runs(
                    base_runs,
                    remapping=remapping,
                )
            )

        def _validate_run(run):
            logger.debug(f"Validating {run=}")
            self._validate_run(run, remapping=remapping)
            logger.debug(f"Finished validating {run=}")

        for_each(_validate_run, base_runs)

    def _collect_failed_runs(self):
        if (df := _read_ndjson(RUN_ERRORS_FNAME)) is None:
            logger.debug(f"{RUN_ERRORS_FNAME=} is empty, returning nothing")
            return

        unique_failed_runs = df[
            ["src_entity", "src_project", "dst_entity", "dst_project", "run_id"]
        ].unique()

        for row in unique_failed_runs.iter_rows(named=True):
            src_entity = row["src_entity"]
            src_project = row["src_project"]
            # dst_entity = row["dst_entity"]
            # dst_project = row["dst_project"]
            run_id = row["run_id"]

            run = self.src_api.run(f"{src_entity}/{src_project}/{run_id}")
            yield WandbRun(run, **self.run_api_kwargs)

    def _filter_previously_checked_artifacts(self, seqs: Iterable[ArtifactSequence]):
        if (df := _read_ndjson(ARTIFACT_SUCCESSES_FNAME)) is None:
            logger.info(
                f"{ARTIFACT_SUCCESSES_FNAME=} is empty, yielding all artifact sequences"
            )
            for seq in seqs:
                yield from seq.artifacts
            return

        for seq in seqs:
            for art in seq:
                try:
                    logged_by = _get_run_or_dummy_from_art(art, self.src_api)
                except requests.HTTPError as e:
                    logger.error(f"Failed to get run, skipping: {art=}, {e=}")
                    continue

                if art.type == "wandb-history" and isinstance(logged_by, _DummyRun):
                    logger.debug(f"Skipping history artifact {art=}")
                    # We can never upload valid history for a deleted run, so skip it
                    continue

                entity = art.entity
                project = art.project
                _type = art.type
                name, ver = _get_art_name_ver(art)

                filtered_df = df.filter(
                    (df["src_entity"] == entity)
                    & (df["src_project"] == project)
                    & (df["name"] == name)
                    & (df["version"] == ver)
                    & (df["type"] == _type)
                )

                # not in file, so not verified yet, don't filter out
                if len(filtered_df) == 0:
                    yield art

    def _validate_artifact_sequences(
        self,
        seqs: Iterable[ArtifactSequence],
        *,
        incremental: bool = True,
        download_files_and_compare: bool = False,
        check_entries_are_downloadable: bool = True,
        remapping: Optional[Dict[Namespace, Namespace]] = None,
    ):
        if incremental:
            logger.info("Validating in incremental mode")

            def filtered_sequences():
                for seq in seqs:
                    if not seq.artifacts:
                        continue

                    art = seq.artifacts[0]
                    try:
                        logged_by = _get_run_or_dummy_from_art(art, self.src_api)
                    except requests.HTTPError as e:
                        logger.error(
                            f"Validate Artifact http error: {art.entity=}, {art.project=}, {art.name=}, {e=}"
                        )
                        continue

                    if art.type == "wandb-history" and isinstance(logged_by, _DummyRun):
                        # We can never upload valid history for a deleted run, so skip it
                        continue

                    yield seq

            artifacts = self._filter_previously_checked_artifacts(filtered_sequences())
        else:
            logger.info("Validating in non-incremental mode")
            artifacts = [art for seq in seqs for art in seq.artifacts]

        def _validate_artifact_wrapped(args):
            art, entity, project = args
            if (ns := Namespace(entity, project)) in remapping:
                remapped_ns = remapping[ns]
                entity = remapped_ns.entity
                project = remapped_ns.project

            logger.debug(f"Validating {art=}, {entity=}, {project=}")
            result = self._validate_artifact(
                art,
                entity,
                project,
                download_files_and_compare=download_files_and_compare,
                check_entries_are_downloadable=check_entries_are_downloadable,
            )
            logger.debug(f"Finished validating {art=}, {entity=}, {project=}")
            return result

        args = ((art, art.entity, art.project) for art in artifacts)
        art_problems = for_each(_validate_artifact_wrapped, args)
        for art, dst_entity, dst_project, problems in art_problems:
            name, ver = _get_art_name_ver(art)
            d = {
                "src_entity": art.entity,
                "src_project": art.project,
                "dst_entity": dst_entity,
                "dst_project": dst_project,
                "name": name,
                "version": ver,
                "type": art.type,
            }

            if problems:
                d["problems"] = problems
                fname = ARTIFACT_ERRORS_FNAME
            else:
                fname = ARTIFACT_SUCCESSES_FNAME

            with open(fname, "a") as f:
                f.write(json.dumps(d) + "\n")

    def _collect_runs(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
        skip_ids: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        api: Optional[Api] = None,
    ) -> Iterable[WandbRun]:
        api = coalesce(api, self.src_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        filters: Dict[str, Any] = {}
        if skip_ids is not None:
            filters["name"] = {"$nin": skip_ids}
        if start_date is not None:
            filters["createdAt"] = {"$gte": start_date}

        def _runs():
            for ns in namespaces:
                logger.debug(f"Collecting runs from {ns=}")
                for run in api.runs(ns.path, filters=filters):
                    yield WandbRun(run, **self.run_api_kwargs)

        runs = itertools.islice(_runs(), limit)
        yield from runs

    def _all_namespaces(
        self, *, entity: Optional[str] = None, api: Optional[Api] = None
    ):
        api = coalesce(api, self.src_api)
        entity = coalesce(entity, api.default_entity)
        projects = api.projects(entity)
        for p in projects:
            yield Namespace(p.entity, p.name)

    def _collect_reports(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        wandb.login(key=self.src_api_key, host=self.src_base_url)

        def reports():
            for ns in namespaces:
                for r in api.reports(ns.path):
                    yield wr.Report.from_url(r.url, api=api)

        yield from itertools.islice(reports(), limit)

    def _collect_artifact_sequences(
        self,
        *,
        namespaces: Optional[Iterable[Namespace]] = None,
        limit: Optional[int] = None,
        api: Optional[Api] = None,
    ):
        api = coalesce(api, self.src_api)
        namespaces = coalesce(namespaces, self._all_namespaces())

        def artifact_sequences():
            for ns in namespaces:
                logger.debug(f"Collecting artifact sequences from {ns=}")
                types = []
                try:
                    types = [t for t in api.artifact_types(ns.path)]
                except Exception as e:
                    logger.error(f"Failed to get artifact types {e=}")

                for t in types:
                    collections = []

                    # Skip history because it's really for run history
                    if t.name == "wandb-history":
                        continue

                    try:
                        collections = t.collections()
                    except Exception as e:
                        logger.error(f"Failed to get artifact collections {e=}")

                    for c in collections:
                        if c.is_sequence():
                            yield ArtifactSequence.from_collection(c)

        seqs = itertools.islice(artifact_sequences(), limit)
        unique_sequences = {seq.identifier: seq for seq in seqs}
        yield from unique_sequences.values()


def _check_entries_are_downloadable(art):
    entries = _collect_entries(art)
    for entry in entries:
        if not _check_entry_is_downloable(entry):
            return False
    return True


def _collect_entries(art):
    has_next_page = True
    cursor = None
    entries = []
    while has_next_page:
        attrs = art._fetch_file_urls(cursor)
        has_next_page = attrs["pageInfo"]["hasNextPage"]
        cursor = attrs["pageInfo"]["endCursor"]
        for edge in attrs["edges"]:
            name = edge["node"]["name"]
            entry = art.get_entry(name)
            entry._download_url = edge["node"]["directUrl"]
            entries.append(entry)
    return entries


def _check_entry_is_downloable(entry):
    url = entry._download_url
    expected_size = entry.size

    try:
        resp = requests.head(url, allow_redirects=True)
    except Exception as e:
        logger.error(f"Problem validating {entry=}, {e=}")
        return False

    if resp.status_code != 200:
        return False

    actual_size = resp.headers.get("content-length", -1)
    actual_size = int(actual_size)

    if expected_size == actual_size:
        return True

    return False


def _get_art_name_ver(art: Artifact) -> Tuple[str, int]:
    name, ver = art.name.split(":v")
    return name, int(ver)


def _make_dummy_art(name: str, _type: str, ver: int):
    art = Artifact(name, ART_DUMMY_PLACEHOLDER_TYPE)
    art._type = _type
    art._description = ART_SEQUENCE_DUMMY_PLACEHOLDER

    p = Path(ART_DUMMY_PLACEHOLDER_PATH)
    p.mkdir(parents=True, exist_ok=True)
    fname = p / str(ver)
    with open(fname, "w"):
        pass
    art.add_file(fname)
    return art


def _make_groups_of_artifacts(seq, start=0):
    prev_ver, first = None, True

    for art in seq:
        name, ver = _get_art_name_ver(art)
        if first:
            if ver > start:
                yield [_make_dummy_art(name, art.type, v) for v in range(start, ver)]
            first = False
        else:
            if ver - prev_ver > 1:
                yield [
                    _make_dummy_art(name, art.type, v) for v in range(prev_ver + 1, ver)
                ]
        yield [art]
        prev_ver = ver


def _recursive_cast_to_dict(obj):
    if isinstance(obj, list):
        return [_recursive_cast_to_dict(item) for item in obj]
    elif isinstance(obj, dict) or hasattr(obj, "items"):
        new_dict = {}
        for key, value in obj.items():
            new_dict[key] = _recursive_cast_to_dict(value)
        return new_dict
    else:
        return obj


def _almost_equal(x, y, eps=1e-6):
    if isinstance(x, dict) and isinstance(y, dict):
        if x.keys() != y.keys():
            return False
        return all(_almost_equal(x[k], y[k], eps) for k in x)

    if isinstance(x, numbers.Number) and isinstance(y, numbers.Number):
        return abs(x - y) < eps

    if type(x) is not type(y):
        return False

    return x == y


@dataclass
class _DummyUser:
    username: str = ""


@dataclass
class _DummyRun:
    entity: str = ""
    project: str = ""
    run_id: str = RUN_DUMMY_PLACEHOLDER
    id: str = RUN_DUMMY_PLACEHOLDER
    display_name: str = RUN_DUMMY_PLACEHOLDER
    notes: str = ""
    url: str = ""
    group: str = ""
    created_at: str = "2000-01-01"
    user: _DummyUser = field(default_factory=_DummyUser)
    tags: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def files(self):
        return []


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


def _get_run_or_dummy_from_art(art: Artifact, api=None):
    run = None
    try:
        run = art.logged_by()
    except ValueError as e:
        logger.warn(
            f"Can't log artifact because run does't exist, {art=}, {run=}, {e=}"
        )

    if run is not None:
        return run

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
    response = api.client.execute(query, variable_values={"id": art.id})
    creator = response.get("artifact", {}).get("createdBy", {})
    run = _DummyRun(
        entity=art.entity,
        project=art.project,
        run_id=creator.get("name", RUN_DUMMY_PLACEHOLDER),
        id=creator.get("name", RUN_DUMMY_PLACEHOLDER),
    )
    return run


def _clear_fname(fname: str) -> None:
    src = "./" + fname
    dst = "./prev_" + fname

    logger.debug(f"Moving {src=} to {dst=}")
    try:
        shutil.copy2(src, dst)
    except FileNotFoundError:
        # this is just to make a copy of the last iteration, so its ok if the src doesn't exist
        pass

    with open(fname, "w"):
        pass


def _download_art(art: Artifact, root: str) -> Optional[str]:
    try:
        with patch("click.echo"):
            return art.download(root=root, skip_cache=True)
    except Exception as e:
        logger.error(f"Error downloading artifact {art=}, {e=}")


def _clone_art(art: Artifact, root: Optional[str] = None):
    if root is None:
        # Currently, we would only ever clone a src artifact to move it to dst.
        root = f"./artifacts/src/{art.name}"

    if (path := _download_art(art, root=root)) is None:
        raise ValueError(f"Problem downloading {art=}")

    name, _ = art.name.split(":v")

    # Hack: skip naming validation check for wandb-* types
    new_art = Artifact(name, ART_DUMMY_PLACEHOLDER_TYPE)
    new_art._type = art.type
    new_art._created_at = art.created_at

    new_art._aliases = art.aliases
    new_art._description = art.description

    with patch("click.echo"):
        new_art.add_dir(path)

    return new_art


def _create_files_if_not_exists():
    fnames = [
        ARTIFACT_ERRORS_FNAME,
        ARTIFACT_SUCCESSES_FNAME,
        RUN_ERRORS_FNAME,
        RUN_SUCCESSES_FNAME,
    ]

    for fname in fnames:
        logger.debug(f"Creating {fname=} if not exists")
        with open(fname, "a"):
            pass


def _merge_dfs(dfs: List[pl.DataFrame]) -> pl.DataFrame:
    # Ensure there are DataFrames in the list
    if len(dfs) == 0:
        return pl.DataFrame()

    if len(dfs) == 1:
        return dfs[0]

    merged_df = dfs[0]
    for df in dfs[1:]:
        merged_df = merged_df.join(df, how="outer", on=["_step"])
        col_pairs = [
            (c, f"{c}_right")
            for c in merged_df.columns
            if f"{c}_right" in merged_df.columns
        ]
        for col, right in col_pairs:
            new_col = merged_df[col].fill_null(merged_df[right])
            merged_df = merged_df.with_columns(new_col).drop(right)

    return merged_df

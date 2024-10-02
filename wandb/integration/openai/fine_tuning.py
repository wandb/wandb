import base64
import datetime
import io
import json
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import wandb
from wandb import util
from wandb.data_types import Table
from wandb.sdk.lib import telemetry
from wandb.sdk.wandb_run import Run
from wandb.util import parse_version

openai = util.get_module(
    name="openai",
    required="This integration requires `openai`. To install, please run `pip install openai`",
    lazy=False,
)

if parse_version(openai.__version__) < parse_version("1.12.0"):
    raise wandb.Error(
        f"This integration requires openai version 1.12.0 and above. Your current version is {openai.__version__} "
        "To fix, please `pip install -U openai`"
    )

from openai import OpenAI  # noqa: E402
from openai.types.fine_tuning import FineTuningJob  # noqa: E402
from openai.types.fine_tuning.fine_tuning_job import (  # noqa: E402
    Error,
    Hyperparameters,
)

np = util.get_module(
    name="numpy",
    required="`numpy` not installed >> This integration requires numpy!  To fix, please `pip install numpy`",
    lazy=False,
)

pd = util.get_module(
    name="pandas",
    required="`pandas` not installed >> This integration requires pandas!  To fix, please `pip install pandas`",
    lazy=False,
)


class WandbLogger:
    """Log OpenAI fine-tunes to [Weights & Biases](https://wandb.me/openai-docs)."""

    _wandb_api: Optional[wandb.Api] = None
    _logged_in: bool = False
    openai_client: Optional[OpenAI] = None
    _run: Optional[Run] = None

    @classmethod
    def sync(
        cls,
        fine_tune_job_id: Optional[str] = None,
        openai_client: Optional[OpenAI] = None,
        num_fine_tunes: Optional[int] = None,
        project: str = "OpenAI-Fine-Tune",
        entity: Optional[str] = None,
        overwrite: bool = False,
        wait_for_job_success: bool = True,
        log_datasets: bool = True,
        model_artifact_name: str = "model-metadata",
        model_artifact_type: str = "model",
        **kwargs_wandb_init: Dict[str, Any],
    ) -> str:
        """Sync fine-tunes to Weights & Biases.

        :param fine_tune_job_id: The id of the fine-tune (optional)
        :param openai_client: Pass the `OpenAI()` client (optional)
        :param num_fine_tunes: Number of most recent fine-tunes to log when an fine_tune_job_id is not provided. By default, every fine-tune is synced.
        :param project: Name of the project where you're sending runs. By default, it is "GPT-3".
        :param entity: Username or team name where you're sending runs. By default, your default entity is used, which is usually your username.
        :param overwrite: Forces logging and overwrite existing wandb run of the same fine-tune.
        :param wait_for_job_success: Waits for the fine-tune to be complete and then log metrics to W&B. By default, it is True.
        :param model_artifact_name: Name of the model artifact that is logged
        :param model_artifact_type: Type of the model artifact that is logged
        """
        if openai_client is None:
            openai_client = OpenAI()
        cls.openai_client = openai_client

        if fine_tune_job_id:
            wandb.termlog("Retrieving fine-tune job...")
            fine_tune = openai_client.fine_tuning.jobs.retrieve(
                fine_tuning_job_id=fine_tune_job_id
            )
            fine_tunes = [fine_tune]
        else:
            # get list of fine_tune to log
            fine_tunes = openai_client.fine_tuning.jobs.list()
            if not fine_tunes or fine_tunes.data is None:
                wandb.termwarn("No fine-tune has been retrieved")
                return
            # Select the `num_fine_tunes` from the `fine_tunes.data` list.
            # If `num_fine_tunes` is None, it selects all items in the list (from start to end).
            # If for example, `num_fine_tunes` is 5, it selects the last 5 items in the list.
            # Note that the last items in the list are the latest fine-tune jobs.
            fine_tunes = fine_tunes.data[
                -num_fine_tunes if num_fine_tunes is not None else None :
            ]

        # log starting from oldest fine_tune
        show_individual_warnings = (
            fine_tune_job_id is not None or num_fine_tunes is not None
        )
        fine_tune_logged = []
        for fine_tune in fine_tunes:
            fine_tune_id = fine_tune.id
            # check run with the given `fine_tune_id` has not been logged already
            run_path = f"{project}/{fine_tune_id}"
            if entity is not None:
                run_path = f"{entity}/{run_path}"
            wandb_run = cls._get_wandb_run(run_path)
            if wandb_run:
                wandb_status = wandb_run.summary.get("status")
                if show_individual_warnings:
                    if wandb_status == "succeeded" and not overwrite:
                        wandb.termwarn(
                            f"Fine-tune {fine_tune_id} has already been logged successfully at {wandb_run.url}. "
                            "Use `overwrite=True` if you want to overwrite previous run"
                        )
                    elif wandb_status != "succeeded" or overwrite:
                        if wandb_status != "succeeded":
                            wandb.termwarn(
                                f"A run for fine-tune {fine_tune_id} was previously created but didn't end successfully"
                            )
                        wandb.termlog(
                            f"A new wandb run will be created for fine-tune {fine_tune_id} and previous run will be overwritten"
                        )
                        overwrite = True
                if wandb_status == "succeeded" and not overwrite:
                    return

            # check if the user has not created a wandb run externally
            if wandb.run is None:
                cls._run = wandb.init(
                    job_type="fine-tune",
                    project=project,
                    entity=entity,
                    name=fine_tune_id,
                    id=fine_tune_id,
                    **kwargs_wandb_init,
                )
            else:
                # if a run exits - created externally
                cls._run = wandb.run

            if wait_for_job_success:
                fine_tune = cls._wait_for_job_success(fine_tune)

            cls._log_fine_tune(
                fine_tune,
                project,
                entity,
                overwrite,
                show_individual_warnings,
                log_datasets,
                model_artifact_name,
                model_artifact_type,
                **kwargs_wandb_init,
            )

        if not show_individual_warnings and not any(fine_tune_logged):
            wandb.termwarn("No new successful fine-tunes were found")

        return "🎉 wandb sync completed successfully"

    @classmethod
    def _wait_for_job_success(cls, fine_tune: FineTuningJob) -> FineTuningJob:
        wandb.termlog("Waiting for the OpenAI fine-tuning job to finish training...")
        wandb.termlog(
            "To avoid blocking, you can call `WandbLogger.sync` with `wait_for_job_success=False` after OpenAI training completes."
        )
        while True:
            if fine_tune.status == "succeeded":
                wandb.termlog(
                    "Fine-tuning finished, logging metrics, model metadata, and run metadata to Weights & Biases"
                )
                return fine_tune
            if fine_tune.status == "failed":
                wandb.termwarn(
                    f"Fine-tune {fine_tune.id} has failed and will not be logged"
                )
                return fine_tune
            if fine_tune.status == "cancelled":
                wandb.termwarn(
                    f"Fine-tune {fine_tune.id} was cancelled and will not be logged"
                )
                return fine_tune
            time.sleep(10)
            fine_tune = cls.openai_client.fine_tuning.jobs.retrieve(
                fine_tuning_job_id=fine_tune.id
            )

    @classmethod
    def _log_fine_tune(
        cls,
        fine_tune: FineTuningJob,
        project: str,
        entity: Optional[str],
        overwrite: bool,
        show_individual_warnings: bool,
        log_datasets: bool,
        model_artifact_name: str,
        model_artifact_type: str,
        **kwargs_wandb_init: Dict[str, Any],
    ):
        fine_tune_id = fine_tune.id
        status = fine_tune.status

        with telemetry.context(run=cls._run) as tel:
            tel.feature.openai_finetuning = True

        # check run completed successfully
        if status != "succeeded":
            if show_individual_warnings:
                wandb.termwarn(
                    f'Fine-tune {fine_tune_id} has the status "{status}" and will not be logged'
                )
            return

        # check results are present
        try:
            results_id = fine_tune.result_files[0]
            try:
                encoded_results = cls.openai_client.files.content(
                    file_id=results_id
                ).read()
                results = base64.b64decode(encoded_results).decode("utf-8")
            except Exception:
                # attempt to read as text, works for older jobs
                results = cls.openai_client.files.content(file_id=results_id).text
        except openai.NotFoundError:
            if show_individual_warnings:
                wandb.termwarn(
                    f"Fine-tune {fine_tune_id} has no results and will not be logged"
                )
            return

        # update the config
        cls._run.config.update(cls._get_config(fine_tune))

        # log results
        df_results = pd.read_csv(io.StringIO(results))
        for _, row in df_results.iterrows():
            metrics = {k: v for k, v in row.items() if not np.isnan(v)}
            step = metrics.pop("step")
            if step is not None:
                step = int(step)
            cls._run.log(metrics, step=step)
        fine_tuned_model = fine_tune.fine_tuned_model
        if fine_tuned_model is not None:
            cls._run.summary["fine_tuned_model"] = fine_tuned_model

        # training/validation files and fine-tune details
        cls._log_artifacts(
            fine_tune,
            project,
            entity,
            log_datasets,
            overwrite,
            model_artifact_name,
            model_artifact_type,
        )

        # mark run as complete
        cls._run.summary["status"] = "succeeded"

        cls._run.finish()
        return True

    @classmethod
    def _ensure_logged_in(cls):
        if not cls._logged_in:
            if wandb.login():
                cls._logged_in = True
            else:
                raise Exception(
                    "It appears you are not currently logged in to Weights & Biases. "
                    "Please run `wandb login` in your terminal or `wandb.login()` in a notebook."
                    "When prompted, you can obtain your API key by visiting wandb.ai/authorize."
                )

    @classmethod
    def _get_wandb_run(cls, run_path: str):
        cls._ensure_logged_in()
        try:
            if cls._wandb_api is None:
                cls._wandb_api = wandb.Api()
            return cls._wandb_api.run(run_path)
        except Exception:
            return None

    @classmethod
    def _get_wandb_artifact(cls, artifact_path: str):
        cls._ensure_logged_in()
        try:
            if cls._wandb_api is None:
                cls._wandb_api = wandb.Api()
            return cls._wandb_api.artifact(artifact_path)
        except Exception:
            return None

    @classmethod
    def _get_config(cls, fine_tune: FineTuningJob) -> Dict[str, Any]:
        config = dict(fine_tune)
        config["result_files"] = config["result_files"][0]
        if config.get("created_at"):
            config["created_at"] = datetime.datetime.fromtimestamp(
                config["created_at"]
            ).strftime("%Y-%m-%d %H:%M:%S")
        if config.get("finished_at"):
            config["finished_at"] = datetime.datetime.fromtimestamp(
                config["finished_at"]
            ).strftime("%Y-%m-%d %H:%M:%S")
        if config.get("hyperparameters"):
            config["hyperparameters"] = cls.sanitize(config["hyperparameters"])
        if config.get("error"):
            config["error"] = cls.sanitize(config["error"])
        return config

    @classmethod
    def _unpack_hyperparameters(cls, hyperparameters: Hyperparameters):
        # `Hyperparameters` object is not unpacking properly using `vars` or `__dict__`,
        # vars(hyperparameters) return {n_epochs: n} only.
        hyperparams = {}
        try:
            hyperparams["n_epochs"] = hyperparameters.n_epochs
            hyperparams["batch_size"] = hyperparameters.batch_size
            hyperparams["learning_rate_multiplier"] = (
                hyperparameters.learning_rate_multiplier
            )
        except Exception:
            # If unpacking fails, return the object to be logged as config
            return None

        return hyperparams

    @staticmethod
    def sanitize(input: Any) -> Union[Dict, List, str]:
        valid_types = [bool, int, float, str]
        if isinstance(input, (Hyperparameters, Error)):
            return dict(input)
        if isinstance(input, dict):
            return {
                k: v if type(v) in valid_types else str(v) for k, v in input.items()
            }
        elif isinstance(input, list):
            return [v if type(v) in valid_types else str(v) for v in input]
        else:
            return str(input)

    @classmethod
    def _log_artifacts(
        cls,
        fine_tune: FineTuningJob,
        project: str,
        entity: Optional[str],
        log_datasets: bool,
        overwrite: bool,
        model_artifact_name: str,
        model_artifact_type: str,
    ) -> None:
        if log_datasets:
            wandb.termlog("Logging training/validation files...")
            # training/validation files
            training_file = fine_tune.training_file if fine_tune.training_file else None
            validation_file = (
                fine_tune.validation_file if fine_tune.validation_file else None
            )
            for file, prefix, artifact_type in (
                (training_file, "train", "training_files"),
                (validation_file, "valid", "validation_files"),
            ):
                if file is not None:
                    cls._log_artifact_inputs(
                        file, prefix, artifact_type, project, entity, overwrite
                    )

        # fine-tune details
        fine_tune_id = fine_tune.id
        artifact = wandb.Artifact(
            model_artifact_name,
            type=model_artifact_type,
            metadata=dict(fine_tune),
        )

        with artifact.new_file("model_metadata.json", mode="w", encoding="utf-8") as f:
            dict_fine_tune = dict(fine_tune)
            dict_fine_tune["hyperparameters"] = cls.sanitize(
                dict_fine_tune["hyperparameters"]
            )
            dict_fine_tune["error"] = cls.sanitize(dict_fine_tune["error"])
            dict_fine_tune = cls.sanitize(dict_fine_tune)
            json.dump(dict_fine_tune, f, indent=2)
        cls._run.log_artifact(
            artifact,
            aliases=["latest", fine_tune_id],
        )

    @classmethod
    def _log_artifact_inputs(
        cls,
        file_id: Optional[str],
        prefix: str,
        artifact_type: str,
        project: str,
        entity: Optional[str],
        overwrite: bool,
    ) -> None:
        # get input artifact
        artifact_name = f"{prefix}-{file_id}"
        # sanitize name to valid wandb artifact name
        artifact_name = re.sub(r"[^a-zA-Z0-9_\-.]", "_", artifact_name)
        artifact_alias = file_id
        artifact_path = f"{project}/{artifact_name}:{artifact_alias}"
        if entity is not None:
            artifact_path = f"{entity}/{artifact_path}"
        artifact = cls._get_wandb_artifact(artifact_path)

        # create artifact if file not already logged previously
        if artifact is None or overwrite:
            # get file content
            try:
                file_content = cls.openai_client.files.content(file_id=file_id)
            except openai.NotFoundError:
                wandb.termerror(
                    f"File {file_id} could not be retrieved. Make sure you have OpenAI permissions to download training/validation files"
                )
                return

            artifact = wandb.Artifact(artifact_name, type=artifact_type)
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_file.write(file_content.content)
                tmp_file_path = tmp_file.name
            artifact.add_file(tmp_file_path, file_id)
            os.unlink(tmp_file_path)

            # create a Table
            try:
                table, n_items = cls._make_table(file_content.text)
                # Add table to the artifact.
                artifact.add(table, file_id)
                # Add the same table to the workspace.
                cls._run.log({f"{prefix}_data": table})
                # Update the run config and artifact metadata
                cls._run.config.update({f"n_{prefix}": n_items})
                artifact.metadata["items"] = n_items
            except Exception as e:
                wandb.termerror(
                    f"Issue saving {file_id} as a Table to Artifacts, exception:\n  '{e}'"
                )
        else:
            # log number of items
            cls._run.config.update({f"n_{prefix}": artifact.metadata.get("items")})

        cls._run.use_artifact(artifact, aliases=["latest", artifact_alias])

    @classmethod
    def _make_table(cls, file_content: str) -> Tuple[Table, int]:
        table = wandb.Table(columns=["role: system", "role: user", "role: assistant"])

        df = pd.read_json(io.StringIO(file_content), orient="records", lines=True)
        for _idx, message in df.iterrows():
            messages = message.messages
            assert len(messages) == 3
            table.add_data(
                messages[0]["content"],
                messages[1]["content"],
                messages[2]["content"],
            )

        return table, len(df)

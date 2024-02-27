import json
import logging
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from unittest.mock import MagicMock

import numpy as np
from rich.logging import RichHandler
from tenacity import retry, stop_after_attempt, wait_random_exponential

from wandb import Artifact
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as telem_pb
from wandb.sdk.interface.interface import file_policy_to_enum
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import context, sender, settings_static
from wandb.util import cast_dictlike_to_dict, coalesce

from .protocols import ImporterRun

logging.basicConfig(
    handlers=[
        RichHandler(
            rich_tracebacks=True,
            tracebacks_show_locals=True,
        )
    ]
)

logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

logger = logging.getLogger("import_logger")
logger.setLevel(logging.DEBUG)


exp_retry = retry(
    wait=wait_random_exponential(multiplier=1, max=10), stop=stop_after_attempt(3)
)


class AlternateSendManager(sender.SendManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_artifact = exp_retry(self._send_artifact)


@dataclass(frozen=True)
class SendManagerConfig:
    """Configure which parts of SendManager tooling to use."""

    use_artifacts: bool = False
    log_artifacts: bool = False
    metadata: bool = False
    files: bool = False
    media: bool = False
    code: bool = False
    history: bool = False
    summary: bool = False
    terminal_output: bool = False


@dataclass
class RecordMaker:
    run: ImporterRun
    interface: InterfaceQueue = InterfaceQueue()

    @property
    def run_dir(self) -> str:
        p = Path(f"./wandb-importer/{self.run.run_id()}/wandb")
        p.mkdir(parents=True, exist_ok=True)
        return f"./wandb-importer/{self.run.run_id()}"

    def _make_fake_run_record(self):
        """Make a fake run record.

        Unfortunately, the vanilla Run object does a check for existence on the server,
        so we use this as the simplest hack to skip that check.
        """
        # in this case run is a magicmock, so we need to convert the return types back to vanilla py types
        run = pb.RunRecord()
        run.entity = self.run.run.entity.return_value
        run.project = self.run.run.project.return_value
        run.run_id = self.run.run.run_id.return_value

        return self.interface._make_record(run=run)

    def _make_header_record(self) -> pb.Record:
        header = pb.HeaderRecord()
        # header.run_id = self.run.run_id()
        # header.project = self.run.project()
        # header.entity = self.run.entity()
        return self.interface._make_record(header=header)

    def _make_footer_record(self) -> pb.Record:
        footer = pb.FooterRecord()
        # footer.run_id = self.run.run_id()
        return self.interface._make_record(footer=footer)

    def _make_run_record(self) -> pb.Record:
        # unfortunate hack to get deleted wandb runs to work...
        if hasattr(self.run, "run") and isinstance(self.run.run, MagicMock):
            return self._make_fake_run_record()

        run = pb.RunRecord()
        run.run_id = self.run.run_id()
        run.entity = self.run.entity()
        run.project = self.run.project()
        run.display_name = coalesce(self.run.display_name())
        run.notes = coalesce(self.run.notes(), "")
        run.tags.extend(coalesce(self.run.tags(), []))
        run.start_time.FromMilliseconds(self.run.start_time())

        host = self.run.host()
        if host is not None:
            run.host = host

        runtime = self.run.runtime()
        if runtime is not None:
            run.runtime = runtime

        run_group = self.run.run_group()
        if run_group is not None:
            run.run_group = run_group

        config = self.run.config()
        if "_wandb" not in config:
            config["_wandb"] = {}

        # how do I get this automatically?
        config["_wandb"]["code_path"] = self.run.code_path()
        config["_wandb"]["python_version"] = self.run.python_version()
        config["_wandb"]["cli_version"] = self.run.cli_version()

        self.interface._make_config(
            data=config,
            obj=run.config,
        )  # is there a better way?
        return self.interface._make_record(run=run)

    def _make_output_record(self, line) -> pb.Record:
        output_raw = pb.OutputRawRecord()
        output_raw.output_type = pb.OutputRawRecord.OutputType.STDOUT
        output_raw.line = line
        return self.interface._make_record(output_raw=output_raw)

    def _make_summary_record(self) -> pb.Record:
        d: dict = {
            **self.run.summary(),
            "_runtime": self.run.runtime(),  # quirk of runtime -- it has to be here!
            # '_timestamp': self.run.start_time()/1000,
        }
        d = cast_dictlike_to_dict(d)
        summary = self.interface._make_summary_from_dict(d)
        return self.interface._make_record(summary=summary)

    def _make_history_records(self) -> Iterable[pb.Record]:
        import math

        for metrics in self.run.metrics():
            history = pb.HistoryRecord()
            for k, v in metrics.items():
                item = history.item.add()
                item.key = k
                # There seems to be some conversion issue to breaks when we try to re-upload.
                # np.NaN gets converted to float("nan"), which is not expected by our system.
                # If this cast to string (!) is not done, the row will be dropped.
                if (isinstance(v, float) and math.isnan(v)) or v == "NaN":
                    v = np.NaN

                if isinstance(v, bytes):
                    # it's a json string encoded as bytes
                    v = v.decode("utf-8")
                else:
                    v = json.dumps(v)

                item.value_json = v
            rec = self.interface._make_record(history=history)
            yield rec

    def _make_files_record(
        self, metadata, artifacts, files, media, code
    ) -> pb.FilesRecord:
        files = self.run.files()
        metadata_fname = f"{self.run_dir}/files/wandb-metadata.json"
        if files is None:
            metadata_fname = self._make_metadata_file()
            files = [(metadata_fname, "end")]

        # path = f"{self.run_dir}/files/media"
        # logger.info(f"Made {path=}")
        # filesystem.mkdir_exists_ok(path)

        # path = f"{self.run_dir}/files/media/images"
        # logger.info(f"Made {path=}")
        # filesystem.mkdir_exists_ok(path)

        files_record = pb.FilesRecord()
        for path, policy in files:
            print(f"Start making files record {path=}, {policy=}")
            if not metadata and path == metadata_fname:
                continue
            if not artifacts and path.startswith("artifact/"):
                continue
            if not media and path.startswith("media/"):
                continue
            if not code and path.startswith("code/"):
                continue

            f = files_record.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)  # is this always end?
            print(f"Making files record {f=}")

        return files_record
        # return self.interface._make_record(files=files_record)

    def _make_artifact_record(self, artifact, use_artifact=False) -> pb.Record:
        proto = self.interface._make_artifact(artifact)
        proto.run_id = str(self.run.run_id())
        proto.project = str(self.run.project())
        proto.entity = str(self.run.entity())
        proto.user_created = use_artifact
        proto.use_after_commit = use_artifact
        proto.finalize = True

        aliases = artifact._aliases
        aliases += ["latest", "imported"]

        for alias in aliases:
            proto.aliases.append(alias)
        return self.interface._make_record(artifact=proto)

    def _make_telem_record(self) -> pb.Record:
        telem = telem_pb.TelemetryRecord()

        feature = telem_pb.Feature()
        feature.importer_mlflow = True
        telem.feature.CopyFrom(feature)

        cli_version = self.run.cli_version()
        if cli_version:
            telem.cli_version = cli_version

        python_version = self.run.python_version()
        if python_version:
            telem.python_version = python_version

        return self.interface._make_record(telemetry=telem)

    def _make_metadata_file(self) -> str:
        missing_text = "This data was not captured"

        d = {}
        d["os"] = coalesce(self.run.os_version(), missing_text)
        d["python"] = coalesce(self.run.python_version(), missing_text)
        d["program"] = coalesce(self.run.program(), missing_text)
        d["cuda"] = coalesce(self.run.cuda_version(), missing_text)
        d["host"] = coalesce(self.run.host(), missing_text)
        d["username"] = coalesce(self.run.username(), missing_text)
        d["executable"] = coalesce(self.run.executable(), missing_text)

        gpus_used = self.run.gpus_used()
        if gpus_used is not None:
            d["gpu_devices"] = json.dumps(gpus_used)
            d["gpu_count"] = json.dumps(len(gpus_used))

        cpus_used = self.run.cpus_used()
        if cpus_used is not None:
            d["cpu_count"] = json.dumps(self.run.cpus_used())

        mem_used = self.run.memory_used()
        if mem_used is not None:
            d["memory"] = json.dumps({"total": self.run.memory_used()})

        fname = f"{self.run_dir}/files/wandb-metadata.json"
        with open(fname, "w") as f:
            f.write(json.dumps(d))
        return fname


def _make_settings(root_dir: str, settings_override: Optional[Dict[str, Any]] = None):
    _settings_override = coalesce(settings_override, {})

    default_settings: Dict[str, Any] = {
        # "files_dir": os.path.join(root_dir, "files"),
        "files_dir": "files",
        "root_dir": root_dir,
        "resume": "false",
        "program": None,
        "ignore_globs": [],
        "disable_job_creation": True,
        "_start_time": 0.0,
        "_offline": None,
        "_sync": True,
        "_live_policy_rate_limit": 15,  # matches dir_watcher
        "_live_policy_wait_time": 600,  # matches dir_watcher
        "_async_upload_concurrency_limit": None,
        "_file_stream_timeout_seconds": 60,
    }

    combined_settings = {**default_settings, **_settings_override}
    import os

    from wandb import Settings
    from wandb.proto import wandb_settings_pb2

    Settings, wandb_settings_pb2

    # settings_message = wandb_settings_pb2.Settings()
    # settings = Settings(**combined_settings)
    # s = settings_static.SettingsStatic(settings.to_proto())
    # from google.protobuf.json_format import ParseDict

    # ParseDict(combined_settings, settings_message)

    # s = settings_static.SettingsStatic(settings_message)

    settings = Settings(**combined_settings)
    s = settings_static.SettingsStatic(settings.to_proto())
    s.files_dir = os.path.join(root_dir, "files")
    s._tmp_code_dir = os.path.join(root_dir, "tmp/code")
    s.log_dir = os.path.join(root_dir, "logs")
    s.log_internal = os.path.join(root_dir, "logs/debug-internal.log")
    s.log_user = os.path.join(root_dir, "logs/debug.log")
    s.sync_dir = root_dir
    s.sync_file = os.path.join(root_dir, "run-something.wandb")
    s.tmp_dir = os.path.join(root_dir, "tmp")

    logger.info(f"Settings is {s=}")
    return s


def _handle_header_record(sm: sender.SendManager, rm: RecordMaker):
    pass


def _print_record_info(rec: pb.Record):
    try:
        record_type = rec.WhichOneof("record_type")
    except:
        record_type = "unknown"
    print("\n----------------------------")
    print(f"Parsed pb, {record_type=}")
    print("----------------------------")
    print(f"{rec=}")


def _handle_run_record(sm: sender.SendManager, rm: RecordMaker):
    # run_id = rm.run.run_id()
    # local_dir = f"./wandb_importer/{run_id}"

    # # convert to full path
    # full_path = os.path.abspath(local_dir)

    # logging.getLogger("import_logger").info(f"{run_id=}")
    # sm.send_run(rm._make_run_record(), file_dir=full_path)

    rec = rm._make_run_record()
    _print_record_info(rec)
    sm.send(rec)
    while not sm._record_q.empty():
        data = sm._record_q.get(block=True)
        print(f"inside extra send block, {data=}")
        sm.send(data)


def _handle_telem(sm: sender.SendManager, rm: RecordMaker):
    rec = rm._make_telem_record()
    _print_record_info(rec)
    sm.send(rec)


def _handle_files(sm: sender.SendManager, rm: RecordMaker, config: SendManagerConfig):
    has_artifacts = config.log_artifacts or config.use_artifacts
    rec = rm._make_files_record(
        config.metadata,
        has_artifacts,
        config.files,
        config.media,
        config.code,
    )
    sm_rec = rm.interface._make_record(files=rec)
    _print_record_info(sm_rec)
    sm.send(sm_rec)

    # logger.info(f"Made files {rec=}")
    # sm.send(sm_rec)

    sm._interface._publish_files(rec)
    while not sm._record_q.empty():
        data = sm._record_q.get(block=True)
        print(f"inside extra send block, {data=}")
        sm.send(data)


def _handle_use_artifacts(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
):
    if config.use_artifacts:
        used_artifacts = rm.run.used_artifacts()
        if used_artifacts is not None:
            used_artifacts = list(used_artifacts)

            for artifact in used_artifacts:
                rec = rm._make_artifact_record(artifact, use_artifact=True)
                _print_record_info(rec)
                sm.send(rec)


def _handle_log_artifacts(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
):
    if config.log_artifacts:
        artifacts = rm.run.artifacts()
        if artifacts is not None:
            artifacts = list(artifacts)
            for artifact in artifacts:
                rec = rm._make_artifact_record(artifact)
                _print_record_info(rec)
                sm.send(rec)


def _handle_log_specific_artifact(
    sm: sender.SendManager,
    rm: RecordMaker,
    art: Artifact,
    config: SendManagerConfig,
):
    if config.log_artifacts:
        # sm.send(rm._make_artifact_record(art))
        rec = rm._make_artifact_record(art)
        _print_record_info(rec)
        sm.send(rec)


def _handle_use_specific_artifact(
    sm: sender.SendManager,
    rm: RecordMaker,
    art: Artifact,
    config: SendManagerConfig,
):
    if config.use_artifacts:
        # sm.send(rm._make_artifact_record(art, use_artifact=True))
        rec = rm._make_artifact_record(art, use_artifact=True)
        _print_record_info(rec)
        sm.send(rec)


def _handle_history(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
):
    if config.history:
        for history_record in rm._make_history_records():
            _print_record_info(history_record)
            sm.send(history_record)


def _handle_summary(sm: sender.SendManager, rm: RecordMaker, config: SendManagerConfig):
    if config.summary:
        # sm.send(rm._make_summary_record())
        rec = rm._make_summary_record()
        _print_record_info(rec)
        sm.send(rec)


def _handle_terminal_output(
    sm: sender.SendManager,
    rm: RecordMaker,
    config: SendManagerConfig,
):
    if config.terminal_output:
        lines = rm.run.logs()
        if lines is not None:
            for line in lines:
                # sm.send(rm._make_output_record(line))
                rec = rm._make_output_record(line)
                _print_record_info(rec)
                sm.send(rec)


def send_run_with_send_manager(
    run: ImporterRun,
    overrides: Optional[Dict[str, Any]] = None,
    settings_override: Optional[Dict[str, Any]] = None,
    config: Optional[SendManagerConfig] = None,
) -> None:
    logger.debug("inside send_run_with_send_manager")
    if config is None:
        config = SendManagerConfig()

    # does this need to be here for pmap?
    if overrides:
        for k, v in overrides.items():
            # `lambda: v` won't work!
            # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
            setattr(run, k, lambda v=v: v)
    rm = RecordMaker(run)

    root_dir = rm.run_dir
    settings = _make_settings(root_dir, settings_override)

    record_q: queue.Queue = queue.Queue()
    result_q: queue.Queue = queue.Queue()
    interface = InterfaceQueue(record_q=record_q)
    context_keeper = context.ContextKeeper()

    logger.debug("before setup AlternateSendManager")

    sm = AlternateSendManager(settings, record_q, result_q, interface, context_keeper)
    # sm = sender.SendManager.setup(root_dir, resume="true")

    # with AlternateSendManager(
    #     settings, record_q, result_q, interface, context_keeper
    # ) as sm:

    def clear_record_q():
        print(f"clearing record q, {sm._record_q.empty()=}")
        while not sm._record_q.empty():
            data = sm._record_q.get(block=True)
            print(f"clearing {data=}")
            sm.send(data)

    logger.debug("before handling records")

    # handle header
    rec = rm._make_header_record()
    _print_record_info(rec)
    sm.send(rec)

    _handle_run_record(sm, rm)
    clear_record_q()

    _handle_files(sm, rm, config)
    clear_record_q()

    _handle_telem(sm, rm)
    clear_record_q()

    _handle_history(sm, rm, config)
    clear_record_q()

    _handle_use_artifacts(sm, rm, config)
    clear_record_q()

    _handle_log_artifacts(sm, rm, config)
    clear_record_q()

    _handle_summary(sm, rm, config)
    clear_record_q()

    _handle_terminal_output(sm, rm, config)
    clear_record_q()

    # print("sending cleanup requests")
    # req = pb.DeferRequest()
    # rec = sm._interface._make_request(defer=req)
    # sm.send_request_defer(rec)

    print("sending exit")
    # rec = pb.RunExitRecord()
    # rec.exit_code = 0
    # rec.runtime = 0
    sm.send_exit(rec)
    clear_record_q()

    # for i in range(0, 15):
    # for i in range(1, 11):
    #     req = pb.DeferRequest()
    #     req.state = i

    #     rec = sm._interface._make_request(defer=req)

    #     _print_record_info(rec)
    #     sm.send_request(rec)

    print("sending final")
    # sm._interface.publish_final()
    rec = pb.FinalRecord()
    _print_record_info(rec)
    sm.send_final(rec)
    clear_record_q()

    # handle footer
    rec = rm._make_footer_record()
    _print_record_info(rec)
    sm.send(rec)
    clear_record_q()

    logger.debug("before setup handler...")
    # import datetime
    # import tempfile
    # import time

    # from wandb import Settings

    # temp_dir = tempfile.TemporaryDirectory()
    # handler_settings = {
    #     "root_dir": temp_dir.name,
    #     "run_id": rm.run.run_id(),
    #     "_start_datetime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #     "_start_time": time.time(),
    # }

    # # handler_settings = Settings(
    # #     root_dir=temp_dir.name,
    # #     run_id=rm.run.run_id(),
    # #     _start_datetime=datetime.datetime.now(),
    # #     _start_time=time.time(),
    # # )

    # settings_msg = Settings(
    #     root_dir=temp_dir.name,
    #     run_id=rm.run.run_id(),
    #     _start_datetime=datetime.datetime.now(),
    #     _start_time=time.time(),
    # )

    # # settings_msg = Settings()
    # # ParseDict(handler_settings, settings_msg)
    # handler_settings_static = SettingsStatic(settings_msg.to_proto())

    # logger.debug("made handler settings static")

    # handler_record_q = queue.Queue()
    # handler_interface = InterfaceQueue(handler_record_q)
    # handler_context_keeper = context.ContextKeeper()
    # handle_manager = handler.HandleManager(
    #     settings=handler_settings_static,
    #     record_q=handler_record_q,
    #     result_q=None,
    #     stopped=False,
    #     writer_q=record_q,
    #     interface=handler_interface,
    #     context_keeper=handler_context_keeper,
    # )

    # logger.debug("setup handle manager")
    # while len(handle_manager) > 0:
    #     data = next(handle_manager)
    #     logger.debug(f"Handle manager has data, {data=}")
    #     handle_manager.handle(data)
    #     while len(sm) > 0:
    #         data = next(sm)
    #         logger.debug(f"Send manager has data, {data=}")
    #         sm.send(data)

    # handle_manager.finish()
    # print(f"push remaining records, {len(sm)=}")
    # while len(sm) > 0:
    #     data = next(sm)
    #     print(f"remaining records {len(sm)=}")
    #     print(f"pushing {data=}")
    #     sm.send(data)

    # print(f"pushing record q, {sm._record_q.empty()=}")
    # while not sm._record_q.empty():
    #     data = sm._record_q.get(block=True)
    #     print(f"pushing {data=}")
    #     sm.send(data)

    print("Finish up sm")
    sm.finish()


def send_artifacts_with_send_manager(
    arts: Iterable[Artifact],
    run: ImporterRun,
    overrides: Optional[Dict[str, Any]] = None,
    settings_override: Optional[Dict[str, Any]] = None,
    config: Optional[SendManagerConfig] = None,
) -> None:
    if config is None:
        config = SendManagerConfig()

    # does this need to be here for pmap?
    if overrides:
        for k, v in overrides.items():
            # `lambda: v` won't work!
            # https://stackoverflow.com/questions/10802002/why-deepcopy-doesnt-create-new-references-to-lambda-function
            setattr(run, k, lambda v=v: v)

    rm = RecordMaker(run)

    root_dir = rm.run_dir
    settings = _make_settings(root_dir, settings_override)

    record_q: queue.Queue = queue.Queue()
    result_q: queue.Queue = queue.Queue()
    interface = InterfaceQueue(record_q=record_q)
    context_keeper = context.ContextKeeper()

    with AlternateSendManager(
        settings, record_q, result_q, interface, context_keeper
    ) as sm:
        _handle_run_record(sm, rm)

        # for art in progress.subsubtask_progress(arts):
        for art in arts:
            _handle_use_specific_artifact(sm, rm, art, config)
            _handle_log_specific_artifact(sm, rm, art, config)

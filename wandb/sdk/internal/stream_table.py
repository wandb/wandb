import atexit
import typing
import uuid
import os
import datetime
import json
from dataclasses import dataclass, asdict
import wandb
from wandb import errors
from wandb.apis.public import Run
from wandb.sdk.artifacts.artifact_saver import ArtifactSaver
from wandb.sdk.interface.interface import InterfaceBase
from wandb.sdk.internal import file_stream
from wandb.sdk.internal.file_pusher import FilePusher
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.internal.sender import _manifest_json_from_proto
from wandb.sdk.lib import runid
from wandb.sdk.data_types.base_types.wb_value import WBValue
from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.data_types import _dtypes



WANDB_HIDDEN_JOB_TYPE = "test-controller"

class InMemoryLazyLiteRun:
    # ID
    _entity_name: str
    _project_name: str
    _run_name: str
    _step: int = 0

    # Optional
    _display_name: typing.Optional[str] = None
    _job_type: typing.Optional[str] = None
    _group: typing.Optional[str] = None

    # Property Cache
    _i_api: typing.Optional[InternalApi] = None
    _run: typing.Optional[Run] = None
    _stream: typing.Optional[file_stream.FileStreamApi] = None
    _pusher: typing.Optional[FilePusher] = None
    _use_async_file_stream: bool = False

    def __init__(
        self,
        entity_name: str,
        project_name: str,
        run_name: typing.Optional[str] = None,
        *,
        job_type: typing.Optional[str] = None,
        group: typing.Optional[str] = None,
        _hide_in_wb: bool = False,
        _use_async_file_stream: bool = False,
    ):
        if entity_name is None or entity_name == "":
            raise ValueError("Must specify entity_name")
        elif project_name is None or project_name == "":
            raise ValueError("Must specify project_name")

        self._entity_name = entity_name
        self._project_name = project_name
        self._display_name = run_name
        self._run_name = run_name or runid.generate_id()
        self._job_type = job_type if not _hide_in_wb else WANDB_HIDDEN_JOB_TYPE
        if _hide_in_wb and group is None:
            group = "weave_hidden_runs"
        self._group = group

        self._use_async_file_stream = (
            _use_async_file_stream
            and os.getenv("WEAVE_DISABLE_ASYNC_FILE_STREAM") == None
        )

        self._project_created = False
        self._is_log_setup = False

    def ensure_run(self) -> Run:
        return self.run

    @property
    def i_api(self) -> InternalApi:
        if self._i_api is None:
            self._i_api = InternalApi(
                {"project": self._project_name, "entity": self._entity_name}
            )
        return self._i_api

    @property
    def run(self) -> Run:
        if self._run is None:
            try:
                # Ensure project exists
                self.upsert_project()

                # Produce a run
                run_res, _, _ = self.i_api.upsert_run(
                    name=self._run_name,
                    display_name=self._display_name,
                    job_type=self._job_type,
                    group=self._group,
                    project=self._project_name,
                    entity=self._entity_name,
                )

                self._run = Run(
                    self._i_api.client,
                    run_res["project"]["entity"]["name"],
                    run_res["project"]["name"],
                    run_res["name"],
                    {
                        "id": run_res["id"],
                        "config": "{}",
                        "systemMetrics": "{}",
                        "summaryMetrics": "{}",
                        "tags": [],
                        "description": None,
                        "notes": None,
                        "state": "running",
                    },
                )
            except errors.CommError as e:
                raise errors.AuthenticationError()

            self.i_api.set_current_run_id(self._run.id)

        return self._run

    @property
    def stream(self) -> file_stream.FileStreamApi:
        if self._stream is None:
            # Setup the FileStream
            self._stream = file_stream.FileStreamApi(
                self.i_api, self.run.id, datetime.datetime.utcnow().timestamp()
            )
            if self._use_async_file_stream:
                self._stream._client.headers.update(
                    {"X-WANDB-USE-ASYNC-FILESTREAM": "true"}
                )
            self._stream.start()

        return self._stream

    @property
    def pusher(self) -> FilePusher:
        if self._pusher is None:
            self._pusher = FilePusher(self.i_api, self.stream)

        return self._pusher

    def setup_log_deps(self) -> None:
        if not self._is_log_setup:
            self._step = self.run.lastHistoryStep + 1
            self.stream.set_file_policy(
                "wandb-history.jsonl",
                file_stream.JsonlFilePolicy(start_chunk_id=self._step),
            )
            self._is_log_setup = True

    def log(self, row_dict: dict) -> None:
        self.setup_log_deps()
        stream = self.stream
        row_dict = {
            **row_dict,
            "_timestamp": datetime.datetime.utcnow().timestamp(),
        }
        if not self._use_async_file_stream:
            row_dict["_step"] = self._step
        self._step += 1
        print(row_dict)
        stream.push("wandb-history.jsonl", json.dumps(row_dict))

    def log_artifact(
        self,
        artifact: wandb.Artifact
    ) -> typing.Optional[typing.Dict]:
        artifact_name = artifact.name
        artifact_type_name = artifact.type
        assert artifact_name is not None
        assert artifact_type_name is not None
        self.upsert_project()
        self.i_api.create_artifact_type(
            artifact_type_name=artifact_type_name,
            entity_name=self._entity_name,
            project_name=self._project_name,
        )
        manifest_dict = _manifest_json_from_proto(
            InterfaceBase()._make_artifact(artifact).manifest
        )

        saver = ArtifactSaver(
            api=self.i_api,
            digest=artifact.digest,
            manifest_json=manifest_dict,
            file_pusher=self.pusher,
            is_user_created=False,
        )

        res = saver.save(
            type=artifact_type_name,
            name=artifact_name,
            client_id=artifact._client_id,
            sequence_client_id=artifact._sequence_client_id,
            metadata=artifact.metadata,
            description=artifact.description,
            aliases=["latest"],
            use_after_commit=False
        )

        return res


    def upsert_project(self) -> None:
        if not self._project_created:
            self.i_api.upsert_project(
                project=self._project_name, entity=self._entity_name
            )
            self._project_created = True

    def finish(self) -> None:
        if self._stream is not None:
            # Finalize the run
            self.stream.finish(0)

        if self._pusher is not None:
            # Wait for the FilePusher and FileStream to finish
            self.pusher.finish()
            self.pusher.join()

        # Reset fields
        self._stream = None
        self._pusher = None
        self._run = None
        self._i_api = None
        self._step = 0

    def __del__(self) -> None:
        self.finish()
        

@dataclass
class StreamTableType:
    table_name: str # maps to run name in W&B
    project_name: str
    entity_name: str

# Shawn recommended we only encode leafs, but in my testing, nested structures
# are not handled as well in in gorilla and we can do better using just weave.
# Uncomment the below to use gorilla for nested structures.
TRUST_GORILLA_FOR_NESTED_STRUCTURES = True

# Weave types are parametrized, but gorilla expects just simple strings. We could
# send the top-level string over the wire, but this fails to encode type specifics
# and therefore loses information. With this flag, we instead stringify the JSON type
# and send that over the wire. This is a bit of a hack, but it works.
ENCODE_ENTIRE_TYPE = True
TYPE_ENCODE_PREFIX = "_wt_::"

ROW_TYPE = typing.Union[typing.Mapping, list[typing.Mapping]]

class _StreamTableSync:
    _lite_run: InMemoryLazyLiteRun
    _table_name: str
    _project_name: str
    _entity_name: str

    _stream_table: StreamTableType
    _artifact: wandb.Artifact
    _client_id: str

    def __init__(
        self,
        table_name: str,
        *,
        project_name: typing.Optional[str] = None,
        entity_name: typing.Optional[str] = None,
        _disable_async_file_stream: bool = False
    ):
        self._client_id = str(uuid.uuid1())
        splits = table_name.split("/")
        if len(splits) == 1:
            pass
        elif len(splits) == 2:
            if project_name is not None:
                raise ValueError(
                    f"Cannot specify project_name and table_name with '/' in it: {table_name}"
                )
            project_name = splits[0]
            table_name = splits[1]
        elif len(splits) == 3:
            if project_name is not None or entity_name is not None:
                raise ValueError(
                    f"Cannot specify project_name or entity_name and table_name with 2 '/'s in it: {table_name}"
                )
            entity_name = splits[0]
            project_name = splits[1]
            table_name = splits[2]

        if entity_name is None or entity_name == "":
            raise ValueError(
                "Must specify entity_name`"
            )
        if project_name is None or project_name == "":
            raise ValueError("Must specify project_name")
        elif table_name is None or table_name == "":
            raise ValueError("Must specify table_name")
        
        self._lite_run = InMemoryLazyLiteRun(
            entity_name,
            project_name,
            table_name,
            group="weave_stream_tables",
            _hide_in_wb=True,
            _use_async_file_stream=not _disable_async_file_stream,
        )
        self._table_name = self._lite_run._run_name
        self._project_name = self._lite_run._project_name
        self._entity_name = self._lite_run._entity_name
        self._ensure_remote_initialized()
        atexit.register(self._at_exit)

    def st_art_exists(self) -> bool:
        pass

    def _ensure_remote_initialized(self) -> StreamTableType:
        self._lite_run.ensure_run()
        if not hasattr(self, "_weave_stream_table"):
            self._weave_stream_table = StreamTableType(  # type: ignore
                table_name=self._table_name,
                project_name=self._project_name,
                entity_name=self._entity_name,
            )
            st_art = wandb.Artifact(
                self._table_name,
                "stream_table",
                metadata={
	                "_weave_meta": {
                        "is_panel": False,
                        "is_weave_obj": True,
                        "type_name": "stream_table"
                    }
                })
            ###@@@@@@@@@### POC CODE ###@@@@@@@@@###
            # This file creation needs to be moved to the correct place.
            # Create type and object JSON files
            obj_type_json = json.dumps({
                "type": "stream_table",
                "_base_type": {"type": "Object"},
                "_is_object": True,
                "table_name": "string",
                "project_name": "string",
                "entity_name": "string"
            })
            obj_json = json.dumps(asdict(self._weave_stream_table))
            
            type_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obj.type.json")
            obj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obj.object.json")
            
            with open(type_path, "w") as f:
                f.write(obj_type_json)
            with open(obj_path, "w") as f:
                f.write(obj_json)

            st_art.add_file(type_path, "obj.type.json")
            st_art.add_file(obj_path, "obj.object.json")

            try:
                os.remove(type_path)
                os.remove(obj_path)
            except (IOError, OSError):
                pass
            ###@@@@@@@@@### END POC CODE ###@@@@@@@@@###
            self._lite_run.log_artifact(st_art)
            self._artifact = st_art

        return self._weave_stream_table
    
    def finish(self) -> None:
        if self._lite_run:
            self._lite_run.finish()

    def __del__(self) -> None:
        self.finish()

    def _at_exit(self) -> None:
        self.finish()
    
    def log(self, row_or_rows: ROW_TYPE) -> None:
        if isinstance(row_or_rows, dict):
            row_or_rows = [row_or_rows]

        for row in row_or_rows:
            self._log_row(row)

    def _log_row(self, row: typing.Mapping) -> None:
        row_copy = {**row}
        row_copy["_client_id"] = self._client_id
        if "timestamp" not in row_copy:
            row_copy["timestamp"] = datetime.datetime.now()
        client = wandb.Api()
        art = client.artifact(f"{self._table_name}:latest")
        draft_artifact = art.new_draft()
        payload = self.row_to_weave(row_copy, draft_artifact)
        self._lite_run.log(payload)
        self._lite_run.log_artifact(draft_artifact)

    def handle_logged_wb_value(self, obj: WBValue, artifact: wandb.Artifact):
        res = obj.to_json(artifact)
        return res

    def row_to_weave(
        self, row: typing.Dict[str, typing.Any], artifact: wandb.Artifact
    ) -> typing.Dict[str, typing.Any]:
        return {key: self.obj_to_weave(value, artifact) for key, value in row.items()}


    def obj_to_weave(self, obj: typing.Any, artifact: wandb.Artifact) -> typing.Any:
        def recurse(obj: typing.Any) -> typing.Any:
            return self.obj_to_weave(obj, artifact)

        if isinstance(obj, (int, float, str, bool, type(None))):
            return obj
        else:
            if TRUST_GORILLA_FOR_NESTED_STRUCTURES:
                if isinstance(obj, dict):
                    return {key: recurse(value) for key, value in obj.items()}
                elif isinstance(obj, list):
                    return [recurse(value) for value in obj]
                elif isinstance(obj, tuple):
                    return [recurse(value) for value in obj]
                elif isinstance(obj, set):
                    return [recurse(value) for value in obj]
                elif isinstance(obj, frozenset):
                    return [recurse(value) for value in obj]
                elif isinstance(obj, WBValue):
                    return self.handle_logged_wb_value(obj, artifact)
                else:
                    obj_type = TypeRegistry.type_of(obj)
                    ###@@@@@@@@@### POC CODE ###@@@@@@@@@###
                    # weave_query uses a mapper to handle non-primitive types like Timestamp
                    # We'll need to implement that mapper
                    if isinstance(obj_type, _dtypes.TimestampType):
                        res =  {
                            "_type": {
                                "type": "timestamp"
                            },
                            "_val": int(obj.timestamp() * 1000)
                        }
                        if ENCODE_ENTIRE_TYPE:
                            return {
                                "_type": w_type_to_type_name(res["_type"]),
                                "_val": res["_val"]
                            }
            else:
                return self.leaf_to_weave(obj, artifact)


    def leaf_to_weave(self, leaf: typing.Any, artifact: wandb.Artifact) -> typing.Any:
        res = self.handle_logged_wb_value(leaf, artifact)
        w_type = res["_type"]
        type_name = w_type_to_type_name(w_type)

        if ENCODE_ENTIRE_TYPE:
            return {"_type": type_name, "_val": res["_val"]}
        else:
            return {
                "_type": type_name,
                "_weave_type": w_type,
                "_val": res["_val"],
            }

    
def w_type_to_type_name(w_type: typing.Union[str, dict]) -> str:
    if isinstance(w_type, str):
        return w_type
    if ENCODE_ENTIRE_TYPE:
        print("dumping!")
        return TYPE_ENCODE_PREFIX + json.dumps(w_type)
    else:
        return w_type["type"]

    




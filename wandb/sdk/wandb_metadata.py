from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from google.protobuf.timestamp_pb2 import Timestamp
from pydantic import BaseModel, ConfigDict, Field, model_validator

from wandb.proto import wandb_internal_pb2

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class DiskInfo(BaseModel, validate_assignment=True):
    total: int | None = None
    used: int | None = None

    def to_proto(self) -> wandb_internal_pb2.DiskInfo:
        return wandb_internal_pb2.DiskInfo(
            total=self.total or 0,
            used=self.used or 0,
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.DiskInfo) -> DiskInfo:
        return cls(total=proto.total, used=proto.used)


class MemoryInfo(BaseModel, validate_assignment=True):
    total: int | None = None

    def to_proto(self) -> wandb_internal_pb2.MemoryInfo:
        return wandb_internal_pb2.MemoryInfo(total=self.total or 0)

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.MemoryInfo) -> MemoryInfo:
        return cls(total=proto.total)


class CpuInfo(BaseModel, validate_assignment=True):
    count: int | None = None
    count_logical: int | None = None

    def to_proto(self) -> wandb_internal_pb2.CpuInfo:
        return wandb_internal_pb2.CpuInfo(
            count=self.count or 0,
            count_logical=self.count_logical or 0,
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.CpuInfo) -> CpuInfo:
        return cls(count=proto.count, count_logical=proto.count_logical)


class AppleInfo(BaseModel, validate_assignment=True):
    name: str | None = None
    ecpu_cores: int | None = None
    pcpu_cores: int | None = None
    gpu_cores: int | None = None
    memory_gb: int | None = None
    swap_total_bytes: int | None = None
    ram_total_bytes: int | None = None

    def to_proto(self) -> wandb_internal_pb2.AppleInfo:
        return wandb_internal_pb2.AppleInfo(
            name=self.name or "",
            ecpu_cores=self.ecpu_cores or 0,
            pcpu_cores=self.pcpu_cores or 0,
            gpu_cores=self.gpu_cores or 0,
            memory_gb=self.memory_gb or 0,
            swap_total_bytes=self.swap_total_bytes or 0,
            ram_total_bytes=self.ram_total_bytes or 0,
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.AppleInfo) -> AppleInfo:
        return cls(
            name=proto.name,
            ecpu_cores=proto.ecpu_cores,
            pcpu_cores=proto.pcpu_cores,
            gpu_cores=proto.gpu_cores,
            memory_gb=proto.memory_gb,
            swap_total_bytes=proto.swap_total_bytes,
            ram_total_bytes=proto.ram_total_bytes,
        )


class GpuNvidiaInfo(BaseModel, validate_assignment=True):
    name: str | None = None
    memory_total: int | None = None
    cuda_cores: int | None = None
    architecture: str | None = None

    def to_proto(self) -> wandb_internal_pb2.GpuNvidiaInfo:
        return wandb_internal_pb2.GpuNvidiaInfo(
            name=self.name or "",
            memory_total=self.memory_total or 0,
            cuda_cores=self.cuda_cores or 0,
            architecture=self.architecture or "",
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.GpuNvidiaInfo) -> GpuNvidiaInfo:
        return cls(
            name=proto.name,
            memory_total=proto.memory_total,
            cuda_cores=proto.cuda_cores,
            architecture=proto.architecture,
        )


class GpuAmdInfo(BaseModel, validate_assignment=True):
    id: str | None = None
    unique_id: str | None = None
    vbios_version: str | None = None
    performance_level: str | None = None
    gpu_overdrive: str | None = None
    gpu_memory_overdrive: str | None = None
    max_power: str | None = None
    series: str | None = None
    model: str | None = None
    vendor: str | None = None
    sku: str | None = None
    sclk_range: str | None = None
    mclk_range: str | None = None

    def to_proto(self) -> wandb_internal_pb2.GpuAmdInfo:
        return wandb_internal_pb2.GpuAmdInfo(
            id=self.id or "",
            unique_id=self.unique_id or "",
            vbios_version=self.vbios_version or "",
            performance_level=self.performance_level or "",
            gpu_overdrive=self.gpu_overdrive or "",
            gpu_memory_overdrive=self.gpu_memory_overdrive or "",
            max_power=self.max_power or "",
            series=self.series or "",
            model=self.model or "",
            vendor=self.vendor or "",
            sku=self.sku or "",
            sclk_range=self.sclk_range or "",
            mclk_range=self.mclk_range or "",
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.GpuAmdInfo) -> GpuAmdInfo:
        return cls(
            id=proto.id,
            unique_id=proto.unique_id,
            vbios_version=proto.vbios_version,
            performance_level=proto.performance_level,
            gpu_overdrive=proto.gpu_overdrive,
            gpu_memory_overdrive=proto.gpu_memory_overdrive,
            max_power=proto.max_power,
            series=proto.series,
            model=proto.model,
            vendor=proto.vendor,
            sku=proto.sku,
            sclk_range=proto.sclk_range,
            mclk_range=proto.mclk_range,
        )


class TrainiumInfo(BaseModel, validate_assignment=True):
    name: str | None = None
    vendor: str | None = None
    neuron_device_count: int | None = None
    neuroncore_per_device_count: int | None = None

    def to_proto(self) -> wandb_internal_pb2.TrainiumInfo:
        return wandb_internal_pb2.TrainiumInfo(
            name=self.name or "",
            vendor=self.vendor or "",
            neuron_device_count=self.neuron_device_count or 0,
            neuroncore_per_device_count=self.neuroncore_per_device_count or 0,
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.TrainiumInfo) -> TrainiumInfo:
        return cls(
            name=proto.name,
            vendor=proto.vendor,
            neuron_device_count=proto.neuron_device_count,
            neuroncore_per_device_count=proto.neuroncore_per_device_count,
        )


class TPUInfo(BaseModel, validate_assignment=True):
    name: str | None = None
    hbm_gib: int | None = None
    devices_per_chip: int | None = None
    count: int | None = None

    def to_proto(self) -> wandb_internal_pb2.TPUInfo:
        return wandb_internal_pb2.TPUInfo(
            name=self.name or "",
            hbm_gib=self.hbm_gib or 0,
            devices_per_chip=self.devices_per_chip or 0,
            count=self.count or 0,
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.TPUInfo) -> TPUInfo:
        return cls(
            name=proto.name,
            hbm_gib=proto.hbm_gib,
            devices_per_chip=proto.devices_per_chip,
            count=proto.count,
        )


class GitRepoRecord(BaseModel, validate_assignment=True):
    remote_url: str | None = Field(None, alias="remote")
    commit: str | None = None

    def to_proto(self) -> wandb_internal_pb2.GitRepoRecord:
        return wandb_internal_pb2.GitRepoRecord(
            remote_url=self.remote_url or "",
            commit=self.commit or "",
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.GitRepoRecord) -> GitRepoRecord:
        return cls(remote=proto.remote_url, commit=proto.commit)


class Metadata(BaseModel, validate_assignment=True):
    """Metadata about the run environment.

    NOTE: Definitions must be kept in sync with wandb_internal.proto::MetadataRequest.

    Attributes:
        os (str, optional): Operating system.
        python (str, optional): Python version.
        heartbeat_at (datetime, optional): Timestamp of last heartbeat.
        started_at (datetime, optional): Timestamp of run start.
        docker (str, optional): Docker image.
        cuda (str, optional): CUDA version.
        args (List[str]): Command-line arguments.
        state (str, optional): Run state.
        program (str, optional): Program name.
        code_path (str, optional): Path to code.
        git (GitRepoRecord, optional): Git repository information.
        email (str, optional): Email address.
        root (str, optional): Root directory.
        host (str, optional): Host name.
        username (str, optional): Username.
        executable (str, optional): Python executable path.
        code_path_local (str, optional): Local code path.
        colab (str, optional): Colab URL.
        cpu_count (int, optional): CPU count.
        cpu_count_logical (int, optional): Logical CPU count.
        gpu_type (str, optional): GPU type.
        disk (Dict[str, DiskInfo]): Disk information.
        memory (MemoryInfo, optional): Memory information.
        cpu (CpuInfo, optional): CPU information.
        apple (AppleInfo, optional): Apple silicon information.
        gpu_nvidia (List[GpuNvidiaInfo]): NVIDIA GPU information.
        gpu_amd (List[GpuAmdInfo]): AMD GPU information.
        slurm (Dict[str, str]): Slurm environment information.
        cuda_version (str, optional): CUDA version.
        trainium (TrainiumInfo, optional): Trainium information.
        tpu (TPUInfo, optional): TPU information.
    """

    # TODO: Pydantic configuration.
    model_config = ConfigDict(
        extra="ignore",  # ignore extra fields
        validate_default=True,  # validate default values
    )

    os: str | None = None
    python: str | None = None
    heartbeat_at: datetime | None = Field(default=None, alias="heartbeatAt")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    docker: str | None = None
    cuda: str | None = None
    args: list[str] = Field(default_factory=list)
    state: str | None = None
    program: str | None = None
    code_path: str | None = Field(default=None, alias="codePath")
    git: GitRepoRecord | None = None
    email: str | None = None
    root: str | None = None
    host: str | None = None
    username: str | None = None
    executable: str | None = None
    code_path_local: str | None = Field(default=None, alias="codePathLocal")
    colab: str | None = None
    cpu_count: int | None = Field(default=None, alias="cpuCount")
    cpu_count_logical: int | None = Field(default=None, alias="cpuCountLogical")
    gpu_type: str | None = Field(default=None, alias="gpuType")
    gpu_count: int | None = Field(default=None, alias="gpuCount")
    disk: dict[str, DiskInfo] = Field(default_factory=dict)
    memory: MemoryInfo | None = None
    cpu: CpuInfo | None = None
    apple: AppleInfo | None = None
    gpu_nvidia: list[GpuNvidiaInfo] = Field(default_factory=list, alias="gpuNvidia")
    gpu_amd: list[GpuAmdInfo] = Field(default_factory=list, alias="gpuAmd")
    slurm: dict[str, str] = Field(default_factory=dict)
    cuda_version: str | None = Field(default=None, alias="cudaVersion")
    trainium: TrainiumInfo | None = None
    tpu: TPUInfo | None = None

    def __init__(self, **data):
        super().__init__(**data)

        # Callback for post-update. This is used in the Run object to trigger
        # a metadata update after the object is modified.
        self._post_update_callback: Callable | None = None  # type: ignore

    def _set_callback(self, callback: Callable) -> None:
        self._post_update_callback = callback

    @contextmanager
    def disable_callback(self):
        """Temporarily disable callback."""
        original_callback = self._post_update_callback
        self._post_update_callback = None
        try:
            yield
        finally:
            self._post_update_callback = original_callback

    @model_validator(mode="after")
    def _callback(self) -> Self:
        if getattr(self, "_post_update_callback", None) is not None:
            self._post_update_callback(self.to_proto())  # type: ignore

        return self

    @classmethod
    def _datetime_to_timestamp(cls, dt: datetime | None) -> Timestamp | None:
        """Convert a datetime to a protobuf Timestamp."""
        if dt is None:
            return None
        ts = Timestamp()
        # Convert to UTC if the datetime has a timezone
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        # Convert to seconds and nanos
        ts.seconds = int(dt.timestamp())
        ts.nanos = dt.microsecond * 1000
        return ts

    @classmethod
    def _timestamp_to_datetime(cls, ts: Timestamp | None) -> datetime | None:
        """Convert a protobuf Timestamp to a datetime."""
        if ts is None:
            return None
        # Create UTC datetime from seconds and add microseconds
        dt = datetime.fromtimestamp(ts.seconds, tz=timezone.utc)
        return dt.replace(microsecond=ts.nanos // 1000)

    def to_proto(self) -> wandb_internal_pb2.MetadataRequest:  # noqa: C901
        """Convert the metadata to a protobuf message."""
        proto = wandb_internal_pb2.MetadataRequest()

        # A flag to indicate that the metadata has been modified by the user.
        # Updates to the metadata object originating from the user take precedence
        # over automatic updates.
        proto._user_modified = True

        # Handle all scalar fields
        if self.os is not None:
            proto.os = self.os
        if self.python is not None:
            proto.python = self.python
        if self.docker is not None:
            proto.docker = self.docker
        if self.cuda is not None:
            proto.cuda = self.cuda
        if self.state is not None:
            proto.state = self.state
        if self.program is not None:
            proto.program = self.program
        if self.code_path is not None:
            proto.code_path = self.code_path
        if self.email is not None:
            proto.email = self.email
        if self.root is not None:
            proto.root = self.root
        if self.host is not None:
            proto.host = self.host
        if self.username is not None:
            proto.username = self.username
        if self.executable is not None:
            proto.executable = self.executable
        if self.code_path_local is not None:
            proto.code_path_local = self.code_path_local
        if self.colab is not None:
            proto.colab = self.colab
        if self.cpu_count is not None:
            proto.cpu_count = self.cpu_count
        if self.cpu_count_logical is not None:
            proto.cpu_count_logical = self.cpu_count_logical
        if self.gpu_type is not None:
            proto.gpu_type = self.gpu_type
        if self.gpu_count is not None:
            proto.gpu_count = self.gpu_count
        if self.cuda_version is not None:
            proto.cuda_version = self.cuda_version

        # Handle timestamp fields
        if self.heartbeat_at is not None:
            proto.heartbeat_at.CopyFrom(self._datetime_to_timestamp(self.heartbeat_at))
        if self.started_at is not None:
            proto.started_at.CopyFrom(self._datetime_to_timestamp(self.started_at))

        # Handle nested message fields
        if self.git is not None:
            proto.git.CopyFrom(self.git.to_proto())
        if self.memory is not None:
            proto.memory.CopyFrom(self.memory.to_proto())
        if self.cpu is not None:
            proto.cpu.CopyFrom(self.cpu.to_proto())
        if self.apple is not None:
            proto.apple.CopyFrom(self.apple.to_proto())
        if self.trainium is not None:
            proto.trainium.CopyFrom(self.trainium.to_proto())
        if self.tpu is not None:
            proto.tpu.CopyFrom(self.tpu.to_proto())

        # Handle repeated fields
        if self.args:
            proto.args.extend(self.args)
        if self.gpu_nvidia:
            proto.gpu_nvidia.extend(gpu.to_proto() for gpu in self.gpu_nvidia)
        if self.gpu_amd:
            proto.gpu_amd.extend(gpu.to_proto() for gpu in self.gpu_amd)

        # Handle map fields
        if self.disk:
            for k, v in self.disk.items():
                proto.disk[k].CopyFrom(v.to_proto())
        if self.slurm:
            proto.slurm.update(self.slurm)

        return proto

    def update_from_proto(  # noqa: C901
        self,
        proto: wandb_internal_pb2.MetadataRequest,
        skip_existing: bool = False,
    ):
        """Update the metadata from a protobuf message.

        Args:
            proto (wandb_internal_pb2.MetadataRequest): The protobuf message.
            skip_existing (bool, optional): Skip updating fields that are already set.
        """
        data: dict[str, Any] = {}

        # Handle all scalar fields.
        if proto.os:
            data["os"] = proto.os
        if proto.python:
            data["python"] = proto.python
        if proto.docker:
            data["docker"] = proto.docker
        if proto.cuda:
            data["cuda"] = proto.cuda
        if proto.state:
            data["state"] = proto.state
        if proto.program:
            data["program"] = proto.program
        if proto.code_path:
            data["code_path"] = proto.code_path
        if proto.email:
            data["email"] = proto.email
        if proto.root:
            data["root"] = proto.root
        if proto.host:
            data["host"] = proto.host
        if proto.username:
            data["username"] = proto.username
        if proto.executable:
            data["executable"] = proto.executable
        if proto.code_path_local:
            data["code_path_local"] = proto.code_path_local
        if proto.colab:
            data["colab"] = proto.colab
        if proto.cpu_count:
            data["cpu_count"] = proto.cpu_count
        if proto.cpu_count_logical:
            data["cpu_count_logical"] = proto.cpu_count_logical
        if proto.gpu_type:
            data["gpu_type"] = proto.gpu_type
        if proto.gpu_count:
            data["gpu_count"] = proto.gpu_count
        if proto.cuda_version:
            data["cuda_version"] = proto.cuda_version

        # Handle timestamp fields (these are messages, so use HasField)
        if proto.HasField("heartbeat_at"):
            data["heartbeat_at"] = self._timestamp_to_datetime(proto.heartbeat_at)
        if proto.HasField("started_at"):
            data["started_at"] = self._timestamp_to_datetime(proto.started_at)

        # Handle nested message fields (these have presence)
        if proto.HasField("git"):
            data["git"] = GitRepoRecord.from_proto(proto.git)
        if proto.HasField("memory"):
            data["memory"] = MemoryInfo.from_proto(proto.memory)
        if proto.HasField("cpu"):
            data["cpu"] = CpuInfo.from_proto(proto.cpu)
        if proto.HasField("apple"):
            data["apple"] = AppleInfo.from_proto(proto.apple)
        if proto.HasField("trainium"):
            data["trainium"] = TrainiumInfo.from_proto(proto.trainium)
        if proto.HasField("tpu"):
            data["tpu"] = TPUInfo.from_proto(proto.tpu)

        # Handle repeated fields
        if len(proto.args) > 0:
            data["args"] = list(proto.args)
        else:
            data["args"] = []
        if len(proto.gpu_nvidia) > 0:
            data["gpu_nvidia"] = [
                GpuNvidiaInfo.from_proto(gpu) for gpu in proto.gpu_nvidia
            ]
        else:
            data["gpu_nvidia"] = []
        if len(proto.gpu_amd) > 0:
            data["gpu_amd"] = [GpuAmdInfo.from_proto(gpu) for gpu in proto.gpu_amd]
        else:
            data["gpu_amd"] = []

        # Handle map fields
        if len(proto.disk) > 0:
            data["disk"] = {k: DiskInfo.from_proto(v) for k, v in proto.disk.items()}
        else:
            data["disk"] = {}
        if len(proto.slurm) > 0:
            data["slurm"] = dict(proto.slurm)
        else:
            data["slurm"] = {}

        for k, v in data.items():
            if skip_existing and getattr(self, k) is not None:
                continue
            setattr(self, k, v)

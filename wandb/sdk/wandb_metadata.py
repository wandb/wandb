from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

# For backward compatibility with pydantic v1
from typing import Any, Callable, Dict, List, Optional

from google.protobuf.timestamp_pb2 import Timestamp
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Self

from wandb import termwarn
from wandb._pydantic import IS_PYDANTIC_V2
from wandb.proto import wandb_internal_pb2

if IS_PYDANTIC_V2:
    from pydantic import model_validator


class DiskInfo(BaseModel, validate_assignment=True):
    total: Optional[int] = None
    used: Optional[int] = None

    def to_proto(self) -> wandb_internal_pb2.DiskInfo:
        return wandb_internal_pb2.DiskInfo(
            total=self.total or 0,
            used=self.used or 0,
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.DiskInfo) -> DiskInfo:
        return cls(total=proto.total, used=proto.used)


class MemoryInfo(BaseModel, validate_assignment=True):
    total: Optional[int] = None

    def to_proto(self) -> wandb_internal_pb2.MemoryInfo:
        return wandb_internal_pb2.MemoryInfo(total=self.total or 0)

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.MemoryInfo) -> MemoryInfo:
        return cls(total=proto.total)


class CpuInfo(BaseModel, validate_assignment=True):
    count: Optional[int] = None
    count_logical: Optional[int] = None

    def to_proto(self) -> wandb_internal_pb2.CpuInfo:
        return wandb_internal_pb2.CpuInfo(
            count=self.count or 0,
            count_logical=self.count_logical or 0,
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.CpuInfo) -> CpuInfo:
        return cls(count=proto.count, count_logical=proto.count_logical)


class AppleInfo(BaseModel, validate_assignment=True):
    name: Optional[str] = None
    ecpu_cores: Optional[int] = None
    pcpu_cores: Optional[int] = None
    gpu_cores: Optional[int] = None
    memory_gb: Optional[int] = None
    swap_total_bytes: Optional[int] = None
    ram_total_bytes: Optional[int] = None

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
    name: Optional[str] = None
    memory_total: Optional[int] = None
    cuda_cores: Optional[int] = None
    architecture: Optional[str] = None
    uuid: Optional[str] = None

    def to_proto(self) -> wandb_internal_pb2.GpuNvidiaInfo:
        return wandb_internal_pb2.GpuNvidiaInfo(
            name=self.name or "",
            memory_total=self.memory_total or 0,
            cuda_cores=self.cuda_cores or 0,
            architecture=self.architecture or "",
            uuid=self.uuid or "",
        )

    @classmethod
    def from_proto(cls, proto: wandb_internal_pb2.GpuNvidiaInfo) -> GpuNvidiaInfo:
        return cls(
            name=proto.name,
            memory_total=proto.memory_total,
            cuda_cores=proto.cuda_cores,
            architecture=proto.architecture,
            uuid=proto.uuid,
        )


class GpuAmdInfo(BaseModel, validate_assignment=True):
    id: Optional[str] = None
    unique_id: Optional[str] = None
    vbios_version: Optional[str] = None
    performance_level: Optional[str] = None
    gpu_overdrive: Optional[str] = None
    gpu_memory_overdrive: Optional[str] = None
    max_power: Optional[str] = None
    series: Optional[str] = None
    model: Optional[str] = None
    vendor: Optional[str] = None
    sku: Optional[str] = None
    sclk_range: Optional[str] = None
    mclk_range: Optional[str] = None

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
    name: Optional[str] = None
    vendor: Optional[str] = None
    neuron_device_count: Optional[int] = None
    neuroncore_per_device_count: Optional[int] = None

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
    name: Optional[str] = None
    hbm_gib: Optional[int] = None
    devices_per_chip: Optional[int] = None
    count: Optional[int] = None

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
    remote_url: Optional[str] = Field(None, alias="remote")
    commit: Optional[str] = None

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

    Examples:
        Update Run metadata:

        ```python
        with wandb.init(settings=settings) as run:
            run._metadata.gpu_nvidia = [
                {
                    "name": "Tesla T4",
                    "memory_total": "16106127360",
                    "cuda_cores": 2560,
                    "architecture": "Turing",
                },
                ...,
            ]

            run._metadata.gpu_type = "Tesla T4"
            run._metadata.gpu_count = 42

            run._metadata.tpu = {
                "name": "v6e",
                "hbm_gib": 32,
                "devices_per_chip": 1,
                "count": 1337,
            }
        ```
    """

    model_config = ConfigDict(
        extra="ignore",  # ignore extra fields
        validate_default=True,  # validate default values
        use_attribute_docstrings=True,  # for field descriptions
        revalidate_instances="always",
    )

    os: Optional[str] = None
    """Operating system."""

    python: Optional[str] = None
    """Python version."""

    heartbeat_at: Optional[datetime] = Field(default=None, alias="heartbeatAt")
    """Timestamp of last heartbeat."""

    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    """Timestamp of run start."""

    docker: Optional[str] = None
    """Docker image."""

    cuda: Optional[str] = None
    """CUDA version."""

    args: List[str] = Field(default_factory=list)
    """Command-line arguments."""

    state: Optional[str] = None
    """Run state."""

    program: Optional[str] = None
    """Program name."""

    code_path: Optional[str] = Field(default=None, alias="codePath")
    """Path to code."""

    git: Optional[GitRepoRecord] = None
    """Git repository information."""

    email: Optional[str] = None
    """Email address."""

    root: Optional[str] = None
    """Root directory."""

    host: Optional[str] = None
    """Host name."""

    username: Optional[str] = None
    """Username."""

    executable: Optional[str] = None
    """Python executable path."""

    code_path_local: Optional[str] = Field(default=None, alias="codePathLocal")
    """Local code path."""

    colab: Optional[str] = None
    """Colab URL."""

    cpu_count: Optional[int] = Field(default=None, alias="cpuCount")
    """CPU count."""

    cpu_count_logical: Optional[int] = Field(default=None, alias="cpuCountLogical")
    """Logical CPU count."""

    gpu_type: Optional[str] = Field(default=None, alias="gpuType")
    """GPU type."""

    gpu_count: Optional[int] = Field(default=None, alias="gpuCount")
    """GPU count."""

    disk: Dict[str, DiskInfo] = Field(default_factory=dict)
    """Disk information."""

    memory: Optional[MemoryInfo] = None
    """Memory information."""

    cpu: Optional[CpuInfo] = None
    """CPU information."""

    apple: Optional[AppleInfo] = None
    """Apple silicon information."""

    gpu_nvidia: List[GpuNvidiaInfo] = Field(default_factory=list, alias="gpuNvidia")
    """NVIDIA GPU information."""

    gpu_amd: List[GpuAmdInfo] = Field(default_factory=list, alias="gpuAmd")
    """AMD GPU information."""

    slurm: Dict[str, str] = Field(default_factory=dict)
    """Slurm environment information."""

    cuda_version: Optional[str] = Field(default=None, alias="cudaVersion")
    """CUDA version."""

    trainium: Optional[TrainiumInfo] = None
    """Trainium information."""

    tpu: Optional[TPUInfo] = None
    """TPU information."""

    def __init__(self, **data):
        super().__init__(**data)

        if not IS_PYDANTIC_V2:
            termwarn(
                "Metadata is read-only when using pydantic v1.",
                repeat=False,
            )
            return

        # Callback for post-update. This is used in the Run object to trigger
        # a metadata update after the object is modified.
        self._post_update_callback: Optional[Callable] = None  # type: ignore

    def _set_callback(self, callback: Callable) -> None:
        if not IS_PYDANTIC_V2:
            return
        self._post_update_callback = callback

    @contextmanager
    def disable_callback(self):
        """Temporarily disable callback."""
        if not IS_PYDANTIC_V2:
            yield
        else:
            original_callback = self._post_update_callback
            self._post_update_callback = None
            try:
                yield
            finally:
                self._post_update_callback = original_callback

    if IS_PYDANTIC_V2:

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
        data: Dict[str, Any] = {}

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

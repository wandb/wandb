from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from wandb.proto import wandb_base_pb2 as _wandb_base_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Binding(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BINDING_UNSPECIFIED: _ClassVar[Binding]
    VISIBLE: _ClassVar[Binding]
    VISIBLE_DEVICES: _ClassVar[Binding]
    PROCESS: _ClassVar[Binding]
    SCHEDULER: _ClassVar[Binding]

class AcceleratorType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACCELERATOR_UNSPECIFIED: _ClassVar[AcceleratorType]
    NVIDIA_GPU: _ClassVar[AcceleratorType]
    AMD_GPU: _ClassVar[AcceleratorType]
    APPLE_GPU: _ClassVar[AcceleratorType]
    APPLE_ANE: _ClassVar[AcceleratorType]
    GOOGLE_TPU: _ClassVar[AcceleratorType]
    AWS_TRAINIUM: _ClassVar[AcceleratorType]
BINDING_UNSPECIFIED: Binding
VISIBLE: Binding
VISIBLE_DEVICES: Binding
PROCESS: Binding
SCHEDULER: Binding
ACCELERATOR_UNSPECIFIED: AcceleratorType
NVIDIA_GPU: AcceleratorType
AMD_GPU: AcceleratorType
APPLE_GPU: AcceleratorType
APPLE_ANE: AcceleratorType
GOOGLE_TPU: AcceleratorType
AWS_TRAINIUM: AcceleratorType
METRIC_FIELD_NUMBER: _ClassVar[int]
metric: _descriptor.FieldDescriptor
ATTRIBUTE_FIELD_NUMBER: _ClassVar[int]
attribute: _descriptor.FieldDescriptor
DISTRIBUTION_FIELD_NUMBER: _ClassVar[int]
distribution: _descriptor.FieldDescriptor

class MetricInfo(_message.Message):
    __slots__ = ("unit", "display", "kind", "legacy", "legacy_process_copy", "range_min", "range_max", "names")
    class Kind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        GAUGE: _ClassVar[MetricInfo.Kind]
        COUNTER: _ClassVar[MetricInfo.Kind]
    GAUGE: MetricInfo.Kind
    COUNTER: MetricInfo.Kind
    UNIT_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    LEGACY_FIELD_NUMBER: _ClassVar[int]
    LEGACY_PROCESS_COPY_FIELD_NUMBER: _ClassVar[int]
    RANGE_MIN_FIELD_NUMBER: _ClassVar[int]
    RANGE_MAX_FIELD_NUMBER: _ClassVar[int]
    NAMES_FIELD_NUMBER: _ClassVar[int]
    unit: str
    display: str
    kind: MetricInfo.Kind
    legacy: _containers.RepeatedCompositeFieldContainer[LegacyKey]
    legacy_process_copy: bool
    range_min: float
    range_max: float
    names: _containers.RepeatedCompositeFieldContainer[MetricName]
    def __init__(self, unit: _Optional[str] = ..., display: _Optional[str] = ..., kind: _Optional[_Union[MetricInfo.Kind, str]] = ..., legacy: _Optional[_Iterable[_Union[LegacyKey, _Mapping]]] = ..., legacy_process_copy: bool = ..., range_min: _Optional[float] = ..., range_max: _Optional[float] = ..., names: _Optional[_Iterable[_Union[MetricName, _Mapping]]] = ...) -> None: ...

class MetricName(_message.Message):
    __slots__ = ("accelerator_type", "name", "attributes")
    ACCELERATOR_TYPE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    accelerator_type: _containers.RepeatedScalarFieldContainer[AcceleratorType]
    name: str
    attributes: _containers.RepeatedCompositeFieldContainer[MetricLabel]
    def __init__(self, accelerator_type: _Optional[_Iterable[_Union[AcceleratorType, str]]] = ..., name: _Optional[str] = ..., attributes: _Optional[_Iterable[_Union[MetricLabel, _Mapping]]] = ...) -> None: ...

class LegacyKey(_message.Message):
    __slots__ = ("accelerator_type", "source", "template", "unit")
    ACCELERATOR_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    accelerator_type: AcceleratorType
    source: str
    template: str
    unit: str
    def __init__(self, accelerator_type: _Optional[_Union[AcceleratorType, str]] = ..., source: _Optional[str] = ..., template: _Optional[str] = ..., unit: _Optional[str] = ...) -> None: ...

class SystemMetricsRecord(_message.Message):
    __slots__ = ("timestamp", "interval_ms", "dropped_samples", "writer", "host", "process", "sdk", "accelerators", "tpu_runtime", "trainium_host", "generic", "_info")
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_MS_FIELD_NUMBER: _ClassVar[int]
    DROPPED_SAMPLES_FIELD_NUMBER: _ClassVar[int]
    WRITER_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    PROCESS_FIELD_NUMBER: _ClassVar[int]
    SDK_FIELD_NUMBER: _ClassVar[int]
    ACCELERATORS_FIELD_NUMBER: _ClassVar[int]
    TPU_RUNTIME_FIELD_NUMBER: _ClassVar[int]
    TRAINIUM_HOST_FIELD_NUMBER: _ClassVar[int]
    GENERIC_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    timestamp: _timestamp_pb2.Timestamp
    interval_ms: int
    dropped_samples: int
    writer: WriterInfo
    host: HostMetrics
    process: ProcessMetrics
    sdk: SdkMetrics
    accelerators: _containers.RepeatedCompositeFieldContainer[AcceleratorMetrics]
    tpu_runtime: TpuRuntimeMetrics
    trainium_host: TrainiumHostMetrics
    generic: _containers.RepeatedCompositeFieldContainer[GenericMetric]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, timestamp: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., interval_ms: _Optional[int] = ..., dropped_samples: _Optional[int] = ..., writer: _Optional[_Union[WriterInfo, _Mapping]] = ..., host: _Optional[_Union[HostMetrics, _Mapping]] = ..., process: _Optional[_Union[ProcessMetrics, _Mapping]] = ..., sdk: _Optional[_Union[SdkMetrics, _Mapping]] = ..., accelerators: _Optional[_Iterable[_Union[AcceleratorMetrics, _Mapping]]] = ..., tpu_runtime: _Optional[_Union[TpuRuntimeMetrics, _Mapping]] = ..., trainium_host: _Optional[_Union[TrainiumHostMetrics, _Mapping]] = ..., generic: _Optional[_Iterable[_Union[GenericMetric, _Mapping]]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class WriterInfo(_message.Message):
    __slots__ = ("id", "label", "hostname", "rank", "local_rank", "node_rank", "world_size", "scheduler_job")
    ID_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    HOSTNAME_FIELD_NUMBER: _ClassVar[int]
    RANK_FIELD_NUMBER: _ClassVar[int]
    LOCAL_RANK_FIELD_NUMBER: _ClassVar[int]
    NODE_RANK_FIELD_NUMBER: _ClassVar[int]
    WORLD_SIZE_FIELD_NUMBER: _ClassVar[int]
    SCHEDULER_JOB_FIELD_NUMBER: _ClassVar[int]
    id: str
    label: str
    hostname: str
    rank: int
    local_rank: int
    node_rank: int
    world_size: int
    scheduler_job: str
    def __init__(self, id: _Optional[str] = ..., label: _Optional[str] = ..., hostname: _Optional[str] = ..., rank: _Optional[int] = ..., local_rank: _Optional[int] = ..., node_rank: _Optional[int] = ..., world_size: _Optional[int] = ..., scheduler_job: _Optional[str] = ...) -> None: ...

class HostMetrics(_message.Message):
    __slots__ = ("memory", "swap", "cpu", "disk_usage", "disk_io", "network", "apple", "load", "uptime_s")
    MEMORY_FIELD_NUMBER: _ClassVar[int]
    SWAP_FIELD_NUMBER: _ClassVar[int]
    CPU_FIELD_NUMBER: _ClassVar[int]
    DISK_USAGE_FIELD_NUMBER: _ClassVar[int]
    DISK_IO_FIELD_NUMBER: _ClassVar[int]
    NETWORK_FIELD_NUMBER: _ClassVar[int]
    APPLE_FIELD_NUMBER: _ClassVar[int]
    LOAD_FIELD_NUMBER: _ClassVar[int]
    UPTIME_S_FIELD_NUMBER: _ClassVar[int]
    memory: MemoryMetrics
    swap: SwapMetrics
    cpu: CpuMetrics
    disk_usage: _containers.RepeatedCompositeFieldContainer[DiskUsageMetrics]
    disk_io: _containers.RepeatedCompositeFieldContainer[DiskIoMetrics]
    network: NetworkMetrics
    apple: AppleHostMetrics
    load: LoadMetrics
    uptime_s: float
    def __init__(self, memory: _Optional[_Union[MemoryMetrics, _Mapping]] = ..., swap: _Optional[_Union[SwapMetrics, _Mapping]] = ..., cpu: _Optional[_Union[CpuMetrics, _Mapping]] = ..., disk_usage: _Optional[_Iterable[_Union[DiskUsageMetrics, _Mapping]]] = ..., disk_io: _Optional[_Iterable[_Union[DiskIoMetrics, _Mapping]]] = ..., network: _Optional[_Union[NetworkMetrics, _Mapping]] = ..., apple: _Optional[_Union[AppleHostMetrics, _Mapping]] = ..., load: _Optional[_Union[LoadMetrics, _Mapping]] = ..., uptime_s: _Optional[float] = ...) -> None: ...

class MemoryMetrics(_message.Message):
    __slots__ = ("used_ratio", "available_bytes")
    USED_RATIO_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_BYTES_FIELD_NUMBER: _ClassVar[int]
    used_ratio: float
    available_bytes: int
    def __init__(self, used_ratio: _Optional[float] = ..., available_bytes: _Optional[int] = ...) -> None: ...

class SwapMetrics(_message.Message):
    __slots__ = ("used_bytes", "used_ratio")
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    USED_RATIO_FIELD_NUMBER: _ClassVar[int]
    used_bytes: int
    used_ratio: float
    def __init__(self, used_bytes: _Optional[int] = ..., used_ratio: _Optional[float] = ...) -> None: ...

class CpuMetrics(_message.Message):
    __slots__ = ("cores", "temperature_c", "sockets")
    CORES_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    SOCKETS_FIELD_NUMBER: _ClassVar[int]
    cores: _containers.RepeatedCompositeFieldContainer[CpuCoreMetrics]
    temperature_c: float
    sockets: _containers.RepeatedCompositeFieldContainer[CpuSocketMetrics]
    def __init__(self, cores: _Optional[_Iterable[_Union[CpuCoreMetrics, _Mapping]]] = ..., temperature_c: _Optional[float] = ..., sockets: _Optional[_Iterable[_Union[CpuSocketMetrics, _Mapping]]] = ...) -> None: ...

class CpuSocketMetrics(_message.Message):
    __slots__ = ("index", "model", "physical_cores", "logical_cpus", "user_time_s", "system_time_s")
    INDEX_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    PHYSICAL_CORES_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_CPUS_FIELD_NUMBER: _ClassVar[int]
    USER_TIME_S_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_TIME_S_FIELD_NUMBER: _ClassVar[int]
    index: int
    model: str
    physical_cores: int
    logical_cpus: int
    user_time_s: float
    system_time_s: float
    def __init__(self, index: _Optional[int] = ..., model: _Optional[str] = ..., physical_cores: _Optional[int] = ..., logical_cpus: _Optional[int] = ..., user_time_s: _Optional[float] = ..., system_time_s: _Optional[float] = ...) -> None: ...

class CpuCoreMetrics(_message.Message):
    __slots__ = ("index", "utilization_ratio")
    INDEX_FIELD_NUMBER: _ClassVar[int]
    UTILIZATION_RATIO_FIELD_NUMBER: _ClassVar[int]
    index: int
    utilization_ratio: float
    def __init__(self, index: _Optional[int] = ..., utilization_ratio: _Optional[float] = ...) -> None: ...

class LoadMetrics(_message.Message):
    __slots__ = ("one_minute", "five_minutes", "fifteen_minutes")
    ONE_MINUTE_FIELD_NUMBER: _ClassVar[int]
    FIVE_MINUTES_FIELD_NUMBER: _ClassVar[int]
    FIFTEEN_MINUTES_FIELD_NUMBER: _ClassVar[int]
    one_minute: float
    five_minutes: float
    fifteen_minutes: float
    def __init__(self, one_minute: _Optional[float] = ..., five_minutes: _Optional[float] = ..., fifteen_minutes: _Optional[float] = ...) -> None: ...

class DiskUsageMetrics(_message.Message):
    __slots__ = ("path", "used_ratio", "used_bytes")
    PATH_FIELD_NUMBER: _ClassVar[int]
    USED_RATIO_FIELD_NUMBER: _ClassVar[int]
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    path: str
    used_ratio: float
    used_bytes: int
    def __init__(self, path: _Optional[str] = ..., used_ratio: _Optional[float] = ..., used_bytes: _Optional[int] = ...) -> None: ...

class DiskIoMetrics(_message.Message):
    __slots__ = ("device", "read_bytes", "write_bytes")
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    READ_BYTES_FIELD_NUMBER: _ClassVar[int]
    WRITE_BYTES_FIELD_NUMBER: _ClassVar[int]
    device: str
    read_bytes: int
    write_bytes: int
    def __init__(self, device: _Optional[str] = ..., read_bytes: _Optional[int] = ..., write_bytes: _Optional[int] = ...) -> None: ...

class NetworkMetrics(_message.Message):
    __slots__ = ("sent_bytes", "recv_bytes", "tcp_retransmits")
    SENT_BYTES_FIELD_NUMBER: _ClassVar[int]
    RECV_BYTES_FIELD_NUMBER: _ClassVar[int]
    TCP_RETRANSMITS_FIELD_NUMBER: _ClassVar[int]
    sent_bytes: int
    recv_bytes: int
    tcp_retransmits: int
    def __init__(self, sent_bytes: _Optional[int] = ..., recv_bytes: _Optional[int] = ..., tcp_retransmits: _Optional[int] = ...) -> None: ...

class AppleHostMetrics(_message.Message):
    __slots__ = ("memory_used_bytes", "memory_used_ratio", "ecpu_utilization_ratio", "ecpu_frequency_hz", "pcpu_utilization_ratio", "pcpu_frequency_hz", "cpu_power_w", "system_power_w")
    MEMORY_USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_RATIO_FIELD_NUMBER: _ClassVar[int]
    ECPU_UTILIZATION_RATIO_FIELD_NUMBER: _ClassVar[int]
    ECPU_FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    PCPU_UTILIZATION_RATIO_FIELD_NUMBER: _ClassVar[int]
    PCPU_FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    CPU_POWER_W_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_POWER_W_FIELD_NUMBER: _ClassVar[int]
    memory_used_bytes: int
    memory_used_ratio: float
    ecpu_utilization_ratio: float
    ecpu_frequency_hz: float
    pcpu_utilization_ratio: float
    pcpu_frequency_hz: float
    cpu_power_w: float
    system_power_w: float
    def __init__(self, memory_used_bytes: _Optional[int] = ..., memory_used_ratio: _Optional[float] = ..., ecpu_utilization_ratio: _Optional[float] = ..., ecpu_frequency_hz: _Optional[float] = ..., pcpu_utilization_ratio: _Optional[float] = ..., pcpu_frequency_hz: _Optional[float] = ..., cpu_power_w: _Optional[float] = ..., system_power_w: _Optional[float] = ...) -> None: ...

class ProcessMetrics(_message.Message):
    __slots__ = ("cpu_ratio", "rss_bytes", "memory_ratio", "threads", "cgroup_cpu_throttled_ratio", "cgroup_oom_kills", "cpu_user_ratio", "cpu_system_ratio", "cgroup_cpu_limit", "cpu_user_time_s", "cpu_system_time_s")
    CPU_RATIO_FIELD_NUMBER: _ClassVar[int]
    RSS_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_RATIO_FIELD_NUMBER: _ClassVar[int]
    THREADS_FIELD_NUMBER: _ClassVar[int]
    CGROUP_CPU_THROTTLED_RATIO_FIELD_NUMBER: _ClassVar[int]
    CGROUP_OOM_KILLS_FIELD_NUMBER: _ClassVar[int]
    CPU_USER_RATIO_FIELD_NUMBER: _ClassVar[int]
    CPU_SYSTEM_RATIO_FIELD_NUMBER: _ClassVar[int]
    CGROUP_CPU_LIMIT_FIELD_NUMBER: _ClassVar[int]
    CPU_USER_TIME_S_FIELD_NUMBER: _ClassVar[int]
    CPU_SYSTEM_TIME_S_FIELD_NUMBER: _ClassVar[int]
    cpu_ratio: float
    rss_bytes: int
    memory_ratio: float
    threads: int
    cgroup_cpu_throttled_ratio: float
    cgroup_oom_kills: int
    cpu_user_ratio: float
    cpu_system_ratio: float
    cgroup_cpu_limit: float
    cpu_user_time_s: float
    cpu_system_time_s: float
    def __init__(self, cpu_ratio: _Optional[float] = ..., rss_bytes: _Optional[int] = ..., memory_ratio: _Optional[float] = ..., threads: _Optional[int] = ..., cgroup_cpu_throttled_ratio: _Optional[float] = ..., cgroup_oom_kills: _Optional[int] = ..., cpu_user_ratio: _Optional[float] = ..., cpu_system_ratio: _Optional[float] = ..., cgroup_cpu_limit: _Optional[float] = ..., cpu_user_time_s: _Optional[float] = ..., cpu_system_time_s: _Optional[float] = ...) -> None: ...

class SdkMetrics(_message.Message):
    __slots__ = ("cpu_ratio", "rss_bytes", "cpu_user_ratio", "cpu_system_ratio")
    CPU_RATIO_FIELD_NUMBER: _ClassVar[int]
    RSS_BYTES_FIELD_NUMBER: _ClassVar[int]
    CPU_USER_RATIO_FIELD_NUMBER: _ClassVar[int]
    CPU_SYSTEM_RATIO_FIELD_NUMBER: _ClassVar[int]
    cpu_ratio: float
    rss_bytes: int
    cpu_user_ratio: float
    cpu_system_ratio: float
    def __init__(self, cpu_ratio: _Optional[float] = ..., rss_bytes: _Optional[int] = ..., cpu_user_ratio: _Optional[float] = ..., cpu_system_ratio: _Optional[float] = ...) -> None: ...

class AcceleratorMetrics(_message.Message):
    __slots__ = ("type", "index", "uuid", "host", "source", "binding", "pci_bus_id", "model", "parent_uuid", "profile", "share", "utilization_ratio", "memory_activity_ratio", "memory_used_ratio", "memory_used_bytes", "memory_total_bytes", "temperature_c", "power_w", "power_ratio", "power_limit_w", "clock_hz", "fan_speed_ratio", "energy_j", "nvidia", "amd", "tpu", "trainium")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    BINDING_FIELD_NUMBER: _ClassVar[int]
    PCI_BUS_ID_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    PARENT_UUID_FIELD_NUMBER: _ClassVar[int]
    PROFILE_FIELD_NUMBER: _ClassVar[int]
    SHARE_FIELD_NUMBER: _ClassVar[int]
    UTILIZATION_RATIO_FIELD_NUMBER: _ClassVar[int]
    MEMORY_ACTIVITY_RATIO_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_RATIO_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    POWER_W_FIELD_NUMBER: _ClassVar[int]
    POWER_RATIO_FIELD_NUMBER: _ClassVar[int]
    POWER_LIMIT_W_FIELD_NUMBER: _ClassVar[int]
    CLOCK_HZ_FIELD_NUMBER: _ClassVar[int]
    FAN_SPEED_RATIO_FIELD_NUMBER: _ClassVar[int]
    ENERGY_J_FIELD_NUMBER: _ClassVar[int]
    NVIDIA_FIELD_NUMBER: _ClassVar[int]
    AMD_FIELD_NUMBER: _ClassVar[int]
    TPU_FIELD_NUMBER: _ClassVar[int]
    TRAINIUM_FIELD_NUMBER: _ClassVar[int]
    type: AcceleratorType
    index: int
    uuid: str
    host: str
    source: str
    binding: Binding
    pci_bus_id: str
    model: str
    parent_uuid: str
    profile: str
    share: float
    utilization_ratio: float
    memory_activity_ratio: float
    memory_used_ratio: float
    memory_used_bytes: int
    memory_total_bytes: int
    temperature_c: float
    power_w: float
    power_ratio: float
    power_limit_w: float
    clock_hz: float
    fan_speed_ratio: float
    energy_j: float
    nvidia: NvidiaMetrics
    amd: AmdMetrics
    tpu: TpuMetrics
    trainium: TrainiumMetrics
    def __init__(self, type: _Optional[_Union[AcceleratorType, str]] = ..., index: _Optional[int] = ..., uuid: _Optional[str] = ..., host: _Optional[str] = ..., source: _Optional[str] = ..., binding: _Optional[_Union[Binding, str]] = ..., pci_bus_id: _Optional[str] = ..., model: _Optional[str] = ..., parent_uuid: _Optional[str] = ..., profile: _Optional[str] = ..., share: _Optional[float] = ..., utilization_ratio: _Optional[float] = ..., memory_activity_ratio: _Optional[float] = ..., memory_used_ratio: _Optional[float] = ..., memory_used_bytes: _Optional[int] = ..., memory_total_bytes: _Optional[int] = ..., temperature_c: _Optional[float] = ..., power_w: _Optional[float] = ..., power_ratio: _Optional[float] = ..., power_limit_w: _Optional[float] = ..., clock_hz: _Optional[float] = ..., fan_speed_ratio: _Optional[float] = ..., energy_j: _Optional[float] = ..., nvidia: _Optional[_Union[NvidiaMetrics, _Mapping]] = ..., amd: _Optional[_Union[AmdMetrics, _Mapping]] = ..., tpu: _Optional[_Union[TpuMetrics, _Mapping]] = ..., trainium: _Optional[_Union[TrainiumMetrics, _Mapping]] = ...) -> None: ...

class NvidiaMetrics(_message.Message):
    __slots__ = ("sm_clock_hz", "memory_clock_hz", "corrected_memory_errors", "uncorrected_memory_errors", "pcie_tx_bytes_per_s", "pcie_rx_bytes_per_s", "nvlink_tx_bytes_per_s", "nvlink_rx_bytes_per_s", "sm_active_ratio", "sm_occupancy_ratio", "dram_active_ratio", "pipe_tensor_active_ratio", "pipe_tensor_hmma_active_ratio", "pipe_fp64_active_ratio", "pipe_fp32_active_ratio", "pipe_fp16_active_ratio", "memory_temperature_c", "max_operating_temperature_c", "memory_max_operating_temperature_c", "memory_free_bytes")
    SM_CLOCK_HZ_FIELD_NUMBER: _ClassVar[int]
    MEMORY_CLOCK_HZ_FIELD_NUMBER: _ClassVar[int]
    CORRECTED_MEMORY_ERRORS_FIELD_NUMBER: _ClassVar[int]
    UNCORRECTED_MEMORY_ERRORS_FIELD_NUMBER: _ClassVar[int]
    PCIE_TX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    PCIE_RX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    NVLINK_TX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    NVLINK_RX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    SM_ACTIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    SM_OCCUPANCY_RATIO_FIELD_NUMBER: _ClassVar[int]
    DRAM_ACTIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    PIPE_TENSOR_ACTIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    PIPE_TENSOR_HMMA_ACTIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    PIPE_FP64_ACTIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    PIPE_FP32_ACTIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    PIPE_FP16_ACTIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    MEMORY_TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    MAX_OPERATING_TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    MEMORY_MAX_OPERATING_TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    MEMORY_FREE_BYTES_FIELD_NUMBER: _ClassVar[int]
    sm_clock_hz: float
    memory_clock_hz: float
    corrected_memory_errors: int
    uncorrected_memory_errors: int
    pcie_tx_bytes_per_s: float
    pcie_rx_bytes_per_s: float
    nvlink_tx_bytes_per_s: float
    nvlink_rx_bytes_per_s: float
    sm_active_ratio: float
    sm_occupancy_ratio: float
    dram_active_ratio: float
    pipe_tensor_active_ratio: float
    pipe_tensor_hmma_active_ratio: float
    pipe_fp64_active_ratio: float
    pipe_fp32_active_ratio: float
    pipe_fp16_active_ratio: float
    memory_temperature_c: float
    max_operating_temperature_c: float
    memory_max_operating_temperature_c: float
    memory_free_bytes: int
    def __init__(self, sm_clock_hz: _Optional[float] = ..., memory_clock_hz: _Optional[float] = ..., corrected_memory_errors: _Optional[int] = ..., uncorrected_memory_errors: _Optional[int] = ..., pcie_tx_bytes_per_s: _Optional[float] = ..., pcie_rx_bytes_per_s: _Optional[float] = ..., nvlink_tx_bytes_per_s: _Optional[float] = ..., nvlink_rx_bytes_per_s: _Optional[float] = ..., sm_active_ratio: _Optional[float] = ..., sm_occupancy_ratio: _Optional[float] = ..., dram_active_ratio: _Optional[float] = ..., pipe_tensor_active_ratio: _Optional[float] = ..., pipe_tensor_hmma_active_ratio: _Optional[float] = ..., pipe_fp64_active_ratio: _Optional[float] = ..., pipe_fp32_active_ratio: _Optional[float] = ..., pipe_fp16_active_ratio: _Optional[float] = ..., memory_temperature_c: _Optional[float] = ..., max_operating_temperature_c: _Optional[float] = ..., memory_max_operating_temperature_c: _Optional[float] = ..., memory_free_bytes: _Optional[int] = ...) -> None: ...

class AmdMetrics(_message.Message):
    __slots__ = ("memory_overdrive_ratio",)
    MEMORY_OVERDRIVE_RATIO_FIELD_NUMBER: _ClassVar[int]
    memory_overdrive_ratio: float
    def __init__(self, memory_overdrive_ratio: _Optional[float] = ...) -> None: ...

class TpuMetrics(_message.Message):
    __slots__ = ("duty_cycle_ratio", "tensorcore_idle_duration_s", "runtime_hbm_utilization_ratio", "ici_link_health", "throttle_score")
    DUTY_CYCLE_RATIO_FIELD_NUMBER: _ClassVar[int]
    TENSORCORE_IDLE_DURATION_S_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_HBM_UTILIZATION_RATIO_FIELD_NUMBER: _ClassVar[int]
    ICI_LINK_HEALTH_FIELD_NUMBER: _ClassVar[int]
    THROTTLE_SCORE_FIELD_NUMBER: _ClassVar[int]
    duty_cycle_ratio: float
    tensorcore_idle_duration_s: float
    runtime_hbm_utilization_ratio: float
    ici_link_health: float
    throttle_score: float
    def __init__(self, duty_cycle_ratio: _Optional[float] = ..., tensorcore_idle_duration_s: _Optional[float] = ..., runtime_hbm_utilization_ratio: _Optional[float] = ..., ici_link_health: _Optional[float] = ..., throttle_score: _Optional[float] = ...) -> None: ...

class TrainiumMetrics(_message.Message):
    __slots__ = ("memory_constants_bytes", "memory_model_code_bytes", "memory_model_shared_scratchpad_bytes", "memory_runtime_bytes", "memory_tensors_bytes")
    MEMORY_CONSTANTS_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_MODEL_CODE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_MODEL_SHARED_SCRATCHPAD_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_RUNTIME_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_TENSORS_BYTES_FIELD_NUMBER: _ClassVar[int]
    memory_constants_bytes: int
    memory_model_code_bytes: int
    memory_model_shared_scratchpad_bytes: int
    memory_runtime_bytes: int
    memory_tensors_bytes: int
    def __init__(self, memory_constants_bytes: _Optional[int] = ..., memory_model_code_bytes: _Optional[int] = ..., memory_model_shared_scratchpad_bytes: _Optional[int] = ..., memory_runtime_bytes: _Optional[int] = ..., memory_tensors_bytes: _Optional[int] = ...) -> None: ...

class TpuRuntimeMetrics(_message.Message):
    __slots__ = ("distributions", "hlo_queue_sizes")
    class DistributionKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        DISTRIBUTION_UNSPECIFIED: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        BUFFER_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        INBOUND_BUFFER_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        HOST_TO_DEVICE_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        DEVICE_TO_HOST_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        COLLECTIVE_E2E_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        HOST_COMPUTE_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        HLO_EXEC_TIMING: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        GRPC_TCP_MIN_RTT: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        GRPC_TCP_DELIVERY_RATE: _ClassVar[TpuRuntimeMetrics.DistributionKind]
    DISTRIBUTION_UNSPECIFIED: TpuRuntimeMetrics.DistributionKind
    BUFFER_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    INBOUND_BUFFER_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    HOST_TO_DEVICE_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    DEVICE_TO_HOST_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    COLLECTIVE_E2E_LATENCY: TpuRuntimeMetrics.DistributionKind
    HOST_COMPUTE_LATENCY: TpuRuntimeMetrics.DistributionKind
    HLO_EXEC_TIMING: TpuRuntimeMetrics.DistributionKind
    GRPC_TCP_MIN_RTT: TpuRuntimeMetrics.DistributionKind
    GRPC_TCP_DELIVERY_RATE: TpuRuntimeMetrics.DistributionKind
    class Distribution(_message.Message):
        __slots__ = ("kind", "label", "mean", "p50", "p90", "p95", "p99", "p999")
        KIND_FIELD_NUMBER: _ClassVar[int]
        LABEL_FIELD_NUMBER: _ClassVar[int]
        MEAN_FIELD_NUMBER: _ClassVar[int]
        P50_FIELD_NUMBER: _ClassVar[int]
        P90_FIELD_NUMBER: _ClassVar[int]
        P95_FIELD_NUMBER: _ClassVar[int]
        P99_FIELD_NUMBER: _ClassVar[int]
        P999_FIELD_NUMBER: _ClassVar[int]
        kind: TpuRuntimeMetrics.DistributionKind
        label: str
        mean: float
        p50: float
        p90: float
        p95: float
        p99: float
        p999: float
        def __init__(self, kind: _Optional[_Union[TpuRuntimeMetrics.DistributionKind, str]] = ..., label: _Optional[str] = ..., mean: _Optional[float] = ..., p50: _Optional[float] = ..., p90: _Optional[float] = ..., p95: _Optional[float] = ..., p99: _Optional[float] = ..., p999: _Optional[float] = ...) -> None: ...
    class QueueSize(_message.Message):
        __slots__ = ("label", "size")
        LABEL_FIELD_NUMBER: _ClassVar[int]
        SIZE_FIELD_NUMBER: _ClassVar[int]
        label: str
        size: float
        def __init__(self, label: _Optional[str] = ..., size: _Optional[float] = ...) -> None: ...
    DISTRIBUTIONS_FIELD_NUMBER: _ClassVar[int]
    HLO_QUEUE_SIZES_FIELD_NUMBER: _ClassVar[int]
    distributions: _containers.RepeatedCompositeFieldContainer[TpuRuntimeMetrics.Distribution]
    hlo_queue_sizes: _containers.RepeatedCompositeFieldContainer[TpuRuntimeMetrics.QueueSize]
    def __init__(self, distributions: _Optional[_Iterable[_Union[TpuRuntimeMetrics.Distribution, _Mapping]]] = ..., hlo_queue_sizes: _Optional[_Iterable[_Union[TpuRuntimeMetrics.QueueSize, _Mapping]]] = ...) -> None: ...

class TrainiumHostMetrics(_message.Message):
    __slots__ = ("host_memory_bytes", "device_memory_bytes", "host_memory_application_bytes", "host_memory_constants_bytes", "host_memory_dma_buffers_bytes", "host_memory_tensors_bytes")
    HOST_MEMORY_BYTES_FIELD_NUMBER: _ClassVar[int]
    DEVICE_MEMORY_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_APPLICATION_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_CONSTANTS_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_DMA_BUFFERS_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_TENSORS_BYTES_FIELD_NUMBER: _ClassVar[int]
    host_memory_bytes: int
    device_memory_bytes: int
    host_memory_application_bytes: int
    host_memory_constants_bytes: int
    host_memory_dma_buffers_bytes: int
    host_memory_tensors_bytes: int
    def __init__(self, host_memory_bytes: _Optional[int] = ..., device_memory_bytes: _Optional[int] = ..., host_memory_application_bytes: _Optional[int] = ..., host_memory_constants_bytes: _Optional[int] = ..., host_memory_dma_buffers_bytes: _Optional[int] = ..., host_memory_tensors_bytes: _Optional[int] = ...) -> None: ...

class GenericMetric(_message.Message):
    __slots__ = ("source", "name", "labels", "kind", "value", "series")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    SERIES_FIELD_NUMBER: _ClassVar[int]
    source: str
    name: str
    labels: _containers.RepeatedCompositeFieldContainer[MetricLabel]
    kind: MetricInfo.Kind
    value: float
    series: int
    def __init__(self, source: _Optional[str] = ..., name: _Optional[str] = ..., labels: _Optional[_Iterable[_Union[MetricLabel, _Mapping]]] = ..., kind: _Optional[_Union[MetricInfo.Kind, str]] = ..., value: _Optional[float] = ..., series: _Optional[int] = ...) -> None: ...

class MetricLabel(_message.Message):
    __slots__ = ("key", "value")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: str
    def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

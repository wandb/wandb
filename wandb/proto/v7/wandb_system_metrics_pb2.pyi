import datetime

from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from wandb.proto import wandb_base_pb2 as _wandb_base_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AcceleratorType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACCELERATOR_UNSPECIFIED: _ClassVar[AcceleratorType]
    NVIDIA_GPU: _ClassVar[AcceleratorType]
    AMD_GPU: _ClassVar[AcceleratorType]
    APPLE_GPU: _ClassVar[AcceleratorType]
    APPLE_ANE: _ClassVar[AcceleratorType]
    GOOGLE_TPU: _ClassVar[AcceleratorType]
    AWS_TRAINIUM: _ClassVar[AcceleratorType]
ACCELERATOR_UNSPECIFIED: AcceleratorType
NVIDIA_GPU: AcceleratorType
AMD_GPU: AcceleratorType
APPLE_GPU: AcceleratorType
APPLE_ANE: AcceleratorType
GOOGLE_TPU: AcceleratorType
AWS_TRAINIUM: AcceleratorType
METRIC_FIELD_NUMBER: _ClassVar[int]
metric: _descriptor.FieldDescriptor

class MetricInfo(_message.Message):
    __slots__ = ("unit", "display", "kind", "legacy", "legacy_process_copy", "range_min", "range_max")
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
    unit: str
    display: str
    kind: MetricInfo.Kind
    legacy: _containers.RepeatedCompositeFieldContainer[LegacyKey]
    legacy_process_copy: bool
    range_min: float
    range_max: float
    def __init__(self, unit: _Optional[str] = ..., display: _Optional[str] = ..., kind: _Optional[_Union[MetricInfo.Kind, str]] = ..., legacy: _Optional[_Iterable[_Union[LegacyKey, _Mapping]]] = ..., legacy_process_copy: _Optional[bool] = ..., range_min: _Optional[float] = ..., range_max: _Optional[float] = ...) -> None: ...

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
    __slots__ = ("timestamp", "writer_id", "label", "host", "process", "accelerators", "tpu_runtime", "trainium_host", "generic", "_info")
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    WRITER_ID_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    PROCESS_FIELD_NUMBER: _ClassVar[int]
    ACCELERATORS_FIELD_NUMBER: _ClassVar[int]
    TPU_RUNTIME_FIELD_NUMBER: _ClassVar[int]
    TRAINIUM_HOST_FIELD_NUMBER: _ClassVar[int]
    GENERIC_FIELD_NUMBER: _ClassVar[int]
    _INFO_FIELD_NUMBER: _ClassVar[int]
    timestamp: _timestamp_pb2.Timestamp
    writer_id: str
    label: str
    host: HostMetrics
    process: ProcessMetrics
    accelerators: _containers.RepeatedCompositeFieldContainer[AcceleratorMetrics]
    tpu_runtime: TpuRuntimeMetrics
    trainium_host: TrainiumHostMetrics
    generic: _containers.RepeatedCompositeFieldContainer[GenericMetric]
    _info: _wandb_base_pb2._RecordInfo
    def __init__(self, timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., writer_id: _Optional[str] = ..., label: _Optional[str] = ..., host: _Optional[_Union[HostMetrics, _Mapping]] = ..., process: _Optional[_Union[ProcessMetrics, _Mapping]] = ..., accelerators: _Optional[_Iterable[_Union[AcceleratorMetrics, _Mapping]]] = ..., tpu_runtime: _Optional[_Union[TpuRuntimeMetrics, _Mapping]] = ..., trainium_host: _Optional[_Union[TrainiumHostMetrics, _Mapping]] = ..., generic: _Optional[_Iterable[_Union[GenericMetric, _Mapping]]] = ..., _info: _Optional[_Union[_wandb_base_pb2._RecordInfo, _Mapping]] = ...) -> None: ...

class HostMetrics(_message.Message):
    __slots__ = ("cpu", "memory", "swap", "disk_usage", "disk_io", "network", "power")
    CPU_FIELD_NUMBER: _ClassVar[int]
    MEMORY_FIELD_NUMBER: _ClassVar[int]
    SWAP_FIELD_NUMBER: _ClassVar[int]
    DISK_USAGE_FIELD_NUMBER: _ClassVar[int]
    DISK_IO_FIELD_NUMBER: _ClassVar[int]
    NETWORK_FIELD_NUMBER: _ClassVar[int]
    POWER_FIELD_NUMBER: _ClassVar[int]
    cpu: CpuMetrics
    memory: MemoryMetrics
    swap: SwapMetrics
    disk_usage: _containers.RepeatedCompositeFieldContainer[DiskUsageMetrics]
    disk_io: _containers.RepeatedCompositeFieldContainer[DiskIoMetrics]
    network: NetworkMetrics
    power: PowerMetrics
    def __init__(self, cpu: _Optional[_Union[CpuMetrics, _Mapping]] = ..., memory: _Optional[_Union[MemoryMetrics, _Mapping]] = ..., swap: _Optional[_Union[SwapMetrics, _Mapping]] = ..., disk_usage: _Optional[_Iterable[_Union[DiskUsageMetrics, _Mapping]]] = ..., disk_io: _Optional[_Iterable[_Union[DiskIoMetrics, _Mapping]]] = ..., network: _Optional[_Union[NetworkMetrics, _Mapping]] = ..., power: _Optional[_Union[PowerMetrics, _Mapping]] = ...) -> None: ...

class CpuMetrics(_message.Message):
    __slots__ = ("cores", "apple")
    CORES_FIELD_NUMBER: _ClassVar[int]
    APPLE_FIELD_NUMBER: _ClassVar[int]
    cores: _containers.RepeatedCompositeFieldContainer[CpuCoreMetrics]
    apple: AppleCpuMetrics
    def __init__(self, cores: _Optional[_Iterable[_Union[CpuCoreMetrics, _Mapping]]] = ..., apple: _Optional[_Union[AppleCpuMetrics, _Mapping]] = ...) -> None: ...

class CpuCoreMetrics(_message.Message):
    __slots__ = ("index", "utilization_percent")
    INDEX_FIELD_NUMBER: _ClassVar[int]
    UTILIZATION_PERCENT_FIELD_NUMBER: _ClassVar[int]
    index: int
    utilization_percent: float
    def __init__(self, index: _Optional[int] = ..., utilization_percent: _Optional[float] = ...) -> None: ...

class AppleCpuMetrics(_message.Message):
    __slots__ = ("ecpu_utilization_percent", "ecpu_frequency_mhz", "pcpu_utilization_percent", "pcpu_frequency_mhz", "temperature_c", "power_w")
    ECPU_UTILIZATION_PERCENT_FIELD_NUMBER: _ClassVar[int]
    ECPU_FREQUENCY_MHZ_FIELD_NUMBER: _ClassVar[int]
    PCPU_UTILIZATION_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PCPU_FREQUENCY_MHZ_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    POWER_W_FIELD_NUMBER: _ClassVar[int]
    ecpu_utilization_percent: float
    ecpu_frequency_mhz: float
    pcpu_utilization_percent: float
    pcpu_frequency_mhz: float
    temperature_c: float
    power_w: float
    def __init__(self, ecpu_utilization_percent: _Optional[float] = ..., ecpu_frequency_mhz: _Optional[float] = ..., pcpu_utilization_percent: _Optional[float] = ..., pcpu_frequency_mhz: _Optional[float] = ..., temperature_c: _Optional[float] = ..., power_w: _Optional[float] = ...) -> None: ...

class MemoryMetrics(_message.Message):
    __slots__ = ("used_percent", "available_bytes", "apple")
    USED_PERCENT_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_BYTES_FIELD_NUMBER: _ClassVar[int]
    APPLE_FIELD_NUMBER: _ClassVar[int]
    used_percent: float
    available_bytes: int
    apple: AppleMemoryMetrics
    def __init__(self, used_percent: _Optional[float] = ..., available_bytes: _Optional[int] = ..., apple: _Optional[_Union[AppleMemoryMetrics, _Mapping]] = ...) -> None: ...

class AppleMemoryMetrics(_message.Message):
    __slots__ = ("used_bytes", "used_percent")
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    USED_PERCENT_FIELD_NUMBER: _ClassVar[int]
    used_bytes: int
    used_percent: float
    def __init__(self, used_bytes: _Optional[int] = ..., used_percent: _Optional[float] = ...) -> None: ...

class SwapMetrics(_message.Message):
    __slots__ = ("used_bytes", "used_percent")
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    USED_PERCENT_FIELD_NUMBER: _ClassVar[int]
    used_bytes: int
    used_percent: float
    def __init__(self, used_bytes: _Optional[int] = ..., used_percent: _Optional[float] = ...) -> None: ...

class DiskUsageMetrics(_message.Message):
    __slots__ = ("path", "used_percent", "used_bytes")
    PATH_FIELD_NUMBER: _ClassVar[int]
    USED_PERCENT_FIELD_NUMBER: _ClassVar[int]
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    path: str
    used_percent: float
    used_bytes: int
    def __init__(self, path: _Optional[str] = ..., used_percent: _Optional[float] = ..., used_bytes: _Optional[int] = ...) -> None: ...

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
    __slots__ = ("sent_bytes", "recv_bytes")
    SENT_BYTES_FIELD_NUMBER: _ClassVar[int]
    RECV_BYTES_FIELD_NUMBER: _ClassVar[int]
    sent_bytes: int
    recv_bytes: int
    def __init__(self, sent_bytes: _Optional[int] = ..., recv_bytes: _Optional[int] = ...) -> None: ...

class PowerMetrics(_message.Message):
    __slots__ = ("total_w",)
    TOTAL_W_FIELD_NUMBER: _ClassVar[int]
    total_w: float
    def __init__(self, total_w: _Optional[float] = ...) -> None: ...

class ProcessMetrics(_message.Message):
    __slots__ = ("cpu_percent", "rss_bytes", "memory_percent", "threads")
    CPU_PERCENT_FIELD_NUMBER: _ClassVar[int]
    RSS_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_PERCENT_FIELD_NUMBER: _ClassVar[int]
    THREADS_FIELD_NUMBER: _ClassVar[int]
    cpu_percent: float
    rss_bytes: int
    memory_percent: float
    threads: int
    def __init__(self, cpu_percent: _Optional[float] = ..., rss_bytes: _Optional[int] = ..., memory_percent: _Optional[float] = ..., threads: _Optional[int] = ...) -> None: ...

class AcceleratorMetrics(_message.Message):
    __slots__ = ("type", "index", "uuid", "host", "source", "in_use_by_process", "pci_bus_id", "utilization_percent", "memory_activity_percent", "memory_used_percent", "memory_used_bytes", "memory_total_bytes", "temperature_c", "power_w", "power_percent", "power_limit_w", "clock_mhz", "fan_speed_percent", "energy_j", "process_memory_used_bytes", "nvidia", "amd", "tpu", "trainium")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    HOST_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    IN_USE_BY_PROCESS_FIELD_NUMBER: _ClassVar[int]
    PCI_BUS_ID_FIELD_NUMBER: _ClassVar[int]
    UTILIZATION_PERCENT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_ACTIVITY_PERCENT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_PERCENT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEMORY_TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    POWER_W_FIELD_NUMBER: _ClassVar[int]
    POWER_PERCENT_FIELD_NUMBER: _ClassVar[int]
    POWER_LIMIT_W_FIELD_NUMBER: _ClassVar[int]
    CLOCK_MHZ_FIELD_NUMBER: _ClassVar[int]
    FAN_SPEED_PERCENT_FIELD_NUMBER: _ClassVar[int]
    ENERGY_J_FIELD_NUMBER: _ClassVar[int]
    PROCESS_MEMORY_USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    NVIDIA_FIELD_NUMBER: _ClassVar[int]
    AMD_FIELD_NUMBER: _ClassVar[int]
    TPU_FIELD_NUMBER: _ClassVar[int]
    TRAINIUM_FIELD_NUMBER: _ClassVar[int]
    type: AcceleratorType
    index: int
    uuid: str
    host: str
    source: str
    in_use_by_process: bool
    pci_bus_id: str
    utilization_percent: float
    memory_activity_percent: float
    memory_used_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    temperature_c: float
    power_w: float
    power_percent: float
    power_limit_w: float
    clock_mhz: float
    fan_speed_percent: float
    energy_j: float
    process_memory_used_bytes: int
    nvidia: NvidiaMetrics
    amd: AmdMetrics
    tpu: TpuMetrics
    trainium: TrainiumMetrics
    def __init__(self, type: _Optional[_Union[AcceleratorType, str]] = ..., index: _Optional[int] = ..., uuid: _Optional[str] = ..., host: _Optional[str] = ..., source: _Optional[str] = ..., in_use_by_process: _Optional[bool] = ..., pci_bus_id: _Optional[str] = ..., utilization_percent: _Optional[float] = ..., memory_activity_percent: _Optional[float] = ..., memory_used_percent: _Optional[float] = ..., memory_used_bytes: _Optional[int] = ..., memory_total_bytes: _Optional[int] = ..., temperature_c: _Optional[float] = ..., power_w: _Optional[float] = ..., power_percent: _Optional[float] = ..., power_limit_w: _Optional[float] = ..., clock_mhz: _Optional[float] = ..., fan_speed_percent: _Optional[float] = ..., energy_j: _Optional[float] = ..., process_memory_used_bytes: _Optional[int] = ..., nvidia: _Optional[_Union[NvidiaMetrics, _Mapping]] = ..., amd: _Optional[_Union[AmdMetrics, _Mapping]] = ..., tpu: _Optional[_Union[TpuMetrics, _Mapping]] = ..., trainium: _Optional[_Union[TrainiumMetrics, _Mapping]] = ...) -> None: ...

class NvidiaMetrics(_message.Message):
    __slots__ = ("sm_clock_mhz", "memory_clock_mhz", "corrected_memory_errors", "uncorrected_memory_errors", "encoder_utilization_percent", "pcie_link_gen", "pcie_link_width", "pcie_link_speed_bps", "pcie_link_gen_max", "pcie_link_width_max", "pcie_tx_bytes_per_s", "pcie_rx_bytes_per_s", "nvlink_tx_bytes_per_s", "nvlink_rx_bytes_per_s", "sm_active_percent", "sm_occupancy_percent", "dram_active_percent", "pipe_tensor_active_percent", "pipe_tensor_hmma_active_percent", "pipe_fp64_active_percent", "pipe_fp32_active_percent", "pipe_fp16_active_percent", "memory_temperature_c", "max_operating_temperature_c", "memory_max_operating_temperature_c", "memory_free_bytes")
    SM_CLOCK_MHZ_FIELD_NUMBER: _ClassVar[int]
    MEMORY_CLOCK_MHZ_FIELD_NUMBER: _ClassVar[int]
    CORRECTED_MEMORY_ERRORS_FIELD_NUMBER: _ClassVar[int]
    UNCORRECTED_MEMORY_ERRORS_FIELD_NUMBER: _ClassVar[int]
    ENCODER_UTILIZATION_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PCIE_LINK_GEN_FIELD_NUMBER: _ClassVar[int]
    PCIE_LINK_WIDTH_FIELD_NUMBER: _ClassVar[int]
    PCIE_LINK_SPEED_BPS_FIELD_NUMBER: _ClassVar[int]
    PCIE_LINK_GEN_MAX_FIELD_NUMBER: _ClassVar[int]
    PCIE_LINK_WIDTH_MAX_FIELD_NUMBER: _ClassVar[int]
    PCIE_TX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    PCIE_RX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    NVLINK_TX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    NVLINK_RX_BYTES_PER_S_FIELD_NUMBER: _ClassVar[int]
    SM_ACTIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    SM_OCCUPANCY_PERCENT_FIELD_NUMBER: _ClassVar[int]
    DRAM_ACTIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PIPE_TENSOR_ACTIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PIPE_TENSOR_HMMA_ACTIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PIPE_FP64_ACTIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PIPE_FP32_ACTIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    PIPE_FP16_ACTIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    MAX_OPERATING_TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    MEMORY_MAX_OPERATING_TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    MEMORY_FREE_BYTES_FIELD_NUMBER: _ClassVar[int]
    sm_clock_mhz: float
    memory_clock_mhz: float
    corrected_memory_errors: int
    uncorrected_memory_errors: int
    encoder_utilization_percent: float
    pcie_link_gen: int
    pcie_link_width: int
    pcie_link_speed_bps: float
    pcie_link_gen_max: int
    pcie_link_width_max: int
    pcie_tx_bytes_per_s: float
    pcie_rx_bytes_per_s: float
    nvlink_tx_bytes_per_s: float
    nvlink_rx_bytes_per_s: float
    sm_active_percent: float
    sm_occupancy_percent: float
    dram_active_percent: float
    pipe_tensor_active_percent: float
    pipe_tensor_hmma_active_percent: float
    pipe_fp64_active_percent: float
    pipe_fp32_active_percent: float
    pipe_fp16_active_percent: float
    memory_temperature_c: float
    max_operating_temperature_c: float
    memory_max_operating_temperature_c: float
    memory_free_bytes: int
    def __init__(self, sm_clock_mhz: _Optional[float] = ..., memory_clock_mhz: _Optional[float] = ..., corrected_memory_errors: _Optional[int] = ..., uncorrected_memory_errors: _Optional[int] = ..., encoder_utilization_percent: _Optional[float] = ..., pcie_link_gen: _Optional[int] = ..., pcie_link_width: _Optional[int] = ..., pcie_link_speed_bps: _Optional[float] = ..., pcie_link_gen_max: _Optional[int] = ..., pcie_link_width_max: _Optional[int] = ..., pcie_tx_bytes_per_s: _Optional[float] = ..., pcie_rx_bytes_per_s: _Optional[float] = ..., nvlink_tx_bytes_per_s: _Optional[float] = ..., nvlink_rx_bytes_per_s: _Optional[float] = ..., sm_active_percent: _Optional[float] = ..., sm_occupancy_percent: _Optional[float] = ..., dram_active_percent: _Optional[float] = ..., pipe_tensor_active_percent: _Optional[float] = ..., pipe_tensor_hmma_active_percent: _Optional[float] = ..., pipe_fp64_active_percent: _Optional[float] = ..., pipe_fp32_active_percent: _Optional[float] = ..., pipe_fp16_active_percent: _Optional[float] = ..., memory_temperature_c: _Optional[float] = ..., max_operating_temperature_c: _Optional[float] = ..., memory_max_operating_temperature_c: _Optional[float] = ..., memory_free_bytes: _Optional[int] = ...) -> None: ...

class AmdMetrics(_message.Message):
    __slots__ = ("memory_overdrive_percent",)
    MEMORY_OVERDRIVE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    memory_overdrive_percent: float
    def __init__(self, memory_overdrive_percent: _Optional[float] = ...) -> None: ...

class TpuMetrics(_message.Message):
    __slots__ = ("duty_cycle_percent", "tensorcore_idle_duration_s", "runtime_hbm_utilization_percent", "ici_link_health", "throttle_score")
    DUTY_CYCLE_PERCENT_FIELD_NUMBER: _ClassVar[int]
    TENSORCORE_IDLE_DURATION_S_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_HBM_UTILIZATION_PERCENT_FIELD_NUMBER: _ClassVar[int]
    ICI_LINK_HEALTH_FIELD_NUMBER: _ClassVar[int]
    THROTTLE_SCORE_FIELD_NUMBER: _ClassVar[int]
    duty_cycle_percent: float
    tensorcore_idle_duration_s: float
    runtime_hbm_utilization_percent: float
    ici_link_health: float
    throttle_score: float
    def __init__(self, duty_cycle_percent: _Optional[float] = ..., tensorcore_idle_duration_s: _Optional[float] = ..., runtime_hbm_utilization_percent: _Optional[float] = ..., ici_link_health: _Optional[float] = ..., throttle_score: _Optional[float] = ...) -> None: ...

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
    __slots__ = ("distributions", "hlo_queue_size")
    class DistributionKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        DISTRIBUTION_UNSPECIFIED: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        BUFFER_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        INBOUND_BUFFER_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        HOST_TO_DEVICE_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        DEVICE_TO_HOST_TRANSFER_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        COLLECTIVE_E2E_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        HOST_COMPUTE_LATENCY: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        GRPC_TCP_MIN_RTT: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        GRPC_TCP_DELIVERY_RATE: _ClassVar[TpuRuntimeMetrics.DistributionKind]
        HLO_EXEC_TIMING: _ClassVar[TpuRuntimeMetrics.DistributionKind]
    DISTRIBUTION_UNSPECIFIED: TpuRuntimeMetrics.DistributionKind
    BUFFER_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    INBOUND_BUFFER_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    HOST_TO_DEVICE_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    DEVICE_TO_HOST_TRANSFER_LATENCY: TpuRuntimeMetrics.DistributionKind
    COLLECTIVE_E2E_LATENCY: TpuRuntimeMetrics.DistributionKind
    HOST_COMPUTE_LATENCY: TpuRuntimeMetrics.DistributionKind
    GRPC_TCP_MIN_RTT: TpuRuntimeMetrics.DistributionKind
    GRPC_TCP_DELIVERY_RATE: TpuRuntimeMetrics.DistributionKind
    HLO_EXEC_TIMING: TpuRuntimeMetrics.DistributionKind
    class Distribution(_message.Message):
        __slots__ = ("kind", "label", "mean", "p50", "p90", "p95", "p99", "p999", "count", "sum", "bucket_bounds", "bucket_counts")
        KIND_FIELD_NUMBER: _ClassVar[int]
        LABEL_FIELD_NUMBER: _ClassVar[int]
        MEAN_FIELD_NUMBER: _ClassVar[int]
        P50_FIELD_NUMBER: _ClassVar[int]
        P90_FIELD_NUMBER: _ClassVar[int]
        P95_FIELD_NUMBER: _ClassVar[int]
        P99_FIELD_NUMBER: _ClassVar[int]
        P999_FIELD_NUMBER: _ClassVar[int]
        COUNT_FIELD_NUMBER: _ClassVar[int]
        SUM_FIELD_NUMBER: _ClassVar[int]
        BUCKET_BOUNDS_FIELD_NUMBER: _ClassVar[int]
        BUCKET_COUNTS_FIELD_NUMBER: _ClassVar[int]
        kind: TpuRuntimeMetrics.DistributionKind
        label: str
        mean: float
        p50: float
        p90: float
        p95: float
        p99: float
        p999: float
        count: int
        sum: float
        bucket_bounds: _containers.RepeatedScalarFieldContainer[float]
        bucket_counts: _containers.RepeatedScalarFieldContainer[int]
        def __init__(self, kind: _Optional[_Union[TpuRuntimeMetrics.DistributionKind, str]] = ..., label: _Optional[str] = ..., mean: _Optional[float] = ..., p50: _Optional[float] = ..., p90: _Optional[float] = ..., p95: _Optional[float] = ..., p99: _Optional[float] = ..., p999: _Optional[float] = ..., count: _Optional[int] = ..., sum: _Optional[float] = ..., bucket_bounds: _Optional[_Iterable[float]] = ..., bucket_counts: _Optional[_Iterable[int]] = ...) -> None: ...
    class QueueSize(_message.Message):
        __slots__ = ("label", "size")
        LABEL_FIELD_NUMBER: _ClassVar[int]
        SIZE_FIELD_NUMBER: _ClassVar[int]
        label: str
        size: float
        def __init__(self, label: _Optional[str] = ..., size: _Optional[float] = ...) -> None: ...
    DISTRIBUTIONS_FIELD_NUMBER: _ClassVar[int]
    HLO_QUEUE_SIZE_FIELD_NUMBER: _ClassVar[int]
    distributions: _containers.RepeatedCompositeFieldContainer[TpuRuntimeMetrics.Distribution]
    hlo_queue_size: _containers.RepeatedCompositeFieldContainer[TpuRuntimeMetrics.QueueSize]
    def __init__(self, distributions: _Optional[_Iterable[_Union[TpuRuntimeMetrics.Distribution, _Mapping]]] = ..., hlo_queue_size: _Optional[_Iterable[_Union[TpuRuntimeMetrics.QueueSize, _Mapping]]] = ...) -> None: ...

class TrainiumHostMetrics(_message.Message):
    __slots__ = ("host_memory_total_bytes", "device_memory_total_bytes", "host_memory_application_bytes", "host_memory_constants_bytes", "host_memory_dma_buffers_bytes", "host_memory_tensors_bytes")
    HOST_MEMORY_TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    DEVICE_MEMORY_TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_APPLICATION_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_CONSTANTS_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_DMA_BUFFERS_BYTES_FIELD_NUMBER: _ClassVar[int]
    HOST_MEMORY_TENSORS_BYTES_FIELD_NUMBER: _ClassVar[int]
    host_memory_total_bytes: int
    device_memory_total_bytes: int
    host_memory_application_bytes: int
    host_memory_constants_bytes: int
    host_memory_dma_buffers_bytes: int
    host_memory_tensors_bytes: int
    def __init__(self, host_memory_total_bytes: _Optional[int] = ..., device_memory_total_bytes: _Optional[int] = ..., host_memory_application_bytes: _Optional[int] = ..., host_memory_constants_bytes: _Optional[int] = ..., host_memory_dma_buffers_bytes: _Optional[int] = ..., host_memory_tensors_bytes: _Optional[int] = ...) -> None: ...

class GenericMetric(_message.Message):
    __slots__ = ("source", "name", "labels", "kind", "unit", "help", "value", "legacy_series_index")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    HELP_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    LEGACY_SERIES_INDEX_FIELD_NUMBER: _ClassVar[int]
    source: str
    name: str
    labels: _containers.RepeatedCompositeFieldContainer[MetricLabel]
    kind: MetricInfo.Kind
    unit: str
    help: str
    value: float
    legacy_series_index: int
    def __init__(self, source: _Optional[str] = ..., name: _Optional[str] = ..., labels: _Optional[_Iterable[_Union[MetricLabel, _Mapping]]] = ..., kind: _Optional[_Union[MetricInfo.Kind, str]] = ..., unit: _Optional[str] = ..., help: _Optional[str] = ..., value: _Optional[float] = ..., legacy_series_index: _Optional[int] = ...) -> None: ...

class MetricLabel(_message.Message):
    __slots__ = ("key", "value")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: str
    def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

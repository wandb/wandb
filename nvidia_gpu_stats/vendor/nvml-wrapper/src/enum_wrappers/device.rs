use crate::error::NvmlError;
use crate::ffi::bindings::*;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};
use wrapcenum_derive::EnumWrapper;

/// API types that allow changes to default permission restrictions.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlRestrictedAPI_enum")]
pub enum Api {
    /**
    APIs that change application clocks.

    Applicable methods on `Device`: `.set_applications_clocks()`,
    `.reset_applications_clocks()`
    */
    #[wrap(c_variant = "NVML_RESTRICTED_API_SET_APPLICATION_CLOCKS")]
    ApplicationClocks,
    /// APIs that enable/disable auto boosted clocks.
    ///
    /// Applicable methods on `Device`: `.set_auto_boosted_clocks()`
    #[wrap(c_variant = "NVML_RESTRICTED_API_SET_AUTO_BOOSTED_CLOCKS")]
    AutoBoostedClocks,
}

/// Clock types. All speeds are in MHz.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlClockType_enum")]
pub enum Clock {
    /// Graphics clock domain.
    #[wrap(c_variant = "NVML_CLOCK_GRAPHICS")]
    Graphics,
    /// SM (Streaming Multiprocessor) clock domain.
    ///
    /// What AMD calls a CU (Compute Unit) can be compared to this.
    #[wrap(c_variant = "NVML_CLOCK_SM")]
    SM,
    /// Memory clock domain.
    #[wrap(c_variant = "NVML_CLOCK_MEM")]
    Memory,
    /// Video encoder/decoder clock domain.
    #[wrap(c_variant = "NVML_CLOCK_VIDEO")]
    Video,
}

/// These are used in combo with `Clock` to specify a single clock value.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlClockId_enum")]
pub enum ClockId {
    /// Current actual clock value.
    #[wrap(c_variant = "NVML_CLOCK_ID_CURRENT")]
    Current,
    /// Target application clock.
    #[wrap(c_variant = "NVML_CLOCK_ID_APP_CLOCK_TARGET")]
    TargetAppClock,
    /// Default application clock target.
    #[wrap(c_variant = "NVML_CLOCK_ID_APP_CLOCK_DEFAULT")]
    DefaultAppClock,
    /// OEM-defined maximum clock rate.
    #[wrap(c_variant = "NVML_CLOCK_ID_CUSTOMER_BOOST_MAX")]
    CustomerMaxBoost,
}

/// GPU brand.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlBrandType_enum")]
pub enum Brand {
    #[wrap(c_variant = "NVML_BRAND_UNKNOWN")]
    Unknown,
    /// Targeted at workstations.
    #[wrap(c_variant = "NVML_BRAND_QUADRO")]
    Quadro,
    /// Targeted at high-end compute.
    #[wrap(c_variant = "NVML_BRAND_TESLA")]
    Tesla,
    /// NVIDIA's multi-display cards.
    #[wrap(c_variant = "NVML_BRAND_NVS")]
    NVS,
    /// Targeted at virtualization (vGPUs).
    ///
    /// Deprecated from API reporting, still here for backwards compatibility.
    #[wrap(c_variant = "NVML_BRAND_GRID")]
    GRID,
    /// Targeted at gaming.
    #[wrap(c_variant = "NVML_BRAND_GEFORCE")]
    GeForce,
    /// Targeted at... people who don't quite need quadros?
    #[wrap(c_variant = "NVML_BRAND_TITAN")]
    Titan,
    /// Targeted at virtualized apps.
    #[wrap(c_variant = "NVML_BRAND_NVIDIA_VAPPS")]
    VApps,
    /// Targeted at virtualized pcs.
    #[wrap(c_variant = "NVML_BRAND_NVIDIA_VPC")]
    VPC,
    /// Targeted at virtualized servers.
    #[wrap(c_variant = "NVML_BRAND_NVIDIA_VCS")]
    VCS,
    /// Targeted at virtualized work stations.
    #[wrap(c_variant = "NVML_BRAND_NVIDIA_VWS")]
    VWS,
    /// Targeted at cloud gaming servers.
    #[wrap(c_variant = "NVML_BRAND_NVIDIA_CLOUD_GAMING")]
    CloudGaming,
    /// Deprecated from API reporting, still here for backwards compatibility.
    /// Symlinks to [`Brand::CloudGaming`].
    #[wrap(c_variant = "NVML_BRAND_NVIDIA_VGAMING")]
    VGaming,
    /// Targeted at Quadro RTX cards.
    #[wrap(c_variant = "NVML_BRAND_QUADRO_RTX")]
    QuadroRTX,
    /// Targeted at RTX cards.
    #[wrap(c_variant = "NVML_BRAND_NVIDIA_RTX")]
    NvidiaRTX,
    /// Nvidia
    #[wrap(c_variant = "NVML_BRAND_NVIDIA")]
    Nvidia,
    /// Targeted at gaming RTX cards.
    #[wrap(c_variant = "NVML_BRAND_GEFORCE_RTX")]
    GeForceRTX,
    /// Targeted at Titan RTX cards.
    #[wrap(c_variant = "NVML_BRAND_TITAN_RTX")]
    TitanRTX,
}

/**
Represents type of a bridge chip.

NVIDIA does not provide docs (in the code, that is) explaining what each chip
type is, so you're on your own there.
*/
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlBridgeChipType_enum")]
pub enum BridgeChip {
    #[wrap(c_variant = "NVML_BRIDGE_CHIP_PLX")]
    PLX,
    #[wrap(c_variant = "NVML_BRIDGE_CHIP_BRO4")]
    BRO4,
}

/// Memory error types.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlMemoryErrorType_enum")]
pub enum MemoryError {
    /**
    A memory error that was corrected.

    ECC error: single bit error.
    Texture memory: error fixed by a resend.
    */
    #[wrap(c_variant = "NVML_MEMORY_ERROR_TYPE_CORRECTED")]
    Corrected,
    /**
    A memory error that was not corrected.

    ECC error: double bit error.
    Texture memory: error occurred and resend failed.
    */
    #[wrap(c_variant = "NVML_MEMORY_ERROR_TYPE_UNCORRECTED")]
    Uncorrected,
}

/**
ECC counter types.

Note: Volatile counts are reset each time the driver loads. On Windows this is
once per boot. On Linux this can be more frequent; the driver unloads when no
active clients exist. If persistence mode is enabled or there is always a
driver client active (such as X11), then Linux also sees per-boot behavior.
If not, volatile counts are reset each time a compute app is run.
*/
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlEccCounterType_enum")]
pub enum EccCounter {
    /// Volatile counts are reset each time the driver loads.
    #[wrap(c_variant = "NVML_VOLATILE_ECC")]
    Volatile,
    /// Aggregate counts persist across reboots (i.e. for the lifetime of the
    /// device).
    #[wrap(c_variant = "NVML_AGGREGATE_ECC")]
    Aggregate,
}

/// Memory locations. See `Device.memory_error_counter()`.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlMemoryLocation_enum")]
pub enum MemoryLocation {
    /// GPU L1 cache.
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_L1_CACHE")]
    L1Cache,
    /// GPU L2 cache.
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_L2_CACHE")]
    L2Cache,
    /// GPU device memory.
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_DEVICE_MEMORY")]
    Device,
    /// GPU register file.
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_REGISTER_FILE")]
    RegisterFile,
    /// GPU texture memory.
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_TEXTURE_MEMORY")]
    Texture,
    /// Shared memory.
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_TEXTURE_SHM")]
    Shared,
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_CBU")]
    Cbu,
    /// SRAM present on Turing and above.
    #[wrap(c_variant = "NVML_MEMORY_LOCATION_SRAM")]
    SRAM,
}

/// Driver models, Windows only.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlDriverModel_enum")]
#[cfg(target_os = "windows")]
pub enum DriverModel {
    /// GPU treated as a display device.
    #[wrap(c_variant = "NVML_DRIVER_WDDM")]
    WDDM,
    /// (TCC model) GPU treated as a generic device (recommended).
    #[wrap(c_variant = "NVML_DRIVER_WDM")]
    WDM,
}

/**
GPU operation mode.

Allows for the reduction of power usage and optimization of GPU throughput
by disabling GPU features. Each mode is designed to meet specific needs.
*/
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlGom_enum")]
pub enum OperationMode {
    /// Everything is enabled and running at full speed.
    #[wrap(c_variant = "NVML_GOM_ALL_ON")]
    AllOn,
    /// Designed for running only compute tasks; disables graphics operations.
    #[wrap(c_variant = "NVML_GOM_COMPUTE")]
    Compute,
    /// Designed for running graphics applications that don't require high
    /// bandwidth double precision.
    #[wrap(c_variant = "NVML_GOM_LOW_DP")]
    LowDP,
}

/// Available infoROM objects.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlInforomObject_enum")]
pub enum InfoRom {
    /// An object defined by OEM.
    #[wrap(c_variant = "NVML_INFOROM_OEM")]
    OEM,
    /// The ECC object determining the level of ECC support.
    #[wrap(c_variant = "NVML_INFOROM_ECC")]
    ECC,
    /// The power management object.
    #[wrap(c_variant = "NVML_INFOROM_POWER")]
    Power,
}

/// Represents the queryable PCIe utilization counters (in bytes). 1KB
/// granularity.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlPcieUtilCounter_enum")]
pub enum PcieUtilCounter {
    #[wrap(c_variant = "NVML_PCIE_UTIL_TX_BYTES")]
    Send,
    #[wrap(c_variant = "NVML_PCIE_UTIL_RX_BYTES")]
    Receive,
}

/**
Allowed performance states.

```text
Value    Performance
  0       (highest)
 ...
 15       (lowest)
```
*/
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlPStates_enum")]
pub enum PerformanceState {
    /// Maximum performance.
    #[wrap(c_variant = "NVML_PSTATE_0")]
    Zero,
    #[wrap(c_variant = "NVML_PSTATE_1")]
    One,
    #[wrap(c_variant = "NVML_PSTATE_2")]
    Two,
    #[wrap(c_variant = "NVML_PSTATE_3")]
    Three,
    #[wrap(c_variant = "NVML_PSTATE_4")]
    Four,
    #[wrap(c_variant = "NVML_PSTATE_5")]
    Five,
    #[wrap(c_variant = "NVML_PSTATE_6")]
    Six,
    #[wrap(c_variant = "NVML_PSTATE_7")]
    Seven,
    #[wrap(c_variant = "NVML_PSTATE_8")]
    Eight,
    #[wrap(c_variant = "NVML_PSTATE_9")]
    Nine,
    #[wrap(c_variant = "NVML_PSTATE_10")]
    Ten,
    #[wrap(c_variant = "NVML_PSTATE_11")]
    Eleven,
    #[wrap(c_variant = "NVML_PSTATE_12")]
    Twelve,
    #[wrap(c_variant = "NVML_PSTATE_13")]
    Thirteen,
    #[wrap(c_variant = "NVML_PSTATE_14")]
    Fourteen,
    /// Minimum peformance.
    #[wrap(c_variant = "NVML_PSTATE_15")]
    Fifteen,
    /// Unknown performance state.
    #[wrap(c_variant = "NVML_PSTATE_UNKNOWN")]
    Unknown,
}

/// Causes for page retirement.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlPageRetirementCause_enum")]
pub enum RetirementCause {
    /// Page was retired due to multiple single bit ECC errors.
    #[wrap(c_variant = "NVML_PAGE_RETIREMENT_CAUSE_MULTIPLE_SINGLE_BIT_ECC_ERRORS")]
    MultipleSingleBitEccErrors,
    /// Page was retired due to a single double bit ECC error.
    #[wrap(c_variant = "NVML_PAGE_RETIREMENT_CAUSE_DOUBLE_BIT_ECC_ERROR")]
    DoubleBitEccError,
}

/// Possible types of sampling events.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlSamplingType_enum")]
pub enum Sampling {
    /// Total power drawn by GPU.
    #[wrap(c_variant = "NVML_TOTAL_POWER_SAMPLES")]
    Power,
    /// Percent of time during which one or more kernels was executing on the
    /// GPU.
    #[wrap(c_variant = "NVML_GPU_UTILIZATION_SAMPLES")]
    GpuUtilization,
    /// Percent of time during which global (device) memory was being read or
    /// written.
    #[wrap(c_variant = "NVML_MEMORY_UTILIZATION_SAMPLES")]
    MemoryUtilization,
    /// Percent of time during which NVENC remains busy.
    #[wrap(c_variant = "NVML_ENC_UTILIZATION_SAMPLES")]
    EncoderUtilization,
    /// Percent of time during which NVDEC remains busy.
    #[wrap(c_variant = "NVML_DEC_UTILIZATION_SAMPLES")]
    DecoderUtilization,
    /// Processor clock samples.
    #[wrap(c_variant = "NVML_PROCESSOR_CLK_SAMPLES")]
    ProcessorClock,
    /// Memory clock samples.
    #[wrap(c_variant = "NVML_MEMORY_CLK_SAMPLES")]
    MemoryClock,
}

// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlTemperatureSensors_enum")]
pub enum TemperatureSensor {
    /// Sensor for the GPU die.
    #[wrap(c_variant = "NVML_TEMPERATURE_GPU")]
    Gpu,
}

// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlTemperatureThresholds_enum")]
pub enum TemperatureThreshold {
    /// Temperature at which the GPU will shut down for hardware protection.
    #[wrap(c_variant = "NVML_TEMPERATURE_THRESHOLD_SHUTDOWN")]
    Shutdown,
    /// Temperature at which the GPU will begin hardware throttling.
    #[wrap(c_variant = "NVML_TEMPERATURE_THRESHOLD_SLOWDOWN")]
    Slowdown,
    /// Memory temperature at which the GPU will begin software slowdown.
    #[wrap(c_variant = "NVML_TEMPERATURE_THRESHOLD_MEM_MAX")]
    MemoryMax,
    /// GPU temperature at which the GPU can be throttled below the base clock.
    #[wrap(c_variant = "NVML_TEMPERATURE_THRESHOLD_GPU_MAX")]
    GpuMax,
}

/// Level relationships within a system between two GPUs.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlGpuLevel_enum")]
pub enum TopologyLevel {
    /// e.g. Tesla K80.
    #[wrap(c_variant = "NVML_TOPOLOGY_INTERNAL")]
    Internal,
    /// All devices that only need traverse a single PCIe switch.
    #[wrap(c_variant = "NVML_TOPOLOGY_SINGLE")]
    Single,
    /// All devices that need not traverse a host bridge.
    #[wrap(c_variant = "NVML_TOPOLOGY_MULTIPLE")]
    Multiple,
    /// All devices that are connected to the same host bridge.
    #[wrap(c_variant = "NVML_TOPOLOGY_HOSTBRIDGE")]
    HostBridge,
    /**
    All devices that are connected to the same NUMA node but possibly
    multiple host bridges.

    This was `Cpu` in previous versions of NVML.
    */
    #[wrap(c_variant = "NVML_TOPOLOGY_NODE")]
    Node,
    /// All devices in the system
    #[wrap(c_variant = "NVML_TOPOLOGY_SYSTEM")]
    System,
}

/// Types of performance policy for which violation times can be queried.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlPerfPolicyType_enum")]
pub enum PerformancePolicy {
    #[wrap(c_variant = "NVML_PERF_POLICY_POWER")]
    Power,
    #[wrap(c_variant = "NVML_PERF_POLICY_THERMAL")]
    Thermal,
    #[wrap(c_variant = "NVML_PERF_POLICY_SYNC_BOOST")]
    SyncBoost,
    #[wrap(c_variant = "NVML_PERF_POLICY_BOARD_LIMIT")]
    BoardLimit,
    #[wrap(c_variant = "NVML_PERF_POLICY_LOW_UTILIZATION")]
    LowUtilization,
    /// Board reliability limit.
    #[wrap(c_variant = "NVML_PERF_POLICY_RELIABILITY")]
    Reliability,

    /// Total time the GPU was limited by any of the above.
    #[wrap(c_variant = "NVML_PERF_POLICY_TOTAL_APP_CLOCKS")]
    TotalAppClocks,
    /// Total time the GPU was held below base clocks.
    #[wrap(c_variant = "NVML_PERF_POLICY_TOTAL_BASE_CLOCKS")]
    TotalBaseClocks,
}

/// `ExclusiveProcess` was added in CUDA 4.0. Earlier CUDA versions supported a
/// single exclusive mode, which is equivalent to `ExclusiveThread` in CUDA 4.0
/// and beyond.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlComputeMode_enum")]
pub enum ComputeMode {
    /// Multiple contexts per device.
    #[wrap(c_variant = "NVML_COMPUTEMODE_DEFAULT")]
    Default,
    /// *SUPPORT REMOVED*
    ///
    /// Only one context per device, usable from one thread at a time. *NOT
    /// SUPPORTED*
    #[wrap(c_variant = "NVML_COMPUTEMODE_EXCLUSIVE_THREAD")]
    ExclusiveThread,
    /// No contexts per device.
    #[wrap(c_variant = "NVML_COMPUTEMODE_PROHIBITED")]
    Prohibited,
    /// Only one context per device, usable from multiple threads at a time.
    #[wrap(c_variant = "NVML_COMPUTEMODE_EXCLUSIVE_PROCESS")]
    ExclusiveProcess,
}

/// P2P capability index status.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlGpuP2PStatus_enum")]
pub enum P2pStatus {
    #[wrap(c_variant = "NVML_P2P_STATUS_OK")]
    Ok,
    #[wrap(c_variant = "NVML_P2P_STATUS_CHIPSET_NOT_SUPPORED")]
    ChipsetNotSupported,
    #[wrap(c_variant = "NVML_P2P_STATUS_GPU_NOT_SUPPORTED")]
    GpuNotSupported,
    #[wrap(c_variant = "NVML_P2P_STATUS_IOH_TOPOLOGY_NOT_SUPPORTED")]
    IohTopologyNotSupported,
    #[wrap(c_variant = "NVML_P2P_STATUS_DISABLED_BY_REGKEY")]
    DisabledByRegkey,
    #[wrap(c_variant = "NVML_P2P_STATUS_NOT_SUPPORTED")]
    NotSupported,
    #[wrap(c_variant = "NVML_P2P_STATUS_UNKNOWN")]
    Unknown,
}

// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlGpuP2PCapsIndex_enum")]
pub enum P2pCapabilitiesIndex {
    #[wrap(c_variant = "NVML_P2P_CAPS_INDEX_READ")]
    Read,
    #[wrap(c_variant = "NVML_P2P_CAPS_INDEX_WRITE")]
    Write,
    #[wrap(c_variant = "NVML_P2P_CAPS_INDEX_NVLINK")]
    NvLink,
    #[wrap(c_variant = "NVML_P2P_CAPS_INDEX_ATOMICS")]
    Atomics,
    #[wrap(c_variant = "NVML_P2P_CAPS_INDEX_PROP")]
    Prop,
    #[wrap(c_variant = "NVML_P2P_CAPS_INDEX_UNKNOWN")]
    Unknown,
}

/// Represents types for returned sample values.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlValueType_enum")]
pub enum SampleValueType {
    #[wrap(c_variant = "NVML_VALUE_TYPE_DOUBLE")]
    Double,
    #[wrap(c_variant = "NVML_VALUE_TYPE_UNSIGNED_INT")]
    UnsignedInt,
    #[wrap(c_variant = "NVML_VALUE_TYPE_UNSIGNED_LONG")]
    UnsignedLong,
    #[wrap(c_variant = "NVML_VALUE_TYPE_UNSIGNED_LONG_LONG")]
    UnsignedLongLong,
    #[wrap(c_variant = "NVML_VALUE_TYPE_SIGNED_LONG_LONG")]
    SignedLongLong,
}

/// Represents encoder types that capacity can be queried for.
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlEncoderQueryType_enum")]
pub enum EncoderType {
    #[wrap(c_variant = "NVML_ENCODER_QUERY_H264")]
    H264,
    #[wrap(c_variant = "NVML_ENCODER_QUERY_HEVC")]
    HEVC,
}

/// The type of a frame buffer capture session
///
/// NVIDIA doesn't document the variants beyond their names.
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlFBCSessionType_enum")]
pub enum FbcSessionType {
    #[wrap(c_variant = "NVML_FBC_SESSION_TYPE_UNKNOWN")]
    Unknown,
    #[wrap(c_variant = "NVML_FBC_SESSION_TYPE_TOSYS")]
    ToSys,
    #[wrap(c_variant = "NVML_FBC_SESSION_TYPE_CUDA")]
    Cuda,
    #[wrap(c_variant = "NVML_FBC_SESSION_TYPE_VID")]
    Vid,
    #[wrap(c_variant = "NVML_FBC_SESSION_TYPE_HWENC")]
    HwEnc,
}

/// Options to pass to [`crate::Device::remove()`].
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlDetachGpuState_enum")]
pub enum DetachGpuState {
    #[wrap(c_variant = "NVML_DETACH_GPU_KEEP")]
    Keep,
    #[wrap(c_variant = "NVML_DETACH_GPU_REMOVE")]
    Remove,
}

/// Options to pass to [`crate::Device::remove()`].
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlPcieLinkState_enum")]
pub enum PcieLinkState {
    #[wrap(c_variant = "NVML_PCIE_LINK_KEEP")]
    Keep,
    #[wrap(c_variant = "NVML_PCIE_LINK_SHUT_DOWN")]
    ShutDown,
}

/// Clock limit IDs for use with [`crate::Device::set_gpu_locked_clocks()`].
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlClockLimitId_enum")]
pub enum ClockLimitId {
    /// Bound clock speed by the TDP of the device.
    #[wrap(c_variant = "NVML_CLOCK_LIMIT_ID_TDP")]
    Tdp,
    /// No bound for clock speed.
    #[wrap(c_variant = "NVML_CLOCK_LIMIT_ID_UNLIMITED")]
    Unlimited,
}

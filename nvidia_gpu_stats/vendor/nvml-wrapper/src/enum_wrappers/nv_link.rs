use crate::error::NvmlError;
use crate::ffi::bindings::*;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};
use wrapcenum_derive::EnumWrapper;

/// Represents the NvLink utilization counter packet units.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlNvLinkUtilizationCountUnits_enum")]
pub enum UtilizationCountUnit {
    #[wrap(c_variant = "NVML_NVLINK_COUNTER_UNIT_CYCLES")]
    Cycles,
    #[wrap(c_variant = "NVML_NVLINK_COUNTER_UNIT_PACKETS")]
    Packets,
    #[wrap(c_variant = "NVML_NVLINK_COUNTER_UNIT_BYTES")]
    Bytes,
}

/// Represents queryable NvLink capabilities.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlNvLinkCapability_enum")]
pub enum Capability {
    /// P2P over NVLink is supported.
    #[wrap(c_variant = "NVML_NVLINK_CAP_P2P_SUPPORTED")]
    P2p,
    /// Access to system memory is supported.
    #[wrap(c_variant = "NVML_NVLINK_CAP_SYSMEM_ACCESS")]
    SysMemAccess,
    /// P2P atomics are supported.
    #[wrap(c_variant = "NVML_NVLINK_CAP_P2P_ATOMICS")]
    P2pAtomics,
    /// System memory atomics are supported.
    #[wrap(c_variant = "NVML_NVLINK_CAP_SYSMEM_ATOMICS")]
    SysMemAtomics,
    /// SLI is supported over this link.
    #[wrap(c_variant = "NVML_NVLINK_CAP_SLI_BRIDGE")]
    SliBridge,
    /// Link is supported on this device.
    #[wrap(c_variant = "NVML_NVLINK_CAP_VALID")]
    ValidLink,
}

/// Represents queryable NvLink error counters.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlNvLinkErrorCounter_enum")]
pub enum ErrorCounter {
    /// Data link transmit replay error counter.
    #[wrap(c_variant = "NVML_NVLINK_ERROR_DL_REPLAY")]
    DlReplay,
    /// Data link transmit recovery error counter.
    #[wrap(c_variant = "NVML_NVLINK_ERROR_DL_RECOVERY")]
    DlRecovery,
    /// Data link receive flow control digit CRC error counter.
    #[wrap(c_variant = "NVML_NVLINK_ERROR_DL_CRC_FLIT")]
    DlCrcFlit,
    /// Data link receive data CRC error counter.
    #[wrap(c_variant = "NVML_NVLINK_ERROR_DL_CRC_DATA")]
    DlCrcData,
}

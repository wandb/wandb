use crate::ffi::bindings::*;
use bitflags::bitflags;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};

bitflags! {
    /**
    Represents the NvLink utilization counter packet types that can be counted.

    Only applicable when `UtilizationCountUnit`s are packets or bytes. All
    packet filter descriptions are target GPU centric.
    */
    // Checked against local
    #[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
    #[derive(Debug, Copy, Clone, Eq, PartialEq, Hash)]
    pub struct PacketTypes: u32 {
        const NO_OP      = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_NOP;
        const READ       = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_READ;
        const WRITE      = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_WRITE;
        /// Reduction atomic requests.
        const RATOM      = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_RATOM;
        /// Non-reduction atomic requests.
        const NON_RATOM  = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_NRATOM;
        /// Flush requests.
        const FLUSH      = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_FLUSH;
        /// Responses with data.
        const WITH_DATA  = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_RESPDATA;
        /// Responses without data.
        const NO_DATA    = nvmlNvLinkUtilizationCountPktTypes_enum_NVML_NVLINK_COUNTER_PKTFILTER_RESPNODATA;
    }
}

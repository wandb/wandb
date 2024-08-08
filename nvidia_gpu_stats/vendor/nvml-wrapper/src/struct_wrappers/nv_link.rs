use crate::bitmasks::nv_link::PacketTypes;
use crate::enum_wrappers::nv_link::UtilizationCountUnit;
use crate::error::NvmlError;
use crate::ffi::bindings::*;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};
use std::convert::TryFrom;

/// Defines NvLink counter controls.
// TODO: Write a test going to / from C repr
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct UtilizationControl {
    pub units: UtilizationCountUnit,
    pub packet_filter: PacketTypes,
}

impl UtilizationControl {
    /// Obtain this struct's C counterpart.
    pub fn as_c(&self) -> nvmlNvLinkUtilizationControl_t {
        nvmlNvLinkUtilizationControl_t {
            units: self.units.as_c(),
            pktfilter: self.packet_filter.bits(),
        }
    }
}

impl TryFrom<nvmlNvLinkUtilizationControl_t> for UtilizationControl {
    type Error = NvmlError;

    /**
    Construct `UtilizationControl` from the corresponding C struct.

    The `packet_filter` bitmask is created via the `PacketTypes::from_bits_truncate`
    method, meaning that any bits that don't correspond to flags present in this
    version of the wrapper will be dropped.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    */
    fn try_from(value: nvmlNvLinkUtilizationControl_t) -> Result<Self, Self::Error> {
        let bits = value.pktfilter;

        Ok(UtilizationControl {
            units: UtilizationCountUnit::try_from(value.units)?,
            packet_filter: PacketTypes::from_bits_truncate(bits),
        })
    }
}

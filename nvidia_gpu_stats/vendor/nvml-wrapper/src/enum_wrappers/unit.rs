use crate::error::NvmlError;
use crate::ffi::bindings::*;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};
use wrapcenum_derive::EnumWrapper;

/// Unit fan state.
// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlFanState_enum")]
pub enum FanState {
    /// Working properly
    #[wrap(c_variant = "NVML_FAN_NORMAL")]
    Normal,
    #[wrap(c_variant = "NVML_FAN_FAILED")]
    Failed,
}

// Checked against local
#[derive(EnumWrapper, Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[wrap(c_enum = "nvmlLedColor_enum")]
pub enum LedColor {
    /// Used to indicate good health.
    #[wrap(c_variant = "NVML_LED_COLOR_GREEN")]
    Green,
    /// Used to indicate a problem.
    #[wrap(c_variant = "NVML_LED_COLOR_AMBER")]
    Amber,
}

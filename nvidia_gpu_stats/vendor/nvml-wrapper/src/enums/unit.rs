use crate::error::NvmlError;
use crate::ffi::bindings::*;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};
use std::{convert::TryFrom, ffi::CStr};

/// LED states for an S-class unit.
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub enum LedState {
    /// Indicates good health.
    Green,
    /// Indicates a problem along with the accompanying cause.
    Amber(String),
}

impl TryFrom<nvmlLedState_t> for LedState {
    type Error = NvmlError;

    /**
    Construct `LedState` from the corresponding C struct.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    */
    fn try_from(value: nvmlLedState_t) -> Result<Self, Self::Error> {
        let color = value.color;

        match color {
            nvmlLedColor_enum_NVML_LED_COLOR_GREEN => Ok(LedState::Green),
            nvmlLedColor_enum_NVML_LED_COLOR_AMBER => unsafe {
                let cause_raw = CStr::from_ptr(value.cause.as_ptr());
                Ok(LedState::Amber(cause_raw.to_str()?.into()))
            },
            _ => Err(NvmlError::UnexpectedVariant(color)),
        }
    }
}

/// The type of temperature reading to take for a `Unit`.
///
/// Available readings depend on the product.
#[repr(u32)]
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub enum TemperatureReading {
    Intake = 0,
    Exhaust = 1,
    Board = 2,
}

use crate::enum_wrappers::unit::FanState;
use crate::error::NvmlError;
use crate::ffi::bindings::*;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};
use std::{convert::TryFrom, ffi::CStr};

/// Fan information readings for an entire S-class unit.
// Checked against local
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct FansInfo {
    /// Number of fans in the unit.
    pub count: u32,
    /// Fan data for each fan.
    pub fans: Vec<FanInfo>,
}

impl TryFrom<nvmlUnitFanSpeeds_t> for FansInfo {
    type Error = NvmlError;

    /**
    Construct `FansInfo` from the corresponding C struct.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    */
    fn try_from(value: nvmlUnitFanSpeeds_t) -> Result<Self, Self::Error> {
        let fans = value
            .fans
            .iter()
            .map(|f| FanInfo::try_from(*f))
            .collect::<Result<_, NvmlError>>()?;

        Ok(FansInfo {
            count: value.count,
            fans,
        })
    }
}

/// Fan info reading for a single fan in an S-class unit.
// Checked against local
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct FanInfo {
    /// Fan speed (RPM).
    pub speed: u32,
    /// Indicates whether a fan is working properly.
    pub state: FanState,
}

impl TryFrom<nvmlUnitFanInfo_t> for FanInfo {
    type Error = NvmlError;

    /**
    Construct `FanInfo` from the corresponding C struct.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    */
    fn try_from(value: nvmlUnitFanInfo_t) -> Result<Self, Self::Error> {
        Ok(FanInfo {
            speed: value.speed,
            state: FanState::try_from(value.state)?,
        })
    }
}

/**
Power usage information for an S-class unit.

The power supply state is a human-readable string that equals "Normal" or contains
a combination of "Abnormal" plus one or more of the following (aka good luck matching
on it):

* High voltage
* Fan failure
* Heatsink temperature
* Current limit
* Voltage below UV alarm threshold
* Low-voltage
* SI2C remote off command
* MOD_DISABLE input
* Short pin transition
*/
// Checked against local
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct PsuInfo {
    /// PSU current (in A)
    pub current: u32,
    /// PSU power draw (in W)
    pub power_draw: u32,
    /// Human-readable string describing the PSU state.
    pub state: String,
    /// PSU voltage (in V)
    pub voltage: u32,
}

impl TryFrom<nvmlPSUInfo_t> for PsuInfo {
    type Error = NvmlError;

    /**
    Construct `PsuInfo` from the corresponding C struct.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    */
    fn try_from(value: nvmlPSUInfo_t) -> Result<Self, Self::Error> {
        unsafe {
            let state_raw = CStr::from_ptr(value.state.as_ptr());
            Ok(PsuInfo {
                current: value.current,
                power_draw: value.power,
                state: state_raw.to_str()?.into(),
                voltage: value.voltage,
            })
        }
    }
}

/// Static S-class unit info.
// Checked against local
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct UnitInfo {
    pub firmware_version: String,
    /// Product identifier.
    pub id: String,
    pub name: String,
    /// Product serial number.
    pub serial: String,
}

impl TryFrom<nvmlUnitInfo_t> for UnitInfo {
    type Error = NvmlError;

    /**
    Construct `UnitInfo` from the corresponding C struct.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    */
    fn try_from(value: nvmlUnitInfo_t) -> Result<Self, Self::Error> {
        unsafe {
            let version_raw = CStr::from_ptr(value.firmwareVersion.as_ptr());
            let id_raw = CStr::from_ptr(value.id.as_ptr());
            let name_raw = CStr::from_ptr(value.name.as_ptr());
            let serial_raw = CStr::from_ptr(value.serial.as_ptr());

            Ok(UnitInfo {
                firmware_version: version_raw.to_str()?.into(),
                id: id_raw.to_str()?.into(),
                name: name_raw.to_str()?.into(),
                serial: serial_raw.to_str()?.into(),
            })
        }
    }
}

/// Description of an HWBC entry.
// Checked against local
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct HwbcEntry {
    pub id: u32,
    pub firmware_version: String,
}

impl TryFrom<nvmlHwbcEntry_t> for HwbcEntry {
    type Error = NvmlError;

    /**
    Construct `HwbcEntry` from the corresponding C struct.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    */
    fn try_from(value: nvmlHwbcEntry_t) -> Result<Self, Self::Error> {
        unsafe {
            let version_raw = CStr::from_ptr(value.firmwareVersion.as_ptr());
            Ok(HwbcEntry {
                id: value.hwbcId,
                firmware_version: version_raw.to_str()?.into(),
            })
        }
    }
}

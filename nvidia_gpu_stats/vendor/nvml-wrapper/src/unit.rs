use crate::device::Device;
use crate::enum_wrappers::unit::LedColor;
use crate::enums::unit::{LedState, TemperatureReading};
use crate::error::{nvml_sym, nvml_try, NvmlError};
use crate::ffi::bindings::*;
use crate::struct_wrappers::unit::{FansInfo, PsuInfo, UnitInfo};
use crate::Nvml;
use static_assertions::assert_impl_all;
use std::mem;
use std::{convert::TryFrom, os::raw::c_uint};

/**
Struct that represents a unit.

Obtain a `Unit` with the various methods available to you on the `Nvml`
struct.

Lifetimes are used to enforce that each `Unit` instance cannot be used after
the `Nvml` instance it was obtained from is dropped:

```compile_fail
use nvml_wrapper::Nvml;
# use nvml_wrapper::error::*;

# fn main() -> Result<(), NvmlError> {
let nvml = Nvml::init()?;
let unit = nvml.unit_by_index(0)?;

drop(nvml);

// This won't compile
let unit_devices = unit.devices()?;
# Ok(())
# }
```

Note that I cannot test any `Unit` methods myself as I do not have access to
such hardware. **Test the functionality in this module before you use it**.
*/
#[derive(Debug)]
pub struct Unit<'nvml> {
    unit: nvmlUnit_t,
    nvml: &'nvml Nvml,
}

unsafe impl<'nvml> Send for Unit<'nvml> {}
unsafe impl<'nvml> Sync for Unit<'nvml> {}

assert_impl_all!(Unit: Send, Sync);

impl<'nvml> Unit<'nvml> {
    /**
    Create a new `Unit` wrapper.

    You will most likely never need to call this; see the methods available to you
    on the `Nvml` struct to get one.

    # Safety

    It is your responsibility to ensure that the given `nvmlUnit_t` pointer
    is valid.
    */
    // Clippy bug, see https://github.com/rust-lang/rust-clippy/issues/5593
    #[allow(clippy::missing_safety_doc)]
    pub unsafe fn new(unit: nvmlUnit_t, nvml: &'nvml Nvml) -> Self {
        Self { unit, nvml }
    }

    /// Access the `NVML` reference this struct wraps
    pub fn nvml(&self) -> &'nvml Nvml {
        self.nvml
    }

    /// Get the raw unit handle contained in this struct
    ///
    /// Sometimes necessary for C interop.
    ///
    /// # Safety
    ///
    /// This is unsafe to prevent it from being used without care.
    pub unsafe fn handle(&self) -> nvmlUnit_t {
        self.unit
    }

    /**
    Gets the set of GPU devices that are attached to this `Unit`.

    **I do not have the hardware to test this call. Verify for yourself that it
    works before you use it**. If it works, please let me know; if it doesn't,
    I would love a PR. If NVML is sane this should work, but NVIDIA's docs
    on this call are _anything_ but clear.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlUnitGetDevices")]
    pub fn devices(&self) -> Result<Vec<Device>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitGetDevices.as_ref())?;

        unsafe {
            let mut count: c_uint = match self.device_count()? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut devices: Vec<nvmlDevice_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.unit, &mut count, devices.as_mut_ptr()))?;

            Ok(devices
                .into_iter()
                .map(|d| Device::new(d, self.nvml))
                .collect())
        }
    }

    /**
    Gets the count of GPU devices that are attached to this `Unit`.

    **I do not have the hardware to test this call. Verify for yourself that it
    works before you use it**. If it works, please let me know; if it doesn't,
    I would love a PR. If NVML is sane this should work, but NVIDIA's docs
    on this call are _anything_ but clear.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products.
    */
    // Tested as part of the above
    #[doc(alias = "nvmlUnitGetDevices")]
    pub fn device_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitGetDevices.as_ref())?;

        unsafe {
            /*
            NVIDIA doesn't even say that `count` will be set to the count if
            `InsufficientSize` is returned. But we can assume sanity, right?

            The idea here is:
            If there are 0 devices, NVML_SUCCESS is returned, `count` is set
              to 0. We return count, all good.
            If there is 1 device, NVML_SUCCESS is returned, `count` is set to
              1. We return count, all good.
            If there are >= 2 devices, NVML_INSUFFICIENT_SIZE is returned.
             `count` is theoretically set to the actual count, and we
              return it.
            */
            let mut count: c_uint = 1;
            let mut devices: [nvmlDevice_t; 1] = [mem::zeroed()];

            match sym(self.unit, &mut count, devices.as_mut_ptr()) {
                nvmlReturn_enum_NVML_SUCCESS | nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => {
                    Ok(count)
                }
                // We know that this will be an error
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets fan information for this `Unit` (fan count and state + speed for each).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `NotSupported`, if this is not an S-class product
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlUnitGetFanSpeedInfo")]
    pub fn fan_info(&self) -> Result<FansInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitGetFanSpeedInfo.as_ref())?;

        unsafe {
            let mut fans_info: nvmlUnitFanSpeeds_t = mem::zeroed();
            nvml_try(sym(self.unit, &mut fans_info))?;

            FansInfo::try_from(fans_info)
        }
    }

    /**
    Gets the LED state associated with this `Unit`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `NotSupported`, if this is not an S-class product
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlUnitGetLedState")]
    pub fn led_state(&self) -> Result<LedState, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitGetLedState.as_ref())?;

        unsafe {
            let mut state: nvmlLedState_t = mem::zeroed();
            nvml_try(sym(self.unit, &mut state))?;

            LedState::try_from(state)
        }
    }

    /**
    Gets the PSU stats for this `Unit`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `NotSupported`, if this is not an S-class product
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlUnitGetPsuInfo")]
    pub fn psu_info(&self) -> Result<PsuInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitGetPsuInfo.as_ref())?;
        unsafe {
            let mut info: nvmlPSUInfo_t = mem::zeroed();
            nvml_try(sym(self.unit, &mut info))?;

            PsuInfo::try_from(info)
        }
    }

    /**
    Gets the temperature for the specified `UnitTemperatureReading`, in °C.

    Available readings depend on the product.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `NotSupported`, if this is not an S-class product
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products. Available readings depend on the product.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlUnitGetTemperature")]
    pub fn temperature(&self, reading_type: TemperatureReading) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitGetTemperature.as_ref())?;

        unsafe {
            let mut temp: c_uint = mem::zeroed();

            nvml_try(sym(self.unit, reading_type as c_uint, &mut temp))?;

            Ok(temp)
        }
    }

    /**
    Gets the static information associated with this `Unit`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8

    # Device Support

    For S-class products.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlUnitGetUnitInfo")]
    pub fn info(&self) -> Result<UnitInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitGetUnitInfo.as_ref())?;

        unsafe {
            let mut info: nvmlUnitInfo_t = mem::zeroed();
            nvml_try(sym(self.unit, &mut info))?;

            UnitInfo::try_from(info)
        }
    }

    // Unit commands starting here

    /**
    Sets the LED color for this `Unit`.

    Requires root/admin permissions. This operation takes effect immediately.

    Note: Current S-class products don't provide unique LEDs for each unit. As such,
    both front and back LEDs will be toggled in unison regardless of which unit is
    specified with this method (aka the `Unit` represented by this struct).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the unit is invalid
    * `NotSupported`, if this is not an S-class product
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products.
    */
    // checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlUnitSetLedState")]
    pub fn set_led_color(&mut self, color: LedColor) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlUnitSetLedState.as_ref())?;

        unsafe { nvml_try(sym(self.unit, color.as_c())) }
    }
}

// I do not have access to this hardware and cannot test anything
#[cfg(test)]
#[deny(unused_mut)]
mod test {
    use crate::enum_wrappers::unit::LedColor;
    use crate::enums::unit::TemperatureReading;
    use crate::test_utils::*;

    #[test]
    #[ignore = "my machine does not support this call"]
    fn devices() {
        let nvml = nvml();
        let unit = unit(&nvml);
        unit.devices().expect("devices");
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn fan_info() {
        let nvml = nvml();
        test_with_unit(3, &nvml, |unit| unit.fan_info())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn led_state() {
        let nvml = nvml();
        test_with_unit(3, &nvml, |unit| unit.led_state())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn psu_info() {
        let nvml = nvml();
        test_with_unit(3, &nvml, |unit| unit.psu_info())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn temperature() {
        let nvml = nvml();
        test_with_unit(3, &nvml, |unit| unit.temperature(TemperatureReading::Board))
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn info() {
        let nvml = nvml();
        test_with_unit(3, &nvml, |unit| unit.info())
    }

    // This modifies unit state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_led_color() {
        let nvml = nvml();
        let mut unit = unit(&nvml);

        unit.set_led_color(LedColor::Amber).expect("set to true")
    }
}

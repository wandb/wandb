use crate::Device;

use crate::enum_wrappers::{
    bool_from_state,
    nv_link::{Capability, ErrorCounter},
    state_from_bool,
};

use crate::enums::nv_link::Counter;
use crate::error::{nvml_sym, nvml_try, NvmlError};
use crate::ffi::bindings::*;
use crate::struct_wrappers::{device::PciInfo, nv_link::UtilizationControl};
use crate::structs::nv_link::UtilizationCounter;

use std::{
    convert::TryFrom,
    mem,
    os::raw::{c_uint, c_ulonglong},
};

use static_assertions::assert_impl_all;

/**
Struct that represents a `Device`'s NvLink.

Obtain this via `Device.link_wrapper_for()`.

Lifetimes are used to enforce that each `NvLink` instance cannot be used after
the `Device` instance it was obtained from is dropped:

```compile_fail
use nvml_wrapper::Nvml;
# use nvml_wrapper::error::*;

# fn main() -> Result<(), NvmlError> {
let nvml = Nvml::init()?;
let device = nvml.device_by_index(0)?;
let link = device.link_wrapper_for(0);

drop(device);

// This won't compile
link.is_active()?;
# Ok(())
# }
```

Note that I cannot test any `NvLink` methods myself as I do not have access to
such a link setup. **Test the functionality in this module before you use it**.
*/
#[derive(Debug)]
pub struct NvLink<'device, 'nvml: 'device> {
    pub(crate) device: &'device Device<'nvml>,
    pub(crate) link: c_uint,
}

assert_impl_all!(NvLink: Send, Sync);

impl<'device, 'nvml: 'device> NvLink<'device, 'nvml> {
    /// Obtain the `Device` reference stored within this struct.
    pub fn device(&self) -> &Device {
        self.device
    }

    /// Obtain the value of this struct's `link` field.
    pub fn link(&self) -> u32 {
        self.link
    }

    /**
    Gets whether or not this `Device`'s NvLink is active.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // Test written
    #[doc(alias = "nvmlDeviceGetNvLinkState")]
    pub fn is_active(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.device.nvml().lib.nvmlDeviceGetNvLinkState.as_ref())?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();

            nvml_try(sym(self.device.handle(), self.link, &mut state))?;

            bool_from_state(state)
        }
    }

    /**
    Gets the NvLink version of this `Device` / `NvLink`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // Test written
    #[doc(alias = "nvmlDeviceGetNvLinkVersion")]
    pub fn version(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.device.nvml().lib.nvmlDeviceGetNvLinkVersion.as_ref())?;

        unsafe {
            let mut version: c_uint = mem::zeroed();

            nvml_try(sym(self.device.handle(), self.link, &mut version))?;

            Ok(version)
        }
    }

    /**
    Gets whether or not this `Device` / `NvLink` has a `Capability`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // Test written
    #[doc(alias = "nvmlDeviceGetNvLinkCapability")]
    pub fn has_capability(&self, cap_type: Capability) -> Result<bool, NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceGetNvLinkCapability
                .as_ref(),
        )?;

        unsafe {
            // NVIDIA says that this should be interpreted as a boolean
            let mut capability: c_uint = mem::zeroed();

            nvml_try(sym(
                self.device.handle(),
                self.link,
                cap_type.as_c(),
                &mut capability,
            ))?;

            #[allow(clippy::match_like_matches_macro)]
            Ok(match capability {
                0 => false,
                // Not worth an error or a panic if the value is > 1
                _ => true,
            })
        }
    }

    /**
    Gets the PCI information for this `NvLink`'s remote node.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // Test written
    #[doc(alias = "nvmlDeviceGetNvLinkRemotePciInfo_v2")]
    pub fn remote_pci_info(&self) -> Result<PciInfo, NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceGetNvLinkRemotePciInfo_v2
                .as_ref(),
        )?;

        unsafe {
            let mut pci_info: nvmlPciInfo_t = mem::zeroed();

            nvml_try(sym(self.device.handle(), self.link, &mut pci_info))?;

            PciInfo::try_from(pci_info, false)
        }
    }

    /**
    Gets the specified `ErrorCounter` value.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // Test written
    #[doc(alias = "nvmlDeviceGetNvLinkErrorCounter")]
    pub fn error_counter(&self, counter: ErrorCounter) -> Result<u64, NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceGetNvLinkErrorCounter
                .as_ref(),
        )?;

        unsafe {
            let mut value: c_ulonglong = mem::zeroed();

            nvml_try(sym(
                self.device.handle(),
                self.link,
                counter.as_c(),
                &mut value,
            ))?;

            Ok(value)
        }
    }

    /**
    Resets all error counters to zero.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // No-run test written
    #[doc(alias = "nvmlDeviceResetNvLinkErrorCounters")]
    pub fn reset_error_counters(&mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceResetNvLinkErrorCounters
                .as_ref(),
        )?;

        unsafe { nvml_try(sym(self.device.handle(), self.link)) }
    }

    /**
    Sets the NvLink utilization counter control information for the specified
    `Counter`.

    The counters will be reset if `reset_counters` is true.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // No-run test written
    #[doc(alias = "nvmlDeviceSetNvLinkUtilizationControl")]
    pub fn set_utilization_control(
        &mut self,
        counter: Counter,
        settings: UtilizationControl,
        reset_counters: bool,
    ) -> Result<(), NvmlError> {
        let reset: c_uint = u32::from(reset_counters);

        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceSetNvLinkUtilizationControl
                .as_ref(),
        )?;

        unsafe {
            nvml_try(sym(
                self.device.handle(),
                self.link,
                counter as c_uint,
                &mut settings.as_c(),
                reset,
            ))
        }
    }

    /**
    Gets the NvLink utilization counter control information for the specified
    `Counter`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // Test written
    #[doc(alias = "nvmlDeviceGetNvLinkUtilizationControl")]
    pub fn utilization_control(&self, counter: Counter) -> Result<UtilizationControl, NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceGetNvLinkUtilizationControl
                .as_ref(),
        )?;

        unsafe {
            let mut controls: nvmlNvLinkUtilizationControl_t = mem::zeroed();

            nvml_try(sym(
                self.device.handle(),
                self.link,
                counter as c_uint,
                &mut controls,
            ))?;

            UtilizationControl::try_from(controls)
        }
    }

    /**
    Gets the NvLink utilization counter for the given `counter`.

    The retrieved values are based on the current controls set for the specified
    `Counter`. **You should use `.set_utilization_control()` before calling this**
    as the utilization counters have no default state.

    I do not attempt to verify, statically or at runtime, that you have controls
    set for `counter` prior to calling this method on `counter`. NVIDIA says that
    it is "In general\[,\] good practice", which does not sound to me as if it
    is in any way unsafe to make this call without having set controls. I don't
    believe it's worth the overhead of using a `Mutex`'d bool to track whether
    or not you have set controls, and it's certainly not worth the effort to
    statically verify it via the type system.

    That being said, I don't know what exactly would happen, either, and I have
    no means of finding out. If you do and discover that garbage values are
    returned, for instance, I would love to hear about it; that would likely
    cause this decision to be reconsidered.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // No-run test written
    #[doc(alias = "nvmlDeviceGetNvLinkUtilizationCounter")]
    pub fn utilization_counter(&self, counter: Counter) -> Result<UtilizationCounter, NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceGetNvLinkUtilizationCounter
                .as_ref(),
        )?;

        unsafe {
            let mut receive: c_ulonglong = mem::zeroed();
            let mut send: c_ulonglong = mem::zeroed();

            nvml_try(sym(
                self.device.handle(),
                self.link,
                counter as c_uint,
                &mut receive,
                &mut send,
            ))?;

            Ok(UtilizationCounter { receive, send })
        }
    }

    /**
    Freezes the specified NvLink utilization `Counter`.

    Both the receive and send counters will be frozen (if I'm reading NVIDIA's
    meaning correctly).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // No-run test written
    #[doc(alias = "nvmlDeviceFreezeNvLinkUtilizationCounter")]
    pub fn freeze_utilization_counter(&mut self, counter: Counter) -> Result<(), NvmlError> {
        self.set_utilization_counter_frozen(counter, true)
    }

    /**
    Unfreezes the specified NvLink utilization `Counter`.

    Both the receive and send counters will be unfrozen (if I'm reading NVIDIA's
    meaning correctly).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // No-run test written
    #[doc(alias = "nvmlDeviceFreezeNvLinkUtilizationCounter")]
    pub fn unfreeze_utilization_counter(&mut self, counter: Counter) -> Result<(), NvmlError> {
        self.set_utilization_counter_frozen(counter, false)
    }

    fn set_utilization_counter_frozen(
        &mut self,
        counter: Counter,
        frozen: bool,
    ) -> Result<(), NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceFreezeNvLinkUtilizationCounter
                .as_ref(),
        )?;

        unsafe {
            nvml_try(sym(
                self.device.handle(),
                self.link,
                counter as c_uint,
                state_from_bool(frozen),
            ))
        }
    }

    /**
    Resets the specified NvLink utilization `Counter`.

    Both the receive and send counters will be rest (if I'm reading NVIDIA's
    meaning correctly).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `link` or `Device` within this `NvLink` struct instance
    is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal or newer fully supported devices.
    */
    // No-run test written
    #[doc(alias = "nvmlDeviceResetNvLinkUtilizationCounter")]
    pub fn reset_utilization_counter(&mut self, counter: Counter) -> Result<(), NvmlError> {
        let sym = nvml_sym(
            self.device
                .nvml()
                .lib
                .nvmlDeviceResetNvLinkUtilizationCounter
                .as_ref(),
        )?;

        unsafe { nvml_try(sym(self.device.handle(), self.link, counter as c_uint)) }
    }
}

#[cfg(test)]
#[deny(unused_mut)]
mod test {
    use crate::bitmasks::nv_link::*;
    use crate::enum_wrappers::nv_link::*;
    use crate::enums::nv_link::*;
    use crate::struct_wrappers::nv_link::*;
    use crate::test_utils::*;

    #[test]
    #[ignore = "my machine does not support this call"]
    fn is_active() {
        let nvml = nvml();
        test_with_link(3, &nvml, |link| link.is_active())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn version() {
        let nvml = nvml();
        test_with_link(3, &nvml, |link| link.version())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn has_capability() {
        let nvml = nvml();
        test_with_link(3, &nvml, |link| link.has_capability(Capability::P2p))
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn remote_pci_info() {
        let nvml = nvml();
        test_with_link(3, &nvml, |link| {
            let info = link.remote_pci_info()?;
            assert_eq!(info.pci_sub_system_id, None);
            Ok(info)
        })
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn error_counter() {
        let nvml = nvml();
        test_with_link(3, &nvml, |link| {
            link.error_counter(ErrorCounter::DlRecovery)
        })
    }

    // This modifies link state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn reset_error_counters() {
        let nvml = nvml();
        let device = device(&nvml);
        let mut link = device.link_wrapper_for(0);

        link.reset_error_counters().unwrap();
    }

    // This modifies link state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_utilization_control() {
        let nvml = nvml();
        let device = device(&nvml);
        let mut link = device.link_wrapper_for(0);

        let settings = UtilizationControl {
            units: UtilizationCountUnit::Cycles,
            packet_filter: PacketTypes::NO_OP
                | PacketTypes::READ
                | PacketTypes::WRITE
                | PacketTypes::RATOM
                | PacketTypes::WITH_DATA,
        };

        link.set_utilization_control(Counter::One, settings, false)
            .unwrap()
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn utilization_control() {
        let nvml = nvml();
        test_with_link(3, &nvml, |link| link.utilization_control(Counter::One))
    }

    // This shouldn't be called without modifying link state, so we don't want
    // to actually run the test
    #[allow(dead_code)]
    fn utilization_counter() {
        let nvml = nvml();
        let device = device(&nvml);
        let link = device.link_wrapper_for(0);

        link.utilization_counter(Counter::One).unwrap();
    }

    // This modifies link state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn freeze_utilization_counter() {
        let nvml = nvml();
        let device = device(&nvml);
        let mut link = device.link_wrapper_for(0);

        link.freeze_utilization_counter(Counter::One).unwrap();
    }

    // This modifies link state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn unfreeze_utilization_counter() {
        let nvml = nvml();
        let device = device(&nvml);
        let mut link = device.link_wrapper_for(0);

        link.unfreeze_utilization_counter(Counter::One).unwrap();
    }

    // This modifies link state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn reset_utilization_counter() {
        let nvml = nvml();
        let device = device(&nvml);
        let mut link = device.link_wrapper_for(0);

        link.reset_utilization_counter(Counter::One).unwrap();
    }
}

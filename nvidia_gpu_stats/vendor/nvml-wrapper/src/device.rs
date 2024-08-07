#[cfg(target_os = "linux")]
use crate::EventSet;
use crate::NvLink;
use crate::Nvml;

use crate::bitmasks::device::ThrottleReasons;
#[cfg(target_os = "linux")]
use crate::bitmasks::event::EventTypes;
#[cfg(target_os = "windows")]
use crate::bitmasks::Behavior;

use crate::enum_wrappers::{bool_from_state, device::*, state_from_bool};

use crate::enums::device::BusType;
use crate::enums::device::DeviceArchitecture;
use crate::enums::device::GpuLockedClocksSetting;
use crate::enums::device::PcieLinkMaxSpeed;
use crate::enums::device::PowerSource;
#[cfg(target_os = "linux")]
use crate::error::NvmlErrorWithSource;
use crate::error::{nvml_sym, nvml_try, Bits, NvmlError};

use crate::ffi::bindings::*;

use crate::struct_wrappers::device::*;
use crate::structs::device::*;

#[cfg(target_os = "linux")]
use std::convert::TryInto;
#[cfg(target_os = "linux")]
use std::os::raw::c_ulong;
use std::{
    convert::TryFrom,
    ffi::CStr,
    mem,
    os::raw::{c_int, c_uint, c_ulonglong},
    ptr,
};

use static_assertions::assert_impl_all;

/**
Struct that represents a device on the system.

Obtain a `Device` with the various methods available to you on the `Nvml`
struct.

Lifetimes are used to enforce that each `Device` instance cannot be used after
the `Nvml` instance it was obtained from is dropped:

```compile_fail
use nvml_wrapper::Nvml;
# use nvml_wrapper::error::*;

# fn main() -> Result<(), NvmlError> {
let nvml = Nvml::init()?;
let device = nvml.device_by_index(0)?;

drop(nvml);

// This won't compile
device.fan_speed(0)?;
# Ok(())
# }
```

This means you shouldn't have to worry about calls to `Device` methods returning
`Uninitialized` errors.
*/
#[derive(Debug)]
pub struct Device<'nvml> {
    device: nvmlDevice_t,
    nvml: &'nvml Nvml,
}

unsafe impl<'nvml> Send for Device<'nvml> {}
unsafe impl<'nvml> Sync for Device<'nvml> {}

assert_impl_all!(Device: Send, Sync);

impl<'nvml> Device<'nvml> {
    /**
    Create a new `Device` wrapper.

    You will most likely never need to call this; see the methods available to you
    on the `Nvml` struct to get one.

    # Safety

    It is your responsibility to ensure that the given `nvmlDevice_t` pointer
    is valid.
    */
    // Clippy bug, see https://github.com/rust-lang/rust-clippy/issues/5593
    #[allow(clippy::missing_safety_doc)]
    pub unsafe fn new(device: nvmlDevice_t, nvml: &'nvml Nvml) -> Self {
        Self { device, nvml }
    }

    /// Access the `Nvml` reference this struct wraps
    pub fn nvml(&self) -> &'nvml Nvml {
        self.nvml
    }

    /// Get the raw device handle contained in this struct
    ///
    /// Sometimes necessary for C interop.
    ///
    /// # Safety
    ///
    /// This is unsafe to prevent it from being used without care.
    pub unsafe fn handle(&self) -> nvmlDevice_t {
        self.device
    }

    /**
    Clear all affinity bindings for the calling thread.

    Note that this was changed as of version 8.0; older versions cleared affinity for
    the calling process and all children.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested (no-run)
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceClearCpuAffinity")]
    pub fn clear_cpu_affinity(&mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceClearCpuAffinity.as_ref())?;

        unsafe { nvml_try(sym(self.device)) }
    }

    /**
    Gets the root/admin permissions for the target API.

    Only root users are able to call functions belonging to restricted APIs. See
    the documentation for the `RestrictedApi` enum for a list of those functions.

    Non-root users can be granted access to these APIs through use of
    `.set_api_restricted()`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or the apiType is invalid (may occur if
    the C lib changes dramatically?)
    * `NotSupported`, if this query is not supported by this `Device` or this `Device`
    does not support the feature that is being queried (e.g. enabling/disabling auto
    boosted clocks is not supported by this `Device`).
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all _fully supported_ products.
    */
    // Checked against local
    // Tested (except for AutoBoostedClocks)
    #[doc(alias = "nvmlDeviceGetAPIRestriction")]
    pub fn is_api_restricted(&self, api: Api) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetAPIRestriction.as_ref())?;

        unsafe {
            let mut restricted_state: nvmlEnableState_t = mem::zeroed();

            nvml_try(sym(self.device, api.as_c(), &mut restricted_state))?;

            bool_from_state(restricted_state)
        }
    }

    /**
    Gets the current clock setting that all applications will use unless an overspec
    situation occurs.

    This setting can be changed using `.set_applications_clocks()`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or the clockType is invalid (may occur
    if the C lib changes dramatically?)
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetApplicationsClock")]
    pub fn applications_clock(&self, clock_type: Clock) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetApplicationsClock.as_ref())?;

        unsafe {
            let mut clock: c_uint = mem::zeroed();

            nvml_try(sym(self.device, clock_type.as_c(), &mut clock))?;

            Ok(clock)
        }
    }

    /**
    Gets the current and default state of auto boosted clocks.

    Auto boosted clocks are enabled by default on some hardware, allowing the GPU to run
    as fast as thermals will allow it to.

    On Pascal and newer hardware, auto boosted clocks are controlled through application
    clocks. Use `.set_applications_clocks()` and `.reset_applications_clocks()` to control
    auto boost behavior.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support auto boosted clocks
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetAutoBoostedClocksEnabled")]
    pub fn auto_boosted_clocks_enabled(&self) -> Result<AutoBoostClocksEnabledInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetAutoBoostedClocksEnabled.as_ref())?;

        unsafe {
            let mut is_enabled: nvmlEnableState_t = mem::zeroed();
            let mut is_enabled_default: nvmlEnableState_t = mem::zeroed();

            nvml_try(sym(self.device, &mut is_enabled, &mut is_enabled_default))?;

            Ok(AutoBoostClocksEnabledInfo {
                is_enabled: bool_from_state(is_enabled)?,
                is_enabled_default: bool_from_state(is_enabled_default)?,
            })
        }
    }

    /**
    Gets the total, available and used size of BAR1 memory.

    BAR1 memory is used to map the FB (device memory) so that it can be directly accessed
    by the CPU or by 3rd party devices (peer-to-peer on the PCIe bus).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this query
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetBAR1MemoryInfo")]
    pub fn bar1_memory_info(&self) -> Result<BAR1MemoryInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetBAR1MemoryInfo.as_ref())?;

        unsafe {
            let mut mem_info: nvmlBAR1Memory_t = mem::zeroed();
            nvml_try(sym(self.device, &mut mem_info))?;

            Ok(mem_info.into())
        }
    }

    /**
    Gets the board ID for this `Device`, from 0-N.

    Devices with the same boardID indicate GPUs connected to the same PLX. Use in
    conjunction with `.is_multi_gpu_board()` to determine if they are on the same
    board as well.

    The boardID returned is a unique ID for the current config. Uniqueness and
    ordering across reboots and system configs is not guaranteed (i.e if a Tesla
    K40c returns 0x100 and the two GPUs on a Tesla K10 in the same system return
    0x200, it is not guaranteed that they will always return those values. They will,
    however, always be different from each other).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetBoardId")]
    pub fn board_id(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetBoardId.as_ref())?;

        unsafe {
            let mut id: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut id))?;

            Ok(id)
        }
    }

    /**
    Gets the brand of this `Device`.

    See the `Brand` enum for documentation of possible values.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, check that error's docs for more info
    * `Unknown`, on any unexpected error
    */
    // Checked against local nvml.h
    // Tested
    #[doc(alias = "nvmlDeviceGetBrand")]
    pub fn brand(&self) -> Result<Brand, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetBrand.as_ref())?;

        unsafe {
            let mut brand: nvmlBrandType_t = mem::zeroed();
            nvml_try(sym(self.device, &mut brand))?;

            Brand::try_from(brand)
        }
    }

    /**
    Gets bridge chip information for all bridge chips on the board.

    Only applicable to multi-GPU devices.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all _fully supported_ devices.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetBridgeChipInfo")]
    pub fn bridge_chip_info(&self) -> Result<BridgeChipHierarchy, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetBridgeChipInfo.as_ref())?;

        unsafe {
            let mut info: nvmlBridgeChipHierarchy_t = mem::zeroed();
            nvml_try(sym(self.device, &mut info))?;

            BridgeChipHierarchy::try_from(info)
        }
    }

    /**
    Gets this `Device`'s current clock speed for the given `Clock` type and `ClockId`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or `clock_type` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested (except for CustomerMaxBoost)
    #[doc(alias = "nvmlDeviceGetClock")]
    pub fn clock(&self, clock_type: Clock, clock_id: ClockId) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetClock.as_ref())?;

        unsafe {
            let mut clock: c_uint = mem::zeroed();

            nvml_try(sym(
                self.device,
                clock_type.as_c(),
                clock_id.as_c(),
                &mut clock,
            ))?;

            Ok(clock)
        }
    }

    /**
    Gets this `Device`'s customer-defined maximum boost clock speed for the
    given `Clock` type.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or `clock_type` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` or the `clock_type` on this `Device`
    does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal and newer fully supported devices.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetMaxCustomerBoostClock")]
    pub fn max_customer_boost_clock(&self, clock_type: Clock) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMaxCustomerBoostClock.as_ref())?;

        unsafe {
            let mut clock: c_uint = mem::zeroed();

            nvml_try(sym(self.device, clock_type.as_c(), &mut clock))?;

            Ok(clock)
        }
    }

    /**
    Gets the current compute mode for this `Device`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, check that error's docs for more info
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetComputeMode")]
    pub fn compute_mode(&self) -> Result<ComputeMode, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetComputeMode.as_ref())?;

        unsafe {
            let mut mode: nvmlComputeMode_t = mem::zeroed();
            nvml_try(sym(self.device, &mut mode))?;

            ComputeMode::try_from(mode)
        }
    }

    /**
    Gets the CUDA compute capability of this `Device`.

    The returned version numbers are the same as those returned by
    `cuDeviceGetAttribute()` from the CUDA API.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    #[doc(alias = "nvmlDeviceGetCudaComputeCapability")]
    pub fn cuda_compute_capability(&self) -> Result<CudaComputeCapability, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetCudaComputeCapability.as_ref())?;

        unsafe {
            let mut major: c_int = mem::zeroed();
            let mut minor: c_int = mem::zeroed();

            nvml_try(sym(self.device, &mut major, &mut minor))?;

            Ok(CudaComputeCapability { major, minor })
        }
    }

    /**
    Gets this `Device`'s current clock speed for the given `Clock` type.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` cannot report the specified clock
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetClockInfo")]
    pub fn clock_info(&self, clock_type: Clock) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetClockInfo.as_ref())?;

        unsafe {
            let mut clock: c_uint = mem::zeroed();

            nvml_try(sym(self.device, clock_type.as_c(), &mut clock))?;

            Ok(clock)
        }
    }

    /**
    Gets information about processes with a compute context running on this `Device`.

    This only returns information about running compute processes (such as a CUDA application
    with an active context). Graphics applications (OpenGL, DirectX) won't be listed by this
    function.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Tested
    #[doc(alias = "nvmlDeviceGetComputeRunningProcesses_v3")]
    pub fn running_compute_processes(&self) -> Result<Vec<ProcessInfo>, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetComputeRunningProcesses_v3
                .as_ref(),
        )?;

        unsafe {
            let mut count: c_uint = match self.running_compute_processes_count()? {
                0 => return Ok(vec![]),
                value => value,
            };
            // Add a bit of headroom in case more processes are launched in
            // between the above call to get the expected count and the time we
            // actually make the call to get data below.
            count += 5;
            let mut processes: Vec<nvmlProcessInfo_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.device, &mut count, processes.as_mut_ptr()))?;

            processes.truncate(count as usize);
            Ok(processes.into_iter().map(ProcessInfo::from).collect())
        }
    }

    /**
    Gets the number of processes with a compute context running on this `Device`.

    This only returns the count of running compute processes (such as a CUDA application
    with an active context). Graphics applications (OpenGL, DirectX) won't be counted by this
    function.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Tested as part of `.running_compute_processes()`
    #[doc(alias = "nvmlDeviceGetComputeRunningProcesses_v3")]
    pub fn running_compute_processes_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetComputeRunningProcesses_v3
                .as_ref(),
        )?;

        unsafe {
            // Indicates that we want the count
            let mut count: c_uint = 0;

            // Passing null doesn't mean we want the count, it's just allowed
            match sym(self.device, &mut count, ptr::null_mut()) {
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => Ok(count),
                // If success, return 0; otherwise, return error
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets information about processes with a compute context running on this `Device`.

    This only returns information about running compute processes (such as a CUDA application
    with an active context). Graphics applications (OpenGL, DirectX) won't be listed by this
    function.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    #[doc(alias = "nvmlDeviceGetComputeRunningProcesses_v2")]
    #[cfg(feature = "legacy-functions")]
    pub fn running_compute_processes_v2(&self) -> Result<Vec<ProcessInfo>, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetComputeRunningProcesses_v2
                .as_ref(),
        )?;

        unsafe {
            let mut count: c_uint = match self.running_compute_processes_count_v2()? {
                0 => return Ok(vec![]),
                value => value,
            };
            // Add a bit of headroom in case more processes are launched in
            // between the above call to get the expected count and the time we
            // actually make the call to get data below.
            count += 5;
            let mut processes: Vec<nvmlProcessInfo_v2_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.device, &mut count, processes.as_mut_ptr()))?;

            processes.truncate(count as usize);
            Ok(processes.into_iter().map(ProcessInfo::from).collect())
        }
    }

    /**
    Gets the number of processes with a compute context running on this `Device`.

    This only returns the count of running compute processes (such as a CUDA application
    with an active context). Graphics applications (OpenGL, DirectX) won't be counted by this
    function.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    #[doc(alias = "nvmlDeviceGetComputeRunningProcesses_v2")]
    #[cfg(feature = "legacy-functions")]
    pub fn running_compute_processes_count_v2(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetComputeRunningProcesses_v2
                .as_ref(),
        )?;

        unsafe {
            // Indicates that we want the count
            let mut count: c_uint = 0;

            // Passing null doesn't mean we want the count, it's just allowed
            match sym(self.device, &mut count, ptr::null_mut()) {
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => Ok(count),
                // If success, return 0; otherwise, return error
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets a vector of bitmasks with the ideal CPU affinity for this `Device`.

    The results are sized to `size`. For example, if processors 0, 1, 32, and 33 are
    ideal for this `Device` and `size` == 2, result\[0\] = 0x3, result\[1\] = 0x3.

    64 CPUs per unsigned long on 64-bit machines, 32 on 32-bit machines.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `InsufficientSize`, if the passed-in `size` is 0 (must be > 0)
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested
    // TODO: Should we trim zeros here or leave it to the caller?
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceGetCpuAffinity")]
    pub fn cpu_affinity(&self, size: usize) -> Result<Vec<c_ulong>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetCpuAffinity.as_ref())?;

        unsafe {
            if size == 0 {
                // Return an error containing the minimum size that can be passed.
                return Err(NvmlError::InsufficientSize(Some(1)));
            }

            let mut affinities: Vec<c_ulong> = vec![mem::zeroed(); size];

            nvml_try(sym(self.device, size as c_uint, affinities.as_mut_ptr()))?;

            Ok(affinities)
        }
    }

    /**
    Gets the current PCIe link generation.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if PCIe link information is not available
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetCurrPcieLinkGeneration")]
    pub fn current_pcie_link_gen(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetCurrPcieLinkGeneration.as_ref())?;

        unsafe {
            let mut link_gen: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut link_gen))?;

            Ok(link_gen)
        }
    }

    /**
    Gets the current PCIe link width.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if PCIe link information is not available
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetCurrPcieLinkWidth")]
    pub fn current_pcie_link_width(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetCurrPcieLinkWidth.as_ref())?;

        unsafe {
            let mut link_width: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut link_width))?;

            Ok(link_width)
        }
    }

    /**
    Gets the current utilization and sampling size (sampling size in μs) for the Decoder.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetDecoderUtilization")]
    pub fn decoder_utilization(&self) -> Result<UtilizationInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetDecoderUtilization.as_ref())?;

        unsafe {
            let mut utilization: c_uint = mem::zeroed();
            let mut sampling_period: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut utilization, &mut sampling_period))?;

            Ok(UtilizationInfo {
                utilization,
                sampling_period,
            })
        }
    }

    /**
    Gets global statistics for active frame buffer capture sessions on this `Device`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Maxwell or newer fully supported devices.
    */
    // tested
    #[doc(alias = "nvmlDeviceGetFBCStats")]
    pub fn fbc_stats(&self) -> Result<FbcStats, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetFBCStats.as_ref())?;

        unsafe {
            let mut fbc_stats: nvmlFBCStats_t = mem::zeroed();
            nvml_try(sym(self.device, &mut fbc_stats))?;

            Ok(fbc_stats.into())
        }
    }

    /**
    Gets information about active frame buffer capture sessions on this `Device`.

    Note that information such as the horizontal and vertical resolutions, the
    average FPS, and the average latency will be zero if no frames have been
    captured since a session was started.

    # Errors

    * `UnexpectedVariant`, for which you can read the docs for
    * `IncorrectBits`, if bits are found in a session's info flags that don't
        match the flags in this wrapper
    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Maxwell or newer fully supported devices.
    */
    // tested
    #[doc(alias = "nvmlDeviceGetFBCSessions")]
    pub fn fbc_sessions_info(&self) -> Result<Vec<FbcSessionInfo>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetFBCSessions.as_ref())?;

        unsafe {
            let mut count: c_uint = match self.fbc_session_count()? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut info: Vec<nvmlFBCSessionInfo_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.device, &mut count, info.as_mut_ptr()))?;

            info.into_iter().map(FbcSessionInfo::try_from).collect()
        }
    }

    /**
    Gets the number of active frame buffer capture sessions on this `Device`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // tested as part of the above
    #[doc(alias = "nvmlDeviceGetFBCSessions")]
    pub fn fbc_session_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetFBCSessions.as_ref())?;

        unsafe {
            let mut count: c_uint = 0;

            nvml_try(sym(self.device, &mut count, ptr::null_mut()))?;

            Ok(count)
        }
    }

    /**
    Gets the default applications clock that this `Device` boots with or defaults to after
    `reset_applications_clocks()`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetDefaultApplicationsClock")]
    pub fn default_applications_clock(&self, clock_type: Clock) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetDefaultApplicationsClock.as_ref())?;

        unsafe {
            let mut clock: c_uint = mem::zeroed();

            nvml_try(sym(self.device, clock_type.as_c(), &mut clock))?;

            Ok(clock)
        }
    }

    /// Not documenting this because it's deprecated. Read NVIDIA's docs if you
    /// must use it.
    #[deprecated(note = "use `Device.memory_error_counter()`")]
    #[doc(alias = "nvmlDeviceGetDetailedEccErrors")]
    pub fn detailed_ecc_errors(
        &self,
        error_type: MemoryError,
        counter_type: EccCounter,
    ) -> Result<EccErrorCounts, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetDetailedEccErrors.as_ref())?;

        unsafe {
            let mut counts: nvmlEccErrorCounts_t = mem::zeroed();

            nvml_try(sym(
                self.device,
                error_type.as_c(),
                counter_type.as_c(),
                &mut counts,
            ))?;

            Ok(counts.into())
        }
    }

    /**
    Gets the display active state for this `Device`.

    This method indicates whether a display is initialized on this `Device`.
    For example, whether or not an X Server is attached to this device and
    has allocated memory for the screen.

    A display can be active even when no monitor is physically attached to this `Device`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetDisplayActive")]
    pub fn is_display_active(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetDisplayActive.as_ref())?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();
            nvml_try(sym(self.device, &mut state))?;

            bool_from_state(state)
        }
    }

    /**
    Gets whether a physical display is currently connected to any of this `Device`'s
    connectors.

    This calls the C function `nvmlDeviceGetDisplayMode`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetDisplayMode")]
    pub fn is_display_connected(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetDisplayMode.as_ref())?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();
            nvml_try(sym(self.device, &mut state))?;

            bool_from_state(state)
        }
    }

    /**
    Gets the current and pending driver model for this `Device`.

    On Windows, the device driver can run in either WDDM or WDM (TCC) modes.
    If a display is attached to the device it must run in WDDM mode. TCC mode
    is preferred if a display is not attached.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if the platform is not Windows
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.

    # Platform Support

    Only supports Windows.
    */
    // Checked against local
    // Tested
    #[cfg(target_os = "windows")]
    #[doc(alias = "nvmlDeviceGetDriverModel")]
    pub fn driver_model(&self) -> Result<DriverModelState, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetDriverModel.as_ref())?;

        unsafe {
            let mut current: nvmlDriverModel_t = mem::zeroed();
            let mut pending: nvmlDriverModel_t = mem::zeroed();

            nvml_try(sym(self.device, &mut current, &mut pending))?;

            Ok(DriverModelState {
                current: DriverModel::try_from(current)?,
                pending: DriverModel::try_from(pending)?,
            })
        }
    }

    /**
    Get the current and pending ECC modes for this `Device`.

    Changing ECC modes requires a reboot. The "pending" ECC mode refers to the target
    mode following the next reboot.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices. Only applicable to devices with
    ECC. Requires `InfoRom::ECC` version 1.0 or higher.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetEccMode")]
    pub fn is_ecc_enabled(&self) -> Result<EccModeState, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetEccMode.as_ref())?;

        unsafe {
            let mut current: nvmlEnableState_t = mem::zeroed();
            let mut pending: nvmlEnableState_t = mem::zeroed();

            nvml_try(sym(self.device, &mut current, &mut pending))?;

            Ok(EccModeState {
                currently_enabled: bool_from_state(current)?,
                pending_enabled: bool_from_state(pending)?,
            })
        }
    }

    /**
    Gets the current utilization and sampling size (sampling size in μs) for the Encoder.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetEncoderUtilization")]
    pub fn encoder_utilization(&self) -> Result<UtilizationInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetEncoderUtilization.as_ref())?;

        unsafe {
            let mut utilization: c_uint = mem::zeroed();
            let mut sampling_period: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut utilization, &mut sampling_period))?;

            Ok(UtilizationInfo {
                utilization,
                sampling_period,
            })
        }
    }

    /**
    Gets the current capacity of this device's encoder in macroblocks per second.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this device is invalid
    * `NotSupported`, if this `Device` does not support the given `for_type`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Maxwell or newer fully supported devices.
    */
    // Tested
    #[doc(alias = "nvmlDeviceGetEncoderCapacity")]
    pub fn encoder_capacity(&self, for_type: EncoderType) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetEncoderCapacity.as_ref())?;

        unsafe {
            let mut capacity: c_uint = mem::zeroed();

            nvml_try(sym(self.device, for_type.as_c(), &mut capacity))?;

            Ok(capacity)
        }
    }

    /**
    Gets the current encoder stats for this device.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this device is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Maxwell or newer fully supported devices.
    */
    // Tested
    #[doc(alias = "nvmlDeviceGetEncoderStats")]
    pub fn encoder_stats(&self) -> Result<EncoderStats, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetEncoderStats.as_ref())?;

        unsafe {
            let mut session_count: c_uint = mem::zeroed();
            let mut average_fps: c_uint = mem::zeroed();
            let mut average_latency: c_uint = mem::zeroed();

            nvml_try(sym(
                self.device,
                &mut session_count,
                &mut average_fps,
                &mut average_latency,
            ))?;

            Ok(EncoderStats {
                session_count,
                average_fps,
                average_latency,
            })
        }
    }

    /**
    Gets information about active encoder sessions on this device.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, if an enum variant not defined in this wrapper gets
    returned in a field of an `EncoderSessionInfo` struct
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Maxwell or newer fully supported devices.
    */
    // Tested
    // TODO: Test this with an active session and make sure it works
    #[doc(alias = "nvmlDeviceGetEncoderSessions")]
    pub fn encoder_sessions(&self) -> Result<Vec<EncoderSessionInfo>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetEncoderSessions.as_ref())?;

        unsafe {
            let mut count = match self.encoder_sessions_count()? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut sessions: Vec<nvmlEncoderSessionInfo_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.device, &mut count, sessions.as_mut_ptr()))?;

            sessions.truncate(count as usize);
            sessions
                .into_iter()
                .map(EncoderSessionInfo::try_from)
                .collect::<Result<_, NvmlError>>()
        }
    }

    /**
    Gets the number of active encoder sessions on this device.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // tested as part of the above
    fn encoder_sessions_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetEncoderSessions.as_ref())?;

        unsafe {
            let mut count: c_uint = 0;

            nvml_try(sym(self.device, &mut count, ptr::null_mut()))?;

            Ok(count)
        }
    }

    /**
    Gets the effective power limit in milliwatts that the driver enforces after taking
    into account all limiters.

    Note: This can be different from the `.power_management_limit()` if other limits
    are set elswhere. This includes the out-of-band power limit interface.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetEnforcedPowerLimit")]
    pub fn enforced_power_limit(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetEnforcedPowerLimit.as_ref())?;

        unsafe {
            let mut limit: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut limit))?;

            Ok(limit)
        }
    }

    /**
    Gets the intended operating speed of the specified fan as a percentage of the
    maximum fan speed (100%).

    Note: The reported speed is the intended fan speed. If the fan is physically blocked
    and unable to spin, the output will not match the actual fan speed.

    You can determine valid fan indices using [`Self::num_fans()`].

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or `fan_idx` is invalid
    * `NotSupported`, if this `Device` does not have a fan or is newer than Maxwell
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all discrete products with dedicated fans.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetFanSpeed_v2")]
    pub fn fan_speed(&self, fan_idx: u32) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetFanSpeed_v2.as_ref())?;

        unsafe {
            let mut speed: c_uint = mem::zeroed();
            nvml_try(sym(self.device, fan_idx, &mut speed))?;

            Ok(speed)
        }
    }

    /**
    Gets the number of fans on this [`Device`].

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` does not have a fan
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all discrete products with dedicated fans.
    */
    #[doc(alias = "nvmlDeviceGetNumFans")]
    pub fn num_fans(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetNumFans.as_ref())?;

        unsafe {
            let mut count: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut count))?;

            Ok(count)
        }
    }

    /**
    Gets the current GPU operation mode and the pending one (that it will switch to
    after a reboot).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports GK110 M-class and X-class Tesla products from the Kepler family. Modes `LowDP`
    and `AllOn` are supported on fully supported GeForce products. Not supported
    on Quadro and Tesla C-class products.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetGpuOperationMode")]
    pub fn gpu_operation_mode(&self) -> Result<OperationModeState, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetGpuOperationMode.as_ref())?;

        unsafe {
            let mut current: nvmlGpuOperationMode_t = mem::zeroed();
            let mut pending: nvmlGpuOperationMode_t = mem::zeroed();

            nvml_try(sym(self.device, &mut current, &mut pending))?;

            Ok(OperationModeState {
                current: OperationMode::try_from(current)?,
                pending: OperationMode::try_from(pending)?,
            })
        }
    }

    /**
    Gets information about processes with a graphics context running on this `Device`.

    This only returns information about graphics based processes (OpenGL, DirectX, etc.).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Tested
    #[doc(alias = "nvmlDeviceGetGraphicsRunningProcesses_v3")]
    pub fn running_graphics_processes(&self) -> Result<Vec<ProcessInfo>, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetGraphicsRunningProcesses_v3
                .as_ref(),
        )?;

        unsafe {
            let mut count: c_uint = match self.running_graphics_processes_count()? {
                0 => return Ok(vec![]),
                value => value,
            };
            // Add a bit of headroom in case more processes are launched in
            // between the above call to get the expected count and the time we
            // actually make the call to get data below.
            count += 5;
            let mut processes: Vec<nvmlProcessInfo_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.device, &mut count, processes.as_mut_ptr()))?;
            processes.truncate(count as usize);

            Ok(processes.into_iter().map(ProcessInfo::from).collect())
        }
    }

    /**
    Gets the number of processes with a graphics context running on this `Device`.

    This only returns the count of graphics based processes (OpenGL, DirectX).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error
    */
    // Tested as part of `.running_graphics_processes()`
    #[doc(alias = "nvmlDeviceGetGraphicsRunningProcesses_v3")]
    pub fn running_graphics_processes_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetGraphicsRunningProcesses_v3
                .as_ref(),
        )?;

        unsafe {
            // Indicates that we want the count
            let mut count: c_uint = 0;

            // Passing null doesn't indicate that we want the count. It's just allowed.
            match sym(self.device, &mut count, ptr::null_mut()) {
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => Ok(count),
                // If success, return 0; otherwise, return error
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets information about processes with a graphics context running on this `Device`.

    This only returns information about graphics based processes (OpenGL, DirectX, etc.).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    #[doc(alias = "nvmlDeviceGetGraphicsRunningProcesses_v2")]
    #[cfg(feature = "legacy-functions")]
    pub fn running_graphics_processes_v2(&self) -> Result<Vec<ProcessInfo>, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetGraphicsRunningProcesses_v2
                .as_ref(),
        )?;

        unsafe {
            let mut count: c_uint = match self.running_graphics_processes_count_v2()? {
                0 => return Ok(vec![]),
                value => value,
            };
            // Add a bit of headroom in case more processes are launched in
            // between the above call to get the expected count and the time we
            // actually make the call to get data below.
            count += 5;
            let mut processes: Vec<nvmlProcessInfo_v2_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.device, &mut count, processes.as_mut_ptr()))?;
            processes.truncate(count as usize);

            Ok(processes.into_iter().map(ProcessInfo::from).collect())
        }
    }

    /**
    Gets the number of processes with a graphics context running on this `Device`.

    This only returns the count of graphics based processes (OpenGL, DirectX).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error
    */
    #[doc(alias = "nvmlDeviceGetGraphicsRunningProcesses_v2")]
    #[cfg(feature = "legacy-functions")]
    pub fn running_graphics_processes_count_v2(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetGraphicsRunningProcesses_v2
                .as_ref(),
        )?;

        unsafe {
            // Indicates that we want the count
            let mut count: c_uint = 0;

            // Passing null doesn't indicate that we want the count. It's just allowed.
            match sym(self.device, &mut count, ptr::null_mut()) {
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => Ok(count),
                // If success, return 0; otherwise, return error
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets utilization stats for relevant currently running processes.

    Utilization stats are returned for processes that had a non-zero utilization stat
    at some point during the target sample period. Passing `None` as the
    `last_seen_timestamp` will target all samples that the driver has buffered; passing
    a timestamp retrieved from a previous query will target samples taken since that
    timestamp.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Maxwell or newer fully supported devices.
    */
    #[doc(alias = "nvmlDeviceGetProcessUtilization")]
    pub fn process_utilization_stats<T>(
        &self,
        last_seen_timestamp: T,
    ) -> Result<Vec<ProcessUtilizationSample>, NvmlError>
    where
        T: Into<Option<u64>>,
    {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetProcessUtilization.as_ref())?;

        unsafe {
            let last_seen_timestamp = last_seen_timestamp.into().unwrap_or(0);
            let mut count = match self.process_utilization_stats_count()? {
                0 => return Ok(vec![]),
                v => v,
            };
            let mut utilization_samples: Vec<nvmlProcessUtilizationSample_t> =
                vec![mem::zeroed(); count as usize];

            nvml_try(sym(
                self.device,
                utilization_samples.as_mut_ptr(),
                &mut count,
                last_seen_timestamp,
            ))?;
            utilization_samples.truncate(count as usize);

            Ok(utilization_samples
                .into_iter()
                .map(ProcessUtilizationSample::from)
                .collect())
        }
    }

    fn process_utilization_stats_count(&self) -> Result<c_uint, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetProcessUtilization.as_ref())?;

        unsafe {
            let mut count: c_uint = 0;

            match sym(self.device, ptr::null_mut(), &mut count, 0) {
                // Despite being undocumented, this appears to be the correct behavior
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => Ok(count),
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets the NVML index of this `Device`.

    Keep in mind that the order in which NVML enumerates devices has no guarantees of
    consistency between reboots. Also, the NVML index may not correlate with other APIs,
    such as the CUDA device index.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetIndex")]
    pub fn index(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetIndex.as_ref())?;

        unsafe {
            let mut index: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut index))?;

            Ok(index)
        }
    }

    /**
    Gets the checksum of the config stored in this `Device`'s infoROM.

    Can be used to make sure that two GPUs have the exact same configuration.
    The current checksum takes into account configuration stored in PWR and ECC
    infoROM objects. The checksum can change between driver released or when the
    user changes the configuration (e.g. disabling/enabling ECC).

    # Errors

    * `CorruptedInfoROM`, if this `Device`'s checksum couldn't be retrieved due to infoROM corruption
    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all devices with an infoROM.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetInforomConfigurationChecksum")]
    pub fn config_checksum(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetInforomConfigurationChecksum
                .as_ref(),
        )?;

        unsafe {
            let mut checksum: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut checksum))?;

            Ok(checksum)
        }
    }

    /**
    Gets the global infoROM image version.

    This image version, just like the VBIOS version, uniquely describes the exact version
    of the infoROM flashed on the board, in contrast to the infoROM object version which
    is only an indicator of supported features.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not have an infoROM
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all devices with an infoROM.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetInforomImageVersion")]
    pub fn info_rom_image_version(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetInforomImageVersion.as_ref())?;

        unsafe {
            let mut version_vec = vec![0; NVML_DEVICE_INFOROM_VERSION_BUFFER_SIZE as usize];

            nvml_try(sym(
                self.device,
                version_vec.as_mut_ptr(),
                NVML_DEVICE_INFOROM_VERSION_BUFFER_SIZE,
            ))?;

            let version_raw = CStr::from_ptr(version_vec.as_ptr());
            Ok(version_raw.to_str()?.into())
        }
    }

    /**
    Gets the version information for this `Device`'s infoROM object, for the passed in
    object type.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not have an infoROM
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Utf8Error`, if the string obtained from the C function is not valid UTF-8
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all devices with an infoROM.

    Fermi and higher parts have non-volatile on-board memory for persisting device info,
    such as aggregate ECC counts. The version of the data structures in this memory may
    change from time to time.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetInforomVersion")]
    pub fn info_rom_version(&self, object: InfoRom) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetInforomVersion.as_ref())?;

        unsafe {
            let mut version_vec = vec![0; NVML_DEVICE_INFOROM_VERSION_BUFFER_SIZE as usize];

            nvml_try(sym(
                self.device,
                object.as_c(),
                version_vec.as_mut_ptr(),
                NVML_DEVICE_INFOROM_VERSION_BUFFER_SIZE,
            ))?;

            let version_raw = CStr::from_ptr(version_vec.as_ptr());
            Ok(version_raw.to_str()?.into())
        }
    }

    /**
    Gets the maximum clock speeds for this `Device`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` cannot report the specified `Clock`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.

    Note: On GPUs from the Fermi family, current P0 (Performance state 0?) clocks
    (reported by `.clock_info()`) can differ from max clocks by a few MHz.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetMaxClockInfo")]
    pub fn max_clock_info(&self, clock_type: Clock) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMaxClockInfo.as_ref())?;

        unsafe {
            let mut clock: c_uint = mem::zeroed();

            nvml_try(sym(self.device, clock_type.as_c(), &mut clock))?;

            Ok(clock)
        }
    }

    /**
    Gets the max PCIe link generation possible with this `Device` and system.

    For a gen 2 PCIe device attached to a gen 1 PCIe bus, the max link generation
    this function will report is generation 1.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if PCIe link information is not available
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetMaxPcieLinkGeneration")]
    pub fn max_pcie_link_gen(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMaxPcieLinkGeneration.as_ref())?;

        unsafe {
            let mut max_gen: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut max_gen))?;

            Ok(max_gen)
        }
    }

    /**
    Gets the maximum PCIe link width possible with this `Device` and system.

    For a device with a 16x PCie bus width attached to an 8x PCIe system bus,
    this method will report a max link width of 8.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if PCIe link information is not available
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetMaxPcieLinkWidth")]
    pub fn max_pcie_link_width(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMaxPcieLinkWidth.as_ref())?;

        unsafe {
            let mut max_width: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut max_width))?;

            Ok(max_width)
        }
    }

    /**
    Gets the requested memory error counter for this `Device`.

    Only applicable to devices with ECC. Requires ECC mode to be enabled.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if `error_type`, `counter_type`, or `location` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support ECC error reporting for the specified
    memory
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices. Requires `InfoRom::ECC` version
    2.0 or higher to report aggregate location-based memory error counts. Requires
    `InfoRom::ECC version 1.0 or higher to report all other memory error counts.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetMemoryErrorCounter")]
    pub fn memory_error_counter(
        &self,
        error_type: MemoryError,
        counter_type: EccCounter,
        location: MemoryLocation,
    ) -> Result<u64, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMemoryErrorCounter.as_ref())?;

        unsafe {
            let mut count: c_ulonglong = mem::zeroed();

            nvml_try(sym(
                self.device,
                error_type.as_c(),
                counter_type.as_c(),
                location.as_c(),
                &mut count,
            ))?;

            Ok(count)
        }
    }

    /**
    Gets the amount of used, free and total memory available on this `Device`, in bytes.

    Note that enabling ECC reduces the amount of total available memory due to the
    extra required parity bits.

    Also note that on Windows, most device memory is allocated and managed on startup
    by Windows.

    Under Linux and Windows TCC (no physical display connected), the reported amount
    of used memory is equal to the sum of memory allocated by all active channels on
    this `Device`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetMemoryInfo")]
    pub fn memory_info(&self) -> Result<MemoryInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMemoryInfo.as_ref())?;

        unsafe {
            let mut info: nvmlMemory_t = mem::zeroed();
            nvml_try(sym(self.device, &mut info))?;

            Ok(info.into())
        }
    }

    /**
    Gets the minor number for this `Device`.

    The minor number is such that the NVIDIA device node file for each GPU will
    have the form `/dev/nvidia[minor number]`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceGetMinorNumber")]
    pub fn minor_number(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMinorNumber.as_ref())?;

        unsafe {
            let mut number: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut number))?;

            Ok(number)
        }
    }

    /**
    Identifies whether or not this `Device` is on a multi-GPU board.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetMultiGpuBoard")]
    pub fn is_multi_gpu_board(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMultiGpuBoard.as_ref())?;

        unsafe {
            let mut int_bool: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut int_bool))?;

            match int_bool {
                0 => Ok(false),
                _ => Ok(true),
            }
        }
    }

    /**
    The name of this `Device`, e.g. "Tesla C2070".

    The name is an alphanumeric string that denotes a particular product.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetName")]
    pub fn name(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetName.as_ref())?;

        unsafe {
            let mut name_vec = vec![0; NVML_DEVICE_NAME_V2_BUFFER_SIZE as usize];

            nvml_try(sym(
                self.device,
                name_vec.as_mut_ptr(),
                NVML_DEVICE_NAME_V2_BUFFER_SIZE,
            ))?;

            let name_raw = CStr::from_ptr(name_vec.as_ptr());
            Ok(name_raw.to_str()?.into())
        }
    }

    /**
    Gets the PCI attributes of this `Device`.

    See `PciInfo` for details about the returned attributes.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `GpuLost`, if the GPU has fallen off the bus or is otherwise inaccessible
    * `Utf8Error`, if a string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPciInfo_v3")]
    pub fn pci_info(&self) -> Result<PciInfo, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPciInfo_v3.as_ref())?;

        unsafe {
            let mut pci_info: nvmlPciInfo_t = mem::zeroed();
            nvml_try(sym(self.device, &mut pci_info))?;

            PciInfo::try_from(pci_info, true)
        }
    }

    /**
    Gets the PCIe replay counter.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPcieReplayCounter")]
    pub fn pcie_replay_counter(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPcieReplayCounter.as_ref())?;

        unsafe {
            let mut value: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut value))?;

            Ok(value)
        }
    }

    /**
    Gets PCIe utilization information in KB/s.

    The function called within this method is querying a byte counter over a 20ms
    interval and thus is the PCIE throughput over that interval.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or `counter` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Maxwell and newer fully supported devices.

    # Environment Support

    This method is not supported on virtual machines running vGPUs.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPcieThroughput")]
    pub fn pcie_throughput(&self, counter: PcieUtilCounter) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPcieThroughput.as_ref())?;

        unsafe {
            let mut throughput: c_uint = mem::zeroed();

            nvml_try(sym(self.device, counter.as_c(), &mut throughput))?;

            Ok(throughput)
        }
    }

    /**
    Gets the current performance state for this `Device`. 0 == max, 15 == min.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPerformanceState")]
    pub fn performance_state(&self) -> Result<PerformanceState, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPerformanceState.as_ref())?;

        unsafe {
            let mut state: nvmlPstates_t = mem::zeroed();
            nvml_try(sym(self.device, &mut state))?;

            PerformanceState::try_from(state)
        }
    }

    /**
    Gets whether or not persistent mode is enabled for this `Device`.

    When driver persistence mode is enabled the driver software is not torn down
    when the last client disconnects. This feature is disabled by default.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceGetPersistenceMode")]
    pub fn is_in_persistent_mode(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPersistenceMode.as_ref())?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();
            nvml_try(sym(self.device, &mut state))?;

            bool_from_state(state)
        }
    }

    /**
    Gets the default power management limit for this `Device`, in milliwatts.

    This is the limit that this `Device` boots with.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPowerManagementDefaultLimit")]
    pub fn power_management_limit_default(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetPowerManagementDefaultLimit
                .as_ref(),
        )?;

        unsafe {
            let mut limit: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut limit))?;

            Ok(limit)
        }
    }

    /**
    Gets the power management limit associated with this `Device`.

    The power limit defines the upper boundary for the card's power draw. If the card's
    total power draw reaches this limit, the power management algorithm kicks in.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi or newer fully supported devices.

    This reading is only supported if power management mode is supported. See
    `.is_power_management_algo_active()`. Yes, it's deprecated, but that's what
    NVIDIA's docs said to see.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPowerManagementLimit")]
    pub fn power_management_limit(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPowerManagementLimit.as_ref())?;

        unsafe {
            let mut limit: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut limit))?;

            Ok(limit)
        }
    }

    /**
    Gets information about possible power management limit values for this `Device`, in milliwatts.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPowerManagementLimitConstraints")]
    pub fn power_management_limit_constraints(
        &self,
    ) -> Result<PowerManagementConstraints, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetPowerManagementLimitConstraints
                .as_ref(),
        )?;

        unsafe {
            let mut min_limit: c_uint = mem::zeroed();
            let mut max_limit: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut min_limit, &mut max_limit))?;

            Ok(PowerManagementConstraints {
                min_limit,
                max_limit,
            })
        }
    }

    /// Not documenting this because it's deprecated. Read NVIDIA's docs if you
    /// must use it.
    // Tested
    #[deprecated(note = "NVIDIA states that \"this API has been deprecated.\"")]
    #[doc(alias = "nvmlDeviceGetPowerManagementMode")]
    pub fn is_power_management_algo_active(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPowerManagementMode.as_ref())?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();
            nvml_try(sym(self.device, &mut state))?;

            bool_from_state(state)
        }
    }

    /// Not documenting this because it's deprecated. Read NVIDIA's docs if you
    /// must use it.
    // Tested
    #[deprecated(note = "use `.performance_state()`.")]
    #[doc(alias = "nvmlDeviceGetPowerState")]
    pub fn power_state(&self) -> Result<PerformanceState, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPowerState.as_ref())?;

        unsafe {
            let mut state: nvmlPstates_t = mem::zeroed();
            nvml_try(sym(self.device, &mut state))?;

            PerformanceState::try_from(state)
        }
    }

    /**
    Gets the power usage for this GPU and its associated circuitry (memory) in milliwatts.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support power readings
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.

    This reading is accurate to within +/- 5% of current power draw on Fermi and Kepler GPUs.
    It is only supported if power management mode is supported. See `.is_power_management_algo_active()`.
    Yes, that is deprecated, but that's what NVIDIA's docs say to see.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetPowerUsage")]
    pub fn power_usage(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPowerUsage.as_ref())?;

        unsafe {
            let mut usage: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut usage))?;

            Ok(usage)
        }
    }

    /**
    Gets this device's total energy consumption in millijoules (mJ) since the last
    driver reload.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support energy readings
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Volta and newer fully supported devices.
    */
    #[doc(alias = "nvmlDeviceGetTotalEnergyConsumption")]
    pub fn total_energy_consumption(&self) -> Result<u64, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetTotalEnergyConsumption.as_ref())?;

        unsafe {
            let mut total: c_ulonglong = mem::zeroed();
            nvml_try(sym(self.device, &mut total))?;

            Ok(total)
        }
    }

    /**
    Gets the list of retired pages filtered by `cause`, including pages pending retirement.

    **I cannot verify that this method will work because the call within is not supported
    on my dev machine**. Please **verify for yourself** that it works before you use it.
    If you are able to test it on your machine, please let me know if it works; if it
    doesn't, I would love a PR.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetRetiredPages_v2")]
    pub fn retired_pages(&self, cause: RetirementCause) -> Result<Vec<RetiredPage>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetRetiredPages_v2.as_ref())?;

        unsafe {
            let mut count = match self.retired_pages_count(&cause)? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut addresses: Vec<c_ulonglong> = vec![mem::zeroed(); count as usize];
            let mut timestamps: Vec<c_ulonglong> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(
                self.device,
                cause.as_c(),
                &mut count,
                addresses.as_mut_ptr(),
                timestamps.as_mut_ptr(),
            ))?;

            Ok(addresses
                .into_iter()
                .zip(timestamps)
                .map(|(address, timestamp)| RetiredPage { address, timestamp })
                .collect())
        }
    }

    // Helper for the above function. Returns # of samples that can be queried.
    fn retired_pages_count(&self, cause: &RetirementCause) -> Result<c_uint, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetRetiredPages.as_ref())?;

        unsafe {
            let mut count: c_uint = 0;

            nvml_try(sym(
                self.device,
                cause.as_c(),
                &mut count,
                // All NVIDIA says is that this
                // can't be null.
                &mut mem::zeroed(),
            ))?;

            Ok(count)
        }
    }

    /**
    Gets whether there are pages pending retirement (they need a reboot to fully retire).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetRetiredPagesPendingStatus")]
    pub fn are_pages_pending_retired(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetRetiredPagesPendingStatus
                .as_ref(),
        )?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();

            nvml_try(sym(self.device, &mut state))?;

            bool_from_state(state)
        }
    }

    /**
    Gets recent samples for this `Device`.

    `last_seen_timestamp` represents the CPU timestamp in μs. Passing in `None`
    will fetch all samples maintained in the underlying buffer; you can
    alternatively pass in a timestamp retrieved from the date of the previous
    query in order to obtain more recent samples.

    The advantage of using this method for samples in contrast to polling via
    existing methods is to get higher frequency data at a lower polling cost.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `NotFound`, if sample entries are not found
    * `UnexpectedVariant`, check that error's docs for more info
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.

    # Examples

    ```
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # fn main() -> Result<(), NvmlError> {
    # match test() {
    # Err(NvmlError::NotFound) => Ok(()),
    # other => other,
    # }
    # }
    # fn test() -> Result<(), NvmlError> {
    # let nvml = Nvml::init()?;
    # let device = nvml.device_by_index(0)?;
    use nvml_wrapper::enum_wrappers::device::Sampling;

    // Passing `None` indicates that we want all `Power` samples in the sample buffer
    let power_samples = device.samples(Sampling::Power, None)?;

    // Take the first sample from the vector, if it exists...
    if let Some(sample) = power_samples.get(0) {
        // ...and now we can get all `ProcessorClock` samples that exist with a later
        // timestamp than the `Power` sample.
        let newer_clock_samples = device.samples(Sampling::ProcessorClock, sample.timestamp)?;
    }
    # Ok(())
    # }
    ```
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetSamples")]
    pub fn samples<T>(
        &self,
        sample_type: Sampling,
        last_seen_timestamp: T,
    ) -> Result<Vec<Sample>, NvmlError>
    where
        T: Into<Option<u64>>,
    {
        let timestamp = last_seen_timestamp.into().unwrap_or(0);
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetSamples.as_ref())?;

        unsafe {
            let mut val_type: nvmlValueType_t = mem::zeroed();
            let mut count = match self.samples_count(&sample_type, timestamp)? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut samples: Vec<nvmlSample_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(
                self.device,
                sample_type.as_c(),
                timestamp,
                &mut val_type,
                &mut count,
                samples.as_mut_ptr(),
            ))?;

            let val_type_rust = SampleValueType::try_from(val_type)?;
            Ok(samples
                .into_iter()
                .map(|s| Sample::from_tag_and_struct(&val_type_rust, s))
                .collect())
        }
    }

    // Helper for the above function. Returns # of samples that can be queried.
    fn samples_count(&self, sample_type: &Sampling, timestamp: u64) -> Result<c_uint, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetSamples.as_ref())?;

        unsafe {
            let mut val_type: nvmlValueType_t = mem::zeroed();
            let mut count: c_uint = mem::zeroed();

            nvml_try(sym(
                self.device,
                sample_type.as_c(),
                timestamp,
                &mut val_type,
                &mut count,
                // Indicates that we want the count
                ptr::null_mut(),
            ))?;

            Ok(count)
        }
    }

    /**
    Get values for the given slice of `FieldId`s.

    NVIDIA's docs say that if any of the `FieldId`s are populated by the same driver
    call, the samples for those IDs will be populated by a single call instead of
    a call per ID. It would appear, then, that this is essentially a "batch-request"
    API path for better performance.

    There are too many field ID constants defined in the header to reasonably
    wrap them with an enum in this crate. Instead, I've re-exported the defined
    ID constants at `nvml_wrapper::sys_exports::field_id::*`; stick those
    constants in `FieldId`s for use with this function.

    # Errors

    ## Outer `Result`

    * `InvalidArg`, if `id_slice` has a length of zero

    ## Inner `Result`

    * `UnexpectedVariant`, check that error's docs for more info

    # Device Support

    Device support varies per `FieldId` that you pass in.
    */
    // TODO: Example
    #[doc(alias = "nvmlDeviceGetFieldValues")]
    pub fn field_values_for(
        &self,
        id_slice: &[FieldId],
    ) -> Result<Vec<Result<FieldValueSample, NvmlError>>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetFieldValues.as_ref())?;

        unsafe {
            let values_count = id_slice.len();
            let mut field_values: Vec<nvmlFieldValue_t> = Vec::with_capacity(values_count);

            for id in id_slice.iter() {
                let mut raw: nvmlFieldValue_t = mem::zeroed();
                raw.fieldId = id.0;

                field_values.push(raw);
            }

            nvml_try(sym(
                self.device,
                values_count as i32,
                field_values.as_mut_ptr(),
            ))?;

            Ok(field_values
                .into_iter()
                .map(FieldValueSample::try_from)
                .collect())
        }
    }

    /**
    Gets the globally unique board serial number associated with this `Device`'s board
    as an alphanumeric string.

    This serial number matches the serial number tag that is physically attached to the board.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all products with an infoROM.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetSerial")]
    pub fn serial(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetSerial.as_ref())?;

        unsafe {
            let mut serial_vec = vec![0; NVML_DEVICE_SERIAL_BUFFER_SIZE as usize];

            nvml_try(sym(
                self.device,
                serial_vec.as_mut_ptr(),
                NVML_DEVICE_SERIAL_BUFFER_SIZE,
            ))?;

            let serial_raw = CStr::from_ptr(serial_vec.as_ptr());
            Ok(serial_raw.to_str()?.into())
        }
    }

    /**
    Gets the board part number for this `Device`.

    The board part number is programmed into the board's infoROM.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if the necessary VBIOS fields have not been filled
    * `GpuLost`, if the target GPU has fellen off the bus or is otherwise inaccessible
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetBoardPartNumber")]
    pub fn board_part_number(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetBoardPartNumber.as_ref())?;

        unsafe {
            let mut part_num_vec = vec![0; NVML_DEVICE_PART_NUMBER_BUFFER_SIZE as usize];

            nvml_try(sym(
                self.device,
                part_num_vec.as_mut_ptr(),
                NVML_DEVICE_PART_NUMBER_BUFFER_SIZE,
            ))?;

            let part_num_raw = CStr::from_ptr(part_num_vec.as_ptr());
            Ok(part_num_raw.to_str()?.into())
        }
    }

    /**
    Gets current throttling reasons.

    Note that multiple reasons can be affecting clocks at once.

    The returned bitmask is created via the `ThrottleReasons::from_bits_truncate`
    method, meaning that any bits that don't correspond to flags present in this
    version of the wrapper will be dropped.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all _fully supported_ devices.
    */
    // Checked against local.
    // Tested
    #[doc(alias = "nvmlDeviceGetCurrentClocksThrottleReasons")]
    pub fn current_throttle_reasons(&self) -> Result<ThrottleReasons, NvmlError> {
        Ok(ThrottleReasons::from_bits_truncate(
            self.current_throttle_reasons_raw()?,
        ))
    }

    /**
    Gets current throttling reasons, erroring if any bits correspond to
    non-present flags.

    Note that multiple reasons can be affecting clocks at once.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `IncorrectBits`, if NVML returns any bits that do not correspond to flags in
    `ThrottleReasons`
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all _fully supported_ devices.
    */
    // Checked against local.
    // Tested
    pub fn current_throttle_reasons_strict(&self) -> Result<ThrottleReasons, NvmlError> {
        let reasons = self.current_throttle_reasons_raw()?;

        ThrottleReasons::from_bits(reasons).ok_or(NvmlError::IncorrectBits(Bits::U64(reasons)))
    }

    // Helper for the above methods.
    fn current_throttle_reasons_raw(&self) -> Result<c_ulonglong, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetCurrentClocksThrottleReasons
                .as_ref(),
        )?;

        unsafe {
            let mut reasons: c_ulonglong = mem::zeroed();

            nvml_try(sym(self.device, &mut reasons))?;

            Ok(reasons)
        }
    }

    /**
    Gets a bitmask of the supported throttle reasons.

    These reasons can be returned by `.current_throttle_reasons()`.

    The returned bitmask is created via the `ThrottleReasons::from_bits_truncate`
    method, meaning that any bits that don't correspond to flags present in this
    version of the wrapper will be dropped.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all _fully supported_ devices.

    # Environment Support

    This method is not supported on virtual machines running vGPUs.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetSupportedClocksThrottleReasons")]
    pub fn supported_throttle_reasons(&self) -> Result<ThrottleReasons, NvmlError> {
        Ok(ThrottleReasons::from_bits_truncate(
            self.supported_throttle_reasons_raw()?,
        ))
    }

    /**
    Gets a bitmask of the supported throttle reasons, erroring if any bits
    correspond to non-present flags.

    These reasons can be returned by `.current_throttle_reasons()`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `IncorrectBits`, if NVML returns any bits that do not correspond to flags in
    `ThrottleReasons`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports all _fully supported_ devices.

    # Environment Support

    This method is not supported on virtual machines running vGPUs.
    */
    // Checked against local
    // Tested
    pub fn supported_throttle_reasons_strict(&self) -> Result<ThrottleReasons, NvmlError> {
        let reasons = self.supported_throttle_reasons_raw()?;

        ThrottleReasons::from_bits(reasons).ok_or(NvmlError::IncorrectBits(Bits::U64(reasons)))
    }

    // Helper for the above methods.
    fn supported_throttle_reasons_raw(&self) -> Result<c_ulonglong, NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceGetSupportedClocksThrottleReasons
                .as_ref(),
        )?;
        unsafe {
            let mut reasons: c_ulonglong = mem::zeroed();

            nvml_try(sym(self.device, &mut reasons))?;

            Ok(reasons)
        }
    }

    /**
    Gets a `Vec` of possible graphics clocks that can be used as an arg for
    `set_applications_clocks()`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotFound`, if the specified `for_mem_clock` is not a supported frequency
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetSupportedGraphicsClocks")]
    pub fn supported_graphics_clocks(&self, for_mem_clock: u32) -> Result<Vec<u32>, NvmlError> {
        match self.supported_graphics_clocks_manual(for_mem_clock, 128) {
            Err(NvmlError::InsufficientSize(Some(s))) =>
            // `s` is the required size for the call; make the call a second time
            {
                self.supported_graphics_clocks_manual(for_mem_clock, s)
            }
            value => value,
        }
    }

    // Removes code duplication in the above function.
    fn supported_graphics_clocks_manual(
        &self,
        for_mem_clock: u32,
        size: usize,
    ) -> Result<Vec<u32>, NvmlError> {
        let mut items: Vec<c_uint> = vec![0; size];
        let mut count = size as c_uint;

        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetSupportedGraphicsClocks.as_ref())?;

        unsafe {
            match sym(self.device, for_mem_clock, &mut count, items.as_mut_ptr()) {
                // `count` is now the size that is required. Return it in the error.
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => {
                    return Err(NvmlError::InsufficientSize(Some(count as usize)))
                }
                value => nvml_try(value)?,
            }
        }

        items.truncate(count as usize);
        Ok(items)
    }

    /**
    Gets a `Vec` of possible memory clocks that can be used as an arg for
    `set_applications_clocks()`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` doesn't support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetSupportedMemoryClocks")]
    pub fn supported_memory_clocks(&self) -> Result<Vec<u32>, NvmlError> {
        match self.supported_memory_clocks_manual(16) {
            Err(NvmlError::InsufficientSize(Some(s))) => {
                // `s` is the required size for the call; make the call a second time
                self.supported_memory_clocks_manual(s)
            }
            value => value,
        }
    }

    // Removes code duplication in the above function.
    fn supported_memory_clocks_manual(&self, size: usize) -> Result<Vec<u32>, NvmlError> {
        let mut items: Vec<c_uint> = vec![0; size];
        let mut count = size as c_uint;

        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetSupportedMemoryClocks.as_ref())?;

        unsafe {
            match sym(self.device, &mut count, items.as_mut_ptr()) {
                // `count` is now the size that is required. Return it in the error.
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => {
                    return Err(NvmlError::InsufficientSize(Some(count as usize)))
                }
                value => nvml_try(value)?,
            }
        }

        items.truncate(count as usize);
        Ok(items)
    }

    /**
    Gets the current temperature readings for the given sensor, in °C.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or `sensor` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not have the specified sensor
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetTemperature")]
    pub fn temperature(&self, sensor: TemperatureSensor) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetTemperature.as_ref())?;

        unsafe {
            let mut temp: c_uint = mem::zeroed();

            nvml_try(sym(self.device, sensor.as_c(), &mut temp))?;

            Ok(temp)
        }
    }

    /**
    Gets the temperature threshold for this `Device` and the specified `threshold_type`, in °C.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or `threshold_type` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not have a temperature sensor or is unsupported
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetTemperatureThreshold")]
    pub fn temperature_threshold(
        &self,
        threshold_type: TemperatureThreshold,
    ) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetTemperatureThreshold.as_ref())?;

        unsafe {
            let mut temp: c_uint = mem::zeroed();

            nvml_try(sym(self.device, threshold_type.as_c(), &mut temp))?;

            Ok(temp)
        }
    }

    /**
    Gets the common ancestor for two devices.

    # Errors

    * `InvalidArg`, if either `Device` is invalid
    * `NotSupported`, if this `Device` or the OS does not support this feature
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, an error has occurred in the underlying topology discovery

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceGetTopologyCommonAncestor")]
    pub fn topology_common_ancestor(
        &self,
        other_device: Device,
    ) -> Result<TopologyLevel, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetTopologyCommonAncestor.as_ref())?;

        unsafe {
            let mut level: nvmlGpuTopologyLevel_t = mem::zeroed();

            nvml_try(sym(self.device, other_device.device, &mut level))?;

            TopologyLevel::try_from(level)
        }
    }

    /**
    Gets the set of GPUs that are nearest to this `Device` at a specific interconnectivity level.

    # Errors

    * `InvalidArg`, if this `Device` is invalid or `level` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` or the OS does not support this feature
    * `Unknown`, an error has occurred in the underlying topology discovery

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceGetTopologyNearestGpus")]
    pub fn topology_nearest_gpus(
        &self,
        level: TopologyLevel,
    ) -> Result<Vec<Device<'nvml>>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetTopologyNearestGpus.as_ref())?;

        unsafe {
            let mut count = match self.top_nearest_gpus_count(&level)? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut gpus: Vec<nvmlDevice_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(
                self.device,
                level.as_c(),
                &mut count,
                gpus.as_mut_ptr(),
            ))?;

            Ok(gpus
                .into_iter()
                .map(|d| Device::new(d, self.nvml))
                .collect())
        }
    }

    // Helper for the above function. Returns # of GPUs in the set.
    #[cfg(target_os = "linux")]
    fn top_nearest_gpus_count(&self, level: &TopologyLevel) -> Result<c_uint, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetTopologyNearestGpus.as_ref())?;

        unsafe {
            let mut count: c_uint = 0;

            nvml_try(sym(
                self.device,
                level.as_c(),
                &mut count,
                // Passing null (I assume?)
                // indicates that we want the
                // GPU count
                ptr::null_mut(),
            ))?;

            Ok(count)
        }
    }

    /**
    Gets the total ECC error counts for this `Device`.

    Only applicable to devices with ECC. The total error count is the sum of errors across
    each of the separate memory systems, i.e. the total set of errors across the entire device.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or either enum is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices. Requires `InfoRom::ECC` version 1.0
    or higher. Requires ECC mode to be enabled.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceGetTotalEccErrors")]
    pub fn total_ecc_errors(
        &self,
        error_type: MemoryError,
        counter_type: EccCounter,
    ) -> Result<u64, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetTotalEccErrors.as_ref())?;

        unsafe {
            let mut count: c_ulonglong = mem::zeroed();

            nvml_try(sym(
                self.device,
                error_type.as_c(),
                counter_type.as_c(),
                &mut count,
            ))?;

            Ok(count)
        }
    }

    /**
    Gets the globally unique immutable UUID associated with this `Device` as a 5 part
    hexadecimal string.

    This UUID augments the immutable, board serial identifier. It is a globally unique
    identifier and is the _only_ available identifier for pre-Fermi-architecture products.
    It does NOT correspond to any identifier printed on the board.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    * `Unknown`, on any unexpected error

    # Examples

    The UUID can be used to compare two `Device`s and find out if they represent
    the same physical device:

    ```no_run
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # fn main() -> Result<(), NvmlError> {
    # let nvml = Nvml::init()?;
    # let device1 = nvml.device_by_index(0)?;
    # let device2 = nvml.device_by_index(1)?;
    if device1.uuid()? == device2.uuid()? {
        println!("`device1` represents the same physical device that `device2` does.");
    }
    # Ok(())
    # }
    ```
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetUUID")]
    pub fn uuid(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetUUID.as_ref())?;

        unsafe {
            let mut uuid_vec = vec![0; NVML_DEVICE_UUID_V2_BUFFER_SIZE as usize];

            nvml_try(sym(
                self.device,
                uuid_vec.as_mut_ptr(),
                NVML_DEVICE_UUID_V2_BUFFER_SIZE,
            ))?;

            let uuid_raw = CStr::from_ptr(uuid_vec.as_ptr());
            Ok(uuid_raw.to_str()?.into())
        }
    }

    /**
    Gets the current utilization rates for this `Device`'s major subsystems.

    Note: During driver initialization when ECC is enabled, one can see high GPU
    and memory utilization readings. This is caused by the ECC memory scrubbing
    mechanism that is performed during driver initialization.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetUtilizationRates")]
    pub fn utilization_rates(&self) -> Result<Utilization, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetUtilizationRates.as_ref())?;

        unsafe {
            let mut utilization: nvmlUtilization_t = mem::zeroed();
            nvml_try(sym(self.device, &mut utilization))?;

            Ok(utilization.into())
        }
    }

    /**
    Gets the VBIOS version of this `Device`.

    The VBIOS version may change from time to time.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Utf8Error`, if the string obtained from the C function is not valid UTF-8
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetVbiosVersion")]
    pub fn vbios_version(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetVbiosVersion.as_ref())?;

        unsafe {
            let mut version_vec = vec![0; NVML_DEVICE_VBIOS_VERSION_BUFFER_SIZE as usize];

            nvml_try(sym(
                self.device,
                version_vec.as_mut_ptr(),
                NVML_DEVICE_VBIOS_VERSION_BUFFER_SIZE,
            ))?;

            let version_raw = CStr::from_ptr(version_vec.as_ptr());
            Ok(version_raw.to_str()?.into())
        }
    }

    /**
    Gets the duration of time during which this `Device` was throttled (lower than the
    requested clocks) due to power or thermal constraints.

    This is important to users who are trying to understand if their GPUs throttle at any
    point while running applications. The difference in violation times at two different
    reference times gives the indication of a GPU throttling event.

    Violation for thermal capping is not supported at this time.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if this `Device` is invalid or `perf_policy` is invalid (shouldn't occur?)
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible

    # Device Support

    Supports Kepler or newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetViolationStatus")]
    pub fn violation_status(
        &self,
        perf_policy: PerformancePolicy,
    ) -> Result<ViolationTime, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetViolationStatus.as_ref())?;
        unsafe {
            let mut viol_time: nvmlViolationTime_t = mem::zeroed();

            nvml_try(sym(self.device, perf_policy.as_c(), &mut viol_time))?;

            Ok(viol_time.into())
        }
    }

    /**
    Gets the interrupt number for this [`Device`].

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    */
    #[doc(alias = "nvmlDeviceGetIrqNum")]
    pub fn irq_num(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetIrqNum.as_ref())?;

        let irq_num = unsafe {
            let mut irq_num: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut irq_num))?;

            irq_num
        };

        Ok(irq_num)
    }

    /**
    Gets the core count for this [`Device`].

    The cores represented in the count here are commonly referred to as
    "CUDA cores".

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    */
    #[doc(alias = "nvmlDeviceGetNumGpuCores")]
    pub fn num_cores(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetNumGpuCores.as_ref())?;

        unsafe {
            let mut count: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut count))?;

            Ok(count)
        }
    }

    /**
    Gets the power source of this [`Device`].

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    */
    #[doc(alias = "nvmlDeviceGetPowerSource")]
    pub fn power_source(&self) -> Result<PowerSource, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPowerSource.as_ref())?;

        let power_source_c = unsafe {
            let mut power_source: nvmlPowerSource_t = mem::zeroed();

            nvml_try(sym(self.device, &mut power_source))?;

            power_source
        };

        PowerSource::try_from(power_source_c)
    }

    /**
    Gets the memory bus width of this [`Device`].

    The returned value is in bits (i.e. 320 for a 320-bit bus width).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    */
    #[doc(alias = "nvmlDeviceGetMemoryBusWidth")]
    pub fn memory_bus_width(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetMemoryBusWidth.as_ref())?;

        let memory_bus_width = unsafe {
            let mut memory_bus_width: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut memory_bus_width))?;

            memory_bus_width
        };

        Ok(memory_bus_width)
    }

    /**
    Gets the max PCIe link speed for this [`Device`].

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    */
    #[doc(alias = "nvmlDeviceGetPcieLinkMaxSpeed")]
    pub fn max_pcie_link_speed(&self) -> Result<PcieLinkMaxSpeed, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPcieLinkMaxSpeed.as_ref())?;

        let pcie_link_max_speed_c = unsafe {
            let mut pcie_link_max_speed: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut pcie_link_max_speed))?;

            pcie_link_max_speed
        };

        PcieLinkMaxSpeed::try_from(pcie_link_max_speed_c)
    }

    /**
    Gets the current PCIe link speed for this [`Device`].

    NVML docs say the returned value is in "MBPS". Looking at the output of
    this function, however, seems to imply it actually returns the transfer
    rate per lane of the PCIe link in MT/s, not the combined multi-lane
    throughput. See [`PcieLinkMaxSpeed`] for the same discussion.

    For example, on my machine currently:

    > Right now the device is connected via a PCIe gen 4 x16 interface and
    > `pcie_link_speed()` returns 16000

    This lines up with the "transfer rate per lane numbers" listed at
    <https://en.wikipedia.org/wiki/PCI_Express>. PCIe gen 4 provides 16.0 GT/s.
    Also, checking my machine at a different moment yields:

    > Right now the device is connected via a PCIe gen 2 x16 interface and
    > `pcie_link_speed()` returns 5000

    Which again lines up with the table on the page above; PCIe gen 2 provides
    5.0 GT/s.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this query is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    */
    #[doc(alias = "nvmlDeviceGetPcieSpeed")]
    pub fn pcie_link_speed(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetPcieSpeed.as_ref())?;

        let pcie_speed_c = unsafe {
            let mut pcie_speed: c_uint = mem::zeroed();

            nvml_try(sym(self.device, &mut pcie_speed))?;

            pcie_speed
        };

        Ok(pcie_speed_c)
    }

    /**
    Gets the type of bus by which this [`Device`] is connected.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    */
    #[doc(alias = "nvmlDeviceGetBusType")]
    pub fn bus_type(&self) -> Result<BusType, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetBusType.as_ref())?;

        let bus_type_c = unsafe {
            let mut bus_type: nvmlBusType_t = mem::zeroed();

            nvml_try(sym(self.device, &mut bus_type))?;

            bus_type
        };

        BusType::try_from(bus_type_c)
    }

    /**
    Gets the architecture of this [`Device`].

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    */
    #[doc(alias = "nvmlDeviceGetArchitecture")]
    pub fn architecture(&self) -> Result<DeviceArchitecture, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetArchitecture.as_ref())?;

        let architecture_c = unsafe {
            let mut architecture: nvmlDeviceArchitecture_t = mem::zeroed();

            nvml_try(sym(self.device, &mut architecture))?;

            architecture
        };

        DeviceArchitecture::try_from(architecture_c)
    }

    /**
    Checks if this `Device` and the passed-in device are on the same physical board.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if either `Device` is invalid
    * `NotSupported`, if this check is not supported by this `Device`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceOnSameBoard")]
    pub fn is_on_same_board_as(&self, other_device: &Device) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceOnSameBoard.as_ref())?;

        unsafe {
            let mut bool_int: c_int = mem::zeroed();

            nvml_try(sym(self.device, other_device.handle(), &mut bool_int))?;

            #[allow(clippy::match_like_matches_macro)]
            Ok(match bool_int {
                0 => false,
                _ => true,
            })
        }
    }

    /**
    Resets the application clock to the default value.

    This is the applications clock that will be used after a system reboot or a driver
    reload. The default value is a constant, but the current value be changed with
    `.set_applications_clocks()`.

    On Pascal and newer hardware, if clocks were previously locked with
    `.set_applications_clocks()`, this call will unlock clocks. This returns clocks
    to their default behavior of automatically boosting above base clocks as
    thermal limits allow.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer non-GeForce fully supported devices and Maxwell or newer
    GeForce devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceResetApplicationsClocks")]
    pub fn reset_applications_clocks(&mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceResetApplicationsClocks.as_ref())?;

        unsafe { nvml_try(sym(self.device)) }
    }

    /**
    Try to set the current state of auto boosted clocks on this `Device`.

    Auto boosted clocks are enabled by default on some hardware, allowing the GPU to run
    as fast as thermals will allow it to. Auto boosted clocks should be disabled if fixed
    clock rates are desired.

    On Pascal and newer hardware, auto boosted clocks are controlled through application
    clocks. Use `.set_applications_clocks()` and `.reset_applications_clocks()` to control
    auto boost behavior.

    Non-root users may use this API by default, but access can be restricted by root using
    `.set_api_restriction()`.

    Note: persistence mode is required to modify the curent auto boost settings and
    therefore must be enabled.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support auto boosted clocks
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    Not sure why nothing is said about `NoPermission`.

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetAutoBoostedClocksEnabled")]
    pub fn set_auto_boosted_clocks(&mut self, enabled: bool) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetAutoBoostedClocksEnabled.as_ref())?;

        unsafe { nvml_try(sym(self.device, state_from_bool(enabled))) }
    }

    /**
    Sets the ideal affinity for the calling thread and `Device` based on the guidelines given in
    `.cpu_affinity()`.

    Currently supports up to 64 processors.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested (no-run)
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceSetCpuAffinity")]
    pub fn set_cpu_affinity(&mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetCpuAffinity.as_ref())?;

        unsafe { nvml_try(sym(self.device)) }
    }

    /**
    Try to set the default state of auto boosted clocks on this `Device`.

    This is the default state that auto boosted clocks will return to when no compute
    processes (e.g. CUDA application with an active context) are running.

    Requires root/admin permissions.

    Auto boosted clocks are enabled by default on some hardware, allowing the GPU to run
    as fast as thermals will allow it to. Auto boosted clocks should be disabled if fixed
    clock rates are desired.

    On Pascal and newer hardware, auto boosted clocks are controlled through application
    clocks. Use `.set_applications_clocks()` and `.reset_applications_clocks()` to control
    auto boost behavior.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NoPermission`, if the calling user does not have permission to change the default state
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support auto boosted clocks
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler or newer non-GeForce fully supported devices and Maxwell or newer
    GeForce devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetDefaultAutoBoostedClocksEnabled")]
    pub fn set_auto_boosted_clocks_default(&mut self, enabled: bool) -> Result<(), NvmlError> {
        let sym = nvml_sym(
            self.nvml
                .lib
                .nvmlDeviceSetDefaultAutoBoostedClocksEnabled
                .as_ref(),
        )?;

        unsafe {
            // Passing 0 because NVIDIA says flags are not supported yet
            nvml_try(sym(self.device, state_from_bool(enabled), 0))
        }
    }

    /**
    Reads the infoROM from this `Device`'s flash and verifies the checksum.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `CorruptedInfoROM`, if this `Device`'s infoROM is corrupted
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    Not sure why `InvalidArg` is not mentioned.

    # Device Support

    Supports all devices with an infoROM.
    */
    // Checked against local
    // Tested on machines other than my own
    #[doc(alias = "nvmlDeviceValidateInforom")]
    pub fn validate_info_rom(&self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceValidateInforom.as_ref())?;

        unsafe { nvml_try(sym(self.device)) }
    }

    // Wrappers for things from Accounting Statistics now

    /**
    Clears accounting information about all processes that have already terminated.

    Requires root/admin permissions.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceClearAccountingPids")]
    pub fn clear_accounting_pids(&mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceClearAccountingPids.as_ref())?;

        unsafe { nvml_try(sym(self.device)) }
    }

    /**
    Gets the number of processes that the circular buffer with accounting PIDs can hold
    (in number of elements).

    This is the max number of processes that accounting information will be stored for
    before the oldest process information will get overwritten by information
    about new processes.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature or accounting mode
    is disabled
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetAccountingBufferSize")]
    pub fn accounting_buffer_size(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetAccountingBufferSize.as_ref())?;

        unsafe {
            let mut count: c_uint = mem::zeroed();
            nvml_try(sym(self.device, &mut count))?;

            Ok(count)
        }
    }

    /**
    Gets whether or not per-process accounting mode is enabled.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetAccountingMode")]
    pub fn is_accounting_enabled(&self) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetAccountingMode.as_ref())?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();
            nvml_try(sym(self.device, &mut state))?;

            bool_from_state(state)
        }
    }

    /**
    Gets the list of processes that can be queried for accounting stats.

    The list of processes returned can be in running or terminated state. Note that
    in the case of a PID collision some processes might not be accessible before
    the circular buffer is full.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature or accounting
    mode is disabled
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetAccountingPids")]
    pub fn accounting_pids(&self) -> Result<Vec<u32>, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetAccountingPids.as_ref())?;

        unsafe {
            let mut count = match self.accounting_pids_count()? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut pids: Vec<c_uint> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(self.device, &mut count, pids.as_mut_ptr()))?;

            Ok(pids)
        }
    }

    // Helper function for the above.
    fn accounting_pids_count(&self) -> Result<c_uint, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetAccountingPids.as_ref())?;

        unsafe {
            // Indicates that we want the count
            let mut count: c_uint = 0;

            // Null also indicates that we want the count
            match sym(self.device, &mut count, ptr::null_mut()) {
                // List is empty
                nvmlReturn_enum_NVML_SUCCESS => Ok(0),
                // Count is set to pids count
                nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => Ok(count),
                // We know this is an error
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets a process's accounting stats.

    Accounting stats capture GPU utilization and other statistics across the lifetime
    of a process. Accounting stats can be queried during the lifetime of the process
    and after its termination. The `time` field in `AccountingStats` is reported as
    zero during the lifetime of the process and updated to the actual running time
    after its termination.

    Accounting stats are kept in a circular buffer; newly created processes overwrite
    information regarding old processes.

    Note:
    * Accounting mode needs to be on. See `.is_accounting_enabled()`.
    * Only compute and graphics applications stats can be queried. Monitoring
    applications can't be queried since they don't contribute to GPU utilization.
    * If a PID collision occurs, the stats of the latest process (the one that
    terminated last) will be reported.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotFound`, if the process stats were not found
    * `NotSupported`, if this `Device` does not support this feature or accounting
    mode is disabled
    * `Unknown`, on any unexpected error

    # Device Support

    Suports Kepler and newer fully supported devices.

    # Warning

    On Kepler devices, per-process stats are accurate _only if_ there's one process
    running on this `Device`.
    */
    // Checked against local
    // Tested (for error)
    #[doc(alias = "nvmlDeviceGetAccountingStats")]
    pub fn accounting_stats_for(&self, process_id: u32) -> Result<AccountingStats, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetAccountingStats.as_ref())?;

        unsafe {
            let mut stats: nvmlAccountingStats_t = mem::zeroed();

            nvml_try(sym(self.device, process_id, &mut stats))?;

            Ok(stats.into())
        }
    }

    /**
    Enables or disables per-process accounting.

    Requires root/admin permissions.

    Note:
    * This setting is not persistent and will default to disabled after the driver
    unloads. Enable persistence mode to be sure the setting doesn't switch off
    to disabled.
    * Enabling accounting mode has no negative impact on GPU performance.
    * Disabling accounting clears accounting information for all PIDs

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetAccountingMode")]
    pub fn set_accounting(&mut self, enabled: bool) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetAccountingMode.as_ref())?;

        unsafe { nvml_try(sym(self.device, state_from_bool(enabled))) }
    }

    // Device commands starting here

    /**
    Clears the ECC error and other memory error counts for this `Device`.

    Sets all of the specified ECC counters to 0, including both detailed and total counts.
    This operation takes effect immediately.

    Requires root/admin permissions and ECC mode to be enabled.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid or `counter_type` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices. Only applicable to devices with
    ECC. Requires `InfoRom::ECC` version 2.0 or higher to clear aggregate
    location-based ECC counts. Requires `InfoRom::ECC` version 1.0 or higher to
    clear all other ECC counts.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceClearEccErrorCounts")]
    pub fn clear_ecc_error_counts(&mut self, counter_type: EccCounter) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceClearEccErrorCounts.as_ref())?;

        unsafe { nvml_try(sym(self.device, counter_type.as_c())) }
    }

    /**
    Changes the root/admin restrictions on certain APIs.

    This method can be used by a root/admin user to give non root/admin users access
    to certain otherwise-restricted APIs. The new setting lasts for the lifetime of
    the NVIDIA driver; it is not persistent. See `.is_api_restricted()` to query
    current settings.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid or `api_type` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support changing API restrictions or
    this `Device` does not support the feature that API restrictions are being set for
    (e.g. enabling/disabling auto boosted clocks is not supported by this `Device`).
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetAPIRestriction")]
    pub fn set_api_restricted(&mut self, api_type: Api, restricted: bool) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetAPIRestriction.as_ref())?;

        unsafe {
            nvml_try(sym(
                self.device,
                api_type.as_c(),
                state_from_bool(restricted),
            ))
        }
    }

    /**
    Sets clocks that applications will lock to.

    Sets the clocks that compute and graphics applications will be running at. e.g.
    CUDA driver requests these clocks during context creation which means this
    property defines clocks at which CUDA applications will be running unless some
    overspec event occurs (e.g. over power, over thermal or external HW brake).

    Can be used as a setting to request constant performance. Requires root/admin
    permissions.

    On Pascal and newer hardware, this will automatically disable automatic boosting
    of clocks. On K80 and newer Kepler and Maxwell GPUs, users desiring fixed performance
    should also call `.set_auto_boosted_clocks(false)` to prevent clocks from automatically
    boosting above the clock value being set here.

    You can determine valid `mem_clock` and `graphics_clock` arg values via
    [`Self::supported_memory_clocks()`] and [`Self::supported_graphics_clocks()`].

    Note that after a system reboot or driver reload applications clocks go back
    to their default value.

    See also [`Self::set_mem_locked_clocks()`].

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid or the clocks are not a valid combo
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer non-GeForce fully supported devices and Maxwell or newer
    GeForce devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetApplicationsClocks")]
    pub fn set_applications_clocks(
        &mut self,
        mem_clock: u32,
        graphics_clock: u32,
    ) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetApplicationsClocks.as_ref())?;

        unsafe { nvml_try(sym(self.device, mem_clock, graphics_clock)) }
    }

    /**
    Sets the compute mode for this `Device`.

    The compute mode determines whether a GPU can be used for compute operations
    and whether it can be shared across contexts.

    This operation takes effect immediately. Under Linux it is not persistent
    across reboots and always resets to `Default`. Under Windows it is
    persistent.

    Under Windows, compute mode may only be set to `Default` when running in WDDM
    (physical display connected).

    Requires root/admin permissions.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid or `mode` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetComputeMode")]
    pub fn set_compute_mode(&mut self, mode: ComputeMode) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetComputeMode.as_ref())?;

        unsafe { nvml_try(sym(self.device, mode.as_c())) }
    }

    /**
    Sets the driver model for this `Device`.

    This operation takes effect after the next reboot. The model may only be
    set to WDDM when running in DEFAULT compute mode. Changing the model to
    WDDM is not supported when the GPU doesn't support graphics acceleration
    or will not support it after a reboot.

    On Windows platforms the device driver can run in either WDDM or WDM (TCC)
    mode. If a physical display is attached to a device it must run in WDDM mode.

    It is possible to force the change to WDM (TCC) while the display is still
    attached with a `Behavior` of `FORCE`. This should only be done if the host
    is subsequently powered down and the display is detached from this `Device`
    before the next reboot.

    Requires root/admin permissions.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid or `model` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.

    # Platform Support

    Only supports Windows.

    # Examples

    ```no_run
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # fn test() -> Result<(), NvmlError> {
    # let nvml = Nvml::init()?;
    # let mut device = nvml.device_by_index(0)?;
    use nvml_wrapper::bitmasks::Behavior;
    use nvml_wrapper::enum_wrappers::device::DriverModel;

    device.set_driver_model(DriverModel::WDM, Behavior::DEFAULT)?;

    // Force the change to WDM (TCC)
    device.set_driver_model(DriverModel::WDM, Behavior::FORCE)?;
    # Ok(())
    # }
    ```
    */
    // Checked against local
    // Tested (no-run)
    #[cfg(target_os = "windows")]
    #[doc(alias = "nvmlDeviceSetDriverModel")]
    pub fn set_driver_model(
        &mut self,
        model: DriverModel,
        flags: Behavior,
    ) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetDriverModel.as_ref())?;

        unsafe { nvml_try(sym(self.device, model.as_c(), flags.bits())) }
    }

    /**
    Lock this `Device`'s clocks to a specific frequency range.

    This setting supercedes application clock values and takes effect regardless
    of whether or not any CUDA apps are running. It can be used to request constant
    performance.

    After a system reboot or a driver reload the clocks go back to their default
    values.

    Requires root/admin permissions.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the provided minimum and maximum clocks are not a valid combo
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Volta and newer fully supported devices.
    */
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetGpuLockedClocks")]
    pub fn set_gpu_locked_clocks(
        &mut self,
        setting: GpuLockedClocksSetting,
    ) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetGpuLockedClocks.as_ref())?;

        let (min_clock_mhz, max_clock_mhz) = setting.into_min_and_max_clocks();

        unsafe { nvml_try(sym(self.device, min_clock_mhz, max_clock_mhz)) }
    }

    /**
    Reset this [`Device`]'s clocks to their default values.

    This resets to the same values that would be used after a reboot or driver
    reload (defaults to idle clocks but can be configured via
    [`Self::set_applications_clocks()`]).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Volta and newer fully supported devices.
    */
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceResetGpuLockedClocks")]
    pub fn reset_gpu_locked_clocks(&mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceResetGpuLockedClocks.as_ref())?;

        unsafe { nvml_try(sym(self.device)) }
    }

    /**
    Lock this [`Device`]'s memory clocks to a specific frequency range.

    This setting supercedes application clock values and takes effect regardless
    of whether or not any CUDA apps are running. It can be used to request
    constant performance. See also [`Self::set_applications_clocks()`].

    After a system reboot or a driver reload the clocks go back to their default
    values. See also [`Self::reset_mem_locked_clocks()`].

    You can use [`Self::supported_memory_clocks()`] to determine valid
    frequency combinations to pass into this call.

    # Device Support

    Supports Ampere and newer fully supported devices.
    */
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetMemoryLockedClocks")]
    pub fn set_mem_locked_clocks(
        &mut self,
        min_clock_mhz: u32,
        max_clock_mhz: u32,
    ) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetMemoryLockedClocks.as_ref())?;

        unsafe { nvml_try(sym(self.device, min_clock_mhz, max_clock_mhz)) }
    }

    /**
    Reset this [`Device`]'s memory clocks to their default values.

    This resets to the same values that would be used after a reboot or driver
    reload (defaults to idle clocks but can be configured via
    [`Self::set_applications_clocks()`]).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Ampere and newer fully supported devices.
    */
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceResetMemoryLockedClocks")]
    pub fn reset_mem_locked_clocks(&mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceResetMemoryLockedClocks.as_ref())?;

        unsafe { nvml_try(sym(self.device)) }
    }

    /**
    Set whether or not ECC mode is enabled for this `Device`.

    Requires root/admin permissions. Only applicable to devices with ECC.

    This operation takes effect after the next reboot.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Kepler and newer fully supported devices. Requires `InfoRom::ECC` version
    1.0 or higher.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetEccMode")]
    pub fn set_ecc(&mut self, enabled: bool) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetEccMode.as_ref())?;

        unsafe { nvml_try(sym(self.device, state_from_bool(enabled))) }
    }

    /**
    Sets the GPU operation mode for this `Device`.

    Requires root/admin permissions. Changing GOMs requires a reboot, a requirement
    that may be removed in the future.

    Compute only GOMs don't support graphics acceleration. Under Windows switching
    to these GOMs when the pending driver model is WDDM (physical display attached)
    is not supported.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid or `mode` is invalid (shouldn't occur?)
    * `NotSupported`, if this `Device` does not support GOMs or a specific mode
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports GK110 M-class and X-class Tesla products from the Kepler family. Modes
    `LowDP` and `AllOn` are supported on fully supported GeForce products. Not
    supported on Quadro and Tesla C-class products.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetGpuOperationMode")]
    pub fn set_gpu_op_mode(&mut self, mode: OperationMode) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetGpuOperationMode.as_ref())?;

        unsafe { nvml_try(sym(self.device, mode.as_c())) }
    }

    /**
    Sets the persistence mode for this `Device`.

    The persistence mode determines whether the GPU driver software is torn down
    after the last client exits.

    This operation takes effect immediately and requires root/admin permissions.
    It is not persistent across reboots; after each reboot it will default to
    disabled.

    Note that after disabling persistence on a device that has its own NUMA
    memory, this `Device` handle will no longer be valid, and to continue to
    interact with the physical device that it represents you will need to
    obtain a new `Device` using the methods available on the `Nvml` struct.
    This limitation is currently only applicable to devices that have a
    coherent NVLink connection to system memory.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid
    * `NotSupported`, if this `Device` does not support this feature
    * `NoPermission`, if the user doesn't have permission to perform this operation
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested (no-run)
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceSetPersistenceMode")]
    pub fn set_persistent(&mut self, enabled: bool) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetPersistenceMode.as_ref())?;

        unsafe { nvml_try(sym(self.device, state_from_bool(enabled))) }
    }

    /**
    Sets the power limit for this `Device`, in milliwatts.

    This limit is not persistent across reboots or driver unloads. Enable
    persistent mode to prevent the driver from unloading when no application
    is using this `Device`.

    Requires root/admin permissions. See `.power_management_limit_constraints()`
    to check the allowed range of values.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the `Device` is invalid or `limit` is out of range
    * `NotSupported`, if this `Device` does not support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    For some reason NVIDIA does not mention `NoPermission`.

    # Device Support

    Supports Kepler and newer fully supported devices.
    */
    // Checked against local
    // Tested (no-run)
    #[doc(alias = "nvmlDeviceSetPowerManagementLimit")]
    pub fn set_power_management_limit(&mut self, limit: u32) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceSetPowerManagementLimit.as_ref())?;

        unsafe { nvml_try(sym(self.device, limit)) }
    }

    // Event handling methods

    /**
    Starts recording the given `EventTypes` for this `Device` and adding them
    to the specified `EventSet`.

    Use `.supported_event_types()` to find out which events you can register for
    this `Device`.

    **Unfortunately, due to the way `error-chain` works, there is no way to
    return the set if it is still valid after an error has occured with the
    register call.** The set that you passed in will be freed if any error
    occurs and will not be returned to you. This is not desired behavior
    and I will fix it as soon as it is possible to do so.

    All events that occurred before this call was made will not be recorded.

    ECC events are only available on `Device`s with ECC enabled. Power capping events
    are only available on `Device`s with power management enabled.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if `events` is invalid (shouldn't occur?)
    * `NotSupported`, if the platform does not support this feature or some of the
    requested event types.
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error. **If this error is returned, the `set` you
    passed in has had its resources freed and will not be returned to you**. NVIDIA's
    docs say that this error means that the set is in an invalid state.

    # Device Support

    Supports Fermi and newer fully supported devices.

    # Platform Support

    Only supports Linux.

    # Examples

    ```
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # fn main() -> Result<(), NvmlErrorWithSource> {
    # let nvml = Nvml::init()?;
    # let device = nvml.device_by_index(0)?;
    use nvml_wrapper::bitmasks::event::EventTypes;

    let set = nvml.create_event_set()?;

    /*
    Register both `CLOCK_CHANGE` and `PSTATE_CHANGE`.

    `let set = ...` is a quick way to re-bind the set to the same variable, since
    `.register_events()` consumes the set in order to enforce safety and returns it
    if everything went well. It does *not* require `set` to be mutable as nothing
    is being mutated.
    */
    let set = device.register_events(
        EventTypes::CLOCK_CHANGE |
        EventTypes::PSTATE_CHANGE,
        set
    )?;
    # Ok(())
    # }
    ```
    */
    // Checked against local
    // Tested
    // Thanks to Thinkofname for helping resolve lifetime issues
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceRegisterEvents")]
    pub fn register_events(
        &self,
        events: EventTypes,
        set: EventSet<'nvml>,
    ) -> Result<EventSet<'nvml>, NvmlErrorWithSource> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceRegisterEvents.as_ref())?;

        unsafe {
            match nvml_try(sym(self.device, events.bits(), set.handle())) {
                Ok(()) => Ok(set),
                Err(NvmlError::Unknown) => {
                    // NVIDIA says that if an Unknown error is returned, `set` will
                    // be in an undefined state and should be freed.
                    if let Err(e) = set.release_events() {
                        return Err(NvmlErrorWithSource {
                            error: NvmlError::SetReleaseFailed,
                            source: Some(e),
                        });
                    }

                    Err(NvmlError::Unknown.into())
                }
                Err(e) => {
                    // TODO: return set here so you can use it again?
                    if let Err(e) = set.release_events() {
                        return Err(NvmlErrorWithSource {
                            error: NvmlError::SetReleaseFailed,
                            source: Some(e),
                        });
                    }

                    Err(e.into())
                }
            }
        }
    }

    /**
    Gets the `EventTypes` that this `Device` supports.

    The returned bitmask is created via the `EventTypes::from_bits_truncate`
    method, meaning that any bits that don't correspond to flags present in this
    version of the wrapper will be dropped.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.

    # Platform Support

    Only supports Linux.

    # Examples

    ```
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # fn main() -> Result<(), NvmlError> {
    # let nvml = Nvml::init()?;
    # let device = nvml.device_by_index(0)?;
    use nvml_wrapper::bitmasks::event::EventTypes;

    let supported = device.supported_event_types()?;

    if supported.contains(EventTypes::CLOCK_CHANGE) {
        println!("The `CLOCK_CHANGE` event is supported.");
    } else if supported.contains(
        EventTypes::SINGLE_BIT_ECC_ERROR |
        EventTypes::DOUBLE_BIT_ECC_ERROR
    ) {
        println!("All ECC error event types are supported.");
    }
    # Ok(())
    # }
    ```
    */
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceGetSupportedEventTypes")]
    pub fn supported_event_types(&self) -> Result<EventTypes, NvmlError> {
        Ok(EventTypes::from_bits_truncate(
            self.supported_event_types_raw()?,
        ))
    }

    /**
    Gets the `EventTypes` that this `Device` supports, erroring if any bits
    correspond to non-present flags.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `IncorrectBits`, if NVML returns any bits that do not correspond to flags in
    `EventTypes`
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.

    # Platform Support

    Only supports Linux.
    */
    // Tested
    #[cfg(target_os = "linux")]
    pub fn supported_event_types_strict(&self) -> Result<EventTypes, NvmlError> {
        let ev_types = self.supported_event_types_raw()?;

        EventTypes::from_bits(ev_types).ok_or(NvmlError::IncorrectBits(Bits::U64(ev_types)))
    }

    // Helper for the above methods.
    #[cfg(target_os = "linux")]
    fn supported_event_types_raw(&self) -> Result<c_ulonglong, NvmlError> {
        let sym = nvml_sym(self.nvml.lib.nvmlDeviceGetSupportedEventTypes.as_ref())?;

        unsafe {
            let mut ev_types: c_ulonglong = mem::zeroed();
            nvml_try(sym(self.device, &mut ev_types))?;

            Ok(ev_types)
        }
    }

    // Drain states

    /**
    Enable or disable drain state for this `Device`.

    If you pass `None` as `pci_info`, `.pci_info()` will be called in order to obtain
    `PciInfo` to be used within this method.

    Enabling drain state forces this `Device` to no longer accept new incoming requests.
    Any new NVML processes will no longer see this `Device`.

    Must be called as administrator. Persistence mode for this `Device` must be turned
    off before this call is made.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` doesn't support this feature
    * `NoPermission`, if the calling process has insufficient permissions to perform
    this operation
    * `InUse`, if this `Device` has persistence mode turned on
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    In addition, all of the errors returned by:

    * `.pci_info()`
    * `PciInfo.try_into()`

    # Device Support

    Supports Pascal and newer fully supported devices.

    Some Kepler devices are also supported (that's all NVIDIA says, no specifics).

    # Platform Support

    Only supports Linux.

    # Examples

    ```no_run
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # fn test() -> Result<(), NvmlError> {
    # let nvml = Nvml::init()?;
    # let mut device = nvml.device_by_index(0)?;
    // Pass `None`, `.set_drain()` call will grab `PciInfo` for us
    device.set_drain(true, None)?;

    let pci_info = device.pci_info()?;

    // Pass in our own `PciInfo`, call will use it instead
    device.set_drain(true, pci_info)?;
    # Ok(())
    # }
    ```
    */
    // Checked against local
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceModifyDrainState")]
    pub fn set_drain<T: Into<Option<PciInfo>>>(
        &mut self,
        enabled: bool,
        pci_info: T,
    ) -> Result<(), NvmlError> {
        let pci_info = if let Some(info) = pci_info.into() {
            info
        } else {
            self.pci_info()?
        };

        let sym = nvml_sym(self.nvml.lib.nvmlDeviceModifyDrainState.as_ref())?;

        unsafe { nvml_try(sym(&mut pci_info.try_into()?, state_from_bool(enabled))) }
    }

    /**
    Query the drain state of this `Device`.

    If you pass `None` as `pci_info`, `.pci_info()` will be called in order to obtain
    `PciInfo` to be used within this method.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` doesn't support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    In addition, all of the errors returned by:

    * `.pci_info()`
    * `PciInfo.try_into()`

    # Device Support

    Supports Pascal and newer fully supported devices.

    Some Kepler devices are also supported (that's all NVIDIA says, no specifics).

    # Platform Support

    Only supports Linux.

    # Examples

    ```
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # fn main() -> Result<(), NvmlError> {
    # let nvml = Nvml::init()?;
    # let mut device = nvml.device_by_index(0)?;
    // Pass `None`, `.is_drain_enabled()` call will grab `PciInfo` for us
    device.is_drain_enabled(None)?;

    let pci_info = device.pci_info()?;

    // Pass in our own `PciInfo`, call will use it instead
    device.is_drain_enabled(pci_info)?;
    # Ok(())
    # }
    ```
    */
    // Checked against local
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceQueryDrainState")]
    pub fn is_drain_enabled<T: Into<Option<PciInfo>>>(
        &self,
        pci_info: T,
    ) -> Result<bool, NvmlError> {
        let pci_info = if let Some(info) = pci_info.into() {
            info
        } else {
            self.pci_info()?
        };

        let sym = nvml_sym(self.nvml.lib.nvmlDeviceQueryDrainState.as_ref())?;

        unsafe {
            let mut state: nvmlEnableState_t = mem::zeroed();

            nvml_try(sym(&mut pci_info.try_into()?, &mut state))?;

            bool_from_state(state)
        }
    }

    /**
    Removes this `Device` from the view of both NVML and the NVIDIA kernel driver.

    If you pass `None` as `pci_info`, `.pci_info()` will be called in order to obtain
    `PciInfo` to be used within this method.

    This call only works if no other processes are attached. If other processes
    are attached when this is called, the `InUse` error will be returned and
    this `Device` will return to its original draining state. The only situation
    where this can occur is if a process was and is still using this `Device`
    before the call to `set_drain()` was made and it was enabled. Note that
    persistence mode counts as an attachment to this `Device` and thus must be
    disabled prior to this call.

    For long-running NVML processes, please note that this will change the
    enumeration of current GPUs. As an example, if there are four GPUs present
    and the first is removed, the new enumeration will be 0-2. Device handles
    for the removed GPU will be invalid.

    NVIDIA doesn't provide much documentation about the `gpu_state` and `link_state`
    parameters, so you're on your own there. It does say that the `gpu_state`
    controls whether or not this `Device` should be removed from the kernel.

    Must be run as administrator.

    # Bad Ergonomics Explanation

    Previously the design of `error-chain` made it impossible to return stuff
    with generic lifetime parameters. The crate's errors are now based on
    `std::error::Error`, so this situation no longer needs to be, but I haven't
    made time to re-work it.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `NotSupported`, if this `Device` doesn't support this feature
    * `GpuLost`, if this `Device` has fallen off the bus or is otherwise inaccessible
    * `InUse`, if this `Device` is still in use and cannot be removed

    In addition, all of the errors returned by:

    * `.pci_info()`
    * `PciInfo.try_into()`

    # Device Support

    Supports Pascal and newer fully supported devices.

    Some Kepler devices are also supported (that's all NVIDIA says, no specifics).

    # Platform Support

    Only supports Linux.

    # Examples

    How to handle error case:

    ```no_run
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # use nvml_wrapper::enum_wrappers::device::{DetachGpuState, PcieLinkState};
    # fn test() -> Result<(), NvmlError> {
    # let nvml = Nvml::init()?;
    # let mut device = nvml.device_by_index(0)?;
    match device.remove(None, DetachGpuState::Remove, PcieLinkState::ShutDown) {
        (Ok(()), None) => println!("Successful call, `Device` removed"),
        (Err(e), Some(d)) => println!("Unsuccessful call. `Device`: {:?}", d),
        _ => println!("Something else",)
    }
    # Ok(())
    # }
    ```
    Demonstration of the `pci_info` parameter's use:

    ```no_run
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    # use nvml_wrapper::enum_wrappers::device::{DetachGpuState, PcieLinkState};
    # fn test() -> Result<(), NvmlErrorWithSource> {
    # let nvml = Nvml::init()?;
    # let mut device = nvml.device_by_index(0)?;
    // Pass `None`, `.remove()` call will grab `PciInfo` for us
    device.remove(None, DetachGpuState::Remove, PcieLinkState::ShutDown).0?;

    # let mut device2 = nvml.device_by_index(0)?;
    // Different `Device` because `.remove()` consumes the `Device`
    let pci_info = device2.pci_info()?;

    // Pass in our own `PciInfo`, call will use it instead
    device2.remove(pci_info, DetachGpuState::Remove, PcieLinkState::ShutDown).0?;
    # Ok(())
    # }
    ```
    */
    // Checked against local
    // TODO: Fix ergonomics here when possible.
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceRemoveGpu_v2")]
    pub fn remove<T: Into<Option<PciInfo>>>(
        self,
        pci_info: T,
        gpu_state: DetachGpuState,
        link_state: PcieLinkState,
    ) -> (Result<(), NvmlErrorWithSource>, Option<Device<'nvml>>) {
        let pci_info = if let Some(info) = pci_info.into() {
            info
        } else {
            match self.pci_info() {
                Ok(info) => info,
                Err(error) => {
                    return (
                        Err(NvmlErrorWithSource {
                            error,
                            source: Some(NvmlError::GetPciInfoFailed),
                        }),
                        Some(self),
                    )
                }
            }
        };

        let mut raw_pci_info = match pci_info.try_into() {
            Ok(info) => info,
            Err(error) => {
                return (
                    Err(NvmlErrorWithSource {
                        error,
                        source: Some(NvmlError::PciInfoToCFailed),
                    }),
                    Some(self),
                )
            }
        };

        let sym = match nvml_sym(self.nvml.lib.nvmlDeviceRemoveGpu_v2.as_ref()) {
            Ok(sym) => sym,
            Err(error) => {
                return (
                    Err(NvmlErrorWithSource {
                        error,
                        source: None,
                    }),
                    Some(self),
                )
            }
        };

        unsafe {
            match nvml_try(sym(&mut raw_pci_info, gpu_state.as_c(), link_state.as_c())) {
                // `Device` removed; call was successful, no `Device` to return
                Ok(()) => (Ok(()), None),
                // `Device` has not been removed; unsuccessful call, return `Device`
                Err(e) => (Err(e.into()), Some(self)),
            }
        }
    }

    // NvLink

    /**
    Obtain a struct that represents an NvLink.

    NVIDIA does not provide any information as to how to obtain a valid NvLink
    value, so you're on your own there.
    */
    pub fn link_wrapper_for(&self, link: u32) -> NvLink {
        NvLink { device: self, link }
    }
}

#[cfg(test)]
#[deny(unused_mut)]
mod test {
    #[cfg(target_os = "linux")]
    use crate::bitmasks::event::*;
    #[cfg(target_os = "windows")]
    use crate::bitmasks::Behavior;
    use crate::enum_wrappers::device::*;
    use crate::enums::device::GpuLockedClocksSetting;
    use crate::error::*;
    use crate::structs::device::FieldId;
    use crate::sys_exports::field_id::*;
    use crate::test_utils::*;

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    #[cfg(target_os = "linux")]
    fn clear_cpu_affinity() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.clear_cpu_affinity().unwrap();
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn is_api_restricted() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.is_api_restricted(Api::ApplicationClocks)?;
            device.is_api_restricted(Api::AutoBoostedClocks)
        })
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn applications_clock() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let gfx_clock = device.applications_clock(Clock::Graphics)?;
            let sm_clock = device.applications_clock(Clock::SM)?;
            let mem_clock = device.applications_clock(Clock::Memory)?;
            let vid_clock = device.applications_clock(Clock::Video)?;

            Ok(format!(
                "Graphics Clock: {}, SM Clock: {}, Memory Clock: {}, Video Clock: {}",
                gfx_clock, sm_clock, mem_clock, vid_clock
            ))
        })
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn auto_boosted_clocks_enabled() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.auto_boosted_clocks_enabled())
    }

    #[test]
    fn bar1_memory_info() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.bar1_memory_info())
    }

    #[test]
    fn board_id() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.board_id())
    }

    #[test]
    fn brand() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.brand())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn bridge_chip_info() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.bridge_chip_info())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn clock() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.clock(Clock::Graphics, ClockId::Current)?;
            device.clock(Clock::SM, ClockId::TargetAppClock)?;
            device.clock(Clock::Memory, ClockId::DefaultAppClock)?;
            device.clock(Clock::Video, ClockId::TargetAppClock)
            // My machine does not support CustomerMaxBoost
        })
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn max_customer_boost_clock() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.max_customer_boost_clock(Clock::Graphics)?;
            device.max_customer_boost_clock(Clock::SM)?;
            device.max_customer_boost_clock(Clock::Memory)?;
            device.max_customer_boost_clock(Clock::Video)
        })
    }

    #[test]
    fn compute_mode() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.compute_mode())
    }

    #[test]
    fn clock_info() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let gfx_clock = device.clock_info(Clock::Graphics)?;
            let sm_clock = device.clock_info(Clock::SM)?;
            let mem_clock = device.clock_info(Clock::Memory)?;
            let vid_clock = device.clock_info(Clock::Video)?;

            Ok(format!(
                "Graphics Clock: {}, SM Clock: {}, Memory Clock: {}, Video Clock: {}",
                gfx_clock, sm_clock, mem_clock, vid_clock
            ))
        })
    }

    #[test]
    fn running_compute_processes() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.running_compute_processes())
    }

    #[cfg(feature = "legacy-functions")]
    #[cfg_attr(feature = "legacy-functions", test)]
    fn running_compute_processes_v2() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.running_compute_processes_v2())
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn cpu_affinity() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.cpu_affinity(64))
    }

    #[test]
    fn current_pcie_link_gen() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.current_pcie_link_gen())
    }

    #[test]
    fn current_pcie_link_width() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.current_pcie_link_width())
    }

    #[test]
    fn decoder_utilization() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.decoder_utilization())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn default_applications_clock() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let gfx_clock = device.default_applications_clock(Clock::Graphics)?;
            let sm_clock = device.default_applications_clock(Clock::SM)?;
            let mem_clock = device.default_applications_clock(Clock::Memory)?;
            let vid_clock = device.default_applications_clock(Clock::Video)?;

            Ok(format!(
                "Graphics Clock: {}, SM Clock: {}, Memory Clock: {}, Video Clock: {}",
                gfx_clock, sm_clock, mem_clock, vid_clock
            ))
        })
    }

    #[test]
    fn is_display_active() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.is_display_active())
    }

    #[test]
    fn is_display_connected() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.is_display_connected())
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn driver_model() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.driver_model())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn is_ecc_enabled() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.is_ecc_enabled())
    }

    #[test]
    fn encoder_utilization() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.encoder_utilization())
    }

    #[test]
    fn encoder_capacity() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.encoder_capacity(EncoderType::H264)
        })
    }

    #[test]
    fn encoder_stats() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.encoder_stats())
    }

    #[test]
    fn encoder_sessions() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.encoder_sessions())
    }

    #[test]
    fn fbc_stats() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.fbc_stats())
    }

    #[test]
    fn fbc_sessions_info() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.fbc_sessions_info())
    }

    #[test]
    fn enforced_power_limit() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.enforced_power_limit())
    }

    #[test]
    fn fan_speed() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.fan_speed(0))
    }

    #[test]
    fn num_fans() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.num_fans())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn gpu_operation_mode() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.gpu_operation_mode())
    }

    #[test]
    fn running_graphics_processes() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.running_graphics_processes())
    }

    #[cfg(feature = "legacy-functions")]
    #[cfg_attr(feature = "legacy-functions", test)]
    fn running_graphics_processes_v2() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.running_graphics_processes_v2())
    }

    #[test]
    fn process_utilization_stats() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.process_utilization_stats(None))
    }

    #[test]
    fn index() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.index())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn config_checksum() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.config_checksum())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn info_rom_image_version() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.info_rom_image_version())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn info_rom_version() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.info_rom_version(InfoRom::OEM)?;
            device.info_rom_version(InfoRom::ECC)?;
            device.info_rom_version(InfoRom::Power)
        })
    }

    #[test]
    fn max_clock_info() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let gfx_clock = device.max_clock_info(Clock::Graphics)?;
            let sm_clock = device.max_clock_info(Clock::SM)?;
            let mem_clock = device.max_clock_info(Clock::Memory)?;
            let vid_clock = device.max_clock_info(Clock::Video)?;

            Ok(format!(
                "Graphics Clock: {}, SM Clock: {}, Memory Clock: {}, Video Clock: {}",
                gfx_clock, sm_clock, mem_clock, vid_clock
            ))
        })
    }

    #[test]
    fn max_pcie_link_gen() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.max_pcie_link_gen())
    }

    #[test]
    fn max_pcie_link_width() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.max_pcie_link_width())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn memory_error_counter() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.memory_error_counter(
                MemoryError::Corrected,
                EccCounter::Volatile,
                MemoryLocation::Device,
            )
        })
    }

    #[test]
    fn memory_info() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.memory_info())
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn minor_number() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.minor_number())
    }

    #[test]
    fn is_multi_gpu_board() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.is_multi_gpu_board())
    }

    #[test]
    fn name() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.name())
    }

    #[test]
    fn pci_info() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.pci_info())
    }

    #[test]
    fn pcie_replay_counter() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.pcie_replay_counter())
    }

    #[test]
    fn pcie_throughput() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.pcie_throughput(PcieUtilCounter::Send)?;
            device.pcie_throughput(PcieUtilCounter::Receive)
        })
    }

    #[test]
    fn performance_state() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.performance_state())
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn is_in_persistent_mode() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.is_in_persistent_mode())
    }

    #[test]
    fn power_management_limit_default() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.power_management_limit_default())
    }

    #[test]
    fn power_management_limit() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.power_management_limit())
    }

    #[test]
    fn power_management_limit_constraints() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.power_management_limit_constraints()
        })
    }

    #[test]
    fn is_power_management_algo_active() {
        let nvml = nvml();

        #[allow(deprecated)]
        test_with_device(3, &nvml, |device| device.is_power_management_algo_active())
    }

    #[test]
    fn power_state() {
        let nvml = nvml();

        #[allow(deprecated)]
        test_with_device(3, &nvml, |device| device.power_state())
    }

    #[test]
    fn power_usage() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.power_usage())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn retired_pages() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.retired_pages(RetirementCause::MultipleSingleBitEccErrors)?;
            device.retired_pages(RetirementCause::DoubleBitEccError)
        })
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn are_pages_pending_retired() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.are_pages_pending_retired())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn samples() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.samples(Sampling::ProcessorClock, None)?;
            Ok(())
        })
    }

    #[test]
    fn field_values_for() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.field_values_for(&[
                FieldId(NVML_FI_DEV_ECC_CURRENT),
                FieldId(NVML_FI_DEV_ECC_PENDING),
                FieldId(NVML_FI_DEV_ECC_SBE_VOL_TOTAL),
                FieldId(NVML_FI_DEV_ECC_DBE_VOL_TOTAL),
                FieldId(NVML_FI_DEV_ECC_SBE_AGG_TOTAL),
                FieldId(NVML_FI_DEV_ECC_DBE_AGG_TOTAL),
                FieldId(NVML_FI_DEV_ECC_SBE_VOL_L1),
                FieldId(NVML_FI_DEV_ECC_DBE_VOL_L1),
                FieldId(NVML_FI_DEV_ECC_SBE_VOL_L2),
                FieldId(NVML_FI_DEV_ECC_DBE_VOL_L2),
                FieldId(NVML_FI_DEV_ECC_SBE_VOL_DEV),
                FieldId(NVML_FI_DEV_ECC_DBE_VOL_DEV),
                FieldId(NVML_FI_DEV_ECC_SBE_VOL_REG),
                FieldId(NVML_FI_DEV_ECC_DBE_VOL_REG),
                FieldId(NVML_FI_DEV_ECC_SBE_VOL_TEX),
                FieldId(NVML_FI_DEV_ECC_DBE_VOL_TEX),
                FieldId(NVML_FI_DEV_ECC_DBE_VOL_CBU),
                FieldId(NVML_FI_DEV_ECC_SBE_AGG_L1),
                FieldId(NVML_FI_DEV_ECC_DBE_AGG_L1),
                FieldId(NVML_FI_DEV_ECC_SBE_AGG_L2),
                FieldId(NVML_FI_DEV_ECC_DBE_AGG_L2),
                FieldId(NVML_FI_DEV_ECC_SBE_AGG_DEV),
                FieldId(NVML_FI_DEV_ECC_DBE_AGG_DEV),
                FieldId(NVML_FI_DEV_ECC_SBE_AGG_REG),
                FieldId(NVML_FI_DEV_ECC_DBE_AGG_REG),
                FieldId(NVML_FI_DEV_ECC_SBE_AGG_TEX),
                FieldId(NVML_FI_DEV_ECC_DBE_AGG_TEX),
                FieldId(NVML_FI_DEV_ECC_DBE_AGG_CBU),
                FieldId(NVML_FI_DEV_PERF_POLICY_POWER),
                FieldId(NVML_FI_DEV_PERF_POLICY_THERMAL),
                FieldId(NVML_FI_DEV_PERF_POLICY_SYNC_BOOST),
                FieldId(NVML_FI_DEV_PERF_POLICY_BOARD_LIMIT),
                FieldId(NVML_FI_DEV_PERF_POLICY_LOW_UTILIZATION),
                FieldId(NVML_FI_DEV_PERF_POLICY_RELIABILITY),
                FieldId(NVML_FI_DEV_PERF_POLICY_TOTAL_APP_CLOCKS),
                FieldId(NVML_FI_DEV_PERF_POLICY_TOTAL_BASE_CLOCKS),
                FieldId(NVML_FI_DEV_MEMORY_TEMP),
                FieldId(NVML_FI_DEV_TOTAL_ENERGY_CONSUMPTION),
            ])
        })
    }

    // Passing an empty slice should return an `InvalidArg` error
    #[should_panic(expected = "InvalidArg")]
    #[test]
    fn field_values_for_empty() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.field_values_for(&[]))
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn serial() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.serial())
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn board_part_number() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.board_part_number())
    }

    #[test]
    fn current_throttle_reasons() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.current_throttle_reasons())
    }

    #[test]
    fn current_throttle_reasons_strict() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.current_throttle_reasons_strict())
    }

    #[test]
    fn supported_throttle_reasons() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.supported_throttle_reasons())
    }

    #[test]
    fn supported_throttle_reasons_strict() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.supported_throttle_reasons_strict()
        })
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn supported_graphics_clocks() {
        let nvml = nvml();
        #[allow(unused_variables)]
        test_with_device(3, &nvml, |device| {
            let supported = device.supported_graphics_clocks(810)?;
            Ok(())
        })
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn supported_memory_clocks() {
        let nvml = nvml();
        #[allow(unused_variables)]
        test_with_device(3, &nvml, |device| {
            let supported = device.supported_memory_clocks()?;

            Ok(())
        })
    }

    #[test]
    fn temperature() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.temperature(TemperatureSensor::Gpu)
        })
    }

    #[test]
    fn temperature_threshold() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let slowdown = device.temperature_threshold(TemperatureThreshold::Slowdown)?;
            let shutdown = device.temperature_threshold(TemperatureThreshold::Shutdown)?;

            Ok((slowdown, shutdown))
        })
    }

    // I do not have 2 devices
    #[ignore = "my machine does not support this call"]
    #[cfg(target_os = "linux")]
    #[test]
    fn topology_common_ancestor() {
        let nvml = nvml();
        let device1 = device(&nvml);
        let device2 = nvml.device_by_index(1).expect("device");

        device1
            .topology_common_ancestor(device2)
            .expect("TopologyLevel");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn topology_nearest_gpus() {
        let nvml = nvml();
        let device = device(&nvml);
        test(3, || device.topology_nearest_gpus(TopologyLevel::System))
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn total_ecc_errors() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.total_ecc_errors(MemoryError::Corrected, EccCounter::Volatile)
        })
    }

    #[test]
    fn uuid() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.uuid())
    }

    #[test]
    fn utilization_rates() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.utilization_rates())
    }

    #[test]
    fn vbios_version() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.vbios_version())
    }

    #[test]
    fn violation_status() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            device.violation_status(PerformancePolicy::Power)
        })
    }

    #[test]
    fn num_cores() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.num_cores())
    }

    #[test]
    fn irq_num() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.irq_num())
    }

    #[test]
    fn power_source() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.power_source())
    }

    #[test]
    fn memory_bus_width() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.memory_bus_width())
    }

    #[test]
    fn pcie_link_max_speed() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.max_pcie_link_speed())
    }

    #[test]
    fn bus_type() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.bus_type())
    }

    #[test]
    fn architecture() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.architecture())
    }

    // I do not have 2 devices
    #[ignore = "my machine does not support this call"]
    #[test]
    fn is_on_same_board_as() {
        let nvml = nvml();
        let device1 = device(&nvml);
        let device2 = nvml.device_by_index(1).expect("device");

        device1.is_on_same_board_as(&device2).expect("bool");
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn reset_applications_clocks() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.reset_applications_clocks().expect("reset clocks")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_auto_boosted_clocks() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.set_auto_boosted_clocks(true).expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    #[cfg(target_os = "linux")]
    fn set_cpu_affinity() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.set_cpu_affinity().expect("ideal affinity set")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_auto_boosted_clocks_default() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_auto_boosted_clocks_default(true)
            .expect("set to true")
    }

    #[test]
    #[ignore = "my machine does not support this call"]
    fn validate_info_rom() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.validate_info_rom())
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn clear_accounting_pids() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.clear_accounting_pids().expect("cleared")
    }

    #[test]
    fn accounting_buffer_size() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.accounting_buffer_size())
    }

    #[test]
    fn is_accounting_enabled() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.is_accounting_enabled())
    }

    #[test]
    fn accounting_pids() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.accounting_pids())
    }

    #[should_panic(expected = "NotFound")]
    #[test]
    fn accounting_stats_for() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let processes = device.running_graphics_processes()?;

            // We never enable accounting mode, so this should return a `NotFound` error
            match device.accounting_stats_for(processes[0].pid) {
                Err(NvmlError::NotFound) => panic!("NotFound"),
                other => other,
            }
        })
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_accounting() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.set_accounting(true).expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn clear_ecc_error_counts() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .clear_ecc_error_counts(EccCounter::Aggregate)
            .expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_api_restricted() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_api_restricted(Api::ApplicationClocks, true)
            .expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_applications_clocks() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.set_applications_clocks(32, 32).expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_compute_mode() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_compute_mode(ComputeMode::Default)
            .expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[cfg(target_os = "windows")]
    #[allow(dead_code)]
    fn set_driver_model() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_driver_model(DriverModel::WDM, Behavior::DEFAULT)
            .expect("set to wdm")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_gpu_locked_clocks() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_gpu_locked_clocks(GpuLockedClocksSetting::Numeric {
                min_clock_mhz: 1048,
                max_clock_mhz: 1139,
            })
            .expect("set to a range")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn reset_gpu_locked_clocks() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.reset_gpu_locked_clocks().expect("clocks reset")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_mem_locked_clocks() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_mem_locked_clocks(1048, 1139)
            .expect("set to a range")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn reset_mem_locked_clocks() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.reset_mem_locked_clocks().expect("clocks reset")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_ecc() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.set_ecc(true).expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_gpu_op_mode() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_gpu_op_mode(OperationMode::AllOn)
            .expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    #[cfg(target_os = "linux")]
    fn set_persistent() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device.set_persistent(true).expect("set to true")
    }

    // This modifies device state, so we don't want to actually run the test
    #[allow(dead_code)]
    fn set_power_management_limit() {
        let nvml = nvml();
        let mut device = device(&nvml);

        device
            .set_power_management_limit(250000)
            .expect("set to true")
    }

    #[cfg(target_os = "linux")]
    #[allow(unused_variables)]
    #[test]
    fn register_events() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let set = nvml.create_event_set()?;
            let set = device
                .register_events(
                    EventTypes::PSTATE_CHANGE
                        | EventTypes::CRITICAL_XID_ERROR
                        | EventTypes::CLOCK_CHANGE,
                    set,
                )
                .map_err(|e| e.error)?;

            Ok(())
        })
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn supported_event_types() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.supported_event_types())
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn supported_event_types_strict() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.supported_event_types_strict())
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn is_drain_enabled() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| device.is_drain_enabled(None))
    }
}

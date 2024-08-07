/*!
A safe and ergonomic Rust wrapper for the [NVIDIA Management Library][nvml] (NVML),
a C-based programmatic interface for monitoring and managing various states within
NVIDIA GPUs.

```
use nvml_wrapper::Nvml;
# use nvml_wrapper::error::*;
# fn test() -> Result<(), NvmlError> {

let nvml = Nvml::init()?;
// Get the first `Device` (GPU) in the system
let device = nvml.device_by_index(0)?;

let brand = device.brand()?; // GeForce on my system
let fan_speed = device.fan_speed(0)?; // Currently 17% on my system
let power_limit = device.enforced_power_limit()?; // 275k milliwatts on my system
let encoder_util = device.encoder_utilization()?; // Currently 0 on my system; Not encoding anything
let memory_info = device.memory_info()?; // Currently 1.63/6.37 GB used on my system

// ... and there's a whole lot more you can do. Most everything in NVML is wrapped and ready to go
# Ok(())
# }
```

NVML is intended to be a platform for building 3rd-party applications, and is
also the underlying library for NVIDIA's nvidia-smi tool.

## Usage

`nvml-wrapper` builds on top of generated bindings for NVML that make use of the
[`libloading`][libloading] crate. This means the NVML library gets loaded upon
calling `Nvml::init` and can return an error if NVML isn't present, making it
possible to drop NVIDIA-related features in your code at runtime on systems that
don't have relevant hardware.

Successful execution of `Nvml::init` means:

* The NVML library was present on the system and able to be opened
* The function symbol to initialize NVML was loaded and called successfully
* An attempt has been made to load all other NVML function symbols

Every function you call thereafter will individually return an error if it couldn't
be loaded from the NVML library during the `Nvml::init` call.

Note that it's not advised to repeatedly call `Nvml::init` as the constructor
has to perform all the work of loading the function symbols from the library
each time it gets called. Instead, call `Nvml::init` once and store the resulting
`Nvml` instance somewhere to be accessed throughout the lifetime of your program
(perhaps in a [`once_cell`][once_cell]).

## NVML Support

This wrapper is being developed against and currently supports NVML version
11. Each new version of NVML is guaranteed to be backwards-compatible according
to NVIDIA, so this wrapper should continue to work without issue regardless of
NVML version bumps.

### Legacy Functions

Sometimes there will be function-level API version bumps in new NVML releases.
For example:

```text
nvmlDeviceGetComputeRunningProcesses
nvmlDeviceGetComputeRunningProcesses_v2
nvmlDeviceGetComputeRunningProcesses_v3
```

The older versions of the functions will generally continue to work with the
newer NVML releases; however, the newer function versions will not work with
older NVML installs.

By default this wrapper only provides access to the newest function versions.
Enable the `legacy-functions` feature if you require the ability to call older
functions.

## MSRV

The Minimum Supported Rust Version is currently 1.51.0. I will not go out of my
way to avoid bumping this.

## Cargo Features

The `serde` feature can be toggled on in order to `#[derive(Serialize, Deserialize)]`
for every NVML data structure.

[nvml]: https://developer.nvidia.com/nvidia-management-library-nvml
[libloading]: https://github.com/nagisa/rust_libloading
[once_cell]: https://docs.rs/once_cell/latest/once_cell/sync/struct.Lazy.html
*/

#![recursion_limit = "1024"]
#![allow(non_upper_case_globals)]

extern crate libloading;
extern crate nvml_wrapper_sys as ffi;

pub mod bitmasks;
pub mod device;
pub mod enum_wrappers;
pub mod enums;
pub mod error;
pub mod event;
pub mod high_level;
pub mod nv_link;
pub mod struct_wrappers;
pub mod structs;
#[cfg(test)]
mod test_utils;
pub mod unit;

// Re-exports for convenience
pub use crate::device::Device;
pub use crate::event::EventSet;
pub use crate::nv_link::NvLink;
pub use crate::unit::Unit;

/// Re-exports from `nvml-wrapper-sys` that are necessary for use of this wrapper.
pub mod sys_exports {
    /// Use these constants to populate the `structs::device::FieldId` newtype.
    pub mod field_id {
        pub use crate::ffi::bindings::field_id::*;
    }
}

#[cfg(target_os = "linux")]
use std::convert::TryInto;
#[cfg(target_os = "linux")]
use std::ptr;
use std::{
    convert::TryFrom,
    ffi::{CStr, CString, OsStr},
    mem::{self, ManuallyDrop},
    os::raw::{c_int, c_uint},
};

use static_assertions::assert_impl_all;

#[cfg(target_os = "linux")]
use crate::enum_wrappers::device::TopologyLevel;

use crate::error::{nvml_sym, nvml_try, NvmlError};
use crate::ffi::bindings::*;

use crate::struct_wrappers::ExcludedDeviceInfo;

#[cfg(target_os = "linux")]
use crate::struct_wrappers::device::PciInfo;
use crate::struct_wrappers::unit::HwbcEntry;

use crate::bitmasks::InitFlags;

#[cfg(not(target_os = "linux"))]
const LIB_PATH: &str = "nvml.dll";

#[cfg(target_os = "linux")]
const LIB_PATH: &str = "libnvidia-ml.so";

/// Determines the major version of the CUDA driver given the full version.
///
/// Obtain the full version via `Nvml.sys_cuda_driver_version()`.
pub fn cuda_driver_version_major(version: i32) -> i32 {
    version / 1000
}

/// Determines the minor version of the CUDA driver given the full version.
///
/// Obtain the full version via `NVML.sys_cuda_driver_version()`.
pub fn cuda_driver_version_minor(version: i32) -> i32 {
    (version % 1000) / 10
}

/**
The main struct that this library revolves around.

According to NVIDIA's documentation, "It is the user's responsibility to call `nvmlInit()`
before calling any other methods, and `nvmlShutdown()` once NVML is no longer being used."
This struct is used to enforce those rules.

Also according to NVIDIA's documentation, "NVML is thread-safe so it is safe to make
simultaneous NVML calls from multiple threads." In the Rust world, this translates to `NVML`
being `Send` + `Sync`. You can `.clone()` an `Arc` wrapped `NVML` and enjoy using it on any thread.

NOTE: If you care about possible errors returned from `nvmlShutdown()`, use the `.shutdown()`
method on this struct. **The `Drop` implementation ignores errors.**

When reading documentation on this struct and its members, remember that a lot of it,
especially in regards to errors returned, is copied from NVIDIA's docs. While they can be found
online [here](http://docs.nvidia.com/deploy/nvml-api/index.html), the hosted docs sometimes outdated
and may not accurately reflect the version of NVML that this library is written for; beware. You
should ideally read the doc comments on an up-to-date NVML API header. Such a header can be
downloaded as part of the [CUDA toolkit](https://developer.nvidia.com/cuda-downloads).
*/
pub struct Nvml {
    lib: ManuallyDrop<NvmlLib>,
}

assert_impl_all!(Nvml: Send, Sync);

impl std::fmt::Debug for Nvml {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("NVML")
    }
}

impl Nvml {
    /**
    Handles NVML initialization and must be called before doing anything else.

    While it is possible to initialize `NVML` multiple times (NVIDIA's docs state
    that reference counting is used internally), you should strive to initialize
    `NVML` once at the start of your program's execution; the constructors handle
    dynamically loading function symbols from the `NVML` lib and are therefore
    somewhat expensive.

    Note that this will initialize NVML but not any GPUs. This means that NVML can
    communicate with a GPU even when other GPUs in a system are bad or unstable.

    By default, initialization looks for "libnvidia-ml.so" on linux and "nvml.dll"
    on Windows. These default names should work for default installs on those
    platforms; if further specification is required, use `Nvml::builder`.

    # Errors

    * `DriverNotLoaded`, if the NVIDIA driver is not running
    * `NoPermission`, if NVML does not have permission to talk to the driver
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    #[doc(alias = "nvmlInit_v2")]
    pub fn init() -> Result<Self, NvmlError> {
        Self::init_internal(LIB_PATH)
    }

    fn init_internal(path: impl AsRef<std::ffi::OsStr>) -> Result<Self, NvmlError> {
        let lib = unsafe {
            let lib = NvmlLib::new(path)?;
            let sym = nvml_sym(lib.nvmlInit_v2.as_ref())?;

            nvml_try(sym())?;
            ManuallyDrop::new(lib)
        };

        Ok(Self { lib })
    }

    /**
    An initialization function that allows you to pass flags to control certain behaviors.

    This is the same as `init()` except for the addition of flags.

    # Errors

    * `DriverNotLoaded`, if the NVIDIA driver is not running
    * `NoPermission`, if NVML does not have permission to talk to the driver
    * `Unknown`, on any unexpected error

    # Examples

    ```
    # use nvml_wrapper::Nvml;
    # use nvml_wrapper::error::*;
    use nvml_wrapper::bitmasks::InitFlags;

    # fn main() -> Result<(), NvmlError> {
    // Don't fail if the system doesn't have any NVIDIA GPUs
    //
    // Also, don't attach any GPUs during initialization
    Nvml::init_with_flags(InitFlags::NO_GPUS | InitFlags::NO_ATTACH)?;
    # Ok(())
    # }
    ```
    */
    #[doc(alias = "nvmlInitWithFlags")]
    pub fn init_with_flags(flags: InitFlags) -> Result<Self, NvmlError> {
        Self::init_with_flags_internal(LIB_PATH, flags)
    }

    fn init_with_flags_internal(
        path: impl AsRef<std::ffi::OsStr>,
        flags: InitFlags,
    ) -> Result<Self, NvmlError> {
        let lib = unsafe {
            let lib = NvmlLib::new(path)?;
            let sym = nvml_sym(lib.nvmlInitWithFlags.as_ref())?;

            nvml_try(sym(flags.bits()))?;
            ManuallyDrop::new(lib)
        };

        Ok(Self { lib })
    }

    /// Create an `NvmlBuilder` for further flexibility in how NVML is initialized.
    pub fn builder<'a>() -> NvmlBuilder<'a> {
        NvmlBuilder::default()
    }

    /**
    Use this to shutdown NVML and release allocated resources if you care about handling
    potential errors (*the `Drop` implementation ignores errors!*).

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `Unknown`, on any unexpected error
    */
    // Thanks to `sorear` on IRC for suggesting this approach
    // Checked against local
    // Tested
    #[doc(alias = "nvmlShutdown")]
    pub fn shutdown(mut self) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.lib.nvmlShutdown.as_ref())?;

        unsafe {
            nvml_try(sym())?;
        }

        // SAFETY: we `mem::forget(self)` after this, so `self.lib` won't get
        // touched by our `Drop` impl
        let lib = unsafe { ManuallyDrop::take(&mut self.lib) };
        mem::forget(self);

        Ok(lib.__library.close()?)
    }

    /**
    Get the number of compute devices in the system (compute device == one GPU).

    Note that this count can include devices you do not have permission to access.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetCount_v2")]
    pub fn device_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlDeviceGetCount_v2.as_ref())?;

        unsafe {
            let mut count: c_uint = mem::zeroed();
            nvml_try(sym(&mut count))?;

            Ok(count)
        }
    }

    /**
    Gets the version of the system's graphics driver and returns it as an alphanumeric
    string.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlSystemGetDriverVersion")]
    pub fn sys_driver_version(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetDriverVersion.as_ref())?;

        unsafe {
            let mut version_vec = vec![0; NVML_SYSTEM_DRIVER_VERSION_BUFFER_SIZE as usize];

            nvml_try(sym(
                version_vec.as_mut_ptr(),
                NVML_SYSTEM_DRIVER_VERSION_BUFFER_SIZE,
            ))?;

            let version_raw = CStr::from_ptr(version_vec.as_ptr());
            Ok(version_raw.to_str()?.into())
        }
    }

    /**
    Gets the version of the system's NVML library and returns it as an alphanumeric
    string.

    # Errors

    * `Utf8Error`, if the string obtained from the C function is not valid Utf8
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlSystemGetNVMLVersion")]
    pub fn sys_nvml_version(&self) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetNVMLVersion.as_ref())?;

        unsafe {
            let mut version_vec = vec![0; NVML_SYSTEM_NVML_VERSION_BUFFER_SIZE as usize];

            nvml_try(sym(
                version_vec.as_mut_ptr(),
                NVML_SYSTEM_NVML_VERSION_BUFFER_SIZE,
            ))?;

            // Thanks to `Amaranth` on IRC for help with this
            let version_raw = CStr::from_ptr(version_vec.as_ptr());
            Ok(version_raw.to_str()?.into())
        }
    }

    /**
    Gets the version of the system's CUDA driver.

    Calls into the CUDA library (cuDriverGetVersion()).

    You can use `cuda_driver_version_major` and `cuda_driver_version_minor`
    to get the major and minor driver versions from this number.

    # Errors

    * `FunctionNotFound`, if cuDriverGetVersion() is not found in the shared library
    * `LibraryNotFound`, if libcuda.so.1 or libcuda.dll cannot be found
    */
    #[doc(alias = "nvmlSystemGetCudaDriverVersion_v2")]
    pub fn sys_cuda_driver_version(&self) -> Result<i32, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetCudaDriverVersion_v2.as_ref())?;

        unsafe {
            let mut version: c_int = mem::zeroed();
            nvml_try(sym(&mut version))?;

            Ok(version)
        }
    }

    /**
    Gets the name of the process for the given process ID, cropped to the provided length.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if the length is 0 (if this is returned without length being 0, file an issue)
    * `NotFound`, if the process does not exist
    * `NoPermission`, if the user doesn't have permission to perform the operation
    * `Utf8Error`, if the string obtained from the C function is not valid UTF-8. NVIDIA's docs say
    that the string encoding is ANSI, so this may very well happen.
    * `Unknown`, on any unexpected error
    */
    // TODO: The docs say the string is ANSI-encoded. Not sure if I should try
    // to do anything about that
    // Checked against local
    // Tested
    #[doc(alias = "nvmlSystemGetProcessName")]
    pub fn sys_process_name(&self, pid: u32, length: usize) -> Result<String, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetProcessName.as_ref())?;

        unsafe {
            let mut name_vec = vec![0; length];

            nvml_try(sym(pid, name_vec.as_mut_ptr(), length as c_uint))?;

            let name_raw = CStr::from_ptr(name_vec.as_ptr());
            Ok(name_raw.to_str()?.into())
        }
    }

    /**
    Acquire the handle for a particular device based on its index (starts at 0).

    Usage of this function causes NVML to initialize the target GPU. Additional
    GPUs may be initialized if the target GPU is an SLI slave.

    You can determine valid indices by using `.device_count()`. This
    function doesn't call that for you, but the actual C function to get
    the device handle will return an error in the case of an invalid index.
    This means that the `InvalidArg` error will be returned if you pass in
    an invalid index.

    NVIDIA's docs state that "The order in which NVML enumerates devices has
    no guarantees of consistency between reboots. For that reason it is recommended
    that devices be looked up by their PCI ids or UUID." In this library, that translates
    into usage of `.device_by_uuid()` and `.device_by_pci_bus_id()`.

    The NVML index may not correlate with other APIs such as the CUDA device index.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if index is invalid
    * `InsufficientPower`, if any attached devices have improperly attached external power cables
    * `NoPermission`, if the user doesn't have permission to talk to this device
    * `IrqIssue`, if the NVIDIA kernel detected an interrupt issue with the attached GPUs
    * `GpuLost`, if the target GPU has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetHandleByIndex_v2")]
    pub fn device_by_index(&self, index: u32) -> Result<Device, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlDeviceGetHandleByIndex_v2.as_ref())?;

        unsafe {
            let mut device: nvmlDevice_t = mem::zeroed();
            nvml_try(sym(index, &mut device))?;

            Ok(Device::new(device, self))
        }
    }

    /**
    Acquire the handle for a particular device based on its PCI bus ID.

    Usage of this function causes NVML to initialize the target GPU. Additional
    GPUs may be initialized if the target GPU is an SLI slave.

    The bus ID corresponds to the `bus_id` returned by `Device.pci_info()`.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if `pci_bus_id` is invalid
    * `NotFound`, if `pci_bus_id` does not match a valid device on the system
    * `InsufficientPower`, if any attached devices have improperly attached external power cables
    * `NoPermission`, if the user doesn't have permission to talk to this device
    * `IrqIssue`, if the NVIDIA kernel detected an interrupt issue with the attached GPUs
    * `GpuLost`, if the target GPU has fallen off the bus or is otherwise inaccessible
    * `NulError`, for which you can read the docs on `std::ffi::NulError`
    * `Unknown`, on any unexpected error
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetHandleByPciBusId_v2")]
    pub fn device_by_pci_bus_id<S: AsRef<str>>(&self, pci_bus_id: S) -> Result<Device, NvmlError>
    where
        Vec<u8>: From<S>,
    {
        let sym = nvml_sym(self.lib.nvmlDeviceGetHandleByPciBusId_v2.as_ref())?;

        unsafe {
            let c_string = CString::new(pci_bus_id)?;
            let mut device: nvmlDevice_t = mem::zeroed();

            nvml_try(sym(c_string.as_ptr(), &mut device))?;

            Ok(Device::new(device, self))
        }
    }

    /// Not documenting this because it's deprecated and does not seem to work
    /// anymore.
    // Tested (for an error)
    #[deprecated(note = "use `.device_by_uuid()`, this errors on dual GPU boards")]
    #[doc(alias = "nvmlDeviceGetHandleBySerial")]
    pub fn device_by_serial<S: AsRef<str>>(&self, board_serial: S) -> Result<Device, NvmlError>
    where
        Vec<u8>: From<S>,
    {
        let sym = nvml_sym(self.lib.nvmlDeviceGetHandleBySerial.as_ref())?;

        unsafe {
            let c_string = CString::new(board_serial)?;
            let mut device: nvmlDevice_t = mem::zeroed();

            nvml_try(sym(c_string.as_ptr(), &mut device))?;

            Ok(Device::new(device, self))
        }
    }

    /**
    Acquire the handle for a particular device based on its globally unique immutable
    UUID.

    Usage of this function causes NVML to initialize the target GPU. Additional
    GPUs may be initialized as the function called within searches for the target GPU.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if `uuid` is invalid
    * `NotFound`, if `uuid` does not match a valid device on the system
    * `InsufficientPower`, if any attached devices have improperly attached external power cables
    * `IrqIssue`, if the NVIDIA kernel detected an interrupt issue with the attached GPUs
    * `GpuLost`, if the target GPU has fallen off the bus or is otherwise inaccessible
    * `NulError`, for which you can read the docs on `std::ffi::NulError`
    * `Unknown`, on any unexpected error

    NVIDIA doesn't mention `NoPermission` for this one. Strange!
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlDeviceGetHandleByUUID")]
    pub fn device_by_uuid<S: AsRef<str>>(&self, uuid: S) -> Result<Device, NvmlError>
    where
        Vec<u8>: From<S>,
    {
        let sym = nvml_sym(self.lib.nvmlDeviceGetHandleByUUID.as_ref())?;

        unsafe {
            let c_string = CString::new(uuid)?;
            let mut device: nvmlDevice_t = mem::zeroed();

            nvml_try(sym(c_string.as_ptr(), &mut device))?;

            Ok(Device::new(device, self))
        }
    }

    /**
    Gets the common ancestor for two devices.

    Note: this is the same as `Device.topology_common_ancestor()`.

    # Errors

    * `InvalidArg`, if the device is invalid
    * `NotSupported`, if this `Device` or the OS does not support this feature
    * `UnexpectedVariant`, for which you can read the docs for
    * `Unknown`, on any unexpected error

    # Platform Support

    Only supports Linux.
    */
    // Checked against local
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceGetTopologyCommonAncestor")]
    pub fn topology_common_ancestor(
        &self,
        device1: &Device,
        device2: &Device,
    ) -> Result<TopologyLevel, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlDeviceGetTopologyCommonAncestor.as_ref())?;

        unsafe {
            let mut level: nvmlGpuTopologyLevel_t = mem::zeroed();

            nvml_try(sym(device1.handle(), device2.handle(), &mut level))?;

            TopologyLevel::try_from(level)
        }
    }

    /**
    Acquire the handle for a particular `Unit` based on its index.

    Valid indices are derived from the count returned by `.unit_count()`.
    For example, if `unit_count` is 2 the valid indices are 0 and 1, corresponding
    to UNIT 0 and UNIT 1.

    Note that the order in which NVML enumerates units has no guarantees of
    consistency between reboots.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `InvalidArg`, if `index` is invalid
    * `Unknown`, on any unexpected error

    # Device Support

    For S-class products.
    */
    // Checked against local
    // Tested (for an error)
    #[doc(alias = "nvmlUnitGetHandleByIndex")]
    pub fn unit_by_index(&self, index: u32) -> Result<Unit, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlUnitGetHandleByIndex.as_ref())?;

        unsafe {
            let mut unit: nvmlUnit_t = mem::zeroed();
            nvml_try(sym(index as c_uint, &mut unit))?;

            Ok(Unit::new(unit, self))
        }
    }

    /**
    Checks if the passed-in `Device`s are on the same physical board.

    Note: this is the same as `Device.is_on_same_board_as()`.

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
    pub fn are_devices_on_same_board(
        &self,
        device1: &Device,
        device2: &Device,
    ) -> Result<bool, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlDeviceOnSameBoard.as_ref())?;

        unsafe {
            let mut bool_int: c_int = mem::zeroed();

            nvml_try(sym(device1.handle(), device2.handle(), &mut bool_int))?;

            match bool_int {
                0 => Ok(false),
                _ => Ok(true),
            }
        }
    }

    /**
    Gets the set of GPUs that have a CPU affinity with the given CPU number.

    # Errors

    * `InvalidArg`, if `cpu_number` is invalid
    * `NotSupported`, if this `Device` or the OS does not support this feature
    * `Unknown`, an error has occurred in the underlying topology discovery

    # Platform Support

    Only supports Linux.
    */
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlSystemGetTopologyGpuSet")]
    pub fn topology_gpu_set(&self, cpu_number: u32) -> Result<Vec<Device>, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetTopologyGpuSet.as_ref())?;

        unsafe {
            let mut count = match self.topology_gpu_set_count(cpu_number)? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut devices: Vec<nvmlDevice_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(cpu_number, &mut count, devices.as_mut_ptr()))?;

            Ok(devices.into_iter().map(|d| Device::new(d, self)).collect())
        }
    }

    // Helper function for the above.
    #[cfg(target_os = "linux")]
    fn topology_gpu_set_count(&self, cpu_number: u32) -> Result<c_uint, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetTopologyGpuSet.as_ref())?;

        unsafe {
            // Indicates that we want the count
            let mut count: c_uint = 0;

            // Passing null doesn't indicate that we want the count, just allowed
            nvml_try(sym(cpu_number, &mut count, ptr::null_mut()))?;

            Ok(count)
        }
    }

    /**
    Gets the IDs and firmware versions for any Host Interface Cards in the system.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized

    # Device Support

    Supports S-class products.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlSystemGetHicVersion")]
    pub fn hic_versions(&self) -> Result<Vec<HwbcEntry>, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetHicVersion.as_ref())?;

        unsafe {
            let mut count: c_uint = match self.hic_count()? {
                0 => return Ok(vec![]),
                value => value,
            };
            let mut hics: Vec<nvmlHwbcEntry_t> = vec![mem::zeroed(); count as usize];

            nvml_try(sym(&mut count, hics.as_mut_ptr()))?;

            hics.into_iter().map(HwbcEntry::try_from).collect()
        }
    }

    /**
    Gets the count of Host Interface Cards in the system.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized

    # Device Support

    Supports S-class products.
    */
    // Tested as part of the above method
    #[doc(alias = "nvmlSystemGetHicVersion")]
    pub fn hic_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlSystemGetHicVersion.as_ref())?;

        unsafe {
            /*
            NVIDIA doesn't even say that `count` will be set to the count if
            `InsufficientSize` is returned. But we can assume sanity, right?

            The idea here is:
            If there are 0 HICs, NVML_SUCCESS is returned, `count` is set
              to 0. We return count, all good.
            If there is 1 HIC, NVML_SUCCESS is returned, `count` is set to
              1. We return count, all good.
            If there are >= 2 HICs, NVML_INSUFFICIENT_SIZE is returned.
             `count` is theoretically set to the actual count, and we
              return it.
            */
            let mut count: c_uint = 1;
            let mut hics: [nvmlHwbcEntry_t; 1] = [mem::zeroed()];

            match sym(&mut count, hics.as_mut_ptr()) {
                nvmlReturn_enum_NVML_SUCCESS | nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => {
                    Ok(count)
                }
                // We know that this will be an error
                other => nvml_try(other).map(|_| 0),
            }
        }
    }

    /**
    Gets the number of units in the system.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `Unknown`, on any unexpected error

    # Device Support

    Supports S-class products.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlUnitGetCount")]
    pub fn unit_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlUnitGetCount.as_ref())?;

        unsafe {
            let mut count: c_uint = mem::zeroed();
            nvml_try(sym(&mut count))?;

            Ok(count)
        }
    }

    /**
    Create an empty set of events.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Fermi and newer fully supported devices.
    */
    // Checked against local
    // Tested
    #[doc(alias = "nvmlEventSetCreate")]
    pub fn create_event_set(&self) -> Result<EventSet, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlEventSetCreate.as_ref())?;

        unsafe {
            let mut set: nvmlEventSet_t = mem::zeroed();
            nvml_try(sym(&mut set))?;

            Ok(EventSet::new(set, self))
        }
    }

    /**
    Request the OS and the NVIDIA kernel driver to rediscover a portion of the PCI
    subsystem in search of GPUs that were previously removed.

    The portion of the PCI tree can be narrowed by specifying a domain, bus, and
    device in the passed-in `pci_info`. **If all of these fields are zeroes, the
    entire PCI tree will be searched.** Note that for long-running NVML processes,
    the enumeration of devices will change based on how many GPUs are discovered
    and where they are inserted in bus order.

    All newly discovered GPUs will be initialized and have their ECC scrubbed which
    may take several seconds per GPU. **All device handles are no longer guaranteed
    to be valid post discovery**. I am not sure if this means **all** device
    handles, literally, or if NVIDIA is referring to handles that had previously
    been obtained to devices that were then removed and have now been
    re-discovered.

    Must be run as administrator.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `OperatingSystem`, if the operating system is denying this feature
    * `NoPermission`, if the calling process has insufficient permissions to
    perform this operation
    * `NulError`, if an issue is encountered when trying to convert a Rust
    `String` into a `CString`.
    * `Unknown`, on any unexpected error

    # Device Support

    Supports Pascal and newer fully supported devices.

    Some Kepler devices are also supported (that's all NVIDIA says, no specifics).

    # Platform Support

    Only supports Linux.
    */
    // TODO: constructor for default pci_infos ^
    // Checked against local
    // Tested
    #[cfg(target_os = "linux")]
    #[doc(alias = "nvmlDeviceDiscoverGpus")]
    pub fn discover_gpus(&self, pci_info: PciInfo) -> Result<(), NvmlError> {
        let sym = nvml_sym(self.lib.nvmlDeviceDiscoverGpus.as_ref())?;

        unsafe { nvml_try(sym(&mut pci_info.try_into()?)) }
    }

    /**
    Gets the number of excluded GPU devices in the system.

    # Device Support

    Supports all devices.
    */
    #[doc(alias = "nvmlGetExcludedDeviceCount")]
    pub fn excluded_device_count(&self) -> Result<u32, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlGetExcludedDeviceCount.as_ref())?;

        unsafe {
            let mut count: c_uint = mem::zeroed();

            nvml_try(sym(&mut count))?;
            Ok(count)
        }
    }

    /**
    Gets information for the specified excluded device.

    # Errors

    * `InvalidArg`, if the given index is invalid
    * `Utf8Error`, if strings obtained from the C function are not valid Utf8

    # Device Support

    Supports all devices.
    */
    #[doc(alias = "nvmlGetExcludedDeviceInfoByIndex")]
    pub fn excluded_device_info(&self, index: u32) -> Result<ExcludedDeviceInfo, NvmlError> {
        let sym = nvml_sym(self.lib.nvmlGetExcludedDeviceInfoByIndex.as_ref())?;

        unsafe {
            let mut info: nvmlExcludedDeviceInfo_t = mem::zeroed();

            nvml_try(sym(index, &mut info))?;
            ExcludedDeviceInfo::try_from(info)
        }
    }
}

/// This `Drop` implementation ignores errors! Use the `.shutdown()` method on
/// the `Nvml` struct
/// if you care about handling them.
impl Drop for Nvml {
    #[doc(alias = "nvmlShutdown")]
    fn drop(&mut self) {
        unsafe {
            self.lib.nvmlShutdown();

            // SAFETY: called after the last usage of `self.lib`
            ManuallyDrop::drop(&mut self.lib);
        }
    }
}

/**
A builder struct that provides further flexibility in how NVML is initialized.

# Examples

Initialize NVML with a non-default name for the shared object file:

```
use nvml_wrapper::Nvml;
use std::ffi::OsStr;

let init_result = Nvml::builder().lib_path(OsStr::new("libnvidia-ml-other-name.so")).init();
```

Initialize NVML with a non-default path to the shared object file:

```
use nvml_wrapper::Nvml;
use std::ffi::OsStr;

let init_result = Nvml::builder().lib_path(OsStr::new("/some/path/to/libnvidia-ml.so")).init();
```
*/
#[derive(Debug, Clone, Eq, PartialEq, Default)]
pub struct NvmlBuilder<'a> {
    lib_path: Option<&'a OsStr>,
    flags: InitFlags,
}

impl<'a> NvmlBuilder<'a> {
    /**
    Set the path to the NVML lib file.

    See [`libloading`'s docs][libloading] for details about how this lib path is
    handled.

    [libloading]: https://docs.rs/libloading/0.6.6/libloading/struct.Library.html#method.new
    */
    pub fn lib_path(&mut self, path: &'a OsStr) -> &mut Self {
        self.lib_path = Some(path);
        self
    }

    /// Set the `InitFlags` to initialize NVML with.
    pub fn flags(&mut self, flags: InitFlags) -> &mut Self {
        self.flags = flags;
        self
    }

    /// Perform initialization.
    pub fn init(&self) -> Result<Nvml, NvmlError> {
        let lib_path = self.lib_path.unwrap_or_else(|| LIB_PATH.as_ref());

        if self.flags.is_empty() {
            Nvml::init_internal(lib_path)
        } else {
            Nvml::init_with_flags_internal(lib_path, self.flags)
        }
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::bitmasks::InitFlags;
    use crate::error::NvmlError;
    use crate::test_utils::*;

    #[test]
    fn init_with_flags() {
        Nvml::init_with_flags(InitFlags::NO_GPUS).unwrap();
    }

    #[test]
    fn shutdown() {
        test(3, || nvml().shutdown())
    }

    #[test]
    fn device_count() {
        test(3, || nvml().device_count())
    }

    #[test]
    fn sys_driver_version() {
        test(3, || nvml().sys_driver_version())
    }

    #[test]
    fn sys_nvml_version() {
        test(3, || nvml().sys_nvml_version())
    }

    #[test]
    fn sys_cuda_driver_version() {
        test(3, || nvml().sys_cuda_driver_version())
    }

    #[test]
    fn sys_cuda_driver_version_major() {
        test(3, || {
            Ok(cuda_driver_version_major(nvml().sys_cuda_driver_version()?))
        })
    }

    #[test]
    fn sys_cuda_driver_version_minor() {
        test(3, || {
            Ok(cuda_driver_version_minor(nvml().sys_cuda_driver_version()?))
        })
    }

    #[test]
    fn sys_process_name() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let processes = device.running_graphics_processes()?;
            match nvml.sys_process_name(processes[0].pid, 64) {
                Err(NvmlError::NoPermission) => Ok("No permission error".into()),
                v => v,
            }
        })
    }

    #[test]
    fn device_by_index() {
        let nvml = nvml();
        test(3, || nvml.device_by_index(0))
    }

    #[test]
    fn device_by_pci_bus_id() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let id = device.pci_info()?.bus_id;
            nvml.device_by_pci_bus_id(id)
        })
    }

    // Can't get serial on my machine
    #[ignore = "my machine does not support this call"]
    #[test]
    fn device_by_serial() {
        let nvml = nvml();

        #[allow(deprecated)]
        test_with_device(3, &nvml, |device| {
            let serial = device.serial()?;
            nvml.device_by_serial(serial)
        })
    }

    #[test]
    fn device_by_uuid() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let uuid = device.uuid()?;
            nvml.device_by_uuid(uuid)
        })
    }

    // I don't have 2 devices
    #[ignore = "my machine does not support this call"]
    #[cfg(target_os = "linux")]
    #[test]
    fn topology_common_ancestor() {
        let nvml = nvml();
        let device1 = device(&nvml);
        let device2 = nvml.device_by_index(1).expect("device");

        nvml.topology_common_ancestor(&device1, &device2)
            .expect("TopologyLevel");
    }

    // Errors on my machine

    #[test]
    #[ignore = "my machine does not support this call"]
    fn unit_by_index() {
        let nvml = nvml();
        test(3, || nvml.unit_by_index(0))
    }

    // I don't have 2 devices
    #[ignore = "my machine does not support this call"]
    #[test]
    fn are_devices_on_same_board() {
        let nvml = nvml();
        let device1 = device(&nvml);
        let device2 = nvml.device_by_index(1).expect("device");

        nvml.are_devices_on_same_board(&device1, &device2)
            .expect("bool");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn topology_gpu_set() {
        let nvml = nvml();
        test(3, || nvml.topology_gpu_set(0))
    }

    #[test]
    fn hic_version() {
        let nvml = nvml();
        test(3, || nvml.hic_versions())
    }

    #[test]
    fn unit_count() {
        test(3, || nvml().unit_count())
    }

    #[test]
    fn create_event_set() {
        let nvml = nvml();
        test(3, || nvml.create_event_set())
    }

    #[cfg(target_os = "linux")]
    #[should_panic(expected = "OperatingSystem")]
    #[test]
    fn discover_gpus() {
        let nvml = nvml();
        test_with_device(3, &nvml, |device| {
            let pci_info = device.pci_info()?;

            // We don't test with admin perms and therefore expect an error
            match nvml.discover_gpus(pci_info) {
                Err(NvmlError::NoPermission) => panic!("NoPermission"),
                other => other,
            }
        })
    }

    #[test]
    fn excluded_device_count() {
        let nvml = nvml();
        test(3, || nvml.excluded_device_count())
    }

    #[test]
    fn excluded_device_info() {
        let nvml = nvml();

        if nvml.excluded_device_count().unwrap() > 0 {
            test(3, || nvml.excluded_device_info(0))
        }
    }
}

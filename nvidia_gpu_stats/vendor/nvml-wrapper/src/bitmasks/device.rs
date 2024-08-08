#![allow(deprecated)]

use crate::ffi::bindings::*;
use bitflags::bitflags;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};

bitflags! {
    /// Flags used to specify why a GPU is throttling.
    // Checked against local
    #[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
    #[derive(Debug, Copy, Clone, Eq, PartialEq, Hash)]
    pub struct ThrottleReasons: u64 {
        /// Nothing is running on the GPU.
        ///
        /// This limiter may be removed in a future release.
        const GPU_IDLE                    = nvmlClocksThrottleReasonGpuIdle as u64;
        /// GPU clocks are limited by the current applications clocks setting.
        const APPLICATIONS_CLOCKS_SETTING = nvmlClocksThrottleReasonApplicationsClocksSetting as u64;
        #[deprecated(note = "Renamed to `APPLICATIONS_CLOCKS_SETTING`.")]
        const USER_DEFINED_CLOCKS         = nvmlClocksThrottleReasonUserDefinedClocks as u64;
        /// Software power scaling algorithm is reducing clocks.
        const SW_POWER_CAP                = nvmlClocksThrottleReasonSwPowerCap as u64;
        /**
        Hardware slowdown (reducing the core clocks by a factor of 2 or more)
        is engaged.

        This is an indicator of:

        * Temperature being too high
        * External Power Brake Asseration being triggered (e.g. by the system power supply)
        * Power draw being too high and Fast Trigger protection reducing the clocks

        This may also be reported during powerstate or clock change, behavior that may be
        removed in a later release.
        */
        const HW_SLOWDOWN                 = nvmlClocksThrottleReasonHwSlowdown as u64;
        /**
        This GPU is being throttled by another GPU in its sync boost group.

        Sync boost groups can be used to maximize performance per watt. All GPUs
        in a sync boost group will boost to the minimum possible clocks across
        the entire group. Look at the throttle reasons for other GPUs in the
        system to find out why this GPU is being held at lower clocks.
        */
        const SYNC_BOOST                  = nvmlClocksThrottleReasonSyncBoost as u64;
        /**
        Software thermal slowdown.

        This is an indicator of one or more of the following:

        * The current GPU temperature is above the max GPU operating temperature
        * The current memory temperature is above the max memory operating temperature
        */
        const SW_THERMAL_SLOWDOWN         = nvmlClocksThrottleReasonSwThermalSlowdown as u64;
        /**
        Hardware thermal slowdown is engaged, reducing core clocks by 2x or more.

        This indicates that the temperature of the GPU is too high.
        */
        const HW_THERMAL_SLOWDOWN         = nvmlClocksThrottleReasonHwThermalSlowdown as u64;
        /**
        Hardware power brake slowdown is engaged, reducing core clocks by 2x or more.

        This indicates that an external power brake assertion is being triggered,
        such as by the system power supply.
        */
        const HW_POWER_BRAKE_SLOWDOWN     = nvmlClocksThrottleReasonHwPowerBrakeSlowdown as u64;
        /// GPU clocks are limited by the current setting of display clocks.
        const DISPLAY_CLOCK_SETTING       = nvmlClocksThrottleReasonDisplayClockSetting as u64;
        /// Clocks are as high as possible and are not being throttled.
        const NONE                        = nvmlClocksThrottleReasonNone as u64;
    }
}

bitflags! {
    /// Flags that specify info about a frame capture session
    #[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
    #[derive(Debug, Copy, Clone, Eq, PartialEq, Hash)]
    pub struct FbcFlags: u32 {
        const DIFFMAP_ENABLED             = NVML_NVFBC_SESSION_FLAG_DIFFMAP_ENABLED;
        const CLASSIFICATIONMAP_ENABLED   = NVML_NVFBC_SESSION_FLAG_CLASSIFICATIONMAP_ENABLED;
        /// Specifies if capture was requested as a non-blocking call.
        const CAPTURE_WITH_WAIT_NO_WAIT   = NVML_NVFBC_SESSION_FLAG_CAPTURE_WITH_WAIT_NO_WAIT;
        /// Specifies if capture was requested as a blocking call.
        const CAPTURE_WITH_WAIT_INFINITE  = NVML_NVFBC_SESSION_FLAG_CAPTURE_WITH_WAIT_INFINITE;
        /// Specifies if capture was requested as a blocking call with a timeout.
        const CAPTURE_WITH_WAIT_TIMEOUT   = NVML_NVFBC_SESSION_FLAG_CAPTURE_WITH_WAIT_TIMEOUT;
    }
}

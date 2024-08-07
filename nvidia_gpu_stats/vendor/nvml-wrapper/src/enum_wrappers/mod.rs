use crate::error::NvmlError;
use crate::ffi::bindings::*;

pub mod device;
pub mod nv_link;
pub mod unit;

pub fn bool_from_state(state: nvmlEnableState_t) -> Result<bool, NvmlError> {
    match state {
        nvmlEnableState_enum_NVML_FEATURE_DISABLED => Ok(false),
        nvmlEnableState_enum_NVML_FEATURE_ENABLED => Ok(true),
        _ => Err(NvmlError::UnexpectedVariant(state)),
    }
}

pub fn state_from_bool(enabled: bool) -> nvmlEnableState_t {
    if enabled {
        nvmlEnableState_enum_NVML_FEATURE_ENABLED
    } else {
        nvmlEnableState_enum_NVML_FEATURE_DISABLED
    }
}

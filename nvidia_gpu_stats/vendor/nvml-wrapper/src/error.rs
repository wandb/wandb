use crate::ffi::bindings::*;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub enum Bits {
    U32(u32),
    U64(u64),
}

/// An `NvmlError` with an optionally present source error for chaining errors
#[derive(Error, Debug)]
#[error("{error}")]
pub struct NvmlErrorWithSource {
    pub error: NvmlError,
    pub source: Option<NvmlError>,
}

impl From<NvmlError> for NvmlErrorWithSource {
    fn from(error: NvmlError) -> Self {
        Self {
            error,
            source: None,
        }
    }
}

#[derive(Error, Debug)]
pub enum NvmlError {
    #[error("could not interpret string as utf-8")]
    Utf8Error(#[from] std::str::Utf8Error),
    #[error("nul byte inside string")]
    NulError(#[from] std::ffi::NulError),
    #[error("a libloading error occurred: {0}")]
    LibloadingError(#[from] libloading::Error),

    /**
    A function symbol failed to load.

    This variant is constructed with a textual description of a
    `libloading::Error`. The error variant itself can't be provided because we're
    unable to take ownership of the error when attempting to use a symbol, and
    `libloading::Error` doesn't impl `Clone`.
    */
    #[error("function symbol failed to load: {0}")]
    FailedToLoadSymbol(String),

    #[error("max string length was {max_len} but string length is {actual_len}")]
    StringTooLong { max_len: usize, actual_len: usize },

    #[error("invalid combination of bits ({0:?}) when trying to interpret as bitflags")]
    IncorrectBits(Bits),

    /**
    An unexpected enum variant was encountered.

    This error is specific to this Rust wrapper. It is used to represent the
    possibility that an enum variant that is not defined within the Rust bindings
    can be returned from a C call.

    The single field contains the value that could not be mapped to a
    defined enum variant.

    See [this issue](https://github.com/rust-lang/rust/issues/36927).
    */
    #[error("unexpected enum variant value: {0}")]
    UnexpectedVariant(u32),

    #[error("a call to `EventSet.release_events()` failed")]
    SetReleaseFailed,

    #[error("a call to `Device.pci_info()` failed")]
    GetPciInfoFailed,

    #[error("a call to `PciInfo.try_into_c()` failed")]
    PciInfoToCFailed,

    #[error("NVML was not first initialized with `Nvml::init()`")]
    Uninitialized,

    #[error("a supplied argument was invalid")]
    InvalidArg,

    #[error("the requested operation is not available on the target device")]
    NotSupported,

    #[error("the current user does not have permission to perform this operation")]
    NoPermission,

    #[error("NVML was already initialized")]
    #[deprecated = "deprecated in NVML (multiple initializations now allowed via refcounting)"]
    AlreadyInitialized,

    #[error("a query to find an object was unsuccessful")]
    NotFound,

    /**
    An input argument is not large enough.

    The single field is the size required for a successful call (if `Some`)
    and `None` if unknown.
    */
    // TODO: verify that ^
    #[error(
        "an input argument is not large enough{}",
        if let Some(size) = .0 {
            format!(", needs to be at least {}", size)
        } else {
            "".into()
        }
    )]
    InsufficientSize(Option<usize>),

    #[error("device's external power cables are not properly attached")]
    InsufficientPower,

    #[error("NVIDIA driver is not loaded")]
    DriverNotLoaded,

    #[error("the provided timeout was reached")]
    Timeout,

    #[error("NVIDIA kernel detected an interrupt issue with a device")]
    IrqIssue,

    #[error("a shared library couldn't be found or loaded")]
    LibraryNotFound,

    #[error("a function couldn't be found in a shared library")]
    FunctionNotFound,

    #[error("the infoROM is corrupted")]
    CorruptedInfoROM,

    #[error("device fell off the bus or has otherwise become inacessible")]
    GpuLost,

    #[error("device requires a reset before it can be used again")]
    ResetRequired,

    #[error("device control has been blocked by the operating system/cgroups")]
    OperatingSystem,

    #[error("RM detects a driver/library version mismatch")]
    LibRmVersionMismatch,

    #[error("operation cannot be performed because the GPU is currently in use")]
    InUse,

    #[error("insufficient memory")]
    InsufficientMemory,

    #[error("no data")]
    NoData,

    #[error(
        "the requested vgpu operation is not available on the target device because \
        ECC is enabled"
    )]
    VgpuEccNotSupported,

    #[error("an internal driver error occured")]
    Unknown,
}

/// Converts an `nvmlReturn_t` type into a `Result<(), NvmlError>`.
#[allow(deprecated)]
pub fn nvml_try(code: nvmlReturn_t) -> Result<(), NvmlError> {
    use NvmlError::*;

    match code {
        nvmlReturn_enum_NVML_SUCCESS => Ok(()),
        nvmlReturn_enum_NVML_ERROR_UNINITIALIZED => Err(Uninitialized),
        nvmlReturn_enum_NVML_ERROR_INVALID_ARGUMENT => Err(InvalidArg),
        nvmlReturn_enum_NVML_ERROR_NOT_SUPPORTED => Err(NotSupported),
        nvmlReturn_enum_NVML_ERROR_NO_PERMISSION => Err(NoPermission),
        nvmlReturn_enum_NVML_ERROR_ALREADY_INITIALIZED => Err(AlreadyInitialized),
        nvmlReturn_enum_NVML_ERROR_NOT_FOUND => Err(NotFound),
        nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_SIZE => Err(InsufficientSize(None)),
        nvmlReturn_enum_NVML_ERROR_INSUFFICIENT_POWER => Err(InsufficientPower),
        nvmlReturn_enum_NVML_ERROR_DRIVER_NOT_LOADED => Err(DriverNotLoaded),
        nvmlReturn_enum_NVML_ERROR_TIMEOUT => Err(Timeout),
        nvmlReturn_enum_NVML_ERROR_IRQ_ISSUE => Err(IrqIssue),
        nvmlReturn_enum_NVML_ERROR_LIBRARY_NOT_FOUND => Err(LibraryNotFound),
        nvmlReturn_enum_NVML_ERROR_FUNCTION_NOT_FOUND => Err(FunctionNotFound),
        nvmlReturn_enum_NVML_ERROR_CORRUPTED_INFOROM => Err(CorruptedInfoROM),
        nvmlReturn_enum_NVML_ERROR_GPU_IS_LOST => Err(GpuLost),
        nvmlReturn_enum_NVML_ERROR_RESET_REQUIRED => Err(ResetRequired),
        nvmlReturn_enum_NVML_ERROR_OPERATING_SYSTEM => Err(OperatingSystem),
        nvmlReturn_enum_NVML_ERROR_LIB_RM_VERSION_MISMATCH => Err(LibRmVersionMismatch),
        nvmlReturn_enum_NVML_ERROR_IN_USE => Err(InUse),
        nvmlReturn_enum_NVML_ERROR_MEMORY => Err(InsufficientMemory),
        nvmlReturn_enum_NVML_ERROR_NO_DATA => Err(NoData),
        nvmlReturn_enum_NVML_ERROR_VGPU_ECC_NOT_SUPPORTED => Err(VgpuEccNotSupported),
        nvmlReturn_enum_NVML_ERROR_UNKNOWN => Err(Unknown),
        _ => Err(UnexpectedVariant(code)),
    }
}

/// Helper to map a `&libloading::Error` into an `NvmlError`
pub fn nvml_sym<'a, T>(sym: Result<&'a T, &libloading::Error>) -> Result<&'a T, NvmlError> {
    sym.map_err(|e| NvmlError::FailedToLoadSymbol(e.to_string()))
}

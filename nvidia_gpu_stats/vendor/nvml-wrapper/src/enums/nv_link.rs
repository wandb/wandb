#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};

/// Used to specify the counter in `NvLink.set_utilization_control_for()`
///
/// NVIDIA simply says that the counter specified can be either 0 or 1.
#[repr(u32)]
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub enum Counter {
    Zero = 0,
    One = 1,
}

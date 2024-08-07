#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};

/// Returned by `NvLink.utilization_counter()`
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct UtilizationCounter {
    /// Receive counter value
    pub receive: u64,
    /// Send counter value
    pub send: u64,
}

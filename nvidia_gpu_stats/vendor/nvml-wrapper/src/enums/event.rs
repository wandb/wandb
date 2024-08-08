#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};

/// A simple wrapper used to encode the `Unknown` value into the type system.
///
/// `Unknown` would otherwise be a value of 999 (if it were not an enum
/// variant).
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub enum XidError {
    /// Contains the value of the error.
    Value(u64),
    /// If the error is unknown.
    Unknown,
}

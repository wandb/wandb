//! Port of `core/internal/leet/runoverview.go` (run metadata data-model).
//!
//! Trial-port scope: only `KeyValuePair` so far — the rest lands in Phase 2.

/// KeyValuePair represents a single key-value item to display.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct KeyValuePair {
    pub key: String,
    pub value: String,

    /// The full path for nested items.
    pub path: Vec<String>,
}

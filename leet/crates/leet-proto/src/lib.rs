//! `leet-proto` — committed prost-generated protobuf types for the leet
//! Rust port (the `wandb_internal` package: Record, HistoryRecord,
//! StatsRecord, …, plus the SystemMonitorService messages used by symon).
//!
//! Regenerate with `cargo xtask proto-gen` (requires protoc); generated
//! code is committed so downstream builds stay protoc-free.

#[allow(clippy::doc_lazy_continuation, clippy::doc_overindented_list_items)]
#[rustfmt::skip]
#[path = "generated/wandb_internal.rs"]
pub mod wandb_internal;

pub use prost;

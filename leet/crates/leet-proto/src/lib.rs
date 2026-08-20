//! `leet-proto` — committed prost-generated protobuf types for the leet
//! Rust port (the `wandb_internal` package: Record, HistoryRecord,
//! StatsRecord, …, plus the SystemMonitorService messages used by symon).
//!
//! Regenerate with `cargo xtask proto-gen` (requires protoc); generated
//! code is committed so downstream builds stay protoc-free.

#[allow(
    clippy::doc_lazy_continuation,
    clippy::doc_overindented_list_items,
// Generated prost code: RequestType/ResponseType oneofs carry large
// inline variants by design; boxing would diverge from codegen output.
    clippy::large_enum_variant
)]
#[rustfmt::skip]
#[path = "generated/wandb_internal.rs"]
pub mod wandb_internal;

pub use prost;

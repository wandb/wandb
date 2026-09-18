//! Run metadata and system metric definitions for the leet Rust port: config,
//! summary, and environment trees flattened for the overview sidebar, and the
//! table that groups system metric keys into charts. Mechanical port of the
//! corresponding files in `core/internal/leet`.

pub mod go_fmt;
pub mod run_config;
pub mod run_environment;
pub mod run_overview;
pub mod run_summary;
pub mod system_metrics;
pub mod units;

//! `leet-data` — pure data layer of the leet Rust port: history parsing,
//! metric definitions, units and Go-format compat, filters, the runs query
//! language, config, and run colors. No TUI dependencies.
//!
//! Mechanical port of the corresponding files in `core/internal/leet`;
//! see `leet/docs/PORTING.md`.

pub mod config;
pub mod go_fmt;
pub mod history_source;
pub mod leveldb_history_source;
pub mod media;
pub mod remote;
pub mod run_config;
pub mod run_environment;
pub mod run_filter_query;
pub mod run_overview;
pub mod run_summary;
pub mod system_metrics;
pub mod test_mode;
pub mod units;
pub mod width;

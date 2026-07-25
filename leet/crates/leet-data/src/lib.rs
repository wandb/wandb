//! `leet-data` — pure data layer of the leet Rust port: history parsing,
//! metric definitions, units and Go-format compat, filters, the runs query
//! language, config, and run colors. No TUI dependencies.
//!
//! Mechanical port of the corresponding files in `core/internal/leet`;
//! see `leet/docs/PORTING.md`.

pub mod go_fmt;
pub mod run_overview;
pub mod test_mode;
pub mod units;

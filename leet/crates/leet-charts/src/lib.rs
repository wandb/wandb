//! `leet-charts` — chart cores of the leet Rust port: braille canvas,
//! epoch/timeseries line charts, french-fries heatmap, styles/palettes.
//!
//! Rendering goes onto ratatui buffers with leet's own drawing code ported
//! verbatim (no ratatui Chart widgets); see `leet/docs/PORTING.md`.

pub mod styles;

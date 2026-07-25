//! `leet-charts` — chart cores of the leet Rust port: canvas + braille
//! grid (ntcharts subset), epoch/timeseries line charts, french-fries
//! heatmap, styles/palettes, run color assignment.
//!
//! Charts render into `canvas::Canvas` (a plain char+style grid mirroring
//! ntcharts' canvas semantics); `leet-tui` blits canvases into ratatui
//! buffers. leet's own drawing code is ported verbatim (no ratatui Chart
//! widgets); see `leet/docs/PORTING.md`.

pub mod braille;
pub mod canvas;
pub mod epoch_line_chart;
pub mod french_fries_chart;
pub mod french_fries_toggle_chart;
pub mod styles;
pub mod timeseries_line_chart;
pub mod workspace_run_colors;

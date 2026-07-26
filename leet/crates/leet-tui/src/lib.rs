//! `leet-tui` — app shell of the leet Rust port: model/workspace/run views,
//! panes, focus, keybindings, layout helpers, media rendering.
//!
//! Mechanical port of the corresponding files in `core/internal/leet`;
//! see `leet/docs/PORTING.md` and `leet/docs/CONCURRENCY.md`.

pub mod animation;
pub mod command;
pub mod console_logs_pane;
pub mod event;
pub mod filter;
pub mod flex_layout;
pub mod focus_manager;
pub mod heartbeat;
pub mod help;
pub mod key;
pub mod keybindings;
pub mod layout;
pub mod media_pane;
pub mod metrics_grid;
pub mod model;
pub mod nav;
pub mod paged_list;
pub mod panel_grid;
pub mod picture;
pub mod right_sidebar;
pub mod run;
pub mod run_console_logs;
pub mod run_focus;
pub mod run_handlers;
pub mod run_overview_sidebar;
pub mod run_overview_sidebar_filter;
pub mod run_overview_sidebar_nav;
pub mod runtime;
pub mod system_metrics_grid;
pub mod system_metrics_view;
pub mod terminal_emulator;
pub mod watcher_manager;
pub mod workspace;
pub mod workspace_dir_watcher;
pub mod workspace_handlers;
pub mod workspace_run_filter;
pub mod workspace_system_metrics_pane;

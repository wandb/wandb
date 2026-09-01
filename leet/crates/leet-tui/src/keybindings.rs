//! Port of `core/internal/leet/keybindings.go` — declarative binding tables
//! for the Run / Workspace / Symon views, `buildKeyMap`, and the shared
//! mouse help category.
//!
//! The table DATA (key names, help strings, category names and order) is
//! byte-identical to Go: the help overlay (help.go
//! `helpEntriesFromCategories`) renders `category.Name`,
//! `strings.Join(binding.Keys, ", ")` and `binding.Description` verbatim,
//! so Tier-1 parity depends on these exact strings.
//!
//! PARITY: Go's `Handler func(*T, tea.KeyPressMsg) tea.Cmd` method
//! references become action enums ([`RunAction`], [`WorkspaceAction`],
//! [`SymonAction`]) — one variant per Go handler func. The views hold
//! `build_key_map(..)` results and dispatch
//! `normalize_key(&msg.key_string())` lookups to the matching handler
//! method, exactly where Go calls `keyMap[normalizeKey(msg.String())]`.
// PHASE-5: the dispatchers and handler executors land with run.rs /
// run_handlers.rs, workspace.rs / workspace_handlers.rs, and the symon view.

use std::collections::HashMap;

/// `normalizeKey` is declared in keybindings.go (:550-555); its port lives
/// in [`crate::key`] next to `key_string()`. Re-exported here to keep the
/// Go-file → Rust-module mapping greppable.
pub use crate::key::normalize_key;
use crate::nav::{NavIntent, concat_keys, nav_keys_for};

/// KeyBinding defines a key binding for a particular target type.
///
/// If Handler is `None`, the binding is shown in the help screen but is not
/// dispatched through the key map (useful for documentation-only bindings
/// handled by a child component or a parent model).
#[derive(Debug, Clone)]
pub struct KeyBinding<A> {
    pub keys: Vec<&'static str>,
    pub description: &'static str,
    /// Go `Handler func(*T, tea.KeyPressMsg) tea.Cmd`, as an action variant.
    pub handler: Option<A>,
}

/// BindingCategory groups related key bindings (primarily for help display).
#[derive(Debug, Clone)]
pub struct BindingCategory<A> {
    pub name: &'static str,
    pub bindings: Vec<KeyBinding<A>>,
}

/// Actions of the single-run view — one variant per `(*Run).handle*` func
/// referenced by [`run_key_bindings`], same names.
// PHASE-5: executed by the Run key dispatcher (run.go:145 `keyMap` lookup);
// the handler bodies live in run_handlers.rs / workspace panes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunAction {
    /// `(*Run).handleQuit` (runhandlers.go:349)
    Quit,
    /// `(*Run).handleToggleMetricsGrid` (runhandlers.go:528)
    ToggleMetricsGrid,
    /// `(*Run).handleToggleLeftSidebar` (runhandlers.go:380)
    ToggleLeftSidebar,
    /// `(*Run).handleToggleRightSidebar` (runhandlers.go:403)
    ToggleRightSidebar,
    /// `(*Run).handleToggleMediaPane` (runhandlers.go:709)
    ToggleMediaPane,
    /// `(*Run).handleToggleConsoleLogsPane` (runhandlers.go:760)
    ToggleConsoleLogsPane,
    /// `(*Run).handlePrevPage` (runhandlers.go:425)
    PrevPage,
    /// `(*Run).handleNextPage` (runhandlers.go:441)
    NextPage,
    /// `(*Run).handleNavHome` (runhandlers.go:457)
    NavHome,
    /// `(*Run).handleNavEnd` (runhandlers.go:473)
    NavEnd,
    /// `(*Run).handleCycleFocusedChartMode` (runhandlers.go:489)
    CycleFocusedChartMode,
    /// `(*Run).handleEnterMetricsFilter` (runhandlers.go:501)
    EnterMetricsFilter,
    /// `(*Run).handleEnterSystemMetricsFilter` (runhandlers.go:652)
    EnterSystemMetricsFilter,
    /// `(*Run).handleClearMetricsFilter` (runhandlers.go:506)
    ClearMetricsFilter,
    /// `(*Run).handleClearSystemMetricsFilter` (runhandlers.go:663)
    ClearSystemMetricsFilter,
    /// `(*Run).handleEnterOverviewFilter` (runhandlers.go:516)
    EnterOverviewFilter,
    /// `(*Run).handleClearOverviewFilter` (runhandlers.go:521)
    ClearOverviewFilter,
    /// `(*Run).handleConfigFocusedCols` (runhandlers.go:628)
    ConfigFocusedCols,
    /// `(*Run).handleConfigFocusedRows` (runhandlers.go:640)
    ConfigFocusedRows,
    /// `(*Run).handleSidebarTabNav` (runhandlers.go:959)
    SidebarTabNav,
    /// `(*Run).handleSidebarVerticalNav` (runhandlers.go:976)
    SidebarVerticalNav,
    /// `(*Run).handleSidebarPageNav` (runhandlers.go:1004)
    SidebarPageNav,
}

/// Actions of the workspace view — one variant per `(*Workspace).handle*`
/// func referenced by [`workspace_key_bindings`], same names.
// PHASE-5: executed by the Workspace key dispatcher (workspace.go:155
// `keyMap` lookup); handler bodies live in workspace_handlers.rs /
// workspace_run_filter.rs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceAction {
    /// `(*Workspace).handleQuit` (workspacehandlers.go:773)
    Quit,
    /// `(*Workspace).handleFocusRuns` (workspacehandlers.go:1224)
    FocusRuns,
    /// `(*Workspace).handleToggleMetricsGrid` (workspacehandlers.go:933)
    ToggleMetricsGrid,
    /// `(*Workspace).handleToggleRunsSidebar` (workspacehandlers.go:344)
    ToggleRunsSidebar,
    /// `(*Workspace).handleToggleSystemMetricsPane` (workspacehandlers.go:421)
    ToggleSystemMetricsPane,
    /// `(*Workspace).handleToggleOverviewSidebar` (workspacehandlers.go:356)
    ToggleOverviewSidebar,
    /// `(*Workspace).handleToggleMediaPane` (workspacehandlers.go:372)
    ToggleMediaPane,
    /// `(*Workspace).handleToggleConsoleLogsPane` (workspacehandlers.go:402)
    ToggleConsoleLogsPane,
    /// `(*Workspace).handlePrevPage` (workspacehandlers.go:782)
    PrevPage,
    /// `(*Workspace).handleNextPage` (workspacehandlers.go:802)
    NextPage,
    /// `(*Workspace).handleNavHome` (workspacehandlers.go:822)
    NavHome,
    /// `(*Workspace).handleNavEnd` (workspacehandlers.go:842)
    NavEnd,
    /// `(*Workspace).handleEnterRunsFilter` (workspacerunfilter.go:24)
    EnterRunsFilter,
    /// `(*Workspace).handleClearRunsFilter` (workspacerunfilter.go:40)
    ClearRunsFilter,
    /// `(*Workspace).handleCycleFocusedChartMode` (workspacehandlers.go:862)
    CycleFocusedChartMode,
    /// `(*Workspace).handleEnterMetricsFilter` (workspacehandlers.go:874)
    EnterMetricsFilter,
    /// `(*Workspace).handleEnterSystemMetricsFilter` (workspacehandlers.go:879)
    EnterSystemMetricsFilter,
    /// `(*Workspace).handleClearMetricsFilter` (workspacehandlers.go:899)
    ClearMetricsFilter,
    /// `(*Workspace).handleClearSystemMetricsFilter` (workspacehandlers.go:909)
    ClearSystemMetricsFilter,
    /// `(*Workspace).handleEnterOverviewFilter` (workspacehandlers.go:921)
    EnterOverviewFilter,
    /// `(*Workspace).handleClearOverviewFilter` (workspacehandlers.go:926)
    ClearOverviewFilter,
    /// `(*Workspace).handleConfigFocusedCols` (workspacehandlers.go:1032)
    ConfigFocusedCols,
    /// `(*Workspace).handleConfigFocusedRows` (workspacehandlers.go:1044)
    ConfigFocusedRows,
    /// `(*Workspace).handleSidebarTabNav` (workspacehandlers.go:1172)
    SidebarTabNav,
    /// `(*Workspace).handleRunsVerticalNav` (workspacehandlers.go:1145)
    RunsVerticalNav,
    /// `(*Workspace).handleRunsPageNav` (workspacehandlers.go:1187)
    RunsPageNav,
    /// `(*Workspace).handleToggleRunSelectedKey` (workspacehandlers.go:1085)
    ToggleRunSelectedKey,
    /// `(*Workspace).handlePinRunKey` (workspacehandlers.go:1113)
    PinRunKey,
}

/// Actions of the standalone system monitor view — one variant per
/// `(*Symon).handle*` func referenced by [`symon_key_bindings`], same names.
// PHASE-5: executed by the Symon key dispatcher (symon.go:79 `keyMap`
// lookup); handler bodies land with the leet-symon view port (Phase 6).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SymonAction {
    /// `(*Symon).handleQuit` (symon.go:238)
    Quit,
    /// `(*Symon).handleGridNav` (symon.go:262)
    GridNav,
    /// `(*Symon).handlePrevPage` (symon.go:242)
    PrevPage,
    /// `(*Symon).handleNextPage` (symon.go:247)
    NextPage,
    /// `(*Symon).handleNavHome` (symon.go:252)
    NavHome,
    /// `(*Symon).handleNavEnd` (symon.go:257)
    NavEnd,
    /// `(*Symon).handleToggleFocusedChartLogY` (symon.go:283)
    ToggleFocusedChartLogY,
    /// `(*Symon).handleEnterSystemMetricsFilter` (symon.go:287)
    EnterSystemMetricsFilter,
    /// `(*Symon).handleClearSystemMetricsFilter` (symon.go:293)
    ClearSystemMetricsFilter,
    /// `(*Symon).handleConfigSystemCols` (symon.go:301)
    ConfigSystemCols,
    /// `(*Symon).handleConfigSystemRows` (symon.go:306)
    ConfigSystemRows,
}

/// RunKeyBindings returns key bindings relevant to the single-run view.
pub fn run_key_bindings() -> Vec<BindingCategory<RunAction>> {
    vec![
        BindingCategory {
            name: "General",
            bindings: vec![
                KeyBinding {
                    keys: vec!["h", "?"],
                    description: "Toggle this help screen",
                    handler: None,
                },
                KeyBinding {
                    keys: vec!["q", "ctrl+c"],
                    description: "Quit",
                    handler: Some(RunAction::Quit),
                },
                KeyBinding {
                    keys: vec!["alt+r"],
                    description: "Restart",
                    handler: None,
                },
                KeyBinding {
                    keys: vec!["esc"],
                    description: "Back to workspace (when not filtering/configuring)",
                    handler: None,
                },
            ],
        },
        BindingCategory {
            name: "Panels",
            bindings: vec![
                KeyBinding {
                    keys: vec!["1"],
                    description: "Toggle metrics grid",
                    handler: Some(RunAction::ToggleMetricsGrid),
                },
                KeyBinding {
                    keys: vec!["["],
                    description: "Toggle left sidebar with run overview",
                    handler: Some(RunAction::ToggleLeftSidebar),
                },
                KeyBinding {
                    keys: vec!["]", "2"],
                    description: "Toggle right sidebar with system metrics",
                    handler: Some(RunAction::ToggleRightSidebar),
                },
                KeyBinding {
                    keys: vec!["3"],
                    description: "Toggle media pane",
                    handler: Some(RunAction::ToggleMediaPane),
                },
                KeyBinding {
                    keys: vec!["4"],
                    description: "Toggle console logs panel",
                    handler: Some(RunAction::ToggleConsoleLogsPane),
                },
            ],
        },
        BindingCategory {
            name: "Navigation (focused pane)",
            bindings: vec![
                KeyBinding {
                    keys: vec!["w/s/a/d", "↑/↓/←/→"],
                    description: "Move within focused pane (chart focus on grids, item nav on lists)",
                    handler: None,
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::PageUp).to_vec(),
                    description: "Previous page / previous series page in media",
                    handler: Some(RunAction::PrevPage),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::PageDown).to_vec(),
                    description: "Next page / next series page in media",
                    handler: Some(RunAction::NextPage),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Home).to_vec(),
                    description: "Jump to first item / first page / scrub to start",
                    handler: Some(RunAction::NavHome),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::End).to_vec(),
                    description: "Jump to last item / last page / scrub to end",
                    handler: Some(RunAction::NavEnd),
                },
            ],
        },
        BindingCategory {
            name: "Charts",
            bindings: vec![
                KeyBinding {
                    keys: vec!["y"],
                    description: "Cycle focused chart mode (log Y / heatmap)",
                    handler: Some(RunAction::CycleFocusedChartMode),
                },
                KeyBinding {
                    keys: vec!["/"],
                    description: "Filter metrics by pattern",
                    handler: Some(RunAction::EnterMetricsFilter),
                },
                KeyBinding {
                    keys: vec!["\\"],
                    description: "Filter system metrics by pattern",
                    handler: Some(RunAction::EnterSystemMetricsFilter),
                },
                KeyBinding {
                    keys: vec!["ctrl+/", "ctrl+l"],
                    description: "Clear metrics filter",
                    handler: Some(RunAction::ClearMetricsFilter),
                },
                KeyBinding {
                    keys: vec!["ctrl+\\"],
                    description: "Clear system metrics filter",
                    handler: Some(RunAction::ClearSystemMetricsFilter),
                },
            ],
        },
        BindingCategory {
            name: "Run Overview",
            bindings: vec![
                KeyBinding {
                    keys: vec!["o"],
                    description: "Filter overview items",
                    handler: Some(RunAction::EnterOverviewFilter),
                },
                KeyBinding {
                    keys: vec!["ctrl+o"],
                    description: "Clear overview filter",
                    handler: Some(RunAction::ClearOverviewFilter),
                },
            ],
        },
        BindingCategory {
            name: "Configuration",
            bindings: vec![
                KeyBinding {
                    keys: vec!["c"],
                    description: "Set grid columns (focused pane)",
                    handler: Some(RunAction::ConfigFocusedCols),
                },
                KeyBinding {
                    keys: vec!["r"],
                    description: "Set grid rows (focused pane)",
                    handler: Some(RunAction::ConfigFocusedRows),
                },
            ],
        },
        BindingCategory {
            name: "Focusable panes (when open)",
            bindings: vec![
                KeyBinding {
                    keys: vec!["tab", "shift+tab"],
                    description: "Cycle focus: overview ↔ metrics ↔ media ↔ logs ↔ system",
                    handler: Some(RunAction::SidebarTabNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Up).to_vec(),
                    description: "Item up (list) / chart focus up (grid) / scrub -10 in media (arrow only)",
                    handler: Some(RunAction::SidebarVerticalNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Down).to_vec(),
                    description: "Item down (list) / chart focus down (grid) / scrub +10 in media (arrow only)",
                    handler: Some(RunAction::SidebarVerticalNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Left).to_vec(),
                    description: "Page prev (list) / chart focus left (grid) / scrub -1 in media (arrow only)",
                    handler: Some(RunAction::SidebarPageNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Right).to_vec(),
                    description: "Page next (list) / chart focus right (grid) / scrub +1 in media (arrow only)",
                    handler: Some(RunAction::SidebarPageNav),
                },
                KeyBinding {
                    keys: vec!["l"],
                    description: "Link scrubbing: arrow keys scrub all media series in sync (media pane focused)",
                    handler: None,
                },
                KeyBinding {
                    keys: vec!["k"],
                    description: "Toggle media image renderer: ANSI ↔ full-res (media pane focused)",
                    handler: None,
                },
            ],
        },
        mouse_category::<RunAction>(),
    ]
}

/// WorkspaceKeyBindings returns key bindings relevant to the workspace view.
pub fn workspace_key_bindings() -> Vec<BindingCategory<WorkspaceAction>> {
    vec![
        BindingCategory {
            name: "General",
            bindings: vec![
                KeyBinding {
                    keys: vec!["h", "?"],
                    description: "Toggle this help screen",
                    handler: None,
                },
                KeyBinding {
                    keys: vec!["q", "ctrl+c"],
                    description: "Quit",
                    handler: Some(WorkspaceAction::Quit),
                },
                KeyBinding {
                    keys: vec!["alt+r"],
                    description: "Restart LEET",
                    handler: None,
                },
                KeyBinding {
                    keys: vec!["esc"],
                    description: "Focus runs list",
                    handler: Some(WorkspaceAction::FocusRuns),
                },
                KeyBinding {
                    keys: vec!["enter"],
                    description: "View selected run (when not filtering/configuring)",
                    handler: None,
                },
            ],
        },
        BindingCategory {
            name: "Panels",
            bindings: vec![
                KeyBinding {
                    keys: vec!["1"],
                    description: "Toggle metrics grid",
                    handler: Some(WorkspaceAction::ToggleMetricsGrid),
                },
                KeyBinding {
                    keys: vec!["["],
                    description: "Toggle runs sidebar",
                    handler: Some(WorkspaceAction::ToggleRunsSidebar),
                },
                KeyBinding {
                    keys: vec!["2"],
                    description: "Toggle system metrics panel",
                    handler: Some(WorkspaceAction::ToggleSystemMetricsPane),
                },
                KeyBinding {
                    keys: vec!["]"],
                    description: "Toggle run overview sidebar",
                    handler: Some(WorkspaceAction::ToggleOverviewSidebar),
                },
                KeyBinding {
                    keys: vec!["3"],
                    description: "Toggle media pane",
                    handler: Some(WorkspaceAction::ToggleMediaPane),
                },
                KeyBinding {
                    keys: vec!["4"],
                    description: "Toggle console logs panel",
                    handler: Some(WorkspaceAction::ToggleConsoleLogsPane),
                },
            ],
        },
        BindingCategory {
            name: "Navigation (focused pane)",
            bindings: vec![
                KeyBinding {
                    keys: vec!["w/s/a/d", "↑/↓/←/→"],
                    description: "Move within focused pane (chart focus on grids, item nav on lists)",
                    handler: None,
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::PageUp).to_vec(),
                    description: "Previous page / previous series page in media",
                    handler: Some(WorkspaceAction::PrevPage),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::PageDown).to_vec(),
                    description: "Next page / next series page in media",
                    handler: Some(WorkspaceAction::NextPage),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Home).to_vec(),
                    description: "Jump to first item / first page / scrub to start",
                    handler: Some(WorkspaceAction::NavHome),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::End).to_vec(),
                    description: "Jump to last item / last page / scrub to end",
                    handler: Some(WorkspaceAction::NavEnd),
                },
            ],
        },
        BindingCategory {
            name: "Runs",
            bindings: vec![
                KeyBinding {
                    keys: vec!["f"],
                    description: "Filter runs by name / metadata",
                    handler: Some(WorkspaceAction::EnterRunsFilter),
                },
                KeyBinding {
                    keys: vec!["ctrl+f"],
                    description: "Clear runs filter",
                    handler: Some(WorkspaceAction::ClearRunsFilter),
                },
            ],
        },
        BindingCategory {
            name: "Charts",
            bindings: vec![
                KeyBinding {
                    keys: vec!["y"],
                    description: "Cycle focused chart mode (log Y / heatmap)",
                    handler: Some(WorkspaceAction::CycleFocusedChartMode),
                },
                KeyBinding {
                    keys: vec!["/"],
                    description: "Filter metrics by pattern",
                    handler: Some(WorkspaceAction::EnterMetricsFilter),
                },
                KeyBinding {
                    keys: vec!["\\"],
                    description: "Filter system metrics by pattern",
                    handler: Some(WorkspaceAction::EnterSystemMetricsFilter),
                },
                KeyBinding {
                    // TODO: remove ctrl+l.
                    keys: vec!["ctrl+/", "ctrl+l"],
                    description: "Clear metrics filter",
                    handler: Some(WorkspaceAction::ClearMetricsFilter),
                },
                KeyBinding {
                    keys: vec!["ctrl+\\"],
                    description: "Clear system metrics filter",
                    handler: Some(WorkspaceAction::ClearSystemMetricsFilter),
                },
            ],
        },
        BindingCategory {
            name: "Run Overview",
            bindings: vec![
                KeyBinding {
                    keys: vec!["o"],
                    description: "Filter overview items",
                    handler: Some(WorkspaceAction::EnterOverviewFilter),
                },
                KeyBinding {
                    keys: vec!["ctrl+o"],
                    description: "Clear overview filter",
                    handler: Some(WorkspaceAction::ClearOverviewFilter),
                },
            ],
        },
        BindingCategory {
            name: "Configuration",
            bindings: vec![
                KeyBinding {
                    keys: vec!["c"],
                    description: "Set grid columns (focused pane)",
                    handler: Some(WorkspaceAction::ConfigFocusedCols),
                },
                KeyBinding {
                    keys: vec!["r"],
                    description: "Set grid rows (focused pane)",
                    handler: Some(WorkspaceAction::ConfigFocusedRows),
                },
            ],
        },
        BindingCategory {
            name: "Focusable panes (when open)",
            bindings: vec![
                KeyBinding {
                    keys: vec!["tab", "shift+tab"],
                    description: "Cycle focus: runs ↔ metrics ↔ system ↔ media ↔ logs ↔ overview",
                    handler: Some(WorkspaceAction::SidebarTabNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Up).to_vec(),
                    description: "Item up (list) / chart focus up (grid) / scrub -10 in media (arrow only)",
                    handler: Some(WorkspaceAction::RunsVerticalNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Down).to_vec(),
                    description: "Item down (list) / chart focus down (grid) / scrub +10 in media (arrow only)",
                    handler: Some(WorkspaceAction::RunsVerticalNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Left).to_vec(),
                    description: "Page prev (list) / chart focus left (grid) / scrub -1 in media (arrow only)",
                    handler: Some(WorkspaceAction::RunsPageNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Right).to_vec(),
                    description: "Page next (list) / chart focus right (grid) / scrub +1 in media (arrow only)",
                    handler: Some(WorkspaceAction::RunsPageNav),
                },
                KeyBinding {
                    keys: vec!["space"],
                    description: "Select/deselect run",
                    handler: Some(WorkspaceAction::ToggleRunSelectedKey),
                },
                KeyBinding {
                    keys: vec!["p"],
                    description: "Pin/unpin selected run",
                    handler: Some(WorkspaceAction::PinRunKey),
                },
                KeyBinding {
                    keys: vec!["l"],
                    description: "Link scrubbing: arrow keys scrub all media series in sync (media pane focused)",
                    handler: None,
                },
                KeyBinding {
                    keys: vec!["k"],
                    description: "Toggle media image renderer: ANSI ↔ full-res (media pane focused)",
                    handler: None,
                },
            ],
        },
        mouse_category::<WorkspaceAction>(),
    ]
}

/// SymonKeyBindings returns key bindings for the standalone system monitor view.
pub fn symon_key_bindings() -> Vec<BindingCategory<SymonAction>> {
    vec![
        BindingCategory {
            name: "General",
            bindings: vec![
                KeyBinding {
                    keys: vec!["h", "?"],
                    description: "Toggle this help screen",
                    handler: None,
                },
                KeyBinding {
                    keys: vec!["q", "ctrl+c"],
                    description: "Quit",
                    handler: Some(SymonAction::Quit),
                },
                KeyBinding {
                    keys: vec!["alt+r"],
                    description: "Restart",
                    handler: None,
                },
            ],
        },
        BindingCategory {
            name: "Navigation",
            bindings: vec![
                KeyBinding {
                    keys: concat_keys(&[
                        nav_keys_for(NavIntent::Up),
                        nav_keys_for(NavIntent::Down),
                        nav_keys_for(NavIntent::Left),
                        nav_keys_for(NavIntent::Right),
                    ]),
                    description: "Navigate chart focus within page",
                    handler: Some(SymonAction::GridNav),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::PageUp).to_vec(),
                    description: "Previous chart page",
                    handler: Some(SymonAction::PrevPage),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::PageDown).to_vec(),
                    description: "Next chart page",
                    handler: Some(SymonAction::NextPage),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::Home).to_vec(),
                    description: "Jump to first chart page",
                    handler: Some(SymonAction::NavHome),
                },
                KeyBinding {
                    keys: nav_keys_for(NavIntent::End).to_vec(),
                    description: "Jump to last chart page",
                    handler: Some(SymonAction::NavEnd),
                },
            ],
        },
        BindingCategory {
            name: "Charts",
            bindings: vec![
                KeyBinding {
                    keys: vec!["y"],
                    description: "Toggle log Y on focused chart",
                    handler: Some(SymonAction::ToggleFocusedChartLogY),
                },
                KeyBinding {
                    keys: vec!["\\"],
                    description: "Filter system metrics by pattern",
                    handler: Some(SymonAction::EnterSystemMetricsFilter),
                },
                KeyBinding {
                    keys: vec!["ctrl+\\"],
                    description: "Clear system metrics filter",
                    handler: Some(SymonAction::ClearSystemMetricsFilter),
                },
            ],
        },
        BindingCategory {
            name: "Configuration",
            bindings: vec![
                KeyBinding {
                    keys: vec!["c", "C"],
                    description: "Set grid columns",
                    handler: Some(SymonAction::ConfigSystemCols),
                },
                KeyBinding {
                    keys: vec!["r", "R"],
                    description: "Set grid rows",
                    handler: Some(SymonAction::ConfigSystemRows),
                },
            ],
        },
        mouse_category::<SymonAction>(),
    ]
}

/// buildKeyMap builds a fast lookup map from key string to handler.
pub fn build_key_map<A: Copy>(categories: &[BindingCategory<A>]) -> HashMap<&'static str, A> {
    let mut key_map = HashMap::new();
    for category in categories {
        for binding in &category.bindings {
            let Some(handler) = binding.handler else {
                continue;
            };
            for key in &binding.keys {
                key_map.insert(normalize_key(key), handler);
            }
        }
    }
    key_map
}

fn mouse_category<A>() -> BindingCategory<A> {
    BindingCategory {
        name: "Mouse",
        bindings: vec![
            KeyBinding {
                keys: vec!["wheel"],
                description: "Zoom in/out on focused chart",
                handler: None,
            },
            KeyBinding {
                keys: vec!["right-click+drag"],
                description: "Inspect: show (x, y) at nearest point on a chart",
                handler: None,
            },
            KeyBinding {
                keys: vec!["alt+right-click+drag"],
                description: "Inspect all visible charts in sync",
                handler: None,
            },
            KeyBinding {
                keys: vec!["shift+drag"],
                description: "Select text",
                handler: None,
            },
        ],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn binding_count<A>(categories: &[BindingCategory<A>]) -> usize {
        categories.iter().map(|c| c.bindings.len()).sum()
    }

    /// Rust-only: locks the table shape against the Go tables
    /// (keybindings.go) — category names in help order and binding counts
    /// per view. The strings themselves are covered by the differential
    /// harness rendering the help overlay.
    #[test]
    fn binding_tables_match_go_shape() {
        let run = run_key_bindings();
        assert_eq!(
            run.iter().map(|c| c.name).collect::<Vec<_>>(),
            vec![
                "General",
                "Panels",
                "Navigation (focused pane)",
                "Charts",
                "Run Overview",
                "Configuration",
                "Focusable panes (when open)",
                "Mouse",
            ]
        );
        assert_eq!(binding_count(&run), 34);

        let workspace = workspace_key_bindings();
        assert_eq!(
            workspace.iter().map(|c| c.name).collect::<Vec<_>>(),
            vec![
                "General",
                "Panels",
                "Navigation (focused pane)",
                "Runs",
                "Charts",
                "Run Overview",
                "Configuration",
                "Focusable panes (when open)",
                "Mouse",
            ]
        );
        assert_eq!(binding_count(&workspace), 40);

        let symon = symon_key_bindings();
        assert_eq!(
            symon.iter().map(|c| c.name).collect::<Vec<_>>(),
            vec!["General", "Navigation", "Charts", "Configuration", "Mouse",]
        );
        assert_eq!(binding_count(&symon), 17);
    }

    /// Rust-only: locks `build_key_map` behavior — documentation-only
    /// bindings (no handler) are skipped, every handler-bearing key lands
    /// under its normalized name, and the per-view distinct-key counts
    /// match the Go tables.
    #[test]
    fn build_key_map_matches_go_tables() {
        let run_map = build_key_map(&run_key_bindings());
        assert_eq!(run_map.len(), 34);
        assert_eq!(run_map.get("q"), Some(&RunAction::Quit));
        assert_eq!(run_map.get("ctrl+c"), Some(&RunAction::Quit));
        assert_eq!(
            run_map.get("ctrl+\\"),
            Some(&RunAction::ClearSystemMetricsFilter)
        );
        // "ctrl+/" only ever reaches the map via the kitty CSI-u encoding
        // (see key.rs: legacy 0x1F stringifies as "ctrl+_", as in Go).
        assert_eq!(run_map.get("ctrl+/"), Some(&RunAction::ClearMetricsFilter));
        assert_eq!(run_map.get("ctrl+l"), Some(&RunAction::ClearMetricsFilter));
        assert_eq!(run_map.get("ctrl+_"), None);
        assert_eq!(run_map.get("shift+tab"), Some(&RunAction::SidebarTabNav));
        // Documentation-only bindings are not dispatched.
        assert_eq!(run_map.get("h"), None);
        assert_eq!(run_map.get("?"), None);
        assert_eq!(run_map.get("alt+r"), None);
        assert_eq!(run_map.get("esc"), None);
        assert_eq!(run_map.get("l"), None);
        assert_eq!(run_map.get("k"), None);
        assert_eq!(run_map.get("w/s/a/d"), None);
        assert_eq!(run_map.get("wheel"), None);

        let workspace_map = build_key_map(&workspace_key_bindings());
        assert_eq!(workspace_map.len(), 39);
        assert_eq!(workspace_map.get("esc"), Some(&WorkspaceAction::FocusRuns));
        // "space" is stored under its normalized (already-explicit) name.
        assert_eq!(
            workspace_map.get("space"),
            Some(&WorkspaceAction::ToggleRunSelectedKey)
        );
        assert_eq!(workspace_map.get("p"), Some(&WorkspaceAction::PinRunKey));
        assert_eq!(workspace_map.get("enter"), None);
        assert_eq!(
            workspace_map.get("ctrl+/"),
            Some(&WorkspaceAction::ClearMetricsFilter)
        );
        assert_eq!(
            workspace_map.get("ctrl+\\"),
            Some(&WorkspaceAction::ClearSystemMetricsFilter)
        );

        let symon_map = build_key_map(&symon_key_bindings());
        assert_eq!(symon_map.len(), 23);
        // concatKeys: all eight grid-nav keys share one handler.
        for key in ["w", "up", "s", "down", "a", "left", "d", "right"] {
            assert_eq!(
                symon_map.get(key),
                Some(&SymonAction::GridNav),
                "key {key:?}"
            );
        }
        // Symon binds the shifted config forms too.
        assert_eq!(symon_map.get("C"), Some(&SymonAction::ConfigSystemCols));
        assert_eq!(symon_map.get("R"), Some(&SymonAction::ConfigSystemRows));
    }
}

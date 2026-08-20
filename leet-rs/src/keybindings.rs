//! Key binding documentation shown on the help screen.
//!
//! Unlike the Go implementation, key dispatch happens in each view's
//! `handle_key` match; these tables only drive the help display.

use crate::nav::{NavIntent, nav_keys_for};

/// A single documented key binding.
pub struct HelpBinding {
    pub keys: Vec<&'static str>,
    pub description: &'static str,
}

/// Groups related key bindings for help display.
pub struct HelpCategory {
    pub name: &'static str,
    pub bindings: Vec<HelpBinding>,
}

fn b(keys: &[&'static str], description: &'static str) -> HelpBinding {
    HelpBinding {
        keys: keys.to_vec(),
        description,
    }
}

fn nav(intent: NavIntent, description: &'static str) -> HelpBinding {
    HelpBinding {
        keys: nav_keys_for(intent).to_vec(),
        description,
    }
}

/// Key bindings relevant to the single-run view.
pub fn run_key_bindings() -> Vec<HelpCategory> {
    vec![
        HelpCategory {
            name: "General",
            bindings: vec![
                b(&["h", "?"], "Toggle this help screen"),
                b(&["q", "ctrl+c"], "Quit"),
                b(
                    &["esc"],
                    "Back to workspace (when not filtering/configuring)",
                ),
            ],
        },
        HelpCategory {
            name: "Panels",
            bindings: vec![
                b(&["1"], "Toggle metrics grid"),
                b(&["["], "Toggle left sidebar with run overview"),
                b(&["]", "2"], "Toggle right sidebar with system metrics"),
                b(&["3"], "Toggle media pane"),
                b(&["4"], "Toggle console logs panel"),
                b(&["0"], "Reset pane sizes to defaults"),
            ],
        },
        HelpCategory {
            name: "Navigation (focused pane)",
            bindings: vec![
                b(
                    &["w/s/a/d", "↑/↓/←/→"],
                    "Move within focused pane (chart focus on grids, item nav on lists)",
                ),
                nav(
                    NavIntent::PageUp,
                    "Previous page / previous series page in media",
                ),
                nav(NavIntent::PageDown, "Next page / next series page in media"),
                nav(
                    NavIntent::Home,
                    "Jump to first item / first page / scrub to start",
                ),
                nav(
                    NavIntent::End,
                    "Jump to last item / last page / scrub to end",
                ),
            ],
        },
        HelpCategory {
            name: "Charts",
            bindings: vec![
                b(&["y"], "Cycle focused chart mode (log Y / heatmap)"),
                b(&["/"], "Filter metrics by pattern"),
                b(&["\\"], "Filter system metrics by pattern"),
                b(&["ctrl+/", "ctrl+l"], "Clear metrics filter"),
                b(&["ctrl+\\"], "Clear system metrics filter"),
            ],
        },
        HelpCategory {
            name: "Run Overview",
            bindings: vec![
                b(&["o"], "Filter overview items"),
                b(&["ctrl+o"], "Clear overview filter"),
            ],
        },
        HelpCategory {
            name: "Configuration",
            bindings: vec![
                b(&["c"], "Set grid columns (focused pane)"),
                b(&["r"], "Set grid rows (focused pane)"),
            ],
        },
        HelpCategory {
            name: "Focusable panes (when open)",
            bindings: vec![
                b(
                    &["tab", "shift+tab"],
                    "Cycle focus: overview ↔ metrics ↔ media ↔ logs ↔ system",
                ),
                nav(
                    NavIntent::Up,
                    "Item up (list) / chart focus up (grid) / scrub -10 in media (arrow only)",
                ),
                nav(
                    NavIntent::Down,
                    "Item down (list) / chart focus down (grid) / scrub +10 in media (arrow only)",
                ),
                nav(
                    NavIntent::Left,
                    "Page prev (list) / chart focus left (grid) / scrub -1 in media (arrow only)",
                ),
                nav(
                    NavIntent::Right,
                    "Page next (list) / chart focus right (grid) / scrub +1 in media (arrow only)",
                ),
                b(
                    &["l"],
                    "Link scrubbing: arrow keys scrub all media series in sync (media pane focused)",
                ),
                b(
                    &["k"],
                    "Toggle media image renderer: ANSI ↔ full-res (media pane focused)",
                ),
            ],
        },
        mouse_category(),
    ]
}

/// Key bindings relevant to the workspace view.
pub fn workspace_key_bindings() -> Vec<HelpCategory> {
    vec![
        HelpCategory {
            name: "General",
            bindings: vec![
                b(&["h", "?"], "Toggle this help screen"),
                b(&["q", "ctrl+c"], "Quit"),
                b(&["esc"], "Focus runs list"),
                b(
                    &["enter"],
                    "View selected run (when not filtering/configuring)",
                ),
            ],
        },
        HelpCategory {
            name: "Panels",
            bindings: vec![
                b(&["1"], "Toggle metrics grid"),
                b(&["["], "Toggle runs sidebar"),
                b(&["2"], "Toggle system metrics panel"),
                b(&["]"], "Toggle run overview sidebar"),
                b(&["3"], "Toggle media pane"),
                b(&["4"], "Toggle console logs panel"),
                b(&["0"], "Reset pane sizes to defaults"),
            ],
        },
        HelpCategory {
            name: "Navigation (focused pane)",
            bindings: vec![
                b(
                    &["w/s/a/d", "↑/↓/←/→"],
                    "Move within focused pane (chart focus on grids, item nav on lists)",
                ),
                nav(
                    NavIntent::PageUp,
                    "Previous page / previous series page in media",
                ),
                nav(NavIntent::PageDown, "Next page / next series page in media"),
                nav(
                    NavIntent::Home,
                    "Jump to first item / first page / scrub to start",
                ),
                nav(
                    NavIntent::End,
                    "Jump to last item / last page / scrub to end",
                ),
            ],
        },
        HelpCategory {
            name: "Runs",
            bindings: vec![
                b(&["f"], "Filter runs by name / metadata"),
                b(&["ctrl+f"], "Clear runs filter"),
            ],
        },
        HelpCategory {
            name: "Charts",
            bindings: vec![
                b(&["y"], "Cycle focused chart mode (log Y / heatmap)"),
                b(&["/"], "Filter metrics by pattern"),
                b(&["\\"], "Filter system metrics by pattern"),
                b(&["ctrl+/", "ctrl+l"], "Clear metrics filter"),
                b(&["ctrl+\\"], "Clear system metrics filter"),
            ],
        },
        HelpCategory {
            name: "Run Overview",
            bindings: vec![
                b(&["o"], "Filter overview items"),
                b(&["ctrl+o"], "Clear overview filter"),
            ],
        },
        HelpCategory {
            name: "Configuration",
            bindings: vec![
                b(&["c"], "Set grid columns (focused pane)"),
                b(&["r"], "Set grid rows (focused pane)"),
            ],
        },
        HelpCategory {
            name: "Focusable panes (when open)",
            bindings: vec![
                b(
                    &["tab", "shift+tab"],
                    "Cycle focus: runs ↔ metrics ↔ system ↔ media ↔ logs ↔ overview",
                ),
                nav(
                    NavIntent::Up,
                    "Item up (list) / chart focus up (grid) / scrub -10 in media (arrow only)",
                ),
                nav(
                    NavIntent::Down,
                    "Item down (list) / chart focus down (grid) / scrub +10 in media (arrow only)",
                ),
                nav(
                    NavIntent::Left,
                    "Page prev (list) / chart focus left (grid) / scrub -1 in media (arrow only)",
                ),
                nav(
                    NavIntent::Right,
                    "Page next (list) / chart focus right (grid) / scrub +1 in media (arrow only)",
                ),
                b(&["space"], "Select/deselect run"),
                b(&["p"], "Pin/unpin selected run"),
                b(
                    &["l"],
                    "Link scrubbing: arrow keys scrub all media series in sync (media pane focused)",
                ),
                b(
                    &["k"],
                    "Toggle media image renderer: ANSI ↔ full-res (media pane focused)",
                ),
            ],
        },
        mouse_category(),
    ]
}

/// Key bindings for the standalone system monitor view.
pub fn symon_key_bindings() -> Vec<HelpCategory> {
    let mut nav_keys: Vec<&'static str> = Vec::new();
    for intent in [
        NavIntent::Up,
        NavIntent::Down,
        NavIntent::Left,
        NavIntent::Right,
    ] {
        nav_keys.extend_from_slice(nav_keys_for(intent));
    }

    vec![
        HelpCategory {
            name: "General",
            bindings: vec![
                b(&["h", "?"], "Toggle this help screen"),
                b(&["q", "ctrl+c"], "Quit"),
            ],
        },
        HelpCategory {
            name: "Navigation",
            bindings: vec![
                HelpBinding {
                    keys: nav_keys,
                    description: "Navigate chart focus within page",
                },
                nav(NavIntent::PageUp, "Previous chart page"),
                nav(NavIntent::PageDown, "Next chart page"),
                nav(NavIntent::Home, "Jump to first chart page"),
                nav(NavIntent::End, "Jump to last chart page"),
            ],
        },
        HelpCategory {
            name: "Charts",
            bindings: vec![
                b(&["y"], "Toggle log Y on focused chart"),
                b(&["\\"], "Filter system metrics by pattern"),
                b(&["ctrl+\\"], "Clear system metrics filter"),
            ],
        },
        HelpCategory {
            name: "Configuration",
            bindings: vec![
                b(&["c", "C"], "Set grid columns"),
                b(&["r", "R"], "Set grid rows"),
            ],
        },
        mouse_category(),
    ]
}

fn mouse_category() -> HelpCategory {
    HelpCategory {
        name: "Mouse",
        bindings: vec![
            b(&["wheel"], "Zoom in/out on focused chart"),
            b(
                &["right-click+drag"],
                "Inspect: show (x, y) at nearest point on a chart",
            ),
            b(
                &["alt+right-click+drag"],
                "Inspect all visible charts in sync",
            ),
            b(
                &["drag border/separator"],
                "Resize panes (press 0 to reset)",
            ),
            b(&["shift+drag"], "Select text"),
        ],
    }
}

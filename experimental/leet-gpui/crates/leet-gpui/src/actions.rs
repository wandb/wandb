//! Actions and the keymap, ported from `core/internal/leet/keybindings.go`
//! and `nav.go`. One table drives both key dispatch and the help overlay.

use gpui::{App, KeyBinding, actions};

actions!(
    leet,
    [
        Quit,
        ToggleHelp,
        Escape,
        Confirm,
        Backspace,
        MoveUp,
        MoveDown,
        MoveLeft,
        MoveRight,
        PageUp,
        PageDown,
        Home,
        End,
        FocusNext,
        FocusPrev,
        ToggleSelect,
        ToggleRunsSidebar,
        ToggleMetrics,
        ToggleLogY,
        CycleSmoothing,
        FilterRuns,
        FilterMetrics,
        ClearFilter,
    ]
);

/// Key context of the workspace when no text field is active.
pub const WORKSPACE: &str = "Workspace";
/// Key context while a filter is being typed.
pub const FILTER: &str = "Filter";

/// Human-readable key list and description, one per action.
pub type Help = Vec<(&'static str, &'static str)>;

macro_rules! keymap {
    ($cx:expr, $bindings:ident, $help:ident; $( [$($key:literal),+] $ctx:expr => $action:expr, $desc:literal; )+) => {
        $(
            $( $bindings.push(KeyBinding::new($key, $action, Some($ctx))); )+
            $help.push((concat!($($key, " "),+), $desc));
        )+
    };
}

/// Registers the keymap and returns the help table.
pub fn bind(cx: &mut App) -> Help {
    let mut bindings = Vec::new();
    let mut help = Vec::new();
    keymap!(cx, bindings, help;
        ["h", "?"] WORKSPACE => ToggleHelp, "Toggle this help screen";
        ["q", "ctrl-c"] WORKSPACE => Quit, "Quit";
        ["escape"] WORKSPACE => Escape, "Close help, clear a filter, or focus the runs list";
        ["["] WORKSPACE => ToggleRunsSidebar, "Toggle runs sidebar";
        ["1"] WORKSPACE => ToggleMetrics, "Toggle metrics grid";
        ["tab", "shift-tab"] WORKSPACE => FocusNext, "Cycle focus: runs / metrics";
        ["w", "up"] WORKSPACE => MoveUp, "Run up (list) / chart focus up (grid)";
        ["s", "down"] WORKSPACE => MoveDown, "Run down (list) / chart focus down (grid)";
        ["a", "left"] WORKSPACE => MoveLeft, "Chart focus left (grid)";
        ["d", "right"] WORKSPACE => MoveRight, "Chart focus right (grid)";
        ["shift-n", "pageup"] WORKSPACE => PageUp, "Previous page";
        ["n", "pagedown"] WORKSPACE => PageDown, "Next page";
        ["home"] WORKSPACE => Home, "First item / first page";
        ["end"] WORKSPACE => End, "Last item / last page";
        ["space"] WORKSPACE => ToggleSelect, "Select or deselect the run under the cursor";
        ["f"] WORKSPACE => FilterRuns, "Filter runs";
        ["/"] WORKSPACE => FilterMetrics, "Filter metrics by pattern";
        ["ctrl-f", "ctrl-/", "ctrl-l"] WORKSPACE => ClearFilter, "Clear the filter of the focused pane";
        ["y"] WORKSPACE => ToggleLogY, "Toggle log Y on the focused chart";
        ["m"] WORKSPACE => CycleSmoothing, "Cycle smoothing (off / 0.6 / 0.9 / 0.99)";
        ["escape"] FILTER => Escape, "Stop editing the filter";
        ["enter"] FILTER => Confirm, "Apply the filter";
        ["backspace"] FILTER => Backspace, "Delete the last character";
    );
    bindings.push(KeyBinding::new("shift-tab", FocusPrev, Some(WORKSPACE)));
    cx.bind_keys(bindings);
    help
}

package leet

import (
	tea "charm.land/bubbletea/v2"
)

// KeyBinding defines a key binding for a particular target type.
//
// If Handler is nil, the binding is shown in the help screen but is not dispatched
// through the key map (useful for documentation-only bindings handled by a child
// component or a parent model).
type KeyBinding[T any] struct {
	Keys        []string
	Description string
	Handler     func(*T, tea.KeyPressMsg) tea.Cmd
}

// BindingCategory groups related key bindings (primarily for help display).
type BindingCategory[T any] struct {
	Name     string
	Bindings []KeyBinding[T]
}

// RunKeyBindings returns key bindings relevant to the single-run view.
func RunKeyBindings() []BindingCategory[Run] {
	return []BindingCategory[Run]{
		{
			Name: "General",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"h", "?"},
					Description: "Toggle this help screen",
				},
				{
					Keys:        []string{"q", "ctrl+c"},
					Description: "Quit",
					Handler:     (*Run).handleQuit,
				},
				{
					Keys:        []string{"alt+r"},
					Description: "Restart",
				},
				{
					Keys:        []string{"esc"},
					Description: "Back to workspace (when not filtering/configuring)",
				},
			},
		},
		{
			Name: "Panels",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"1"},
					Description: "Toggle metrics grid",
					Handler:     (*Run).handleToggleMetricsGrid,
				},
				{
					Keys:        []string{"["},
					Description: "Toggle left sidebar with run overview",
					Handler:     (*Run).handleToggleLeftSidebar,
				},
				{
					Keys:        []string{"]"},
					Description: "Toggle right sidebar with system metrics",
					Handler:     (*Run).handleToggleRightSidebar,
				},
				{
					Keys:        []string{"3"},
					Description: "Toggle media pane",
					Handler:     (*Run).handleToggleMediaPane,
				},
				{
					Keys:        []string{"4"},
					Description: "Toggle console logs panel",
					Handler:     (*Run).handleToggleConsoleLogsPane,
				},
			},
		},
		{
			Name: "Navigation (focused pane)",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"w/s/a/d", "↑/↓/←/→"},
					Description: "Move within focused pane (chart focus on grids, item nav on lists)",
				},
				{
					Keys:        NavKeysFor(NavIntentPageUp),
					Description: "Previous page / previous series page in media",
					Handler:     (*Run).handlePrevPage,
				},
				{
					Keys:        NavKeysFor(NavIntentPageDown),
					Description: "Next page / next series page in media",
					Handler:     (*Run).handleNextPage,
				},
				{
					Keys:        NavKeysFor(NavIntentHome),
					Description: "Jump to first item / first page / scrub to start",
					Handler:     (*Run).handleNavHome,
				},
				{
					Keys:        NavKeysFor(NavIntentEnd),
					Description: "Jump to last item / last page / scrub to end",
					Handler:     (*Run).handleNavEnd,
				},
			},
		},
		{
			Name: "Charts",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"y"},
					Description: "Cycle focused chart mode (log Y / heatmap)",
					Handler:     (*Run).handleCycleFocusedChartMode,
				},
				{
					Keys:        []string{"/"},
					Description: "Filter metrics by pattern",
					Handler:     (*Run).handleEnterMetricsFilter,
				},
				{
					Keys:        []string{"\\"},
					Description: "Filter system metrics by pattern",
					Handler:     (*Run).handleEnterSystemMetricsFilter,
				},
				{
					Keys:        []string{"ctrl+/", "ctrl+l"},
					Description: "Clear metrics filter",
					Handler:     (*Run).handleClearMetricsFilter,
				},
				{
					Keys:        []string{"ctrl+\\"},
					Description: "Clear system metrics filter",
					Handler:     (*Run).handleClearSystemMetricsFilter,
				},
			},
		},
		{
			Name: "Run Overview",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"o"},
					Description: "Filter overview items",
					Handler:     (*Run).handleEnterOverviewFilter,
				},
				{
					Keys:        []string{"ctrl+o"},
					Description: "Clear overview filter",
					Handler:     (*Run).handleClearOverviewFilter,
				},
			},
		},
		{
			Name: "Configuration",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"c"},
					Description: "Set grid columns (focused pane)",
					Handler:     (*Run).handleConfigFocusedCols,
				},
				{
					Keys:        []string{"r"},
					Description: "Set grid rows (focused pane)",
					Handler:     (*Run).handleConfigFocusedRows,
				},
			},
		},

		{
			Name: "Focusable panes (when open)",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"tab", "shift+tab"},
					Description: "Cycle focus: overview ↔ metrics ↔ system ↔ media ↔ logs",
					Handler:     (*Run).handleSidebarTabNav,
				},
				{
					Keys:        NavKeysFor(NavIntentUp),
					Description: "Item up (list) / chart focus up (grid) / scrub -10 in media (arrow only)",
					Handler:     (*Run).handleSidebarVerticalNav,
				},
				{
					Keys:        NavKeysFor(NavIntentDown),
					Description: "Item down (list) / chart focus down (grid) / scrub +10 in media (arrow only)",
					Handler:     (*Run).handleSidebarVerticalNav,
				},
				{
					Keys:        NavKeysFor(NavIntentLeft),
					Description: "Page prev (list) / chart focus left (grid) / scrub -1 in media (arrow only)",
					Handler:     (*Run).handleSidebarPageNav,
				},
				{
					Keys:        NavKeysFor(NavIntentRight),
					Description: "Page next (list) / chart focus right (grid) / scrub +1 in media (arrow only)",
					Handler:     (*Run).handleSidebarPageNav,
				},
			},
		},

		mouseCategory[Run](),
	}
}

// WorkspaceKeyBindings returns key bindings relevant to the workspace view.
func WorkspaceKeyBindings() []BindingCategory[Workspace] {
	return []BindingCategory[Workspace]{
		{
			Name: "General",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"h", "?"},
					Description: "Toggle this help screen",
				},
				{
					Keys:        []string{"q", "ctrl+c"},
					Description: "Quit",
					Handler:     (*Workspace).handleQuit,
				},
				{
					Keys:        []string{"alt+r"},
					Description: "Restart LEET",
				},
				{
					Keys:        []string{"esc"},
					Description: "Focus runs list",
					Handler:     (*Workspace).handleFocusRuns,
				},
				{
					Keys:        []string{"enter"},
					Description: "View selected run (when not filtering/configuring)",
				},
			},
		},
		{
			Name: "Panels",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"1"},
					Description: "Toggle metrics grid",
					Handler:     (*Workspace).handleToggleMetricsGrid,
				},
				{
					Keys:        []string{"["},
					Description: "Toggle runs sidebar",
					Handler:     (*Workspace).handleToggleRunsSidebar,
				},
				{
					Keys:        []string{"2"},
					Description: "Toggle system metrics panel",
					Handler:     (*Workspace).handleToggleSystemMetricsPane,
				},
				{
					Keys:        []string{"]"},
					Description: "Toggle run overview sidebar",
					Handler:     (*Workspace).handleToggleOverviewSidebar,
				},
				{
					Keys:        []string{"3"},
					Description: "Toggle media pane",
					Handler:     (*Workspace).handleToggleMediaPane,
				},
				{
					Keys:        []string{"4"},
					Description: "Toggle console logs panel",
					Handler:     (*Workspace).handleToggleConsoleLogsPane,
				},
			},
		},
		{
			Name: "Navigation (focused pane)",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"w/s/a/d", "↑/↓/←/→"},
					Description: "Move within focused pane (chart focus on grids, item nav on lists)",
				},
				{
					Keys:        NavKeysFor(NavIntentPageUp),
					Description: "Previous page / previous series page in media",
					Handler:     (*Workspace).handlePrevPage,
				},
				{
					Keys:        NavKeysFor(NavIntentPageDown),
					Description: "Next page / next series page in media",
					Handler:     (*Workspace).handleNextPage,
				},
				{
					Keys:        NavKeysFor(NavIntentHome),
					Description: "Jump to first item / first page / scrub to start",
					Handler:     (*Workspace).handleNavHome,
				},
				{
					Keys:        NavKeysFor(NavIntentEnd),
					Description: "Jump to last item / last page / scrub to end",
					Handler:     (*Workspace).handleNavEnd,
				},
			},
		},
		{
			Name: "Runs",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"f"},
					Description: "Filter runs by name / metadata",
					Handler:     (*Workspace).handleEnterRunsFilter,
				},
				{
					Keys:        []string{"ctrl+f"},
					Description: "Clear runs filter",
					Handler:     (*Workspace).handleClearRunsFilter,
				},
			},
		},
		{
			Name: "Charts",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"y"},
					Description: "Cycle focused chart mode (log Y / heatmap)",
					Handler:     (*Workspace).handleCycleFocusedChartMode,
				},
				{
					Keys:        []string{"/"},
					Description: "Filter metrics by pattern",
					Handler:     (*Workspace).handleEnterMetricsFilter,
				},
				{
					Keys:        []string{"\\"},
					Description: "Filter system metrics by pattern",
					Handler:     (*Workspace).handleEnterSystemMetricsFilter,
				},
				{
					// TODO: remove ctrl+l.
					Keys:        []string{"ctrl+/", "ctrl+l"},
					Description: "Clear metrics filter",
					Handler:     (*Workspace).handleClearMetricsFilter,
				},
				{
					Keys:        []string{"ctrl+\\"},
					Description: "Clear system metrics filter",
					Handler:     (*Workspace).handleClearSystemMetricsFilter,
				},
			},
		},
		{
			Name: "Run Overview",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"o"},
					Description: "Filter overview items",
					Handler:     (*Workspace).handleEnterOverviewFilter,
				},
				{
					Keys:        []string{"ctrl+o"},
					Description: "Clear overview filter",
					Handler:     (*Workspace).handleClearOverviewFilter,
				},
			},
		},
		{
			Name: "Configuration",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"c"},
					Description: "Set grid columns (focused pane)",
					Handler:     (*Workspace).handleConfigFocusedCols,
				},
				{
					Keys:        []string{"r"},
					Description: "Set grid rows (focused pane)",
					Handler:     (*Workspace).handleConfigFocusedRows,
				},
			},
		},
		{
			Name: "Focusable panes (when open)",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"tab", "shift+tab"},
					Description: "Cycle focus: runs ↔ metrics ↔ system ↔ media ↔ logs ↔ overview",
					Handler:     (*Workspace).handleSidebarTabNav,
				},
				{
					Keys:        NavKeysFor(NavIntentUp),
					Description: "Item up (list) / chart focus up (grid) / scrub -10 in media (arrow only)",
					Handler:     (*Workspace).handleRunsVerticalNav,
				},
				{
					Keys:        NavKeysFor(NavIntentDown),
					Description: "Item down (list) / chart focus down (grid) / scrub +10 in media (arrow only)",
					Handler:     (*Workspace).handleRunsVerticalNav,
				},
				{
					Keys:        NavKeysFor(NavIntentLeft),
					Description: "Page prev (list) / chart focus left (grid) / scrub -1 in media (arrow only)",
					Handler:     (*Workspace).handleRunsPageNav,
				},
				{
					Keys:        NavKeysFor(NavIntentRight),
					Description: "Page next (list) / chart focus right (grid) / scrub +1 in media (arrow only)",
					Handler:     (*Workspace).handleRunsPageNav,
				},
				{
					Keys:        []string{"space"},
					Description: "Select/deselect run",
					Handler:     (*Workspace).handleToggleRunSelectedKey,
				},
				{
					Keys:        []string{"p"},
					Description: "Pin/unpin selected run",
					Handler:     (*Workspace).handlePinRunKey,
				},
			},
		},

		mouseCategory[Workspace](),
	}
}

// SymonKeyBindings returns key bindings for the standalone system monitor view.
func SymonKeyBindings() []BindingCategory[Symon] {
	return []BindingCategory[Symon]{
		{
			Name: "General",
			Bindings: []KeyBinding[Symon]{
				{
					Keys:        []string{"h", "?"},
					Description: "Toggle this help screen",
				},
				{
					Keys:        []string{"q", "ctrl+c"},
					Description: "Quit",
					Handler:     (*Symon).handleQuit,
				},
				{
					Keys:        []string{"alt+r"},
					Description: "Restart",
				},
			},
		},
		{
			Name: "Navigation",
			Bindings: []KeyBinding[Symon]{
				{
					Keys: concatKeys(
						NavKeysFor(NavIntentUp), NavKeysFor(NavIntentDown),
						NavKeysFor(NavIntentLeft), NavKeysFor(NavIntentRight),
					),
					Description: "Navigate chart focus within page",
					Handler:     (*Symon).handleGridNav,
				},
				{
					Keys:        NavKeysFor(NavIntentPageUp),
					Description: "Previous chart page",
					Handler:     (*Symon).handlePrevPage,
				},
				{
					Keys:        NavKeysFor(NavIntentPageDown),
					Description: "Next chart page",
					Handler:     (*Symon).handleNextPage,
				},
				{
					Keys:        NavKeysFor(NavIntentHome),
					Description: "Jump to first chart page",
					Handler:     (*Symon).handleNavHome,
				},
				{
					Keys:        NavKeysFor(NavIntentEnd),
					Description: "Jump to last chart page",
					Handler:     (*Symon).handleNavEnd,
				},
			},
		},
		{
			Name: "Charts",
			Bindings: []KeyBinding[Symon]{
				{
					Keys:        []string{"y"},
					Description: "Toggle log Y on focused chart",
					Handler:     (*Symon).handleToggleFocusedChartLogY,
				},
				{
					Keys:        []string{"\\"},
					Description: "Filter system metrics by pattern",
					Handler:     (*Symon).handleEnterSystemMetricsFilter,
				},
				{
					Keys:        []string{"ctrl+\\"},
					Description: "Clear system metrics filter",
					Handler:     (*Symon).handleClearSystemMetricsFilter,
				},
			},
		},
		{
			Name: "Configuration",
			Bindings: []KeyBinding[Symon]{
				{
					Keys:        []string{"c", "C"},
					Description: "Set grid columns",
					Handler:     (*Symon).handleConfigSystemCols,
				},
				{
					Keys:        []string{"r", "R"},
					Description: "Set grid rows",
					Handler:     (*Symon).handleConfigSystemRows,
				},
			},
		},

		mouseCategory[Symon](),
	}
}

// buildKeyMap builds a fast lookup map from key string to handler.
func buildKeyMap[T any](
	categories []BindingCategory[T]) map[string]func(*T, tea.KeyPressMsg) tea.Cmd {
	keyMap := make(map[string]func(*T, tea.KeyPressMsg) tea.Cmd)
	for _, category := range categories {
		for _, binding := range category.Bindings {
			if binding.Handler == nil {
				continue
			}
			for _, key := range binding.Keys {
				keyMap[normalizeKey(key)] = binding.Handler
			}
		}
	}
	return keyMap
}

// normalizeKey normalizes Bubble Tea's KeyPressMsg into a stable key used by our maps.
//
// Bubble Tea has historically reported space as " " in some situations; we want a
// help-friendly, explicit key name.
func normalizeKey(key string) string {
	if key == " " {
		return "space"
	}
	return key
}

func mouseCategory[T any]() BindingCategory[T] {
	return BindingCategory[T]{
		Name: "Mouse",
		Bindings: []KeyBinding[T]{
			{
				Keys:        []string{"wheel"},
				Description: "Zoom in/out on focused chart",
			},
			{
				Keys:        []string{"right-click+drag"},
				Description: "Inspect: show (x, y) at nearest point on a chart",
			},
			{
				Keys:        []string{"alt+right-click+drag"},
				Description: "Inspect all visible charts in sync",
			},
			{
				Keys:        []string{"shift+drag"},
				Description: "Select text",
			},
		},
	}
}

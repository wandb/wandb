package leet

import (
	tea "github.com/charmbracelet/bubbletea"
)

// KeyBinding defines a key binding for a particular target type.
//
// If Handler is nil, the binding is shown in the help screen but is not dispatched
// through the key map (useful for documentation-only bindings handled by a child
// component or a parent model).
type KeyBinding[T any] struct {
	Keys        []string
	Description string
	Handler     func(*T, tea.KeyMsg) tea.Cmd
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
					Description: "Restart LEET",
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
					Keys:        []string{"["},
					Description: "Toggle left sidebar with run overview",
					Handler:     (*Run).handleToggleLeftSidebar,
				},
				{
					Keys:        []string{"]"},
					Description: "Toggle right sidebar with system metrics",
					Handler:     (*Run).handleToggleRightSidebar,
				},
			},
		},
		{
			Name: "Navigation",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"N", "pgup"},
					Description: "Previous chart page",
					Handler:     (*Run).handlePrevPage,
				},
				{
					Keys:        []string{"n", "pgdown"},
					Description: "Next chart page",
					Handler:     (*Run).handleNextPage,
				},
				{
					Keys:        []string{"alt+N", "alt+pgup"},
					Description: "Previous system metrics page",
					Handler:     (*Run).handlePrevSystemPage,
				},
				{
					Keys:        []string{"alt+n", "alt+pgdown"},
					Description: "Next system metrics page",
					Handler:     (*Run).handleNextSystemPage,
				},
			},
		},
		{
			Name: "Charts",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"/"},
					Description: "Filter metrics by pattern",
					Handler:     (*Run).handleEnterMetricsFilter,
				},
				{
					Keys:        []string{"ctrl+l"},
					Description: "Clear active filter",
					Handler:     (*Run).handleClearMetricsFilter,
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
					Keys:        []string{"ctrl+k"},
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
					Description: "Set metrics grid columns",
					Handler:     (*Run).handleConfigMetricsCols,
				},
				{
					Keys:        []string{"r"},
					Description: "Set metrics grid rows",
					Handler:     (*Run).handleConfigMetricsRows,
				},
				{
					Keys:        []string{"C"},
					Description: "Set system grid columns (Shift+c)",
					Handler:     (*Run).handleConfigSystemCols,
				},
				{
					Keys:        []string{"R"},
					Description: "Set system grid rows (Shift+r)",
					Handler:     (*Run).handleConfigSystemRows,
				},
			},
		},

		// Documentation-only bindings (handled by subcomponents, not via Run.keyMap).
		{
			Name: "Run Overview Navigation (when sidebar open)",
			Bindings: []KeyBinding[Run]{
				{
					Keys:        []string{"up", "down"},
					Description: "Navigate items in section",
				},
				{
					Keys:        []string{"tab", "shift+tab"},
					Description: "Switch between sections",
				},
				{
					Keys:        []string{"left", "right"},
					Description: "Navigate pages in section",
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
					Keys:        []string{"enter"},
					Description: "View selected run (when not filtering/configuring)",
				},
			},
		},
		{
			Name: "Panels",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"["},
					Description: "Toggle runs sidebar",
					Handler:     (*Workspace).handleToggleRunsSidebar,
				},
				{
					Keys:        []string{"]"},
					Description: "Toggle run overview sidebar",
					Handler:     (*Workspace).handleToggleOverviewSidebar,
				},
			},
		},
		{
			Name: "Navigation",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"N", "pgup"},
					Description: "Previous chart page",
					Handler:     (*Workspace).handlePrevPage,
				},
				{
					Keys:        []string{"n", "pgdown"},
					Description: "Next chart page",
					Handler:     (*Workspace).handleNextPage,
				},
			},
		},
		{
			Name: "Charts",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"/"},
					Description: "Filter metrics by pattern",
					Handler:     (*Workspace).handleEnterMetricsFilter,
				},
				{
					Keys:        []string{"ctrl+l"},
					Description: "Clear active filter",
					Handler:     (*Workspace).handleClearMetricsFilter,
				},
			},
		},
		{
			Name: "Configuration",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"c"},
					Description: "Set metrics grid columns",
					Handler:     (*Workspace).handleConfigMetricsCols,
				},
				{
					Keys:        []string{"r"},
					Description: "Set metrics grid rows",
					Handler:     (*Workspace).handleConfigMetricsRows,
				},
			},
		},
		{
			Name: "Sidebars (when open)",
			Bindings: []KeyBinding[Workspace]{
				{
					Keys:        []string{"tab", "shift+tab"},
					Description: "Cycle focus between runs and overview sections",
					Handler:     (*Workspace).handleSidebarTabNav,
				},
				{
					Keys:        []string{"up", "down"},
					Description: "Navigate focused sidebar list",
					Handler:     (*Workspace).handleRunsVerticalNav,
				},
				{
					Keys:        []string{"left", "right"},
					Description: "Navigate pages in focused sidebar list",
					Handler:     (*Workspace).handleRunsPageNav,
				},
				{
					Keys:        []string{"home"},
					Description: "Jump to first run",
					Handler:     (*Workspace).handleRunsHome,
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

// buildKeyMap builds a fast lookup map from key string to handler.
func buildKeyMap[T any](categories []BindingCategory[T]) map[string]func(*T, tea.KeyMsg) tea.Cmd {
	keyMap := make(map[string]func(*T, tea.KeyMsg) tea.Cmd)
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

// normalizeKey normalizes Bubble Tea's KeyMsg.String() into a stable key used by our maps.
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

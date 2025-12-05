package leet

import (
	tea "github.com/charmbracelet/bubbletea"
)

// KeyBinding represents a key binding with its handler and metadata.
type KeyBinding struct {
	Keys        []string
	Description string
	Handler     func(*Model, tea.KeyMsg) (*Model, tea.Cmd)
}

// BindingCategory groups related key bindings.
type BindingCategory struct {
	Name     string
	Bindings []KeyBinding
}

// KeyBindings returns all model-level key bindings organized by category.
// These are handled by the Model and dispatched via the keyMap.
func KeyBindings() []BindingCategory {
	return []BindingCategory{
		{
			Name: "General",
			Bindings: []KeyBinding{
				{
					Keys:        []string{"h", "?"},
					Description: "Toggle this help screen",
					Handler:     (*Model).handleToggleHelp,
				},
				{
					Keys:        []string{"q", "ctrl+c"},
					Description: "Quit",
					Handler:     (*Model).handleQuit,
				},
				{
					Keys:        []string{"alt+r"},
					Description: "Reload run data",
					Handler:     (*Model).handleRestart,
				},
			},
		},
		{
			Name: "Panels",
			Bindings: []KeyBinding{
				{
					Keys:        []string{"["},
					Description: "Toggle left sidebar with run overview",
					Handler:     (*Model).handleToggleLeftSidebar,
				},
				{
					Keys:        []string{"]"},
					Description: "Toggle right sidebar with system metrics",
					Handler:     (*Model).handleToggleRightSidebar,
				},
			},
		},
		{
			Name: "Navigation",
			Bindings: []KeyBinding{
				{
					Keys:        []string{"N", "pgup"},
					Description: "Navigate between chart pages",
					Handler:     (*Model).handlePrevPage,
				},
				{
					Keys:        []string{"n", "pgdown"},
					Description: "Navigate between chart pages",
					Handler:     (*Model).handleNextPage,
				},
				{
					Keys:        []string{"alt+N", "alt+pgup"},
					Description: "Navigate between system metrics pages",
					Handler:     (*Model).handlePrevSystemPage,
				},
				{
					Keys:        []string{"alt+n", "alt+pgdown"},
					Description: "Navigate between system metrics pages",
					Handler:     (*Model).handleNextSystemPage,
				},
			},
		},
		{
			Name: "Charts",
			Bindings: []KeyBinding{
				{
					Keys:        []string{"/"},
					Description: "Filter metrics by pattern",
					Handler:     (*Model).handleEnterMetricsFilter,
				},
				{
					Keys:        []string{"ctrl+l"},
					Description: "Clear active filter",
					Handler:     (*Model).handleClearMetricsFilter,
				},
			},
		},
		{
			Name: "Run Overview",
			Bindings: []KeyBinding{
				{
					Keys:        []string{"o"},
					Description: "Filter overview items",
					Handler:     (*Model).handleEnterOverviewFilter,
				},
				{
					Keys:        []string{"ctrl+k"},
					Description: "Clear overview filter",
					Handler:     (*Model).handleClearOverviewFilter,
				},
			},
		},
		{
			Name: "Configuration",
			Bindings: []KeyBinding{
				{
					Keys:        []string{"c"},
					Description: "Set metrics grid columns",
					Handler:     (*Model).handleConfigMetricsCols,
				},
				{
					Keys:        []string{"r"},
					Description: "Set metrics grid rows",
					Handler:     (*Model).handleConfigMetricsRows,
				},
				{
					Keys:        []string{"C"},
					Description: "Set system grid columns (Shift+c)",
					Handler:     (*Model).handleConfigSystemCols,
				},
				{
					Keys:        []string{"R"},
					Description: "Set system grid rows (Shift+r)",
					Handler:     (*Model).handleConfigSystemRows,
				},
			},
		},
		// Key bindings below are handled by a component, not the Model.
		// These are for documentation only and don't have handlers.
		{
			Name: "Run Overview Navigation (when sidebar open)",
			Bindings: []KeyBinding{
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
		{
			Name: "Mouse",
			Bindings: []KeyBinding{
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
		},
	}
}

// buildKeyMap builds a lookup map from key string to handler.
func buildKeyMap() map[string]func(*Model, tea.KeyMsg) (*Model, tea.Cmd) {
	keyMap := make(map[string]func(*Model, tea.KeyMsg) (*Model, tea.Cmd))
	for _, category := range KeyBindings() {
		for _, binding := range category.Bindings {
			for _, key := range binding.Keys {
				keyMap[key] = binding.Handler
			}
		}
	}
	return keyMap
}

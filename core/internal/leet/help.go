package leet

import (
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/wandb/wandb/core/internal/version"
)

// HelpEntry represents a single entry in the help screen.
type HelpEntry struct {
	Key         string
	Description string
}

var blankLine = HelpEntry{}

// HelpModel represents the help screen.
type HelpModel struct {
	viewport viewport.Model
	active   bool
	width    int
	height   int

	mode viewMode
}

func NewHelp() *HelpModel {
	vp := viewport.New(80, 20)
	return &HelpModel{
		viewport: vp,
		active:   false,
		mode:     viewModeWorkspace,
	}
}

func (h *HelpModel) SetMode(mode viewMode) {
	h.mode = mode
	if h.active {
		h.viewport.SetContent(h.generateHelpContent())
	}
}

// generateHelpContent generates the help screen content.
func (h *HelpModel) generateHelpContent() string {
	artStyle := lipgloss.NewStyle().
		Foreground(colorHeading).
		Bold(true)

	artSection := artStyle.Render(
		lipgloss.JoinHorizontal(lipgloss.Top, wandbArt, "    ", leetArt),
	) + "\n\n"

	entries := h.entriesForMode()

	helpSection := ""
	for _, entry := range entries {
		switch {
		case entry.Key == "":
			helpSection += "\n"
		case entry.Description == "":
			helpSection += helpSectionStyle.Render(entry.Key) + "\n"
		default:
			key := helpKeyStyle.Render(entry.Key)
			desc := helpDescStyle.Render(entry.Description)
			helpSection += lipgloss.JoinHorizontal(lipgloss.Top, key, desc) + "\n"
		}
	}

	return artSection + helpSection
}

func (h *HelpModel) entriesForMode() []HelpEntry {
	entries := []HelpEntry{
		{Key: "── W&B LEET: Lightweight Experiment Exploration Tool ──", Description: ""},
		{Key: "version", Description: version.Version},
		{Key: "view", Description: h.modeLabel()},
		blankLine,
	}

	entries = append(entries, helpEntriesFromCategories(RunKeyBindings())...)

	return entries
}

func (h *HelpModel) modeLabel() string {
	switch h.mode {
	case viewModeWorkspace:
		return "workspace"
	case viewModeRun:
		return "single run"
	default:
		return "unknown"
	}
}

func helpEntriesFromCategories[T any](categories []BindingCategory[T]) []HelpEntry {
	var entries []HelpEntry
	for _, category := range categories {
		entries = append(entries, HelpEntry{Key: category.Name, Description: ""})
		for _, binding := range category.Bindings {
			entries = append(entries, HelpEntry{
				Key:         strings.Join(binding.Keys, ", "),
				Description: binding.Description,
			})
		}
		entries = append(entries, blankLine)
	}
	return entries
}

// SetSize updates the size of the help screen.
func (h *HelpModel) SetSize(width, height int) {
	h.width = width
	h.height = height - StatusBarHeight
	h.viewport.Width = width
	h.viewport.Height = h.height

	if h.active {
		h.viewport.SetContent(h.generateHelpContent())
	}
}

// Toggle toggles the help screen visibility.
func (h *HelpModel) Toggle() {
	h.active = !h.active
	if h.active {
		h.viewport.GotoTop()
		h.viewport.SetContent(h.generateHelpContent())
	}
}

// IsActive returns whether the help screen is active.
func (h *HelpModel) IsActive() bool {
	return h.active
}

// Update handles messages for the help screen.
func (h *HelpModel) Update(msg tea.Msg) (*HelpModel, tea.Cmd) {
	if !h.active {
		return h, nil
	}

	var cmd tea.Cmd

	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "h", "?", "esc":
			h.Toggle()
			return h, nil
		case "q", "ctrl+c":
			// Allow quitting from help screen
			return h, tea.Quit
		default:
			// Let viewport handle other keys
			h.viewport, cmd = h.viewport.Update(msg)
		}
	case tea.MouseMsg:
		// Let viewport handle mouse events
		h.viewport, cmd = h.viewport.Update(msg)
	}

	return h, cmd
}

// View renders the help screen.
func (h *HelpModel) View() string {
	if !h.active {
		return ""
	}

	content := helpContentStyle.Render(h.viewport.View())

	return lipgloss.Place(
		h.width,
		h.height,
		lipgloss.Left,
		lipgloss.Top,
		content,
	)
}

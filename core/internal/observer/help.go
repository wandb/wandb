package observer

import (
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// HelpEntry represents a single entry in the help screen
type HelpEntry struct {
	Key         string
	Description string
}

// HelpModel represents the help screen
type HelpModel struct {
	viewport viewport.Model
	entries  []HelpEntry
	active   bool
	width    int
	height   int
}

// NewHelp creates a new help screen
func NewHelp() *HelpModel {
	entries := []HelpEntry{
		// General
		{Key: "h, ?", Description: "Toggle this help screen"},
		{Key: "q, ctrl+c", Description: "Quit"},
		{Key: "r", Description: "Reload run data"},
		{Key: "", Description: ""},

		// Panels
		{Key: "── Panels ──", Description: ""},
		{Key: "ctrl+b", Description: "Toggle run overview sidebar"},
		{Key: "ctrl+n", Description: "Toggle system metrics sidebar"},
		{Key: "", Description: ""},

		// Navigation
		{Key: "── Navigation ──", Description: ""},
		{Key: "pgup/pgdn", Description: "Navigate between chart pages"},
		{Key: "ctrl+pgup/pgdn", Description: "Navigate between system metrics pages"},
		{Key: "up/down", Description: "Scroll in run overview"},
		// TODO: make it work :)
		// {Key: "home/end", Description: "Jump to top/bottom of run overview"},
		{Key: "Mouse wheel", Description: "Zoom in/out on focused chart"},
	}

	vp := viewport.New(80, 20) // Initial size, will be updated

	h := &HelpModel{
		viewport: vp,
		entries:  entries,
		active:   false,
	}

	return h
}

// generateHelpContent generates the help screen content
func (h *HelpModel) generateHelpContent() string {
	artStyle := lipgloss.NewStyle().
		Foreground(wandbColor).
		Bold(true)

	// Build the ASCII art section separately
	artSection := artStyle.Render(wandbArt) + "\n" + artStyle.Render(observerArt) + "\n\n"

	// Build the help entries section
	helpSection := ""
	for _, entry := range h.entries {
		switch {
		case entry.Key == "":
			// Empty line for spacing
			helpSection += "\n"
		case entry.Description == "":
			// Section header
			helpSection += helpSectionStyle.Render(entry.Key) + "\n"
		default:
			// Regular entry
			key := helpKeyStyle.Render(entry.Key)
			desc := helpDescStyle.Render(entry.Description)
			helpSection += lipgloss.JoinHorizontal(lipgloss.Top, key, desc) + "\n"
		}
	}

	return artSection + helpSection
}

// SetSize updates the size of the help screen
func (h *HelpModel) SetSize(width, height int) {
	h.width = width
	h.height = height - StatusBarHeight // Account for status bar
	h.viewport.Width = width
	h.viewport.Height = h.height
	h.viewport.SetContent(h.generateHelpContent())
}

// Toggle toggles the help screen visibility
func (h *HelpModel) Toggle() {
	h.active = !h.active
	if h.active {
		h.viewport.GotoTop()
		h.viewport.SetContent(h.generateHelpContent())
	}
}

// IsActive returns whether the help screen is active
func (h *HelpModel) IsActive() bool {
	return h.active
}

// Update handles messages for the help screen
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

// View renders the help screen
func (h *HelpModel) View() string {
	if !h.active {
		return ""
	}

	// Apply margins to the content
	content := helpContentStyle.Render(h.viewport.View())

	// Place with top alignment to respect top margin
	return lipgloss.Place(
		h.width,
		h.height,
		lipgloss.Left,
		lipgloss.Top,
		content,
	)
}

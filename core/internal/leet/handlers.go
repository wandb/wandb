package leet

import tea "github.com/charmbracelet/bubbletea"

// handleKeyMsg processes keyboard events.
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	switch msg.String() {
	case "q", "ctrl+c":
		return m, tea.Quit
	}

	return m, nil
}

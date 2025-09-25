package leet

import tea "github.com/charmbracelet/bubbletea"

// handleKeyMsg processes keyboard events
//
//gocyclo:ignore
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	switch msg.String() {
	case "h", "?":
		m.help.Toggle()
		return m, nil

	case "q", "ctrl+c":
		return m, tea.Quit
	}

	return m, nil
}

package leet

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
)

// handleKeyMsg processes keyboard events.
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// If we're waiting for a config key, handle that next
	if m.waitingForConfigKey {
		return m.handleConfigNumberKey(msg)
	}

	switch msg.String() {
	case "q", "ctrl+c":
		return m, tea.Quit

	case "r":
		// Lowercase r for metrics rows
		m.waitingForConfigKey = true
		m.configKeyType = "r"
		return m, nil

	case "R":
		// Uppercase R - system grid rows
		m.waitingForConfigKey = true
		m.configKeyType = "R"
		return m, nil

	case "c":
		// Lowercase c - metrics grid columns
		m.waitingForConfigKey = true
		m.configKeyType = "c"
		return m, nil

	case "C":
		// Uppercase C - system grid columns
		m.waitingForConfigKey = true
		m.configKeyType = "C"
		return m, nil

	}

	return m, nil
}

// handleConfigNumberKey handles number input for configuration.
func (m *Model) handleConfigNumberKey(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Cancel on escape
	if msg.String() == "esc" {
		m.waitingForConfigKey = false
		m.configKeyType = ""
		return m, nil
	}

	// Check if it's a number 1-9
	var num int
	switch msg.String() {
	case "1":
		num = 1
	case "2":
		num = 2
	case "3":
		num = 3
	case "4":
		num = 4
	case "5":
		num = 5
	case "6":
		num = 6
	case "7":
		num = 7
	case "8":
		num = 8
	case "9":
		num = 9
	default:
		// Not a valid number, cancel
		m.waitingForConfigKey = false
		m.configKeyType = ""
		return m, nil
	}

	// Apply the configuration change
	var err error
	var statusMsg string

	switch m.configKeyType {
	case "c": // Metrics columns
		err = m.config.SetMetricsCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid columns set to %d", num)
		}
	case "r": // Metrics rows
		err = m.config.SetMetricsRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid rows set to %d", num)
		}
	case "C": // System columns
		err = m.config.SetSystemCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid columns set to %d", num)
		}
	case "R": // System rows
		err = m.config.SetSystemRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid rows set to %d", num)
		}
	}

	// Reset state
	m.waitingForConfigKey = false
	m.configKeyType = ""

	if err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to update config: %v", err))
		return m, nil
	}

	// TODO: show in status bar instead.
	m.logger.Info(statusMsg)

	return m, nil
}

package leet

import (
	"fmt"
	"strconv"

	tea "github.com/charmbracelet/bubbletea"
)

// handleKeyMsg processes keyboard events.
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// If we're waiting for a config key, handle that next
	if m.pendingGridConfig != gridConfigNone {
		return m.handleConfigNumberKey(msg)
	}

	switch msg.String() {
	case "q", "ctrl+c":
		return m, tea.Quit

	case "c":
		m.pendingGridConfig = gridConfigMetricsCols
		return m, nil

	case "r":
		m.pendingGridConfig = gridConfigMetricsRows
		return m, nil

	case "C":
		m.pendingGridConfig = gridConfigSystemCols
		return m, nil

	case "R":
		m.pendingGridConfig = gridConfigSystemRows
		return m, nil
	}

	return m, nil
}

// handleConfigNumberKey handles number input for configuration.
func (m *Model) handleConfigNumberKey(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// Cancel on escape.
	if msg.String() == "esc" {
		m.pendingGridConfig = gridConfigNone
		return m, nil
	}

	// Check if it's a number 1-9.
	num, err := strconv.Atoi(msg.String())
	if err != nil || num < 1 || num > 9 {
		// Invalid input, cancel.
		m.pendingGridConfig = gridConfigNone
		return m, nil
	}

	// Apply the configuration change.
	var statusMsg string
	switch m.pendingGridConfig {
	case gridConfigMetricsCols:
		err = m.config.SetMetricsCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid columns set to %d", num)
		}
	case gridConfigMetricsRows:
		err = m.config.SetMetricsRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid rows set to %d", num)
		}
	case gridConfigSystemCols:
		err = m.config.SetSystemCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid columns set to %d", num)
		}
	case gridConfigSystemRows:
		err = m.config.SetSystemRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid rows set to %d", num)
		}
	}

	// Reset state.
	m.pendingGridConfig = gridConfigNone

	if err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to update config: %v", err))
		return m, nil
	}

	// TODO: show in status bar.
	m.logger.Info(statusMsg)

	return m, nil
}

package leet

import (
	"fmt"
	"strconv"

	tea "github.com/charmbracelet/bubbletea"
)

// handleKeyMsg processes keyboard events using the centralized key bindings.
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.pendingGridConfig != gridConfigNone {
		return m.handleConfigNumberKey(msg)
	}

	if handler, ok := m.keyMap[msg.String()]; ok && handler != nil {
		return handler(m, msg)
	}

	return m, nil
}

func (m *Model) handleToggleHelp(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.help.Toggle()
	return m, nil
}

func (m *Model) handleQuit(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, tea.Quit
}

func (m *Model) handleRestart(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.shouldRestart = true
	m.logger.Debug("model: restart requested")
	return m, tea.Quit
}

func (m *Model) handleToggleLeftSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleToggleRightSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handlePrevPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleNextPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handlePrevSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleNextSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleEnterMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleClearMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleEnterOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleClearOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	return m, nil
}

func (m *Model) handleConfigMetricsCols(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigMetricsCols
	return m, nil
}

func (m *Model) handleConfigMetricsRows(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigMetricsRows
	return m, nil
}

func (m *Model) handleConfigSystemCols(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigSystemCols
	return m, nil
}

func (m *Model) handleConfigSystemRows(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.pendingGridConfig = gridConfigSystemRows
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

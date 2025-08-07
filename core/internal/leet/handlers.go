//go:build !wandb_core

package leet

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/runenvironment"
)

// processRecordMsg handles messages that carry data from the .wandb file.
func (m *Model) processRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	// Recover from any panics in message processing
	defer m.recoverPanic("processRecordMsg")

	switch msg := msg.(type) {
	case HistoryMsg:
		m.logger.Debug(fmt.Sprintf("model: processing HistoryMsg with step %d", msg.Step))
		return m.handleHistoryMsg(msg)

	case RunMsg:
		m.logger.Debug("model: processing RunMsg")
		m.runOverview.ID = msg.ID
		m.runOverview.DisplayName = msg.DisplayName
		m.runOverview.Project = msg.Project
		if msg.Config != nil {
			onError := func(err error) {
				m.logger.Error(fmt.Sprintf("model: error applying config record: %v", err))
			}
			m.runConfig.ApplyChangeRecord(msg.Config, onError)
			m.runOverview.Config = m.runConfig.CloneTree()
		}
		m.sidebar.SetRunOverview(m.runOverview)

	case StatsMsg:
		m.logger.Debug(fmt.Sprintf("model: processing StatsMsg with timestamp %d", msg.Timestamp))
		m.rightSidebar.ProcessStatsMsg(msg)

	case SystemInfoMsg:
		m.logger.Debug("model: processing SystemInfoMsg")
		if m.runEnvironment == nil {
			m.runEnvironment = runenvironment.New(msg.Record.GetWriterId())
		}
		m.runEnvironment.ProcessRecord(msg.Record)
		m.runOverview.Environment = m.runEnvironment.ToRunConfigData()
		m.sidebar.SetRunOverview(m.runOverview)

	case SummaryMsg:
		m.logger.Debug("model: processing SummaryMsg")
		for _, update := range msg.Summary.Update {
			err := m.runSummary.SetFromRecord(update)
			if err != nil {
				m.logger.Error(fmt.Sprintf("model: error processing summary: %v", err))
			}
		}
		for _, remove := range msg.Summary.Remove {
			m.runSummary.RemoveFromRecord(remove)
		}
		m.runOverview.Summary = m.runSummary.ToNestedMaps()
		m.sidebar.SetRunOverview(m.runOverview)

	case FileCompleteMsg:
		m.logger.Debug("model: processing FileCompleteMsg - file is complete!")
		if !m.fileComplete {
			m.fileComplete = true
			switch msg.ExitCode {
			case 0:
				m.runState = RunStateFinished
			default:
				m.runState = RunStateFailed
			}
			if m.watcherStarted {
				m.logger.Debug("model: finishing watcher")
				m.watcher.Finish()
				m.watcherStarted = false
			}
		}

	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.fileComplete = true
		m.runState = RunStateFailed
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher due to error")
			m.watcher.Finish()
			m.watcherStarted = false
		}
	}

	return m, nil
}

// handleHistoryMsg processes new history data
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	m.step = msg.Step

	// Track if we need to sort
	needsSort := false

	// Lock for write when modifying charts
	m.chartMu.Lock()
	defer m.chartMu.Unlock()

	// Add data points to existing charts or create new ones
	for metricName, value := range msg.Metrics {
		chart, exists := m.chartsByName[metricName]
		if !exists {
			availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width() - 4
			dims := CalculateChartDimensions(availableWidth, m.height-StatusBarHeight)
			// Create chart without color - it will be assigned during sort
			chart = NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, 0, metricName)

			m.allCharts = append(m.allCharts, chart)
			m.chartsByName[metricName] = chart
			needsSort = true

			// Log when we're creating many charts
			if len(m.allCharts)%1000 == 0 {
				m.logger.Info(fmt.Sprintf("model: created %d charts", len(m.allCharts)))
			}
		}
		chart.AddDataPoint(value)
	}

	// Sort if we added new charts (this will also assign/reassign colors)
	if needsSort {
		m.sortCharts()
		m.totalPages = (len(m.allCharts) + ChartsPerPage - 1) / ChartsPerPage
	}

	// Exit loading state only when we have actual charts with data
	if m.isLoading && len(m.allCharts) > 0 {
		m.isLoading = false
	}

	// Reload page and draw
	if len(msg.Metrics) > 0 {
		m.loadCurrentPageNoLock() // Use a version that doesn't acquire the lock
		m.drawVisibleCharts()
	}

	return m, nil
}

// drawVisibleCharts only draws charts that are currently visible
func (m *Model) drawVisibleCharts() {
	defer func() {
		if r := recover(); r != nil {
			m.logger.Error(fmt.Sprintf("panic in drawVisibleCharts: %v", r))
		}
	}()

	// Force redraw all visible charts
	for row := 0; row < GridRows; row++ {
		for col := 0; col < GridCols; col++ {
			if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
				chart := m.charts[row][col]
				// Always force a redraw when this is called
				chart.dirty = true
				chart.Draw()
				chart.dirty = false
			}
		}
	}
}

// handleMouseMsg processes mouse events
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
	if !tea.MouseEvent(msg).IsWheel() {
		return m, nil
	}

	// Check if mouse is in sidebars
	if msg.X < m.sidebar.Width() || msg.X >= m.width-m.rightSidebar.Width() {
		return m, nil
	}

	// Mouse is in the chart area - account for padding
	const gridPadding = 1
	adjustedX := msg.X - m.sidebar.Width() - gridPadding
	adjustedY := msg.Y - gridPadding - 1 // -1 for header

	availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width() - (gridPadding * 2)
	dims := CalculateChartDimensions(availableWidth, m.height)

	row := adjustedY / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	// Use RLock for reading charts
	m.chartMu.RLock()
	defer m.chartMu.RUnlock()

	if row >= 0 && row < GridRows && col >= 0 && col < GridCols &&
		row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
		chart := m.charts[row][col]

		chartStartX := col * dims.ChartWidthWithPadding
		graphStartX := chartStartX + 1
		if chart.YStep() > 0 {
			graphStartX += chart.Origin().X + 1
		}

		relativeMouseX := adjustedX - graphStartX

		if relativeMouseX >= 0 && relativeMouseX < chart.GraphWidth() {
			m.clearFocus()
			m.focusedRow = row
			m.focusedCol = col
			chart.SetFocused(true)

			switch msg.Button {
			case tea.MouseButtonWheelUp:
				chart.HandleZoom("in", relativeMouseX)
			case tea.MouseButtonWheelDown:
				chart.HandleZoom("out", relativeMouseX)
			}
			chart.DrawIfNeeded()
		}
	}

	return m, nil
}

// handleKeyMsg processes keyboard events
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	// If we're waiting for a config key, handle that first
	if m.waitingForConfigKey {
		return m.handleConfigNumberKey(msg)
	}

	switch msg.Type {
	case tea.KeyCtrlB:
		// Prevent concurrent animations
		m.animationMu.Lock()
		if m.animating {
			m.animationMu.Unlock()
			return m, nil
		}
		m.animating = true
		m.animationMu.Unlock()

		// Update dimensions BEFORE toggling
		m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(m.width, true) // Will be visible after toggle

		// Toggle the sidebar
		m.sidebar.Toggle()

		// Update chart sizes and force redraw
		m.updateChartSizes()

		return m, m.sidebar.animationCmd()

	case tea.KeyCtrlN:
		// Prevent concurrent animations
		m.animationMu.Lock()
		if m.animating {
			m.animationMu.Unlock()
			return m, nil
		}
		m.animating = true
		m.animationMu.Unlock()

		// Update dimensions BEFORE toggling
		m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())
		m.sidebar.UpdateDimensions(m.width, true) // Will be visible after toggle

		// Toggle the sidebar
		m.rightSidebar.Toggle()

		// Update chart sizes and force redraw
		m.updateChartSizes()

		return m, m.rightSidebar.animationCmd()

	case tea.KeyPgUp, tea.KeyShiftUp:
		m.navigatePage(-1)

	case tea.KeyPgDown, tea.KeyShiftDown:
		m.navigatePage(1)
	}

	switch msg.String() {
	case "h", "?":
		m.help.Toggle()
		return m, nil

	case "q", "ctrl+c":
		m.logger.Debug("model: quit requested")
		if m.reader != nil {
			m.reader.Close()
		}
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher on quit")
			m.watcher.Finish()
			m.watcherStarted = false
		}
		close(m.msgChan)
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

	case "alt+r":
		// Alt+r for reload
		return m, m.reloadCharts()

	}

	return m, nil
}

// handleConfigNumberKey handles number input for configuration
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
	cfg := GetConfig()
	var err error
	var statusMsg string

	switch m.configKeyType {
	case "c": // Metrics columns
		err = cfg.SetMetricsCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid columns set to %d", num)
		}
	case "r": // Metrics rows
		err = cfg.SetMetricsRows(num)
		if err == nil {
			statusMsg = fmt.Sprintf("Metrics grid rows set to %d", num)
		}
	case "C": // System columns
		err = cfg.SetSystemCols(num)
		if err == nil {
			statusMsg = fmt.Sprintf("System grid columns set to %d", num)
		}
	case "R": // System rows
		err = cfg.SetSystemRows(num)
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

	// Update grid dimensions and rebuild the UI
	UpdateGridDimensions()
	m.rebuildGrids()
	m.updateChartSizes()

	// Log the status message for now (could show in status bar later)
	m.logger.Info(statusMsg)

	return m, nil
}

// handleOther handles remaining message types
func (m *Model) handleOther(msg tea.Msg) (*Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.MouseMsg:
		return m.handleMouseMsg(msg)

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.help.SetSize(msg.Width, msg.Height)

		// Update sidebar dimensions based on new window size
		m.sidebar.UpdateDimensions(msg.Width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(msg.Width, m.sidebar.IsVisible())

		// Then update chart sizes
		m.updateChartSizes()

	case SidebarAnimationMsg:
		if m.sidebar.IsAnimating() {
			// Don't update chart sizes during every animation frame
			// Just continue the animation
			return m, m.sidebar.animationCmd()
		} else {
			// Animation complete - now update everything
			m.animationMu.Lock()
			m.animating = false
			m.animationMu.Unlock()

			// Final update after animation completes
			m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())
			m.updateChartSizes()

			// Force redraw all visible charts now that animation is complete
			m.drawVisibleCharts()
		}

	case RightSidebarAnimationMsg:
		if m.rightSidebar.IsAnimating() {
			// Don't update chart sizes during every animation frame
			// Just continue the animation
			return m, m.rightSidebar.animationCmd()
		} else {
			// Animation complete - now update everything
			m.animationMu.Lock()
			m.animating = false
			m.animationMu.Unlock()

			// Final update after animation completes
			m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
			m.updateChartSizes()

			// Force redraw all visible charts now that animation is complete
			m.drawVisibleCharts()
		}
		if m.rightSidebar.IsAnimating() {
			// During animation, update other sidebar's dimensions
			m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
			m.updateChartSizes()
			return m, m.rightSidebar.animationCmd()
		}
	}

	return m, nil
}

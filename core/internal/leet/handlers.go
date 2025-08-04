package leet

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/runenvironment"
)

// processRecordMsg handles messages that carry data from the .wandb file.
func (m *Model) processRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
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
		m.loadCurrentPage()
		m.drawVisibleCharts()
	}

	return m, nil
}

// drawVisibleCharts only draws charts that are currently visible
func (m *Model) drawVisibleCharts() {
	for row := 0; row < GridRows; row++ {
		for col := 0; col < GridCols; col++ {
			if row < len(m.charts) && col < len(m.charts[row]) && m.charts[row][col] != nil {
				m.charts[row][col].DrawIfNeeded()
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
	switch msg.Type {
	case tea.KeyCtrlB:
		// Recalculate width before toggling
		m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
		m.sidebar.Toggle()
		m.updateChartSizes()
		return m, m.sidebar.animationCmd()

	case tea.KeyCtrlN:
		// Recalculate width before toggling
		m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())
		m.rightSidebar.Toggle()
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
		return m, m.reloadCharts()
	}

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

		// Update dimensions before updating sizes
		m.sidebar.UpdateDimensions(msg.Width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(msg.Width, m.sidebar.IsVisible())
		m.updateChartSizes()

	case SidebarAnimationMsg:
		if m.sidebar.IsAnimating() {
			// During animation, update other sidebar's dimensions
			m.rightSidebar.UpdateDimensions(m.width, m.sidebar.IsVisible())
			m.updateChartSizes()
			return m, m.sidebar.animationCmd()
		}

	case RightSidebarAnimationMsg:
		if m.rightSidebar.IsAnimating() {
			// During animation, update other sidebar's dimensions
			m.sidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
			m.updateChartSizes()
			return m, m.rightSidebar.animationCmd()
		}
	}

	return m, nil
}

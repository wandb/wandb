package leet

import (
	"fmt"
	"sort"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/runenvironment"
)

// processRecordMsg handles messages that carry data from the .wandb file.
func (m *Model) processRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	switch msg := msg.(type) {
	case BulkDataMsg:
		return m.handleBulkData(msg.Data)

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
			}
		}

	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.fileComplete = true
		m.runState = RunStateFailed
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher due to error")
			m.watcher.Finish()
		}
	}

	return m, nil
}

// handleBulkData processes bulk loaded data efficiently
func (m *Model) handleBulkData(data *ProcessedData) (*Model, tea.Cmd) {
	startTime := time.Now()

	// Process run info
	if data.RunInfo != nil {
		m.runOverview.ID = data.RunInfo.ID
		m.runOverview.DisplayName = data.RunInfo.DisplayName
		m.runOverview.Project = data.RunInfo.Project
	}

	// Process config, summary, and environment
	if data.Config != nil {
		m.runConfig = data.Config
		m.runOverview.Config = m.runConfig.CloneTree()
	}
	if data.SummaryData != nil {
		m.runSummary = data.SummaryData
		m.runOverview.Summary = m.runSummary.ToNestedMaps()
	}
	if data.Environment != nil {
		m.runEnvironment = data.Environment
		m.runOverview.Environment = m.runEnvironment.ToRunConfigData()
	}

	// Update sidebar
	m.sidebar.SetRunOverview(m.runOverview)

	// Process system stats
	for _, stats := range data.Stats {
		m.rightSidebar.ProcessStatsMsg(stats)
	}

	// Process history data
	if len(data.HistoryByStep) > 0 {
		m.loadHistoryDataBulk(data.HistoryByStep)
	}

	// Update run state
	if data.FileComplete {
		m.fileComplete = true
		if data.ExitCode == 0 {
			m.runState = RunStateFinished
		} else {
			m.runState = RunStateFailed
		}
	}

	m.logger.Debug(fmt.Sprintf("Bulk data processed in %v", time.Since(startTime)))
	return m, nil
}

// loadHistoryDataBulk efficiently loads all history data at once
func (m *Model) loadHistoryDataBulk(historyData map[int]map[string]float64) {
	// Get all unique metric names
	metricNames := make(map[string]bool)
	maxStep := 0

	for step, metrics := range historyData {
		if step > maxStep {
			maxStep = step
		}
		for metricName := range metrics {
			metricNames[metricName] = true
		}
	}

	// Create charts for all metrics
	availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	for metricName := range metricNames {
		if _, exists := m.chartsByName[metricName]; !exists {
			colorIndex := len(m.allCharts)
			chart := NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, colorIndex, metricName)
			m.allCharts = append(m.allCharts, chart)
			m.chartsByName[metricName] = chart
		}
	}

	// Sort steps for consistent ordering
	steps := make([]int, 0, len(historyData))
	for step := range historyData {
		steps = append(steps, step)
	}
	sort.Ints(steps)

	// Prepare data for each metric
	metricData := make(map[string][]float64)
	for metricName := range metricNames {
		metricData[metricName] = make([]float64, 0, len(steps))
	}

	// Fill in values in order
	for _, step := range steps {
		metrics := historyData[step]
		for metricName := range metricNames {
			if value, exists := metrics[metricName]; exists {
				metricData[metricName] = append(metricData[metricName], value)
			}
		}
	}

	// Set bulk data for each chart
	for metricName, values := range metricData {
		if chart, exists := m.chartsByName[metricName]; exists {
			chart.SetDataBulk(values)
		}
	}

	// Update state
	m.step = maxStep
	m.isLoading = false
	m.totalPages = (len(m.allCharts) + ChartsPerPage - 1) / ChartsPerPage

	// Load current page and draw visible charts
	m.loadCurrentPage()
	m.drawVisibleCharts()
}

// handleHistoryMsg processes new history data for live updates
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	m.step = msg.Step

	// Exit loading state on first data
	if m.isLoading && len(msg.Metrics) > 0 {
		m.isLoading = false
	}

	// Add data points to existing charts or create new ones
	for metricName, value := range msg.Metrics {
		chart, exists := m.chartsByName[metricName]
		if !exists {
			availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width()
			dims := CalculateChartDimensions(availableWidth, m.height)
			colorIndex := len(m.allCharts)
			chart = NewEpochLineChart(dims.ChartWidth, dims.ChartHeight, colorIndex, metricName)

			m.allCharts = append(m.allCharts, chart)
			m.chartsByName[metricName] = chart
			m.totalPages = (len(m.allCharts) + ChartsPerPage - 1) / ChartsPerPage
		}
		chart.AddDataPoint(value)
	}

	// Only reload page if we created new charts
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

	// Mouse is in the chart area
	adjustedX := msg.X - m.sidebar.Width()
	availableWidth := m.width - m.sidebar.Width() - m.rightSidebar.Width()
	dims := CalculateChartDimensions(availableWidth, m.height)

	row := msg.Y / dims.ChartHeightWithPadding
	col := adjustedX / dims.ChartWidthWithPadding

	if row >= 0 && row < GridRows && col >= 0 && col < GridCols && m.charts[row][col] != nil {
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
		m.sidebar.UpdateExpandedWidth(m.width, m.rightSidebar.IsVisible())
		m.sidebar.Toggle()
		m.updateChartSizes()
		return m, m.sidebar.animationCmd()

	case tea.KeyCtrlN:
		m.rightSidebar.UpdateExpandedWidth(m.width, m.sidebar.IsVisible())
		m.rightSidebar.Toggle()
		m.updateChartSizes()
		return m, m.rightSidebar.animationCmd()
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
		}
		close(m.msgChan)
		return m, tea.Quit

	case "r":
		return m, m.reloadCharts()

	case "pgup":
		m.navigatePage(-1)

	case "pgdown":
		m.navigatePage(1)
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
		m.sidebar.UpdateDimensions(msg.Width, m.rightSidebar.IsVisible())
		m.rightSidebar.UpdateDimensions(msg.Width, m.sidebar.IsVisible())
		m.updateChartSizes()

	case SidebarAnimationMsg:
		if m.sidebar.IsAnimating() {
			m.updateChartSizes()
			return m, m.sidebar.animationCmd()
		}

	case RightSidebarAnimationMsg:
		if m.rightSidebar.IsAnimating() {
			m.updateChartSizes()
			return m, m.rightSidebar.animationCmd()
		}
	}

	return m, nil
}

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
				m.logger.Error(
					fmt.Sprintf("model: error processing summary: %v", err))
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

			// Stop the watcher
			if m.watcherStarted {
				m.logger.Debug("model: finishing watcher")
				m.watcher.Finish()
			}
		}
	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.fileComplete = true
		m.runState = RunStateFailed
		// Stop the watcher
		if m.watcherStarted {
			m.logger.Debug("model: finishing watcher due to error")
			m.watcher.Finish()
		}
	}
	return m, nil
}

// handleMouseMsg processes mouse events
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
	if !tea.MouseEvent(msg).IsWheel() {
		return m, nil
	}

	// Check if mouse is in left sidebar
	if msg.X < m.sidebar.Width() {
		return m, nil
	}

	// Check if mouse is in right sidebar
	if msg.X >= m.width-m.rightSidebar.Width() {
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
			chart.Draw()
		}
	}

	return m, nil
}

// handleKeyMsg processes keyboard events
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	switch msg.Type {
	case tea.KeyCtrlB:
		// Update the sidebar's expanded width before toggling
		m.sidebar.UpdateExpandedWidth(m.width, m.rightSidebar.IsVisible())
		m.sidebar.Toggle()
		m.updateChartSizes()
		return m, m.sidebar.animationCmd()
	case tea.KeyCtrlN:
		// Update the right sidebar's expanded width before toggling
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
		close(m.msgChan) // Clean up the channel
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

// handleOther handles remaining message types.
func (m *Model) handleOther(msg tea.Msg) (*Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.MouseMsg:
		newModel, cmd := m.handleMouseMsg(msg)
		if cmd != nil {
			return newModel, cmd
		}
		return m, nil
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.help.SetSize(msg.Width, msg.Height)
		// Update both sidebars with awareness of each other
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

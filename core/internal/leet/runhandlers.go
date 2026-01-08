package leet

import (
	"fmt"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// handleRecordMsg handles messages that carry data from the .wandb file.
func (m *Run) handleRecordMsg(msg tea.Msg) (*Run, tea.Cmd) {
	defer m.logPanic("processRecordMsg")

	start := time.Now()
	defer func() {
		m.logger.Debug(fmt.Sprintf("perf: processRecordMsg(%T) took %s", msg, time.Since(start)))
	}()

	switch msg := msg.(type) {
	case RunMsg:
		m.logger.Debug("model: processing RunMsg")
		m.leftSidebar.ProcessRunMsg(msg)
		m.runState = RunStateRunning
		m.isLoading = false
		return m, nil

	case HistoryMsg:
		m.logger.Debug("model: processing HistoryMsg")
		if m.runState == RunStateRunning {
			m.heartbeatMgr.Reset(m.isRunning)
		}
		return m.handleHistoryMsg(msg)

	case StatsMsg:
		m.logger.Debug(fmt.Sprintf("model: processing StatsMsg with timestamp %d", msg.Timestamp))
		if m.runState == RunStateRunning {
			m.heartbeatMgr.Reset(m.isRunning)
		}
		m.rightSidebar.ProcessStatsMsg(msg)
		return m, nil

	case SystemInfoMsg:
		m.logger.Debug("model: processing SystemInfoMsg")
		m.leftSidebar.ProcessSystemInfoMsg(msg.Record)
		return m, nil

	case SummaryMsg:
		m.logger.Debug("model: processing SummaryMsg")
		m.leftSidebar.ProcessSummaryMsg(msg.Summary)
		return m, nil

	case FileCompleteMsg:
		m.logger.Debug("model: processing FileCompleteMsg - file is complete!")
		switch msg.ExitCode {
		case 0:
			m.runState = RunStateFinished
		default:
			m.runState = RunStateFailed
		}
		m.leftSidebar.SetRunState(m.runState)

		m.logger.Debug("model: stopping heartbeats and finishing watcher")
		m.heartbeatMgr.Stop()
		m.watcherMgr.Finish()

		return m, nil

	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.runState = RunStateFailed
		m.leftSidebar.SetRunState(m.runState)
		m.logger.Debug("model: stopping heartbeats and finishing watcher due to error")
		m.heartbeatMgr.Stop()
		m.watcherMgr.Finish()
		return m, nil
	}

	return m, nil
}

// handleHistoryMsg processes new history data.
func (m *Run) handleHistoryMsg(msg HistoryMsg) (*Run, tea.Cmd) {
	defer timeit(m.logger, "Model.handleHistoryMsg")()
	// Route to the grid; it handles sorting/filtering/pagination/focus itself.
	shouldDraw := m.metricsGrid.ProcessHistory(msg)
	if shouldDraw && !m.suppressDraw {
		m.metricsGrid.drawVisible()
	}
	return m, nil
}

// handleMouseMsg processes mouse events, routing by region.
func (m *Run) handleMouseMsg(msg tea.MouseMsg) (*Run, tea.Cmd) {
	defer timeit(m.logger, "Model.handleMouseMsg")()

	layout := m.computeViewports()

	if m.isInLeftSidebar(msg, layout) {
		return m.handleLeftSidebarMouse()
	}

	if m.isInRightSidebar(msg, layout) {
		return m.handleRightSidebarMouse(msg, layout)
	}

	return m.handleMainContentMouse(msg, layout)
}

// isInLeftSidebar checks if mouse position is in the left sidebar region.
func (m *Run) isInLeftSidebar(msg tea.MouseMsg, layout Layout) bool {
	return msg.X < layout.leftSidebarWidth
}

// isInRightSidebar checks if mouse position is in the right sidebar region.
func (m *Run) isInRightSidebar(msg tea.MouseMsg, layout Layout) bool {
	rightStart := m.width - layout.rightSidebarWidth
	return msg.X >= rightStart && layout.rightSidebarWidth > 0
}

// handleLeftSidebarMouse handles mouse events in the left sidebar.
func (m *Run) handleLeftSidebarMouse() (*Run, tea.Cmd) {
	m.metricsGrid.clearFocus()
	m.rightSidebar.ClearFocus()
	return m, nil
}

// handleRightSidebarMouse handles mouse events in the right sidebar.
func (m *Run) handleRightSidebarMouse(msg tea.MouseMsg, layout Layout) (*Run, tea.Cmd) {
	rightStart := m.width - layout.rightSidebarWidth
	adjustedX := msg.X - rightStart

	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {

		focusSet := m.rightSidebar.HandleMouseClick(adjustedX, msg.Y)

		if focusSet {
			m.metricsGrid.clearFocus()
		}
	}
	return m, nil
}

// handleMainContentMouse handles mouse events in the main content area.
func (m *Run) handleMainContentMouse(msg tea.MouseMsg, layout Layout) (*Run, tea.Cmd) {
	const gridPaddingX = 1
	const gridPaddingY = 1
	const headerOffset = 1

	adjustedX := msg.X - layout.leftSidebarWidth - gridPaddingX
	adjustedY := msg.Y - gridPaddingY - headerOffset

	dims := m.metricsGrid.CalculateChartDimensions(
		layout.mainContentAreaWidth,
		layout.height,
	)

	// Chart 2D indices on the grid.
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	// Handle left click for chart focus.
	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {
		m.rightSidebar.ClearFocus()
		m.metricsGrid.HandleClick(row, col)
		return m, nil
	}

	// Handle right click/hold+move/release for chart data inspection.
	if tea.MouseEvent(msg).Button == tea.MouseButtonRight {
		// Holding Alt activates synchronised inspection across all charts
		// visible on the current page.
		alt := tea.MouseEvent(msg).Alt

		switch tea.MouseEvent(msg).Action {
		case tea.MouseActionPress:
			m.metricsGrid.StartInspection(adjustedX, row, col, dims, alt)
		case tea.MouseActionMotion:
			m.metricsGrid.UpdateInspection(adjustedX, row, col, dims)
		case tea.MouseActionRelease:
			m.metricsGrid.EndInspection()
		}
	}

	// Handle wheel events for zoom.
	if tea.MouseEvent(msg).IsWheel() {
		m.metricsGrid.HandleWheel(
			adjustedX,
			row,
			col,
			dims,
			msg.Button == tea.MouseButtonWheelUp,
		)
	}

	return m, nil
}

// handleKeyMsg processes keyboard events using the centralized key bindings.
func (m *Run) handleKeyMsg(msg tea.KeyMsg) (*Run, tea.Cmd) {
	if m.leftSidebar.IsFilterMode() {
		return m.handleOverviewFilter(msg)
	}

	if m.metricsGrid.IsFilterMode() {
		return m.handleMetricsFilter(msg)
	}

	if m.config.IsAwaitingGridConfig() {
		return m.handleConfigNumberKey(msg)
	}

	if handler, ok := m.keyMap[msg.String()]; ok && handler != nil {
		return handler(m, msg)
	}

	return m, nil
}

// TODO: move to top model once its keybindings are wired.
// func (m *RunModel) handleToggleHelp(msg tea.KeyMsg) (*RunModel, tea.Cmd) {
// 	m.help.Toggle()
// 	return m, nil
// }

func (m *Run) handleQuit(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.logger.Debug("model: quit requested")
	if m.reader != nil {
		m.reader.Close()
	}
	m.heartbeatMgr.Stop()
	if m.watcherMgr.IsStarted() {
		m.logger.Debug("model: finishing watcher on quit")
		m.watcherMgr.Finish()
	}
	return m, tea.Quit
}

func (m *Run) handleRestart(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.shouldRestart = true
	m.logger.Debug("model: restart requested")
	if m.reader != nil {
		m.reader.Close()
	}
	m.heartbeatMgr.Stop()
	if m.watcherMgr.IsStarted() {
		m.logger.Debug("model: finishing watcher on restart")
		m.watcherMgr.Finish()
	}
	return m, tea.Quit
}

// beginAnimating tries to acquire the one-shot animation token.
//
// Returns true if the caller owns the token and may initiate an animation.
func (m *Run) beginAnimating() bool {
	m.animationMu.Lock()
	if m.animating {
		m.animationMu.Unlock()
		return false
	}
	m.animating = true
	m.animationMu.Unlock()
	return true
}

// endAnimating releases the animation token after an animation completes.
func (m *Run) endAnimating() {
	m.animationMu.Lock()
	m.animating = false
	m.animationMu.Unlock()
}

func (m *Run) handleToggleLeftSidebar(msg tea.KeyMsg) (*Run, tea.Cmd) {
	if !m.beginAnimating() {
		return m, nil
	}

	leftWillBeVisible := !m.leftSidebar.IsVisible()

	if err := m.config.SetLeftSidebarVisible(leftWillBeVisible); err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to save left sidebar state: %v", err))
	}

	m.leftSidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
	m.rightSidebar.UpdateDimensions(m.width, leftWillBeVisible)
	m.leftSidebar.Toggle()

	layout := m.computeViewports()
	m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return m, m.leftSidebar.animationCmd()
}

func (m *Run) handleToggleRightSidebar(msg tea.KeyMsg) (*Run, tea.Cmd) {
	if !m.beginAnimating() {
		return m, nil
	}

	rightWillBeVisible := !m.rightSidebar.IsVisible()

	if err := m.config.SetRightSidebarVisible(rightWillBeVisible); err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to save right sidebar state: %v", err))
	}

	m.rightSidebar.UpdateDimensions(m.width, m.leftSidebar.IsVisible())
	m.leftSidebar.UpdateDimensions(m.width, rightWillBeVisible)
	m.rightSidebar.Toggle()

	layout := m.computeViewports()
	m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return m, m.rightSidebar.animationCmd()
}

func (m *Run) handlePrevPage(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.metricsGrid.Navigate(-1)
	return m, nil
}

func (m *Run) handleNextPage(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.metricsGrid.Navigate(1)
	return m, nil
}

func (m *Run) handlePrevSystemPage(msg tea.KeyMsg) (*Run, tea.Cmd) {
	if m.rightSidebar.IsVisible() && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.Navigate(-1)
	}
	return m, nil
}

func (m *Run) handleNextSystemPage(msg tea.KeyMsg) (*Run, tea.Cmd) {
	if m.rightSidebar.IsVisible() && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.Navigate(1)
	}
	return m, nil
}

func (m *Run) handleEnterMetricsFilter(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.metricsGrid.EnterFilterMode()
	return m, nil
}

func (m *Run) handleClearMetricsFilter(msg tea.KeyMsg) (*Run, tea.Cmd) {
	if m.metricsGrid.FilterQuery() != "" {
		m.metricsGrid.ClearFilter()
	}
	m.focus.Reset()
	return m, nil
}

func (m *Run) handleEnterOverviewFilter(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.leftSidebar.EnterFilterMode()
	return m, nil
}

func (m *Run) handleClearOverviewFilter(msg tea.KeyMsg) (*Run, tea.Cmd) {
	if m.leftSidebar.IsFiltering() {
		m.leftSidebar.ClearFilter()
	}
	return m, nil
}

func (m *Run) handleConfigMetricsCols(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.config.SetPendingGridConfig(gridConfigMetricsCols)
	return m, nil
}

func (m *Run) handleConfigMetricsRows(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.config.SetPendingGridConfig(gridConfigMetricsRows)
	return m, nil
}

func (m *Run) handleConfigSystemCols(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.config.SetPendingGridConfig(gridConfigSystemCols)
	return m, nil
}

func (m *Run) handleConfigSystemRows(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.config.SetPendingGridConfig(gridConfigSystemRows)
	return m, nil
}

// handleMetricsFilter handles filter mode input for metrics
func (m *Run) handleMetricsFilter(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.metricsGrid.handleMetricsFilterKey(msg)
	return m, nil
}

// handleOverviewFilter handles overview filter keyboard input.
func (m *Run) handleOverviewFilter(msg tea.KeyMsg) (*Run, tea.Cmd) {
	switch msg.Type {
	case tea.KeyEsc:
		m.leftSidebar.ExitFilterMode(false)
	case tea.KeyEnter:
		m.leftSidebar.ExitFilterMode(true)
	case tea.KeyTab:
		m.leftSidebar.ToggleFilterMatchMode()
	case tea.KeyBackspace, tea.KeySpace, tea.KeyRunes:
		m.leftSidebar.UpdateFilterDraft(msg)
		m.leftSidebar.ApplyFilter()
		m.leftSidebar.updateSectionHeights()
	}
	return m, nil
}

// handleConfigNumberKey handles number input for configuration.
func (m *Run) handleConfigNumberKey(msg tea.KeyMsg) (*Run, tea.Cmd) {
	m.metricsGrid.handleGridConfigNumberKey(msg, m.computeViewports())

	return m, nil
}

// handleSidebarAnimation handles sidebar animation.
func (m *Run) handleSidebarAnimation(msg tea.Msg) []tea.Cmd {
	switch msg.(type) {
	case LeftSidebarAnimationMsg:
		layout := m.computeViewports()
		m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

		if m.leftSidebar.IsAnimating() {
			return []tea.Cmd{m.leftSidebar.animationCmd()}
		}

		m.endAnimating()
		m.rightSidebar.UpdateDimensions(m.width, m.leftSidebar.IsVisible())

	case RightSidebarAnimationMsg:
		layout := m.computeViewports()
		m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

		if m.rightSidebar.IsAnimating() {
			return []tea.Cmd{m.rightSidebar.animationCmd()}
		}

		m.endAnimating()
		m.leftSidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
	}

	return nil
}

// handleRecordsBatch processes a batch of sub-messages and manages redraw + loading flags.
func (m *Run) handleRecordsBatch(subMsgs []tea.Msg, suppressRedraw bool) []tea.Cmd {
	defer timeit(m.logger, "Model.handleRecordsBatch")()

	var cmds []tea.Cmd

	prev := m.suppressDraw
	m.suppressDraw = suppressRedraw
	for _, subMsg := range subMsgs {
		var cmd tea.Cmd
		m, cmd = m.handleRecordMsg(subMsg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	m.suppressDraw = prev
	if !m.suppressDraw {
		m.metricsGrid.drawVisible()
	}

	return cmds
}

// handleInit handles InitMsg (reader ready).
func (m *Run) handleInit(msg InitMsg) []tea.Cmd {
	m.logger.Debug("model: InitMsg received, reader initialized")
	m.reader = msg.Reader
	m.loadStartTime = time.Now()

	return []tea.Cmd{ReadAllRecordsChunked(m.reader)}
}

// handleChunkedBatch handles boot-load chunked batches.
func (m *Run) handleChunkedBatch(msg ChunkedBatchMsg) []tea.Cmd {
	defer timeit(m.logger, "Model.onChunkedBatch")()

	m.logger.Debug(
		fmt.Sprintf("model: ChunkedBatchMsg received with %d messages, hasMore=%v",
			len(msg.Msgs), msg.HasMore))

	m.recordsLoaded += msg.Progress

	cmds := m.handleRecordsBatch(msg.Msgs, false)

	if msg.HasMore {
		cmds = append(cmds, ReadAllRecordsChunked(m.reader))
		return cmds
	}

	// Boot load complete -> begin live mode once.
	if m.runState == RunStateRunning && !m.watcherMgr.IsStarted() {
		if err := m.watcherMgr.Start(m.runPath); err != nil {
			m.logger.CaptureError(fmt.Errorf("model: error starting watcher: %v", err))
		} else {
			m.logger.Info("model: watcher started successfully")
			m.heartbeatMgr.Start(m.isRunning)
		}
	}
	return cmds
}

// handleBatched handles live drain batches.
func (m *Run) handleBatched(msg BatchedRecordsMsg) []tea.Cmd {
	m.logger.Debug(fmt.Sprintf("model: BatchedRecordsMsg received with %d messages", len(msg.Msgs)))
	cmds := m.handleRecordsBatch(msg.Msgs, true)
	cmds = append(cmds, ReadAvailableRecords(m.reader))
	return cmds
}

// handleHeartbeat triggers a live read and re-arms the heartbeat.
func (m *Run) handleHeartbeat() []tea.Cmd {
	m.logger.Debug("model: processing HeartbeatMsg")
	m.heartbeatMgr.Reset(m.isRunning)
	return []tea.Cmd{
		ReadAvailableRecords(m.reader),
		m.watcherMgr.WaitForMsg,
	}
}

// handleFileChange coalesces change notifications into a read.
func (m *Run) handleFileChange() []tea.Cmd {
	m.heartbeatMgr.Reset(m.isRunning)
	return []tea.Cmd{
		ReadAvailableRecords(m.reader),
		m.watcherMgr.WaitForMsg,
	}
}

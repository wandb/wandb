package leet

import (
	"fmt"
	"strconv"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// processRecordMsg handles messages that carry data from the .wandb file.
func (m *Model) processRecordMsg(msg tea.Msg) (*Model, tea.Cmd) {
	defer m.logPanic("processRecordMsg")

	start := time.Now()
	defer func() {
		m.logger.Debug(fmt.Sprintf("perf: processRecordMsg(%T) took %s", msg, time.Since(start)))
	}()

	switch msg := msg.(type) {
	case HistoryMsg:
		m.logger.Debug("model: processing HistoryMsg")
		if m.runState == RunStateRunning && !m.fileComplete {
			m.heartbeatMgr.Reset(m.isRunning)
		}
		return m.handleHistoryMsg(msg)

	case RunMsg:
		m.logger.Debug("model: processing RunMsg")
		m.leftSidebar.ProcessRunMsg(msg)
		m.runState = RunStateRunning
		return m, nil

	case StatsMsg:
		m.logger.Debug(fmt.Sprintf("model: processing StatsMsg with timestamp %d", msg.Timestamp))
		if m.runState == RunStateRunning && !m.fileComplete {
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
		if !m.fileComplete {
			m.fileComplete = true
			switch msg.ExitCode {
			case 0:
				m.runState = RunStateFinished
			default:
				m.runState = RunStateFailed
			}
			m.leftSidebar.SetRunState(m.runState)
			m.heartbeatMgr.Stop()
			if m.watcherMgr.IsStarted() {
				m.logger.Debug("model: finishing watcher")
				m.watcherMgr.Finish()
			}
		}
		return m, nil

	case ErrorMsg:
		m.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		m.fileComplete = true
		m.runState = RunStateFailed
		m.leftSidebar.SetRunState(m.runState)
		m.heartbeatMgr.Stop()
		if m.watcherMgr.IsStarted() {
			m.logger.Debug("model: finishing watcher due to error")
			m.watcherMgr.Finish()
		}
		return m, nil
	}

	return m, nil
}

// handleHistoryMsg processes new history data.
func (m *Model) handleHistoryMsg(msg HistoryMsg) (*Model, tea.Cmd) {
	defer timeit(m.logger, "Model.handleHistoryMsg")()
	// Route to the grid; it handles sorting/filtering/pagination/focus itself.
	shouldDraw := m.metricsGrid.ProcessHistory(msg.Metrics)
	if m.isLoading && m.metricsGrid.ChartCount() > 0 {
		m.isLoading = false
	}
	if shouldDraw && !m.suppressDraw {
		m.metricsGrid.drawVisible()
	}
	return m, nil
}

// handleMouseMsg processes mouse events, routing by region.
func (m *Model) handleMouseMsg(msg tea.MouseMsg) (*Model, tea.Cmd) {
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
func (m *Model) isInLeftSidebar(msg tea.MouseMsg, layout Layout) bool {
	return msg.X < layout.leftSidebarWidth
}

// isInRightSidebar checks if mouse position is in the right sidebar region.
func (m *Model) isInRightSidebar(msg tea.MouseMsg, layout Layout) bool {
	rightStart := m.width - layout.rightSidebarWidth
	return msg.X >= rightStart && layout.rightSidebarWidth > 0
}

// handleLeftSidebarMouse handles mouse events in the left sidebar.
func (m *Model) handleLeftSidebarMouse() (*Model, tea.Cmd) {
	m.metricsGrid.clearFocus()
	m.rightSidebar.ClearFocus()
	return m, nil
}

// handleRightSidebarMouse handles mouse events in the right sidebar.
func (m *Model) handleRightSidebarMouse(msg tea.MouseMsg, layout Layout) (*Model, tea.Cmd) {
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
func (m *Model) handleMainContentMouse(msg tea.MouseMsg, layout Layout) (*Model, tea.Cmd) {
	const gridPaddingX = 1
	const gridPaddingY = 1
	const headerOffset = 1

	adjustedX := msg.X - layout.leftSidebarWidth - gridPaddingX
	adjustedY := msg.Y - gridPaddingY - headerOffset

	dims := m.metricsGrid.CalculateChartDimensions(
		layout.mainContentAreaWidth,
		layout.height,
	)

	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	// Handle left click for focus
	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {
		m.rightSidebar.ClearFocus()
		m.metricsGrid.HandleClick(row, col)
		return m, nil
	}

	// Handle wheel events for zoom
	if !tea.MouseEvent(msg).IsWheel() {
		return m, nil
	}

	m.metricsGrid.HandleWheel(
		adjustedX,
		row,
		col,
		dims,
		msg.Button == tea.MouseButtonWheelUp,
	)

	return m, nil
}

// handleKeyMsg processes keyboard events using the centralized key bindings.
func (m *Model) handleKeyMsg(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.leftSidebar.IsFilterMode() {
		return m.handleOverviewFilter(msg)
	}

	if m.metricsGrid.filter.inputActive {
		return m.handleMetricsFilter(msg)
	}

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

func (m *Model) handleRestart(msg tea.KeyMsg) (*Model, tea.Cmd) {
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
func (m *Model) beginAnimating() bool {
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
func (m *Model) endAnimating() {
	m.animationMu.Lock()
	m.animating = false
	m.animationMu.Unlock()
}

func (m *Model) handleToggleLeftSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
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

func (m *Model) handleToggleRightSidebar(msg tea.KeyMsg) (*Model, tea.Cmd) {
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

func (m *Model) handlePrevPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.metricsGrid.Navigate(-1)
	return m, nil
}

func (m *Model) handleNextPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.metricsGrid.Navigate(1)
	return m, nil
}

func (m *Model) handlePrevSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.rightSidebar.IsVisible() && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.Navigate(-1)
	}
	return m, nil
}

func (m *Model) handleNextSystemPage(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.rightSidebar.IsVisible() && m.rightSidebar.metricsGrid != nil {
		m.rightSidebar.metricsGrid.Navigate(1)
	}
	return m, nil
}

func (m *Model) handleEnterMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.metricsGrid.EnterFilterMode()
	return m, nil
}

func (m *Model) handleClearMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.metricsGrid.filter.applied != "" {
		m.metricsGrid.ClearFilter()
	}
	// TODO: unset focus?
	return m, nil
}

func (m *Model) handleEnterOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	m.leftSidebar.StartFilter()
	return m, nil
}

func (m *Model) handleClearOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if m.leftSidebar.IsFiltering() {
		m.leftSidebar.clearFilter()
	}
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

// handleMetricsFilter handles filter mode input for metrics
func (m *Model) handleMetricsFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	switch msg.Type {
	case tea.KeyEsc:
		m.metricsGrid.ExitFilterMode(false)
		return m, nil
	case tea.KeyEnter:
		m.metricsGrid.ExitFilterMode(true)
		return m, nil
	case tea.KeyBackspace:
		if len(m.metricsGrid.filter.draft) > 0 {
			m.metricsGrid.filter.draft = m.metricsGrid.filter.draft[:len(m.metricsGrid.filter.draft)-1]
			m.metricsGrid.ApplyFilter(m.metricsGrid.filter.draft)
			m.metricsGrid.drawVisible()
		}
		return m, nil
	case tea.KeyRunes:
		m.metricsGrid.filter.draft += string(msg.Runes)
		m.metricsGrid.ApplyFilter(m.metricsGrid.filter.draft)
		m.metricsGrid.drawVisible()
		return m, nil
	case tea.KeySpace:
		m.metricsGrid.filter.draft += " "
		m.metricsGrid.ApplyFilter(m.metricsGrid.filter.draft)
		m.metricsGrid.drawVisible()
		return m, nil
	default:
		return m, nil
	}
}

// handleOverviewFilter handles overview filter keyboard input.
func (m *Model) handleOverviewFilter(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if !m.leftSidebar.IsFilterMode() {
		return m, nil
	}

	switch msg.Type {
	case tea.KeyEsc:
		m.leftSidebar.CancelFilter()
		return m, nil

	case tea.KeyEnter:
		m.leftSidebar.ConfirmFilter()
		return m, nil

	case tea.KeyBackspace:
		input := m.leftSidebar.FilterDraft()
		if len(input) > 0 {
			m.leftSidebar.UpdateFilter(input[:len(input)-1])
		}
		return m, nil

	case tea.KeyRunes:
		input := m.leftSidebar.FilterDraft()
		m.leftSidebar.UpdateFilter(input + string(msg.Runes))
		return m, nil

	case tea.KeySpace:
		input := m.leftSidebar.FilterDraft()
		m.leftSidebar.UpdateFilter(input + " ")
		return m, nil
	}

	return m, nil
}

// handleConfigNumberKey handles number input for configuration.
func (m *Model) handleConfigNumberKey(msg tea.KeyMsg) (*Model, tea.Cmd) {
	if msg.String() == "esc" {
		m.pendingGridConfig = gridConfigNone
		return m, nil
	}

	num, err := strconv.Atoi(msg.String())
	if err != nil || num < 1 || num > 9 {
		m.pendingGridConfig = gridConfigNone
		return m, nil
	}

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

	m.pendingGridConfig = gridConfigNone

	if err != nil {
		m.logger.Error(fmt.Sprintf("model: failed to update config: %v", err))
		return m, nil
	}

	layout := m.computeViewports()
	m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	m.logger.Info(statusMsg)

	return m, nil
}

// handleOther handles remaining message types
func (m *Model) handleOther(msg tea.Msg) (*Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.MouseMsg:
		return m.handleMouseMsg(msg)

	case tea.WindowSizeMsg:
		m.handleWindowResize(msg)

	case LeftSidebarAnimationMsg:
		layout := m.computeViewports()
		m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

		if m.leftSidebar.IsAnimating() {
			return m, m.leftSidebar.animationCmd()
		}

		m.endAnimating()
		m.rightSidebar.UpdateDimensions(m.width, m.leftSidebar.IsVisible())

	case RightSidebarAnimationMsg:
		layout := m.computeViewports()
		m.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

		if m.rightSidebar.IsAnimating() {
			return m, m.rightSidebar.animationCmd()
		}

		m.endAnimating()
		m.leftSidebar.UpdateDimensions(m.width, m.rightSidebar.IsVisible())
	}

	return m, nil
}

// handleRecordsBatch processes a batch of sub-messages and manages redraw + loading flags.
func (m *Model) handleRecordsBatch(subMsgs []tea.Msg, suppressRedraw bool) []tea.Cmd {
	defer timeit(m.logger, "Model.handleRecordsBatch")()

	var cmds []tea.Cmd

	prev := m.suppressDraw
	m.suppressDraw = suppressRedraw
	for _, subMsg := range subMsgs {
		var cmd tea.Cmd
		m, cmd = m.processRecordMsg(subMsg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	m.suppressDraw = prev
	if !m.suppressDraw {
		m.metricsGrid.drawVisible()
	}

	if m.isLoading && m.metricsGrid.ChartCount() > 0 {
		m.isLoading = false
	}
	return cmds
}

// onInit handles InitMsg (reader ready).
func (m *Model) onInit(msg InitMsg) []tea.Cmd {
	m.logger.Debug("model: InitMsg received, reader initialized")
	m.reader = msg.Reader
	m.loadStartTime = time.Now()

	return []tea.Cmd{ReadAllRecordsChunked(m.reader)}
}

// onChunkedBatch handles boot-load chunked batches.
func (m *Model) onChunkedBatch(msg ChunkedBatchMsg) []tea.Cmd {
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
	if !m.fileComplete && !m.watcherMgr.IsStarted() {
		if err := m.watcherMgr.Start(m.runPath); err != nil {
			m.logger.CaptureError(fmt.Errorf("model: error starting watcher: %v", err))
		} else {
			m.logger.Info("model: watcher started successfully")
			m.heartbeatMgr.Start(m.isRunning)
		}
	}
	return cmds
}

// onBatched handles live drain batches.
func (m *Model) onBatched(msg BatchedRecordsMsg) []tea.Cmd {
	m.logger.Debug(fmt.Sprintf("model: BatchedRecordsMsg received with %d messages", len(msg.Msgs)))
	cmds := m.handleRecordsBatch(msg.Msgs, true)
	cmds = append(cmds, ReadAvailableRecords(m.reader))
	return cmds
}

// onHeartbeat triggers a live read and re-arms the heartbeat.
func (m *Model) onHeartbeat() []tea.Cmd {
	m.logger.Debug("model: processing HeartbeatMsg")
	m.heartbeatMgr.Reset(m.isRunning)
	return []tea.Cmd{
		ReadAvailableRecords(m.reader),
		m.watcherMgr.WaitForMsg,
	}
}

// onFileChange coalesces change notifications into a read.
func (m *Model) onFileChange() []tea.Cmd {
	m.heartbeatMgr.Reset(m.isRunning)
	return []tea.Cmd{
		ReadAvailableRecords(m.reader),
		m.watcherMgr.WaitForMsg,
	}
}

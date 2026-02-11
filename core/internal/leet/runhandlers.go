package leet

import (
	"fmt"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// handleRecordMsg handles messages that carry data from the .wandb file.
func (r *Run) handleRecordMsg(msg tea.Msg) (*Run, tea.Cmd) { // TODO: return just tea.Cmd
	defer r.logPanic("processRecordMsg")

	start := time.Now()
	defer func() {
		r.logger.Debug(fmt.Sprintf("perf: processRecordMsg(%T) took %s", msg, time.Since(start)))
	}()

	switch msg := msg.(type) {
	case RunMsg:
		r.logger.Debug("model: processing RunMsg")
		r.runOverview.ProcessRunMsg(msg)
		r.leftSidebar.Sync()
		r.runState = RunStateRunning
		r.syncLiveRunning()
		r.isLoading = false
		return r, nil

	case HistoryMsg:
		r.logger.Debug("model: processing HistoryMsg")
		if r.runState == RunStateRunning {
			r.heartbeatMgr.Reset(r.isRunning)
		}
		return r.handleHistoryMsg(msg)

	case StatsMsg:
		r.logger.Debug(fmt.Sprintf("model: processing StatsMsg with timestamp %d", msg.Timestamp))
		if r.runState == RunStateRunning {
			r.heartbeatMgr.Reset(r.isRunning)
		}
		r.rightSidebar.ProcessStatsMsg(msg)
		return r, nil

	case SystemInfoMsg:
		r.logger.Debug("model: processing SystemInfoMsg")
		r.runOverview.ProcessSystemInfoMsg(msg.Record)
		r.leftSidebar.Sync()
		return r, nil

	case SummaryMsg:
		r.logger.Debug("model: processing SummaryMsg")
		r.runOverview.ProcessSummaryMsg(msg.Summary)
		r.leftSidebar.Sync()
		return r, nil

	case FileCompleteMsg:
		r.logger.Debug("model: processing FileCompleteMsg - file is complete!")
		switch msg.ExitCode {
		case 0:
			r.runState = RunStateFinished
		default:
			r.runState = RunStateFailed
		}
		r.syncLiveRunning()
		r.runOverview.SetRunState(r.runState)
		r.leftSidebar.Sync()

		r.logger.Debug("model: stopping heartbeats and finishing watcher")
		r.heartbeatMgr.Stop()
		r.watcherMgr.Finish()

		return r, nil

	case ErrorMsg:
		r.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		r.runState = RunStateFailed
		r.syncLiveRunning()
		r.runOverview.SetRunState(r.runState)
		r.logger.Debug("model: stopping heartbeats and finishing watcher due to error")
		r.heartbeatMgr.Stop()
		r.watcherMgr.Finish()
		return r, nil
	}

	return r, nil
}

// handleHistoryMsg processes new history data.
func (r *Run) handleHistoryMsg(msg HistoryMsg) (*Run, tea.Cmd) {
	defer timeit(r.logger, "Model.handleHistoryMsg")()
	// Route to the grid; it handles sorting/filtering/pagination/focus itself.
	shouldDraw := r.metricsGrid.ProcessHistory(msg)
	if shouldDraw && !r.suppressDraw {
		r.metricsGrid.drawVisible()
	}
	return r, nil
}

// handleMouseMsg processes mouse events, routing by region.
func (r *Run) handleMouseMsg(msg tea.MouseMsg) (*Run, tea.Cmd) {
	defer timeit(r.logger, "Model.handleMouseMsg")()

	layout := r.computeViewports()

	if r.isInLeftSidebar(msg, layout) {
		return r.handleLeftSidebarMouse()
	}

	if r.isInRightSidebar(msg, layout) {
		return r.handleRightSidebarMouse(msg, layout)
	}

	return r.handleMainContentMouse(msg, layout)
}

// isInLeftSidebar checks if mouse position is in the left sidebar region.
func (r *Run) isInLeftSidebar(msg tea.MouseMsg, layout Layout) bool {
	return msg.X < layout.leftSidebarWidth
}

// isInRightSidebar checks if mouse position is in the right sidebar region.
func (r *Run) isInRightSidebar(msg tea.MouseMsg, layout Layout) bool {
	rightStart := r.width - layout.rightSidebarWidth
	return msg.X >= rightStart && layout.rightSidebarWidth > 0
}

// handleLeftSidebarMouse handles mouse events in the left sidebar.
func (r *Run) handleLeftSidebarMouse() (*Run, tea.Cmd) {
	r.metricsGrid.clearFocus()
	r.rightSidebar.ClearFocus()
	return r, nil
}

// handleRightSidebarMouse handles mouse events in the right sidebar.
func (r *Run) handleRightSidebarMouse(msg tea.MouseMsg, layout Layout) (*Run, tea.Cmd) {
	rightStart := r.width - layout.rightSidebarWidth
	adjustedX := msg.X - rightStart

	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {

		focusSet := r.rightSidebar.HandleMouseClick(adjustedX, msg.Y)

		if focusSet {
			r.metricsGrid.clearFocus()
		}
	}
	return r, nil
}

// handleMainContentMouse handles mouse events in the main content area.
func (r *Run) handleMainContentMouse(msg tea.MouseMsg, layout Layout) (*Run, tea.Cmd) {
	const gridPaddingX = 1
	const gridPaddingY = 1
	const headerOffset = 1

	adjustedX := msg.X - layout.leftSidebarWidth - gridPaddingX
	adjustedY := msg.Y - gridPaddingY - headerOffset

	dims := r.metricsGrid.CalculateChartDimensions(
		layout.mainContentAreaWidth,
		layout.height,
	)

	// Chart 2D indices on the grid.
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	// Handle left click for chart focus.
	if tea.MouseEvent(msg).Button == tea.MouseButtonLeft &&
		tea.MouseEvent(msg).Action == tea.MouseActionPress {
		r.rightSidebar.ClearFocus()
		r.metricsGrid.HandleClick(row, col)
		return r, nil
	}

	// Handle right click/hold+move/release for chart data inspection.
	if tea.MouseEvent(msg).Button == tea.MouseButtonRight {
		// Holding Alt activates synchronised inspection across all charts
		// visible on the current page.
		alt := tea.MouseEvent(msg).Alt

		switch tea.MouseEvent(msg).Action {
		case tea.MouseActionPress:
			r.metricsGrid.StartInspection(adjustedX, row, col, dims, alt)
		case tea.MouseActionMotion:
			r.metricsGrid.UpdateInspection(adjustedX, row, col, dims)
		case tea.MouseActionRelease:
			r.metricsGrid.EndInspection()
		}
	}

	// Handle wheel events for zoom.
	if tea.MouseEvent(msg).IsWheel() {
		r.metricsGrid.HandleWheel(
			adjustedX,
			row,
			col,
			dims,
			msg.Button == tea.MouseButtonWheelUp,
		)
	}

	return r, nil
}

// handleKeyMsg processes keyboard events using the centralized key bindings.
func (r *Run) handleKeyMsg(msg tea.KeyMsg) tea.Cmd {
	// Filter modes take priority.
	if r.leftSidebar.IsFilterMode() {
		return r.handleOverviewFilter(msg)
	}
	if r.metricsGrid.IsFilterMode() {
		return r.handleMetricsFilter(msg)
	}

	// Grid config capture takes priority.
	if r.config.IsAwaitingGridConfig() {
		return r.handleConfigNumberKey(msg)
	}

	// Dispatch to key map.
	if handler, ok := r.keyMap[normalizeKey(msg.String())]; ok {
		return handler(r, msg)
	}
	return nil
}

func (r *Run) cleanup() {
	if r.reader != nil {
		r.reader.Close()
	}
	if r.heartbeatMgr != nil {
		r.heartbeatMgr.Stop()
	}
	if r.watcherMgr != nil {
		r.watcherMgr.Finish()
	}
}

func (r *Run) handleQuit(msg tea.KeyMsg) tea.Cmd {
	r.logger.Debug("run: quit requested")
	r.cleanup()

	return tea.Quit
}

// beginAnimating tries to acquire the one-shot animation token.
//
// Returns true if the caller owns the token and may initiate an animation.
func (r *Run) beginAnimating() bool {
	r.animationMu.Lock()
	if r.animating {
		r.animationMu.Unlock()
		return false
	}
	r.animating = true
	r.animationMu.Unlock()
	return true
}

// endAnimating releases the animation token after an animation completes.
func (r *Run) endAnimating() {
	r.animationMu.Lock()
	r.animating = false
	r.animationMu.Unlock()
}

func (r *Run) handleToggleLeftSidebar(msg tea.KeyMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	leftWillBeVisible := !r.leftSidebar.IsVisible()

	if err := r.config.SetLeftSidebarVisible(leftWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("model: failed to save left sidebar state: %v", err))
	}

	r.leftSidebar.UpdateDimensions(r.width, r.rightSidebar.IsVisible())
	r.rightSidebar.UpdateDimensions(r.width, leftWillBeVisible)
	r.leftSidebar.Toggle()

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.leftSidebar.animationCmd()
}

func (r *Run) handleToggleRightSidebar(msg tea.KeyMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	rightWillBeVisible := !r.rightSidebar.IsVisible()

	if err := r.config.SetRightSidebarVisible(rightWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("model: failed to save right sidebar state: %v", err))
	}

	r.rightSidebar.UpdateDimensions(r.width, r.leftSidebar.IsVisible())
	r.leftSidebar.UpdateDimensions(r.width, rightWillBeVisible)
	r.rightSidebar.Toggle()

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.rightSidebar.animationCmd()
}

func (r *Run) handlePrevPage(msg tea.KeyMsg) tea.Cmd {
	r.metricsGrid.Navigate(-1)
	return nil
}

func (r *Run) handleNextPage(msg tea.KeyMsg) tea.Cmd {
	r.metricsGrid.Navigate(1)
	return nil
}

func (r *Run) handlePrevSystemPage(msg tea.KeyMsg) tea.Cmd {
	if r.rightSidebar.IsVisible() && r.rightSidebar.metricsGrid != nil {
		r.rightSidebar.metricsGrid.Navigate(-1)
	}
	return nil
}

func (r *Run) handleNextSystemPage(msg tea.KeyMsg) tea.Cmd {
	if r.rightSidebar.IsVisible() && r.rightSidebar.metricsGrid != nil {
		r.rightSidebar.metricsGrid.Navigate(1)
	}
	return nil
}

func (r *Run) handleEnterMetricsFilter(msg tea.KeyMsg) tea.Cmd {
	r.metricsGrid.EnterFilterMode()
	return nil
}

func (r *Run) handleClearMetricsFilter(msg tea.KeyMsg) tea.Cmd {
	if r.metricsGrid.FilterQuery() != "" {
		r.metricsGrid.ClearFilter()
	}
	r.focus.Reset()
	return nil
}

func (r *Run) handleEnterOverviewFilter(msg tea.KeyMsg) tea.Cmd {
	r.leftSidebar.EnterFilterMode()
	return nil
}

func (r *Run) handleClearOverviewFilter(msg tea.KeyMsg) tea.Cmd {
	if r.leftSidebar.IsFiltering() {
		r.leftSidebar.ClearFilter()
	}
	return nil
}

func (r *Run) handleConfigMetricsCols(msg tea.KeyMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigMetricsCols)
	return nil
}

func (r *Run) handleConfigMetricsRows(msg tea.KeyMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigMetricsRows)
	return nil
}

func (r *Run) handleConfigSystemCols(msg tea.KeyMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigSystemCols)
	return nil
}

func (r *Run) handleConfigSystemRows(msg tea.KeyMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigSystemRows)
	return nil
}

// handleMetricsFilter handles filter mode input for metrics
func (r *Run) handleMetricsFilter(msg tea.KeyMsg) tea.Cmd {
	r.metricsGrid.handleMetricsFilterKey(msg)
	return nil
}

// handleOverviewFilter handles overview filter keyboard input.
func (r *Run) handleOverviewFilter(msg tea.KeyMsg) tea.Cmd {
	switch msg.Type {
	case tea.KeyEsc:
		r.leftSidebar.ExitFilterMode(false)
	case tea.KeyEnter:
		r.leftSidebar.ExitFilterMode(true)
	case tea.KeyTab:
		r.leftSidebar.ToggleFilterMatchMode()
	case tea.KeyBackspace, tea.KeySpace, tea.KeyRunes:
		r.leftSidebar.UpdateFilterDraft(msg)
		r.leftSidebar.ApplyFilter()
		r.leftSidebar.updateSectionHeights()
	}
	return nil
}

// handleConfigNumberKey handles number input for configuration.
func (r *Run) handleConfigNumberKey(msg tea.KeyMsg) tea.Cmd {
	r.metricsGrid.handleGridConfigNumberKey(msg, r.computeViewports())

	return nil
}

// handleSidebarAnimation handles sidebar animation.
func (r *Run) handleSidebarAnimation(msg tea.Msg) []tea.Cmd {
	switch msg.(type) {
	case LeftSidebarAnimationMsg:
		layout := r.computeViewports()
		r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

		if r.leftSidebar.IsAnimating() {
			return []tea.Cmd{r.leftSidebar.animationCmd()}
		}

		r.endAnimating()
		r.rightSidebar.UpdateDimensions(r.width, r.leftSidebar.IsVisible())

	case RightSidebarAnimationMsg:
		layout := r.computeViewports()
		r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

		if r.rightSidebar.IsAnimating() {
			return []tea.Cmd{r.rightSidebar.animationCmd()}
		}

		r.endAnimating()
		r.leftSidebar.UpdateDimensions(r.width, r.rightSidebar.IsVisible())
	}

	return nil
}

// handleRecordsBatch processes a batch of sub-messages and manages redraw + loading flags.
func (r *Run) handleRecordsBatch(subMsgs []tea.Msg, suppressRedraw bool) []tea.Cmd {
	defer timeit(r.logger, "Model.handleRecordsBatch")()

	var cmds []tea.Cmd

	prev := r.suppressDraw
	r.suppressDraw = suppressRedraw
	for _, subMsg := range subMsgs {
		var cmd tea.Cmd
		r, cmd = r.handleRecordMsg(subMsg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	r.suppressDraw = prev
	if !r.suppressDraw {
		r.metricsGrid.drawVisible()
	}

	return cmds
}

// handleInit handles InitMsg (reader ready).
func (r *Run) handleInit(msg InitMsg) []tea.Cmd {
	r.logger.Debug("model: InitMsg received, reader initialized")
	r.reader = msg.Reader
	r.loadStartTime = time.Now()

	return []tea.Cmd{ReadAllRecordsChunked(r.reader)}
}

// handleChunkedBatch handles boot-load chunked batches.
func (r *Run) handleChunkedBatch(msg ChunkedBatchMsg) []tea.Cmd {
	defer timeit(r.logger, "Model.onChunkedBatch")()

	r.logger.Debug(
		fmt.Sprintf("model: ChunkedBatchMsg received with %d messages, hasMore=%v",
			len(msg.Msgs), msg.HasMore))

	r.recordsLoaded += msg.Progress

	cmds := r.handleRecordsBatch(msg.Msgs, false)

	if msg.HasMore {
		cmds = append(cmds, ReadAllRecordsChunked(r.reader))
		return cmds
	}

	// Boot load complete -> begin live mode once.
	if r.runState == RunStateRunning && !r.watcherMgr.IsStarted() {
		if err := r.watcherMgr.Start(r.runPath); err != nil {
			r.logger.CaptureError(fmt.Errorf("model: error starting watcher: %v", err))
		} else {
			r.logger.Info("model: watcher started successfully")
			r.heartbeatMgr.Start(r.isRunning)
		}
	}
	return cmds
}

// handleBatched handles live drain batches.
func (r *Run) handleBatched(msg BatchedRecordsMsg) []tea.Cmd {
	r.logger.Debug(fmt.Sprintf("model: BatchedRecordsMsg received with %d messages", len(msg.Msgs)))
	cmds := r.handleRecordsBatch(msg.Msgs, true)
	cmds = append(cmds, ReadAvailableRecords(r.reader))
	return cmds
}

// handleHeartbeat triggers a live read and re-arms the heartbeat.
func (r *Run) handleHeartbeat() []tea.Cmd {
	r.logger.Debug("model: processing HeartbeatMsg")
	r.heartbeatMgr.Reset(r.isRunning)
	return []tea.Cmd{
		ReadAvailableRecords(r.reader),
		r.watcherMgr.WaitForMsg,
	}
}

// handleFileChange coalesces change notifications into a read.
func (r *Run) handleFileChange() []tea.Cmd {
	r.heartbeatMgr.Reset(r.isRunning)
	return []tea.Cmd{
		ReadAvailableRecords(r.reader),
		r.watcherMgr.WaitForMsg,
	}
}

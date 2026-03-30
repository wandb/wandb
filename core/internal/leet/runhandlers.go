package leet

import (
	"errors"
	"fmt"
	"io"
	"time"

	tea "charm.land/bubbletea/v2"
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

	case ConsoleLogMsg:
		r.logger.Debug("model: processing ConsoleLogMsg")
		r.consoleLogs.ProcessRaw(msg.Text, msg.IsStderr, msg.Time)
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

	shouldDraw := r.metricsGrid.ProcessHistory(msg)
	if r.mediaStore.ProcessHistory(msg) {
		r.mediaPane.SetStore(r.mediaStore)
	}
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
	mouse := msg.Mouse()
	return mouse.X < layout.leftSidebarWidth
}

// isInRightSidebar checks if mouse position is in the right sidebar region.
func (r *Run) isInRightSidebar(msg tea.MouseMsg, layout Layout) bool {
	mouse := msg.Mouse()
	rightStart := r.width - layout.rightSidebarWidth
	return mouse.X >= rightStart && layout.rightSidebarWidth > 0
}

// handleLeftSidebarMouse handles mouse events in the left sidebar.
func (r *Run) handleLeftSidebarMouse() (*Run, tea.Cmd) {
	r.metricsGrid.clearFocus()
	r.rightSidebar.ClearFocus()
	return r, nil
}

// handleRightSidebarMouse handles mouse events in the right sidebar.
func (r *Run) handleRightSidebarMouse(msg tea.MouseMsg, layout Layout) (*Run, tea.Cmd) {
	mouse := msg.Mouse()
	alt := mouse.Mod == tea.ModAlt

	rightStart := r.width - layout.rightSidebarWidth
	adjustedX := mouse.X - rightStart

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			r.metricsGrid.clearFocus()
			r.rightSidebar.HandleMouseClick(adjustedX, mouse.Y)
		case tea.MouseRight:
			r.metricsGrid.clearFocus()
			r.rightSidebar.StartInspection(adjustedX, mouse.Y, alt)
		}
	case tea.MouseMotionMsg:
		if m.Button == tea.MouseRight {
			r.rightSidebar.UpdateInspection(adjustedX, mouse.Y)
		}
	case tea.MouseReleaseMsg:
		if m.Button == tea.MouseRight {
			r.rightSidebar.EndInspection()
		}
	case tea.MouseWheelMsg:
		r.metricsGrid.clearFocus()
		switch m.Button {
		case tea.MouseWheelUp:
			r.rightSidebar.HandleWheel(adjustedX, mouse.Y, true)
		case tea.MouseWheelDown:
			r.rightSidebar.HandleWheel(adjustedX, mouse.Y, false)
		}
	}

	return r, nil
}

// handleMainContentMouse handles mouse events in the main content area.
func (r *Run) handleMainContentMouse(msg tea.MouseMsg, layout Layout) (*Run, tea.Cmd) {
	if r.mediaPane.IsFullscreen() {
		return r, nil
	}

	mouse := msg.Mouse()
	alt := mouse.Mod == tea.ModAlt // Alt pressed at the time of the mouse event?

	const gridPaddingX = 1
	const gridPaddingY = 1

	adjustedX := mouse.X - layout.leftSidebarWidth - gridPaddingX
	adjustedY := mouse.Y - gridPaddingY
	if adjustedX < 0 || adjustedY < 0 || adjustedY >= layout.height {
		r.metricsGrid.clearFocus()
		r.rightSidebar.ClearFocus()
		return r, nil
	}

	dims := r.metricsGrid.CalculateChartDimensions(
		layout.mainContentAreaWidth,
		layout.height,
	)

	// Chart 2D indices on the grid.
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			r.rightSidebar.ClearFocus()
			r.metricsGrid.HandleClick(row, col)
		case tea.MouseRight:
			// Holding Alt activates synchronised inspection across all charts
			// visible on the current page.
			r.metricsGrid.StartInspection(adjustedX, row, col, dims, alt)
		}
	case tea.MouseMotionMsg:
		if m.Button == tea.MouseRight {
			r.metricsGrid.UpdateInspection(adjustedX, row, col, dims)
		}
	case tea.MouseReleaseMsg:
		if m.Button == tea.MouseRight {
			r.metricsGrid.EndInspection()
		}
	case tea.MouseWheelMsg:
		switch m.Button {
		case tea.MouseWheelUp:
			r.metricsGrid.HandleWheel(adjustedX, row, col, dims, true)
		case tea.MouseWheelDown:
			r.metricsGrid.HandleWheel(adjustedX, row, col, dims, false)
		}
	}

	return r, nil
}

// handleKeyPressMsg processes keyboard events using the centralized key bindings.
func (r *Run) handleKeyPressMsg(msg tea.KeyPressMsg) tea.Cmd {
	// Filter modes take priority.
	if r.leftSidebar.IsFilterMode() {
		r.leftSidebar.HandleFilterKey(msg)
		return nil
	}
	if r.metricsGrid.IsFilterMode() {
		r.metricsGrid.handleFilterKey(msg)
		return nil
	}
	if r.rightSidebar.IsFilterMode() {
		r.rightSidebar.HandleFilterKey(msg)
		return nil
	}

	// Grid config capture takes priority.
	if r.config.IsAwaitingGridConfig() {
		return r.handleConfigNumberKey(msg)
	}

	// Focus-aware key dispatch: route to the currently focused component.
	switch r.focusMgr.Current() {
	case FocusTargetMetricsGrid, FocusTargetSystemMetrics:
		if cmd := r.handleGridWASD(msg); cmd != nil {
			return cmd
		}
	case FocusTargetMedia:
		if r.mediaPane.HandleKey(msg) {
			return nil
		}
	}

	// Dispatch to key map.
	if handler, ok := r.keyMap[normalizeKey(msg.String())]; ok {
		return handler(r, msg)
	}
	return nil
}

func (r *Run) cleanup() {
	if r.historySource != nil {
		r.historySource.Close()
	}
	if r.heartbeatMgr != nil {
		r.heartbeatMgr.Stop()
	}
	if r.watcherMgr != nil {
		r.watcherMgr.Finish()
	}
}

func (r *Run) handleQuit(msg tea.KeyPressMsg) tea.Cmd {
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

// handleToggleLeftSidebar toggles the left overview sidebar and resolves
// focus so a collapsing sidebar loses focus and an expanding sidebar
// gains it when nothing else is focused.
func (r *Run) handleToggleLeftSidebar(msg tea.KeyPressMsg) tea.Cmd {
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

	r.focusMgr.ResolveAfterVisibilityChange()

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.leftSidebar.animationCmd()
}

func (r *Run) handleToggleRightSidebar(msg tea.KeyPressMsg) tea.Cmd {
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

func (r *Run) handlePrevPage(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		r.rightSidebar.metricsGrid.Navigate(-1)
	case FocusTargetMedia:
		r.mediaPane.NavigatePage(-1)
	default:
		r.metricsGrid.Navigate(-1)
	}
	return nil
}

func (r *Run) handleNextPage(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		r.rightSidebar.metricsGrid.Navigate(1)
	case FocusTargetMedia:
		r.mediaPane.NavigatePage(1)
	default:
		r.metricsGrid.Navigate(1)
	}
	return nil
}

func (r *Run) handleCycleFocusedChartMode(tea.KeyPressMsg) tea.Cmd {
	switch r.focus.Type {
	case FocusMainChart:
		r.metricsGrid.toggleFocusedChartLogY()
	case FocusSystemChart:
		if r.rightSidebar != nil && r.rightSidebar.metricsGrid != nil {
			r.rightSidebar.metricsGrid.cycleFocusedChartMode()
		}
	}
	return nil
}

func (r *Run) handleEnterMetricsFilter(msg tea.KeyPressMsg) tea.Cmd {
	r.metricsGrid.EnterFilterMode()
	return nil
}

func (r *Run) handleClearMetricsFilter(msg tea.KeyPressMsg) tea.Cmd {
	if r.metricsGrid.FilterQuery() != "" {
		r.metricsGrid.ClearFilter()
	}
	r.focus.Reset()
	return nil
}

func (r *Run) handleEnterOverviewFilter(msg tea.KeyPressMsg) tea.Cmd {
	r.leftSidebar.EnterFilterMode()
	return nil
}

func (r *Run) handleClearOverviewFilter(msg tea.KeyPressMsg) tea.Cmd {
	if r.leftSidebar.IsFiltering() {
		r.leftSidebar.ClearFilter()
	}
	return nil
}

func (r *Run) handleToggleMetricsGrid(msg tea.KeyPressMsg) tea.Cmd {
	metricsWillBeVisible := !r.metricsGridAnimState.IsExpanded()

	if err := r.config.SetMetricsGridVisible(metricsWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("runhandlers: failed to save metrics grid state: %v", err))
	}

	r.metricsGridAnimState.Toggle()
	r.focusMgr.ResolveAfterVisibilityChange()

	r.updateBottomPaneHeights(r.mediaPane.IsExpanded(), r.consoleLogsPane.IsExpanded())

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.metricsGridAnimationCmd()
}

func (r *Run) handleMetricsGridAnimation() []tea.Cmd {
	r.metricsGridAnimState.Update(time.Now())

	r.updateBottomPaneHeights(r.mediaPane.IsExpanded(), r.consoleLogsPane.IsExpanded())
	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	if r.metricsGridAnimState.IsAnimating() {
		return []tea.Cmd{r.metricsGridAnimationCmd()}
	}
	return nil
}

func (r *Run) metricsGridAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(time.Time) tea.Msg {
		return MetricsGridAnimationMsg{}
	})
}

func (r *Run) handleGridWASD(msg tea.KeyPressMsg) tea.Cmd {
	var dr, dc int
	switch normalizeKey(msg.String()) {
	case "w":
		dr = -1
	case "s":
		dr = 1
	case "a":
		dc = -1
	case "d":
		dc = 1
	default:
		return nil
	}

	switch r.focusMgr.Current() {
	case FocusTargetMetricsGrid:
		r.metricsGrid.NavigateFocus(dr, dc)
	case FocusTargetSystemMetrics:
		r.rightSidebar.metricsGrid.NavigateFocus(dr, dc)
	}
	// Return a no-op command to signal the key was consumed.
	return func() tea.Msg { return nil }
}

func (r *Run) handleConfigMetricsCols(msg tea.KeyPressMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigMetricsCols)
	return nil
}

func (r *Run) handleConfigMetricsRows(msg tea.KeyPressMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigMetricsRows)
	return nil
}

func (r *Run) handleConfigSystemCols(msg tea.KeyPressMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigSystemCols)
	return nil
}

func (r *Run) handleConfigSystemRows(msg tea.KeyPressMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigSystemRows)
	return nil
}

func (r *Run) handleConfigMediaCols(msg tea.KeyPressMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigMediaCols)
	return nil
}

func (r *Run) handleConfigMediaRows(msg tea.KeyPressMsg) tea.Cmd {
	r.config.SetPendingGridConfig(gridConfigMediaRows)
	return nil
}

func (r *Run) handleConfigFocusedCols(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		r.config.SetPendingGridConfig(gridConfigSystemCols)
	case FocusTargetMedia:
		r.config.SetPendingGridConfig(gridConfigMediaCols)
	default:
		r.config.SetPendingGridConfig(gridConfigMetricsCols)
	}
	return nil
}

func (r *Run) handleConfigFocusedRows(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		r.config.SetPendingGridConfig(gridConfigSystemRows)
	case FocusTargetMedia:
		r.config.SetPendingGridConfig(gridConfigMediaRows)
	default:
		r.config.SetPendingGridConfig(gridConfigMetricsRows)
	}
	return nil
}

func (r *Run) handleEnterSystemMetricsFilter(msg tea.KeyPressMsg) tea.Cmd {
	var cmd tea.Cmd
	if !r.config.RightSidebarVisible() {
		cmd = r.handleToggleRightSidebar(msg)
	}
	r.rightSidebar.metricsGrid.EnterFilterMode()
	r.rightSidebar.metricsGrid.ApplyFilter()

	return cmd
}

func (r *Run) handleClearSystemMetricsFilter(msg tea.KeyPressMsg) tea.Cmd {
	if r.rightSidebar.metricsGrid.FilterQuery() != "" {
		r.rightSidebar.metricsGrid.ClearFilter()
	}
	if r.focus.Type == FocusSystemChart {
		r.focus.Reset()
	}
	return nil
}

// handleConfigNumberKey handles number input for configuration.
func (r *Run) handleConfigNumberKey(msg tea.KeyPressMsg) tea.Cmd {
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

func (r *Run) handleToggleMediaPane(msg tea.KeyPressMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	mediaWillBeVisible := !r.mediaPane.IsExpanded()

	if err := r.config.SetMediaVisible(mediaWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("runhandlers: failed to save media pane state: %v", err))
	}

	if !mediaWillBeVisible {
		r.mediaPane.ExitFullscreen()
	}

	r.mediaPane.Toggle()
	r.updateBottomPaneHeights(mediaWillBeVisible, r.consoleLogsPane.IsExpanded())

	if mediaWillBeVisible {
		r.focusMgr.SetTarget(FocusTargetMedia, 1)
	} else {
		r.focusMgr.ResolveAfterVisibilityChange()
	}

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.mediaPaneAnimationCmd()
}

func (r *Run) handleMediaPaneAnimation() []tea.Cmd {
	r.mediaPane.Update(time.Now())

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	if r.mediaPane.IsAnimating() {
		return []tea.Cmd{r.mediaPaneAnimationCmd()}
	}

	r.endAnimating()
	return nil
}

func (r *Run) mediaPaneAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(time.Time) tea.Msg {
		return MediaPaneAnimationMsg{}
	})
}

// handleToggleConsoleLogsPane toggles the console logs bottom bar and resolves
// focus so a collapsing bar loses focus and an expanding bar gains it
// when nothing else is focused.
func (r *Run) handleToggleConsoleLogsPane(msg tea.KeyPressMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	bottomWillBeVisible := !r.consoleLogsPane.IsExpanded()

	if err := r.config.SetConsoleLogsVisible(bottomWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("runhandlers: failed to save console logs state: %v", err))
	}

	r.consoleLogsPane.Toggle()
	r.updateBottomPaneHeights(r.mediaPane.IsExpanded(), bottomWillBeVisible)
	r.focusMgr.ResolveAfterVisibilityChange()

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.consoleLogsPaneAnimationCmd()
}

func (r *Run) handleConsoleLogsPaneAnimation() []tea.Cmd {
	r.consoleLogsPane.Update(time.Now())

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	if r.consoleLogsPane.IsAnimating() {
		return []tea.Cmd{r.consoleLogsPaneAnimationCmd()}
	}

	r.endAnimating()
	return nil
}

func (r *Run) consoleLogsPaneAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(time.Time) tea.Msg {
		return ConsoleLogsPaneAnimationMsg{}
	})
}

func (r *Run) readChunkCmd(
	source HistorySource,
	chunkSize int,
	maxTimePerChunk time.Duration,
) tea.Cmd {
	return func() tea.Msg {
		if source == nil {
			return nil
		}

		msg, err := source.Read(chunkSize, maxTimePerChunk)
		if err != nil && !errors.Is(err, io.EOF) {
			return ErrorMsg{Err: err}
		}

		return msg
	}
}

func (r *Run) ReadLiveBatchCmd(source HistorySource) tea.Cmd {
	return func() tea.Msg {
		if source == nil {
			return nil
		}

		msg, err := source.Read(LiveMonitorChunkSize, LiveMonitorMaxTime)
		if err != nil && !errors.Is(err, io.EOF) {
			return ErrorMsg{Err: err}
		}
		if msg == nil {
			return nil
		}

		batch, ok := msg.(ChunkedBatchMsg)
		if !ok {
			return msg
		}
		if len(batch.Msgs) == 0 {
			return nil
		}

		return BatchedRecordsMsg{Msgs: batch.Msgs}
	}
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
	r.historySource = msg.Source
	r.loadStartTime = time.Now()

	return []tea.Cmd{
		r.readChunkCmd(r.historySource, BootLoadChunkSize, BootLoadMaxTime),
	}
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
		cmds = append(
			cmds,
			r.readChunkCmd(r.historySource, BootLoadChunkSize, BootLoadMaxTime),
		)
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
	cmds = append(
		cmds,
		r.ReadLiveBatchCmd(r.historySource),
	)
	return cmds
}

// handleHeartbeat triggers a live read and re-arms the heartbeat.
func (r *Run) handleHeartbeat() []tea.Cmd {
	r.logger.Debug("model: processing HeartbeatMsg")
	r.heartbeatMgr.Reset(r.isRunning)
	return []tea.Cmd{
		r.ReadLiveBatchCmd(r.historySource),
		r.watcherMgr.WaitForMsg,
	}
}

// handleFileChange coalesces change notifications into a read.
func (r *Run) handleFileChange() []tea.Cmd {
	r.heartbeatMgr.Reset(r.isRunning)
	return []tea.Cmd{
		r.ReadLiveBatchCmd(r.historySource),
		r.watcherMgr.WaitForMsg,
	}
}

// handleSidebarTabNav cycles focus between overview sections and the
// console logs bar, mirroring the workspace's Tab cycling pattern.
//
// Within the overview region, Tab first cycles through sections. At the
// boundary, it moves to the next available region.
func (r *Run) handleSidebarTabNav(msg tea.KeyPressMsg) tea.Cmd {
	direction := 1
	if msg.Code == tea.KeyTab && msg.Mod == tea.ModShift {
		direction = -1
	}

	withinFn := func(dir int) bool {
		if r.focusMgr.IsTarget(FocusTargetOverview) {
			return r.cycleRunOverviewSection(dir)
		}
		return false
	}

	r.focusMgr.TabWithinOrAdvance(direction, withinFn)
	return nil
}

func (r *Run) handleSidebarVerticalNav(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetMedia:
		switch msg.Code {
		case tea.KeyUp:
			r.mediaPane.Scrub(-10)
		case tea.KeyDown:
			r.mediaPane.Scrub(10)
		}
	case FocusTargetConsoleLogs:
		switch msg.Code {
		case tea.KeyUp:
			r.consoleLogsPane.Up()
		case tea.KeyDown:
			r.consoleLogsPane.Down()
		}
	case FocusTargetOverview:
		if r.leftSidebar.IsVisible() {
			switch msg.Code {
			case tea.KeyUp:
				r.leftSidebar.navigateUp()
			case tea.KeyDown:
				r.leftSidebar.navigateDown()
			}
		}
	}
	return nil
}

func (r *Run) handleSidebarPageNav(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetMedia:
		switch msg.Code {
		case tea.KeyLeft:
			r.mediaPane.Scrub(-1)
		case tea.KeyRight:
			r.mediaPane.Scrub(1)
		}
	case FocusTargetConsoleLogs:
		switch msg.Code {
		case tea.KeyLeft:
			r.consoleLogsPane.PageUp()
		case tea.KeyRight:
			r.consoleLogsPane.PageDown()
		}
	case FocusTargetOverview:
		if r.leftSidebar.IsVisible() {
			switch msg.Code {
			case tea.KeyLeft:
				r.leftSidebar.navigatePageUp()
			case tea.KeyRight:
				r.leftSidebar.navigatePageDown()
			}
		}
	}
	return nil
}

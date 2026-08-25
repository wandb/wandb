package leet

import (
	"errors"
	"fmt"
	"io"
	"os"
	"time"

	tea "charm.land/bubbletea/v2"
)

// handleRecordMsg handles messages that carry data from the .wandb file.
func (r *Run) handleRecordMsg(msg tea.Msg) tea.Cmd {
	defer r.logPanic("processRecordMsg")

	start := time.Now()
	defer func() {
		r.logger.Debug(fmt.Sprintf("perf: processRecordMsg(%T) took %s", msg, time.Since(start)))
	}()
	defer r.resolveFocusAfterData()

	// Anything the reader produced counts as proof of life for the crash
	// check. Terminal messages (FileComplete, Error) also land here, but
	// they leave RunStateRunning, after which lastUpdateAt is irrelevant.
	r.lastUpdateAt = time.Now()

	switch msg := msg.(type) {
	case RunMsg:
		r.logger.Debug("model: processing RunMsg")
		r.lastError = ""
		r.runOverview.ProcessRunMsg(msg)
		r.leftSidebar.Sync()
		r.runState = RunStateRunning
		r.syncLiveRunning()
		r.isLoading = false
		return r.ensureLivePulseCmd()

	case HistoryMsg:
		r.logger.Debug("model: processing HistoryMsg")
		if r.shouldResetLiveHeartbeat() {
			r.heartbeatMgr.Reset(r.isRunning)
		}
		r.handleHistoryMsg(msg)

	case StatsMsg:
		r.logger.Debug(fmt.Sprintf("model: processing StatsMsg with timestamp %d", msg.Timestamp))
		if r.shouldResetLiveHeartbeat() {
			r.heartbeatMgr.Reset(r.isRunning)
		}
		r.rightSidebar.ProcessStatsMsg(msg)

	case SystemInfoMsg:
		r.logger.Debug("model: processing SystemInfoMsg")
		r.runOverview.ProcessSystemInfoMsg(msg.Record)
		r.leftSidebar.Sync()

	case SummaryMsg:
		r.logger.Debug("model: processing SummaryMsg")
		r.runOverview.ProcessSummaryMsg(msg.Summary)
		r.leftSidebar.Sync()

	case ConsoleLogMsg:
		r.logger.Debug("model: processing ConsoleLogMsg")
		r.consoleLogs.ProcessRaw(msg.Text, msg.IsStderr, msg.Time)
		// Keep the pane's data (and thus focus availability) current
		// without waiting for the next render.
		r.consoleLogsPane.SetConsoleLogs(r.consoleLogs.Items())

	case FileCompleteMsg:
		r.logger.Debug("model: processing FileCompleteMsg - file is complete!")
		r.setRunState(runStateForExitCode(msg.ExitCode))

		r.logger.Debug("model: stopping heartbeats and finishing watcher")
		r.heartbeatMgr.Stop()
		r.watcherMgr.Finish()

	case ErrorMsg:
		r.logger.Debug(fmt.Sprintf("model: processing ErrorMsg: %v", msg.Err))
		r.isLoading = false
		r.lastError = "unknown error"
		if msg.Err != nil {
			r.lastError = msg.Err.Error()
		}
		r.setRunState(RunStateFailed)
		r.logger.Debug("model: stopping heartbeats and finishing watcher due to error")
		r.heartbeatMgr.Stop()
		r.watcherMgr.Finish()
	}

	return nil
}

// runStateForExitCode maps an exit record's code to a run state, following
// the server's convention (254 is a client-reported crash).
func runStateForExitCode(exitCode int32) RunState {
	switch exitCode {
	case 0:
		return RunStateFinished
	case 254:
		return RunStateCrashed
	default:
		return RunStateFailed
	}
}

// setRunState updates the run state everywhere it is mirrored: the atomic
// liveness flag, the overview data model, and the sidebar.
func (r *Run) setRunState(state RunState) {
	r.runState = state
	r.syncLiveRunning()
	r.runOverview.SetRunState(state)
	r.leftSidebar.Sync()
}

// handleHistoryMsg processes new history data.
func (r *Run) handleHistoryMsg(msg HistoryMsg) {
	defer timeit(r.logger, "Model.handleHistoryMsg")()

	shouldDraw := r.metricsGrid.ProcessHistory(msg)
	if r.mediaStore.ProcessHistory(msg) {
		r.mediaPane.SetStore(r.mediaStore)
	}
	if shouldDraw && !r.suppressDraw {
		r.metricsGrid.drawVisible()
	}
}

// handleMouseMsg processes mouse events, routing by region.
func (r *Run) handleMouseMsg(msg tea.MouseMsg) tea.Cmd {
	defer timeit(r.logger, "Model.handleMouseMsg")()

	layout := r.computeViewports()

	// Pane resizing wins over pane-local mouse handling.
	if r.drag.handleMouse(msg, layout, r.dragTargets()) {
		return nil
	}

	if r.isInLeftSidebar(msg, layout) {
		return r.handleLeftSidebarMouse()
	}

	if r.isInRightSidebar(msg, layout) {
		return r.handleRightSidebarMouse(msg, layout)
	}

	return r.handleMainContentMouse(msg, layout)
}

// dragTargets reports which layout boundaries a mouse event may grab.
func (r *Run) dragTargets() dragTargets {
	t := dragTargets{
		width:           r.width,
		height:          r.height,
		leftExpanded:    r.leftSidebar.IsExpanded(),
		rightExpanded:   r.rightSidebar.animState.IsExpanded(),
		mediaFullscreen: r.mediaPane.IsFullscreen(),
	}
	if t.leftExpanded {
		t.overview = r.leftSidebar
	}
	return t
}

// handleResetLayout resets the view's pane proportions to the defaults.
func (r *Run) handleResetLayout(tea.KeyPressMsg) tea.Cmd {
	r.drag.reset()
	return nil
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
func (r *Run) handleLeftSidebarMouse() tea.Cmd {
	r.metricsGrid.clearFocus()
	r.rightSidebar.ClearFocus()
	return nil
}

func (r *Run) adoptChartMouseFocus() {
	switch r.focus.Type {
	case FocusMainChart:
		r.focusMgr.AdoptTarget(FocusTargetMetricsGrid)
	case FocusSystemChart:
		r.focusMgr.AdoptTarget(FocusTargetSystemMetrics)
	}
}

func (r *Run) handleMediaMouse(msg tea.MouseMsg, layout Layout) tea.Cmd {
	mouse := msg.Mouse()
	localX := mouse.X - layout.leftSidebarWidth
	localY := mouse.Y - layout.mediaY

	if m, ok := msg.(tea.MouseClickMsg); ok {
		if m.Button == tea.MouseLeft &&
			r.mediaPane.HandleMouseClick(
				localX, localY,
				layout.mainContentAreaWidth, layout.mediaHeight,
			) {
			r.mediaPane.SetActive(true)
			r.focusMgr.AdoptTarget(FocusTargetMedia)
		}
	}

	return nil
}

// handleRightSidebarMouse handles mouse events in the right sidebar.
func (r *Run) handleRightSidebarMouse(msg tea.MouseMsg, layout Layout) tea.Cmd {
	mouse := msg.Mouse()
	alt := mouse.Mod == tea.ModAlt

	rightStart := r.width - layout.rightSidebarWidth
	adjustedX := mouse.X - rightStart

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			r.metricsGrid.clearFocus()
			if r.rightSidebar.HandleMouseClick(adjustedX, mouse.Y) {
				r.adoptChartMouseFocus()
			}
		case tea.MouseRight:
			r.metricsGrid.clearFocus()
			r.rightSidebar.StartInspection(adjustedX, mouse.Y, alt)
			r.adoptChartMouseFocus()
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
		r.adoptChartMouseFocus()
	}

	return nil
}

// handleMainContentMouse handles mouse events in the main content area.
func (r *Run) handleMainContentMouse(msg tea.MouseMsg, layout Layout) tea.Cmd {
	if r.mediaPane.IsFullscreen() {
		return nil
	}

	mouse := msg.Mouse()
	if layout.mediaHeight > 0 &&
		mouse.Y >= layout.mediaY &&
		mouse.Y < layout.mediaY+layout.mediaHeight {
		return r.handleMediaMouse(msg, layout)
	}

	alt := mouse.Mod == tea.ModAlt // Alt pressed at the time of the mouse event?

	const headerOffset = 1

	adjustedX := mouse.X - layout.leftSidebarWidth - ContentPadding
	adjustedY := mouse.Y - headerOffset
	if adjustedX < 0 || adjustedY < 0 || adjustedY >= layout.height {
		r.metricsGrid.clearFocus()
		r.rightSidebar.ClearFocus()
		return nil
	}

	dims := r.metricsGrid.CalculateChartDimensions(
		layout.mainContentAreaWidth,
		layout.height,
	)

	// Grid too small to interact with (e.g. tiny terminal).
	if dims.CellHWithPadding == 0 || dims.CellWWithPadding == 0 {
		return nil
	}

	// Chart 2D indices on the grid.
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			r.rightSidebar.ClearFocus()
			r.metricsGrid.HandleClick(row, col)
			r.adoptChartMouseFocus()
		case tea.MouseRight:
			// Holding Alt activates synchronised inspection across all charts
			// visible on the current page.
			r.metricsGrid.StartInspection(adjustedX, row, col, dims, alt)
			r.adoptChartMouseFocus()
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
		r.adoptChartMouseFocus()
	}

	return nil
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
		if cmd := r.handleGridNav(msg); cmd != nil {
			return cmd
		}
	case FocusTargetMedia:
		if handled, cmd := r.mediaPane.HandleKey(msg); handled {
			return cmd
		}
	}

	// Dispatch to key map.
	if handler, ok := r.keyMap[normalizeKey(msg.String())]; ok {
		return handler(r, msg)
	}
	return nil
}

// cleanup releases the run's data-loading resources: it stops the heartbeat
// and watcher first so they stop producing reads, then cancels any in-flight
// initialization and closes the history source.
//
// The caller must hold stateMu.
func (r *Run) cleanup() {
	if r.heartbeatMgr != nil {
		r.heartbeatMgr.Stop()
	}
	if r.watcherMgr != nil {
		r.watcherMgr.Finish()
	}
	if r.initCancel != nil {
		r.initCancel()
		r.initCancel = nil
	}
	if r.historySource != nil {
		r.historySource.Close()
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
// focus so a collapsing sidebar loses focus.
func (r *Run) handleToggleLeftSidebar(msg tea.KeyPressMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	leftWillBeVisible := !r.leftSidebar.animState.TargetVisible()

	if err := r.config.SetLeftSidebarVisible(leftWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("model: failed to save left sidebar state: %v", err))
	}

	r.updateSidebarDimensions(leftWillBeVisible, r.rightSidebar.animState.TargetVisible())
	r.leftSidebar.Toggle()

	r.focusMgr.Resolve()

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.leftSidebar.animationCmd()
}

func (r *Run) handleToggleRightSidebar(msg tea.KeyPressMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	rightWillBeVisible := !r.rightSidebar.animState.TargetVisible()

	if err := r.config.SetRightSidebarVisible(rightWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("model: failed to save right sidebar state: %v", err))
	}

	r.updateSidebarDimensions(r.leftSidebar.animState.TargetVisible(), rightWillBeVisible)
	r.rightSidebar.Toggle()
	r.focusMgr.Resolve()

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.rightSidebar.animationCmd()
}

func (r *Run) handlePrevPage(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetMetricsGrid:
		r.metricsGrid.Navigate(-1)
	case FocusTargetSystemMetrics:
		r.rightSidebar.metricsGrid.Navigate(-1)
	case FocusTargetMedia:
		r.mediaPane.NavigatePage(-1)
	case FocusTargetOverview:
		r.leftSidebar.navigatePageUp()
	case FocusTargetConsoleLogs:
		r.consoleLogsPane.PageUp()
	}
	return nil
}

func (r *Run) handleNextPage(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetMetricsGrid:
		r.metricsGrid.Navigate(1)
	case FocusTargetSystemMetrics:
		r.rightSidebar.metricsGrid.Navigate(1)
	case FocusTargetMedia:
		r.mediaPane.NavigatePage(1)
	case FocusTargetOverview:
		r.leftSidebar.navigatePageDown()
	case FocusTargetConsoleLogs:
		r.consoleLogsPane.PageDown()
	}
	return nil
}

func (r *Run) handleNavHome(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetMetricsGrid:
		r.metricsGrid.NavigateHome()
	case FocusTargetSystemMetrics:
		r.rightSidebar.metricsGrid.NavigateHome()
	case FocusTargetMedia:
		r.mediaPane.ScrubToStart()
	case FocusTargetOverview:
		r.leftSidebar.navigateHome()
	case FocusTargetConsoleLogs:
		r.consoleLogsPane.ScrollToStart()
	}
	return nil
}

func (r *Run) handleNavEnd(msg tea.KeyPressMsg) tea.Cmd {
	switch r.focusMgr.Current() {
	case FocusTargetMetricsGrid:
		r.metricsGrid.NavigateEnd()
	case FocusTargetSystemMetrics:
		r.rightSidebar.metricsGrid.NavigateEnd()
	case FocusTargetMedia:
		r.mediaPane.ScrubToEnd()
	case FocusTargetOverview:
		r.leftSidebar.navigateEnd()
	case FocusTargetConsoleLogs:
		r.consoleLogsPane.ScrollToEnd()
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

func (r *Run) handleCycleChartGuides(tea.KeyPressMsg) tea.Cmd {
	guides := nextChartGuides(r.config.ChartGuides())
	if err := r.config.SetChartGuides(guides); err != nil {
		r.logger.Error(fmt.Sprintf("runhandlers: failed to save chart guides: %v", err))
	}
	r.metricsGrid.SetChartGuides(guides)
	if r.rightSidebar != nil && r.rightSidebar.metricsGrid != nil {
		r.rightSidebar.metricsGrid.SetChartGuides(guides)
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
	if r.focusMgr.Current() == FocusTargetMetricsGrid {
		r.metricsGrid.NavigateFocus(0, 0)
	}
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
	metricsWillBeVisible := !r.metricsGridAnimState.TargetVisible()

	if err := r.config.SetMetricsGridVisible(metricsWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("runhandlers: failed to save metrics grid state: %v", err))
	}

	r.metricsGridAnimState.Toggle()
	r.focusMgr.Resolve()

	r.updateBottomPaneHeights(
		r.mediaPane.animState.TargetVisible(), r.consoleLogsPane.animState.TargetVisible())

	layout := r.computeViewports()
	r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

	return r.metricsGridAnimationCmd()
}

func (r *Run) handleMetricsGridAnimation() []tea.Cmd {
	r.metricsGridAnimState.Update(time.Now())

	r.updateBottomPaneHeights(
		r.mediaPane.animState.TargetVisible(), r.consoleLogsPane.animState.TargetVisible())
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

func (r *Run) handleGridNav(msg tea.KeyPressMsg) tea.Cmd {
	intent := DecodeNav(msg)
	if intent == NavIntentNone {
		return nil
	}

	applyFocus := func(dr, dc int) {
		switch r.focusMgr.Current() {
		case FocusTargetMetricsGrid:
			r.metricsGrid.NavigateFocus(dr, dc)
		case FocusTargetSystemMetrics:
			r.rightSidebar.metricsGrid.NavigateFocus(dr, dc)
		}
	}
	applyPage := func(dir int) {
		switch r.focusMgr.Current() {
		case FocusTargetMetricsGrid:
			r.metricsGrid.Navigate(dir)
		case FocusTargetSystemMetrics:
			r.rightSidebar.metricsGrid.Navigate(dir)
		}
	}
	applyJump := func(end bool) {
		switch r.focusMgr.Current() {
		case FocusTargetMetricsGrid:
			if end {
				r.metricsGrid.NavigateEnd()
			} else {
				r.metricsGrid.NavigateHome()
			}
		case FocusTargetSystemMetrics:
			if end {
				r.rightSidebar.metricsGrid.NavigateEnd()
			} else {
				r.rightSidebar.metricsGrid.NavigateHome()
			}
		}
	}

	switch intent {
	case NavIntentUp:
		applyFocus(-1, 0)
	case NavIntentDown:
		applyFocus(1, 0)
	case NavIntentLeft:
		applyFocus(0, -1)
	case NavIntentRight:
		applyFocus(0, 1)
	case NavIntentPageUp:
		applyPage(-1)
	case NavIntentPageDown:
		applyPage(1)
	case NavIntentHome:
		applyJump(false)
	case NavIntentEnd:
		applyJump(true)
	}
	// Return a no-op command to signal the key was consumed.
	return func() tea.Msg { return nil }
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
	if r.focusMgr.Current() == FocusTargetSystemMetrics {
		r.rightSidebar.metricsGrid.NavigateFocus(0, 0)
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
		r.rightSidebar.UpdateDimensions(
			r.width, r.leftSidebar.animState.TargetVisible(), r.layoutOverrides().RightSidebar)

	case RightSidebarAnimationMsg:
		layout := r.computeViewports()
		r.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)

		if r.rightSidebar.IsAnimating() {
			return []tea.Cmd{r.rightSidebar.animationCmd()}
		}

		r.endAnimating()
		r.leftSidebar.UpdateDimensions(
			r.width, r.rightSidebar.animState.TargetVisible(), r.layoutOverrides().LeftSidebar)
	}

	return nil
}

func (r *Run) handleToggleMediaPane(msg tea.KeyPressMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	mediaWillBeVisible := !r.mediaPane.animState.TargetVisible()

	if err := r.config.SetMediaVisible(mediaWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("runhandlers: failed to save media pane state: %v", err))
	}

	if !mediaWillBeVisible {
		r.mediaPane.ExitFullscreen()
	}

	r.mediaPane.Toggle()
	r.updateBottomPaneHeights(mediaWillBeVisible, r.consoleLogsPane.animState.TargetVisible())

	r.focusMgr.Resolve()

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

// handleToggleConsoleLogsPane toggles the console logs bottom bar and
// resolves focus so a collapsing bar loses focus.
func (r *Run) handleToggleConsoleLogsPane(msg tea.KeyPressMsg) tea.Cmd {
	if !r.beginAnimating() {
		return nil
	}

	bottomWillBeVisible := !r.consoleLogsPane.animState.TargetVisible()

	if err := r.config.SetConsoleLogsVisible(bottomWillBeVisible); err != nil {
		r.logger.Error(fmt.Sprintf("runhandlers: failed to save console logs state: %v", err))
	}

	r.consoleLogsPane.Toggle()
	r.updateBottomPaneHeights(r.mediaPane.animState.TargetVisible(), bottomWillBeVisible)
	r.focusMgr.Resolve()

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
		if cmd := r.handleRecordMsg(subMsg); cmd != nil {
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

	// Draw once per boot chunk instead of once per history record.
	cmds := r.handleRecordsBatch(msg.Msgs, true)

	if msg.HasMore {
		cmds = append(
			cmds,
			r.readChunkCmd(r.historySource, BootLoadChunkSize, BootLoadMaxTime),
		)
		return cmds
	}

	// Boot load complete -> begin live mode once. The WaitForMsg pump is
	// started alongside the watcher so it only runs while the watcher and
	// heartbeat can produce messages; WatcherManager.Finish unblocks it.
	if !r.IsRemote() && r.runState.mayBeLive() && !r.watcherMgr.IsStarted() {
		if err := r.watcherMgr.Start(r.runParams.RunFile); err != nil {
			r.logger.CaptureError(
				"leet",
				fmt.Errorf("model: error starting watcher: %v", err),
			)
		} else {
			r.logger.Info("model: watcher started successfully")
			// Seed the staleness clock from the file so a run that died
			// before LEET started is caught on the first heartbeat rather
			// than a full RunCrashTimeout later.
			if info, err := os.Stat(r.runParams.RunFile); err == nil {
				r.lastUpdateAt = info.ModTime()
			}
			r.heartbeatMgr.Start(r.isRunning)
			cmds = append(cmds, r.watcherMgr.WaitForMsg)
		}
	}
	return cmds
}

// handleBatched handles live drain batches.
func (r *Run) handleBatched(msg BatchedRecordsMsg) []tea.Cmd {
	r.logger.Debug(fmt.Sprintf("model: BatchedRecordsMsg received with %d messages", len(msg.Msgs)))
	cmds := r.handleRecordsBatch(msg.Msgs, true)
	if r.runState != RunStateRunning {
		return cmds
	}
	cmds = append(
		cmds,
		r.ReadLiveBatchCmd(r.historySource),
	)
	return cmds
}

// handleHeartbeat triggers a live read and re-arms the heartbeat.
func (r *Run) handleHeartbeat() []tea.Cmd {
	r.logger.Debug("model: processing HeartbeatMsg")
	if r.runState != RunStateRunning {
		r.heartbeatMgr.Stop()
		return nil
	}
	if r.presumedCrashed() {
		r.markPresumedCrashed()
		// Keep listening: if the writer comes back, handleFileChange
		// revives the run.
		return []tea.Cmd{r.watcherMgr.WaitForMsg}
	}
	r.heartbeatMgr.Reset(r.isRunning)
	return []tea.Cmd{
		r.ReadLiveBatchCmd(r.historySource),
		r.watcherMgr.WaitForMsg,
	}
}

// presumedCrashed reports whether a live run's transaction log has been
// silent long enough to presume the writer is gone.
func (r *Run) presumedCrashed() bool {
	return !r.lastUpdateAt.IsZero() && time.Since(r.lastUpdateAt) > RunCrashTimeout
}

// markPresumedCrashed mirrors the server's stale-runs sweep: a running run
// that stopped writing without an exit record is moved to the crashed state.
func (r *Run) markPresumedCrashed() {
	r.logger.Info(fmt.Sprintf(
		"model: no transaction log updates in %v, presuming the run crashed",
		time.Since(r.lastUpdateAt).Round(time.Second)))
	r.setRunState(RunStateCrashed)
	r.heartbeatMgr.Stop()
}

// handleFileChange coalesces change notifications into a read.
func (r *Run) handleFileChange() []tea.Cmd {
	if r.runState == RunStateCrashed {
		// The writer came back: revive the presumed-crashed run.
		r.logger.Info("model: transaction log updated, reviving crashed run")
		r.lastUpdateAt = time.Now()
		r.setRunState(RunStateRunning)
	}
	if !r.runState.mayBeLive() {
		return nil
	}
	r.heartbeatMgr.Reset(r.isRunning)
	return []tea.Cmd{
		r.ReadLiveBatchCmd(r.historySource),
		r.watcherMgr.WaitForMsg,
		r.ensureLivePulseCmd(),
	}
}

// livePulseCmd schedules the next live-indicator frame.
func (r *Run) livePulseCmd() tea.Cmd {
	return tea.Tick(LivePulseFrame, func(time.Time) tea.Msg {
		return RunLivePulseMsg{}
	})
}

// ensureLivePulseCmd starts the live-indicator redraw loop for a live run.
// Returns nil if the loop is already ticking or the run is not live.
func (r *Run) ensureLivePulseCmd() tea.Cmd {
	if r.pulseTicking || r.runState != RunStateRunning {
		return nil
	}
	r.pulseTicking = true
	return r.livePulseCmd()
}

// handleLivePulse keeps the live indicator animating while the run is live.
func (r *Run) handleLivePulse() []tea.Cmd {
	if r.runState != RunStateRunning {
		r.pulseTicking = false
		return nil
	}
	return []tea.Cmd{r.livePulseCmd()}
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
	up := DecodeNav(msg) == NavIntentUp
	switch r.focusMgr.Current() {
	case FocusTargetMedia:
		// Media pane keeps arrow-vs-letter distinction: arrows scrub by 10.
		if up {
			r.mediaPane.Scrub(-10)
		} else {
			r.mediaPane.Scrub(10)
		}
	case FocusTargetConsoleLogs:
		if up {
			r.consoleLogsPane.Up()
		} else {
			r.consoleLogsPane.Down()
		}
	case FocusTargetOverview:
		if r.leftSidebar.IsVisible() {
			if up {
				r.leftSidebar.navigateUp()
			} else {
				r.leftSidebar.navigateDown()
			}
		}
	}
	return nil
}

func (r *Run) handleSidebarPageNav(msg tea.KeyPressMsg) tea.Cmd {
	left := DecodeNav(msg) == NavIntentLeft
	switch r.focusMgr.Current() {
	case FocusTargetMedia:
		// Media pane keeps arrow-vs-letter distinction: arrows scrub by 1.
		if left {
			r.mediaPane.Scrub(-1)
		} else {
			r.mediaPane.Scrub(1)
		}
	case FocusTargetConsoleLogs:
		if left {
			r.consoleLogsPane.PageUp()
		} else {
			r.consoleLogsPane.PageDown()
		}
	case FocusTargetOverview:
		if r.leftSidebar.IsVisible() {
			if left {
				r.leftSidebar.navigatePageUp()
			} else {
				r.leftSidebar.navigatePageDown()
			}
		}
	}
	return nil
}

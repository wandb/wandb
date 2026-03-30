package leet

import (
	"fmt"
	"os"
	"time"

	tea "charm.land/bubbletea/v2"
)

// batchCmds combines zero or more commands into one, filtering nils.
func batchCmds(cmds ...tea.Cmd) tea.Cmd {
	n := 0
	for _, c := range cmds {
		if c != nil {
			cmds[n] = c
			n++
		}
	}
	switch n {
	case 0:
		return nil
	case 1:
		return cmds[0]
	default:
		return tea.Batch(cmds[:n]...)
	}
}

// ---- Key / Mouse Dispatch ----

func (w *Workspace) handleKeyPressMsg(msg tea.KeyPressMsg) tea.Cmd {
	// Filter mode takes priority.
	if w.filter.IsActive() {
		w.handleRunFilterKey(msg)
		return nil
	}
	if w.runOverviewSidebar.IsFilterMode() {
		w.runOverviewSidebar.HandleFilterKey(msg)
		return nil
	}
	if w.metricsGrid.IsFilterMode() {
		w.metricsGrid.handleFilterKey(msg)
		return nil
	}
	if g := w.activeSystemMetricsGrid(); g != nil && g.IsFilterMode() {
		g.handleFilterKey(msg)
		return nil
	}

	// Grid config capture takes priority.
	if w.config.IsAwaitingGridConfig() {
		w.metricsGrid.handleGridConfigNumberKey(msg, w.computeViewports())
		return nil
	}

	// Focus-aware key dispatch.
	switch w.focusMgr.Current() {
	case FocusTargetMetricsGrid, FocusTargetSystemMetrics:
		if cmd := w.handleGridWASD(msg); cmd != nil {
			return cmd
		}
	case FocusTargetMedia:
		if w.mediaPane.HandleKey(msg) {
			return nil
		}
	}

	// Dispatch via key map.
	if handler, ok := w.keyMap[normalizeKey(msg.String())]; ok {
		return handler(w, msg)
	}
	return nil
}

func (w *Workspace) handleMouse(msg tea.MouseMsg) tea.Cmd {
	mouse := msg.Mouse()

	// Clicks in the left sidebar clear all chart focus.
	if w.runsAnimState.IsVisible() && mouse.X < w.runsAnimState.Value() {
		w.clearChartFocus()
		return nil
	}

	// Clicks in the right sidebar clear all chart focus.
	if w.runOverviewSidebar.IsVisible() {
		if mouse.X >= w.width-w.runOverviewSidebar.Width() {
			w.clearChartFocus()
			return nil
		}
	}

	if w.mediaPane.IsFullscreen() {
		return nil
	}

	// Determine vertical region within the central column.
	reserved := w.consoleLogsPane.Height() + w.mediaPane.Height() + w.systemMetricsPane.Height()
	metricsHeight := max(w.height-StatusBarHeight-reserved, 1)

	if mouse.Y < metricsHeight {
		return w.handleMetricsMouse(msg, metricsHeight)
	}

	systemBottom := metricsHeight + w.systemMetricsPane.Height()
	mediaBottom := systemBottom + w.mediaPane.Height()

	if w.systemMetricsPane.IsVisible() && mouse.Y < systemBottom {
		return w.handleSystemMetricsMouse(msg, metricsHeight)
	}

	if w.mediaPane.IsVisible() && mouse.Y < mediaBottom {
		w.clearChartFocus()
		return nil
	}

	// Clicks in the logs pane clear all chart focus.
	if w.consoleLogsPane.IsVisible() && mouse.Y >= mediaBottom {
		w.clearChartFocus()
		return nil
	}

	// Bottom bar area — no chart interaction.
	return nil
}

func (w *Workspace) handleMetricsMouse(msg tea.MouseMsg, metricsHeight int) tea.Cmd {
	mouse := msg.Mouse()
	alt := mouse.Mod == tea.ModAlt // Alt pressed at the time of the mouse event?

	const (
		gridPaddingX = 1
		headerOffset = 1 // metrics header line
	)

	leftOffset := w.runsAnimState.Value()
	rightOffset := w.runOverviewSidebar.Width()

	adjustedX := mouse.X - leftOffset - gridPaddingX
	adjustedY := mouse.Y - headerOffset
	if adjustedX < 0 || adjustedY < 0 {
		return nil
	}

	contentWidth := max(w.width-leftOffset-rightOffset, 0)
	dims := w.metricsGrid.CalculateChartDimensions(contentWidth, metricsHeight)

	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			w.clearCurrentSystemMetricsFocus()
			w.metricsGrid.HandleClick(row, col)
		case tea.MouseRight:
			w.metricsGrid.StartInspection(adjustedX, row, col, dims, alt)
		}
	case tea.MouseMotionMsg:
		if m.Button == tea.MouseRight {
			w.metricsGrid.UpdateInspection(adjustedX, row, col, dims)
		}
	case tea.MouseReleaseMsg:
		if m.Button == tea.MouseRight {
			w.metricsGrid.EndInspection()
		}
	case tea.MouseWheelMsg:
		switch m.Button {
		case tea.MouseWheelUp:
			w.metricsGrid.HandleWheel(adjustedX, row, col, dims, true)
		case tea.MouseWheelDown:
			w.metricsGrid.HandleWheel(adjustedX, row, col, dims, false)
		}
	}

	return nil
}

func (w *Workspace) handleSystemMetricsMouse(msg tea.MouseMsg, metricsHeight int) tea.Cmd {
	mouse := msg.Mouse()
	alt := mouse.Mod == tea.ModAlt

	cur, ok := w.runs.CurrentItem()
	if !ok {
		return nil
	}
	grid := w.systemMetrics[cur.Key]
	if grid == nil {
		return nil
	}

	leftOffset := w.runsAnimState.Value()
	adjustedX := mouse.X - leftOffset - systemMetricsPaneContentPadding
	adjustedY := mouse.Y - metricsHeight - systemMetricsPaneBorderLines - systemMetricsPaneHeaderLines
	if adjustedX < 0 || adjustedY < 0 {
		return nil
	}

	dims := grid.calculateChartDimensions()
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			w.metricsGrid.clearFocus()
			grid.HandleMouseClick(row, col)
		case tea.MouseRight:
			w.metricsGrid.clearFocus()
			grid.StartInspection(adjustedX, adjustedY, row, col, dims, alt)
		}
	case tea.MouseMotionMsg:
		if m.Button == tea.MouseRight {
			grid.UpdateInspection(adjustedX, adjustedY, row, col, dims)
		}
	case tea.MouseReleaseMsg:
		if m.Button == tea.MouseRight {
			grid.EndInspection()
		}
	case tea.MouseWheelMsg:
		w.metricsGrid.clearFocus()
		switch m.Button {
		case tea.MouseWheelUp:
			grid.HandleWheel(adjustedX, row, col, dims, true)
		case tea.MouseWheelDown:
			grid.HandleWheel(adjustedX, row, col, dims, false)
		}
	}

	return nil
}

// clearChartFocus clears focus from both the main metrics grid
// and the current run's system metrics grid.
func (w *Workspace) clearChartFocus() {
	w.metricsGrid.clearFocus()
	w.clearCurrentSystemMetricsFocus()
}

// clearCurrentSystemMetricsFocus clears focus from the system metrics
// grid of the currently highlighted run (if any).
func (w *Workspace) clearCurrentSystemMetricsFocus() {
	cur, ok := w.runs.CurrentItem()
	if !ok {
		return
	}
	if grid := w.systemMetrics[cur.Key]; grid != nil {
		grid.ClearFocus()
	}
}

// ---- Animation Handlers ----

func (w *Workspace) handleRunsAnimation() tea.Cmd {
	w.runsAnimState.Update(time.Now())
	w.recalculateLayout()

	if w.runsAnimState.IsAnimating() {
		return w.runsAnimationCmd()
	}

	// Animation complete: let the other sidebar adjust to the new state.
	w.updateSidebarDimensions(w.runsAnimState.IsVisible(), w.runOverviewSidebar.IsVisible())
	return nil
}

func (w *Workspace) handleRunOverviewAnimation() tea.Cmd {
	w.runOverviewSidebar.animState.Update(time.Now())
	w.recalculateLayout()

	if w.runOverviewSidebar.IsAnimating() {
		return w.runOverviewAnimationCmd()
	}

	// Animation complete: let the other sidebar adjust to the new state.
	w.updateSidebarDimensions(w.runsAnimState.IsVisible(), w.runOverviewSidebar.IsVisible())
	return nil
}

func (w *Workspace) handleConsoleLogsPaneAnimation() tea.Cmd {
	w.consoleLogsPane.Update(time.Now())
	w.recalculateLayout()

	if w.consoleLogsPane.IsAnimating() {
		return w.consoleLogsPaneAnimationCmd()
	}
	return nil
}

func (w *Workspace) handleMediaPaneAnimation() tea.Cmd {
	w.mediaPane.Update(time.Now())
	w.recalculateLayout()

	if w.mediaPane.IsAnimating() {
		return w.mediaPaneAnimationCmd()
	}
	return nil
}

func (w *Workspace) handleSystemMetricsPaneAnimation(now time.Time) tea.Cmd {
	done := w.systemMetricsPane.Update(now)
	w.recalculateLayout()
	if done {
		return nil
	}
	return w.systemMetricsPaneAnimationCmd()
}

// ---- UI components Toggle Handlers ----

func (w *Workspace) handleToggleRunsSidebar(msg tea.KeyPressMsg) tea.Cmd {
	leftWillBeVisible := !w.runsAnimState.IsVisible()
	rightIsVisible := w.runOverviewSidebar.IsVisible()

	w.updateSidebarDimensions(leftWillBeVisible, rightIsVisible)
	w.runsAnimState.Toggle()
	w.focusMgr.ResolveAfterVisibilityChange()
	w.recalculateLayout()

	return w.runsAnimationCmd()
}

func (w *Workspace) handleToggleOverviewSidebar(msg tea.KeyPressMsg) tea.Cmd {
	rightWillBeVisible := !w.runOverviewSidebar.IsVisible()
	leftIsVisible := w.runsAnimState.IsVisible()

	if err := w.config.SetWorkspaceOverviewVisible(rightWillBeVisible); err != nil {
		w.logger.Error(fmt.Sprintf("workspace: failed to save overview state: %v", err))
	}

	w.updateSidebarDimensions(leftIsVisible, rightWillBeVisible)
	w.runOverviewSidebar.Toggle()
	w.focusMgr.ResolveAfterVisibilityChange()
	w.recalculateLayout()

	return w.runOverviewAnimationCmd()
}

func (w *Workspace) handleToggleMediaPane(msg tea.KeyPressMsg) tea.Cmd {
	mediaWillBeVisible := !w.mediaPane.IsExpanded()

	if err := w.config.SetWorkspaceMediaVisible(mediaWillBeVisible); err != nil {
		w.logger.Error(fmt.Sprintf("workspace: failed to save media pane state: %v", err))
	}

	if mediaWillBeVisible {
		w.updateBottomPaneHeights(
			w.systemMetricsPane.IsExpanded(),
			true,
			w.consoleLogsPane.IsExpanded(),
		)
		w.focusMgr.SetTarget(FocusTargetMedia, 1)
	} else {
		w.mediaPane.ExitFullscreen()
		w.updateBottomPaneHeights(
			w.systemMetricsPane.IsExpanded(),
			false,
			w.consoleLogsPane.IsExpanded(),
		)
	}

	w.mediaPane.Toggle()
	if !mediaWillBeVisible {
		w.focusMgr.ResolveAfterVisibilityChange()
	}
	w.recalculateLayout()
	return w.mediaPaneAnimationCmd()
}

func (w *Workspace) handleToggleConsoleLogsPane(msg tea.KeyPressMsg) tea.Cmd {
	bottomWillBeVisible := !w.consoleLogsPane.animState.TargetVisible()

	if err := w.config.SetWorkspaceConsoleLogsVisible(bottomWillBeVisible); err != nil {
		w.logger.Error(fmt.Sprintf("workspace: failed to save console logs state: %v", err))
	}

	w.updateBottomPaneHeights(
		w.systemMetricsPane.IsExpanded(),
		w.mediaPane.IsExpanded(),
		bottomWillBeVisible,
	)
	w.consoleLogsPane.Toggle()
	w.focusMgr.ResolveAfterVisibilityChange()
	w.recalculateLayout()

	return w.consoleLogsPaneAnimationCmd()
}

func (w *Workspace) handleToggleSystemMetricsPane(tea.KeyPressMsg) tea.Cmd {
	sysWillBeVisible := !w.systemMetricsPane.IsExpanded()
	mediaVisible := w.mediaPane.IsExpanded()
	logsVisible := w.consoleLogsPane.IsExpanded()

	if err := w.config.SetWorkspaceSystemMetricsVisible(sysWillBeVisible); err != nil {
		w.logger.Error(fmt.Sprintf("workspace: failed to save system metrics state: %v", err))
	}

	w.updateBottomPaneHeights(sysWillBeVisible, mediaVisible, logsVisible)
	w.systemMetricsPane.Toggle()
	w.recalculateLayout()
	return w.systemMetricsPaneAnimationCmd()
}

// ---- Reader / Watcher Commands ----

// initReaderCmd initializes a WandbReader for the given run asynchronously.
func (w *Workspace) initReaderCmd(runKey, runPath string) tea.Cmd {
	return func() tea.Msg {
		reader, err := NewLevelDBHistorySource(runPath, w.logger)
		if err != nil {
			return WorkspaceInitErrMsg{
				RunKey:  runKey,
				RunPath: runPath,
				Err:     err,
			}
		}
		return WorkspaceRunInitMsg{
			RunKey:  runKey,
			RunPath: runPath,
			Reader:  reader,
		}
	}
}

// readAllChunkCmd reads a bounded chunk of records for the given workspace run.
func (w *Workspace) readAllChunkCmd(run *WorkspaceRun) tea.Cmd {
	if run == nil || run.Reader == nil {
		return nil
	}

	reader := run.Reader
	runKey := run.Key

	return func() tea.Msg {
		msg, err := reader.Read(BootLoadChunkSize, BootLoadMaxTime)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		if msg == nil {
			return nil
		}
		if batch, ok := msg.(ChunkedBatchMsg); ok {
			return WorkspaceChunkedBatchMsg{
				RunKey: runKey,
				Batch:  batch,
			}
		}
		return msg
	}
}

// ReadAvailableCmd drains any new records for a live workspace run.
func (w *Workspace) ReadAvailableCmd(run *WorkspaceRun) tea.Cmd {
	if run == nil || run.Reader == nil {
		return nil
	}

	reader := run.Reader
	runKey := run.Key

	return func() tea.Msg {
		msg, err := reader.Read(LiveMonitorChunkSize, LiveMonitorMaxTime)
		if err != nil {
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

		return WorkspaceBatchedRecordsMsg{
			RunKey: runKey,
			Batch: BatchedRecordsMsg{
				Msgs: batch.Msgs,
			},
		}
	}
}

// waitForLiveMsg blocks until the next heartbeat message is available.
func (w *Workspace) waitForLiveMsg() tea.Msg {
	if w.liveChan == nil {
		return nil
	}
	return <-w.liveChan
}

// ensureLiveStreaming wires up watcher + heartbeat for a selected, running run.
//
// It is a no-op if the run is nil, not live, or its reader is not initialized.
// When a watcher is started it also returns a command that waits for the first
// change notification so that subsequent updates are driven primarily by
// filesystem events, with the heartbeat as a safety net.
func (w *Workspace) ensureLiveStreaming(run *WorkspaceRun) tea.Cmd {
	if run == nil || run.Reader == nil || run.state != RunStateRunning {
		return nil
	}

	var watcherCmd tea.Cmd

	if run.watcher == nil {
		ch := make(chan tea.Msg, 1) // coalesce notifications for this run
		run.watcher = NewWatcherManager(ch, w.logger)

		if err := run.watcher.Start(run.wandbPath); err != nil {
			w.logger.CaptureError(fmt.Errorf(
				"workspace: failed to start watcher for %s: %v", run.Key, err))
			run.watcher = nil
		} else {
			watcherCmd = w.waitForWatcher(run.Key)
		}
	}

	w.syncLiveRunState()
	if w.heartbeatMgr != nil && w.hasLiveRuns.Load() {
		w.heartbeatMgr.Start(w.hasLiveRuns.Load)
	}

	return watcherCmd
}

// waitForWatcher blocks until the watcher for the given run emits a change
// and wraps the low-level FileChangedMsg with the originating run key.
//
// The watcher lookup is performed on the calling (Update) goroutine;
// the returned Cmd only blocks on the watcher's channel.
func (w *Workspace) waitForWatcher(runKey string) tea.Cmd {
	run := w.runsByKey[runKey]
	if run == nil || run.watcher == nil {
		return nil
	}

	// Capture the watcher pointer on the main goroutine.
	// The Cmd closure must not reference w.runsByKey.
	watcher := run.watcher

	return func() tea.Msg {
		if msg := watcher.WaitForMsg(); msg != nil {
			if _, ok := msg.(FileChangedMsg); ok {
				return WorkspaceFileChangedMsg{RunKey: runKey}
			}
		}
		return nil
	}
}

// stopWatcher stops and clears the watcher associated with a run, if any.
func (w *Workspace) stopWatcher(run *WorkspaceRun) {
	if run == nil || run.watcher == nil {
		return
	}
	run.watcher.Finish()
	run.watcher = nil
}

// ---- Message Handlers ----

func (w *Workspace) handleWorkspaceInitErr(msg WorkspaceInitErrMsg) tea.Cmd {
	// Revert selection state so we don't get stuck with "selected but never loads".
	if msg.RunKey != "" {
		w.dropRun(msg.RunKey)
	}

	if msg.Err != nil && !os.IsNotExist(msg.Err) {
		w.logger.CaptureError(fmt.Errorf(
			"workspace: init reader for %s (%s): %v",
			msg.RunKey, msg.RunPath, msg.Err,
		))
	}
	return nil
}

// handleWorkspaceRunInit stores the reader and starts the initial load for the run.
func (w *Workspace) handleWorkspaceRunInit(msg WorkspaceRunInitMsg) tea.Cmd {
	if msg.Reader == nil || msg.RunKey == "" {
		return nil
	}

	if !w.selectedRuns[msg.RunKey] {
		// The run was deselected (or removed) while the reader was initializing.
		msg.Reader.Close()
		return nil
	}

	run := &WorkspaceRun{
		Key:       msg.RunKey,
		wandbPath: msg.RunPath,
		Reader:    msg.Reader,
	}
	w.runsByKey[msg.RunKey] = run

	return w.readAllChunkCmd(run)
}

// handleWorkspaceChunkedBatch processes an initial chunk of data for a run.
func (w *Workspace) handleWorkspaceChunkedBatch(msg WorkspaceChunkedBatchMsg) tea.Cmd {
	run := w.runsByKey[msg.RunKey]
	if run == nil {
		return nil
	}

	for _, sub := range msg.Batch.Msgs {
		w.handleWorkspaceRecord(run, sub)
	}
	w.metricsGrid.drawVisible()

	if msg.Batch.HasMore {
		return w.readAllChunkCmd(run)
	}

	// Initial load complete; if this run is live, wire up watcher + heartbeat.
	return w.ensureLiveStreaming(run)
}

// handleWorkspaceBatchedRecords processes incremental updates for a run.
func (w *Workspace) handleWorkspaceBatchedRecords(msg WorkspaceBatchedRecordsMsg) tea.Cmd {
	run := w.runsByKey[msg.RunKey]
	if run == nil {
		return nil
	}

	for _, sub := range msg.Batch.Msgs {
		w.handleWorkspaceRecord(run, sub)
	}
	w.metricsGrid.drawVisible()

	// Continue draining while the run is still live.
	if run.state == RunStateRunning {
		return w.ReadAvailableCmd(run)
	}

	if !w.anyRunRunning() {
		w.heartbeatMgr.Stop()
	}

	return nil
}

// handleWorkspaceRecord updates per‑run and metrics state for an individual record.
func (w *Workspace) handleWorkspaceRecord(run *WorkspaceRun, msg tea.Msg) {
	switch m := msg.(type) {
	case RunMsg:
		w.getOrCreateRunOverview(run.Key).ProcessRunMsg(m)
		w.indexRunFilterData(run.Key, m)
		if w.filter.Query() != "" {
			w.applyRunFilter()
		}
		run.state = RunStateRunning
		w.syncLiveRunState()

	case HistoryMsg:
		w.metricsGrid.ProcessHistory(m)
		w.getOrCreateMediaStore(run.Key).ProcessHistory(m)
		if w.pinnedRun != "" {
			w.refreshPinnedRun()
		}
		if w.hasLiveRuns.Load() {
			w.heartbeatMgr.Reset(w.hasLiveRuns.Load)
		}

	case StatsMsg:
		grid := w.getOrCreateSystemMetricsGrid(run.Key)
		for metricName, value := range m.Metrics {
			grid.AddDataPoint(metricName, m.Timestamp, value)
		}

	case SystemInfoMsg:
		w.getOrCreateRunOverview(run.Key).ProcessSystemInfoMsg(m.Record)

	case SummaryMsg:
		w.getOrCreateRunOverview(run.Key).ProcessSummaryMsg(m.Summary)

	case ConsoleLogMsg:
		w.getOrCreateConsoleLogs(run.Key).ProcessRaw(m.Text, m.IsStderr, m.Time)

	case FileCompleteMsg:
		switch m.ExitCode {
		case 0:
			run.state = RunStateFinished
		default:
			run.state = RunStateFailed
		}
		w.getOrCreateRunOverview(run.Key).SetRunState(run.state)
		w.syncLiveRunState()

		// No more updates expected for this run; stop its watcher.
		w.stopWatcher(run)
		if !w.anyRunRunning() {
			w.heartbeatMgr.Stop()
		}
	}
}

// handleHeartbeat is invoked when the workspace heartbeat timer fires.
func (w *Workspace) handleHeartbeat() tea.Cmd {
	if !w.anyRunRunning() {
		w.heartbeatMgr.Stop()
		return w.waitForLiveMsg
	}

	w.syncLiveRunState()
	w.heartbeatMgr.Reset(w.hasLiveRuns.Load)

	cmds := []tea.Cmd{w.waitForLiveMsg}
	for key, run := range w.runsByKey {
		if run == nil || run.state != RunStateRunning || !w.selectedRuns[key] {
			continue
		}
		cmds = append(cmds, w.ReadAvailableCmd(run))
	}
	return tea.Batch(cmds...)
}

// handleWorkspaceFileChanged reacts to a filesystem change for a given run.
func (w *Workspace) handleWorkspaceFileChanged(msg WorkspaceFileChangedMsg) tea.Cmd {
	run := w.runsByKey[msg.RunKey]
	if run == nil {
		return nil
	}

	// Re‑arm watcher for the next change if we're still watching this run.
	var watcherCmd tea.Cmd
	if run.watcher != nil {
		watcherCmd = w.waitForWatcher(msg.RunKey)
	}

	// Keep the heartbeat as a safety net when we still have live runs.
	if w.heartbeatMgr != nil && w.anyRunRunning() {
		w.syncLiveRunState()
		w.heartbeatMgr.Reset(w.hasLiveRuns.Load)
	}

	return batchCmds(w.ReadAvailableCmd(run), watcherCmd)
}

func (w *Workspace) handleQuit(msg tea.KeyPressMsg) tea.Cmd {
	w.logger.Debug("workspace: quit requested")

	if w.heartbeatMgr != nil {
		w.heartbeatMgr.Stop()
	}
	for _, run := range w.runsByKey {
		if run == nil {
			continue
		}
		w.stopWatcher(run)
		if run.Reader != nil {
			run.Reader.Close()
		}
	}

	return tea.Quit
}

// ---- Navigation Handlers ----

func (w *Workspace) handlePrevPage(msg tea.KeyPressMsg) tea.Cmd {
	switch w.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		if g := w.activeSystemMetricsGrid(); g != nil {
			g.Navigate(-1)
		}
	case FocusTargetMedia:
		w.mediaPane.NavigatePage(-1)
	default:
		w.metricsGrid.Navigate(-1)
	}
	return nil
}

func (w *Workspace) handleNextPage(msg tea.KeyPressMsg) tea.Cmd {
	switch w.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		if g := w.activeSystemMetricsGrid(); g != nil {
			g.Navigate(1)
		}
	case FocusTargetMedia:
		w.mediaPane.NavigatePage(1)
	default:
		w.metricsGrid.Navigate(1)
	}
	return nil
}

func (w *Workspace) handleCycleFocusedChartMode(tea.KeyPressMsg) tea.Cmd {
	switch w.focus.Type {
	case FocusMainChart:
		w.metricsGrid.toggleFocusedChartLogY()
	case FocusSystemChart:
		if g := w.activeSystemMetricsGrid(); g != nil {
			g.cycleFocusedChartMode()
		}
	}
	return nil
}

func (w *Workspace) handleEnterMetricsFilter(msg tea.KeyPressMsg) tea.Cmd {
	w.metricsGrid.EnterFilterMode()
	return nil
}

func (w *Workspace) handleEnterSystemMetricsFilter(msg tea.KeyPressMsg) tea.Cmd {
	var cmds []tea.Cmd
	if !w.systemMetricsPane.IsExpanded() && !w.systemMetricsPane.IsAnimating() {
		cmds = append(cmds, w.handleToggleSystemMetricsPane(msg))
	}

	cur, ok := w.runs.CurrentItem()
	if !ok {
		return batchCmds(cmds...)
	}
	if _, selected := w.selectedRuns[cur.Key]; !selected {
		return batchCmds(cmds...)
	}

	grid := w.getOrCreateSystemMetricsGrid(cur.Key)
	grid.EnterFilterMode()
	grid.ApplyFilter()
	return batchCmds(cmds...)
}

func (w *Workspace) handleClearMetricsFilter(msg tea.KeyPressMsg) tea.Cmd {
	if w.metricsGrid.FilterQuery() != "" {
		w.metricsGrid.ClearFilter()
	}
	if w.focus != nil {
		w.focus.Reset()
	}
	return nil
}

func (w *Workspace) handleClearSystemMetricsFilter(tea.KeyPressMsg) tea.Cmd {
	if g := w.activeSystemMetricsGrid(); g != nil && g.FilterQuery() != "" {
		g.ClearFilter()
	}
	if w.focus != nil && w.focus.Type == FocusSystemChart {
		w.focus.Reset()
	}
	return nil
}

func (w *Workspace) handleEnterOverviewFilter(tea.KeyPressMsg) tea.Cmd {
	w.runOverviewSidebar.EnterFilterMode()
	return nil
}

func (w *Workspace) handleClearOverviewFilter(tea.KeyPressMsg) tea.Cmd {
	if w.runOverviewSidebar.IsFiltering() {
		w.runOverviewSidebar.ClearFilter()
	}
	return nil
}

func (w *Workspace) handleToggleMetricsGrid(msg tea.KeyPressMsg) tea.Cmd {
	metricsWillBeVisible := !w.metricsGridAnimState.IsExpanded()

	if err := w.config.SetWorkspaceMetricsGridVisible(metricsWillBeVisible); err != nil {
		w.logger.Error(fmt.Sprintf("workspace: failed to save metrics grid state: %v", err))
	}

	w.metricsGridAnimState.Toggle()
	w.focusMgr.ResolveAfterVisibilityChange()

	w.updateBottomPaneHeights(
		w.systemMetricsPane.IsExpanded(),
		w.mediaPane.IsExpanded(),
		w.consoleLogsPane.IsExpanded(),
	)
	w.recalculateLayout()
	return w.metricsGridAnimationCmd()
}

func (w *Workspace) handleMetricsGridAnimation() tea.Cmd {
	w.metricsGridAnimState.Update(time.Now())
	w.updateBottomPaneHeights(
		w.systemMetricsPane.IsExpanded(),
		w.mediaPane.IsExpanded(),
		w.consoleLogsPane.IsExpanded(),
	)
	w.recalculateLayout()
	if w.metricsGridAnimState.IsAnimating() {
		return w.metricsGridAnimationCmd()
	}
	return nil
}

func (w *Workspace) handleGridWASD(msg tea.KeyPressMsg) tea.Cmd {
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

	switch {
	case w.focusMgr.IsTarget(FocusTargetMetricsGrid):
		w.metricsGrid.NavigateFocus(dr, dc)
	case w.focusMgr.IsTarget(FocusTargetSystemMetrics):
		if g := w.activeSystemMetricsGrid(); g != nil {
			g.NavigateFocus(dr, dc)
		}
	}
	return func() tea.Msg { return nil }
}

func (w *Workspace) handleConfigMetricsCols(msg tea.KeyPressMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceMetricsCols)
	return nil
}

func (w *Workspace) handleConfigMetricsRows(msg tea.KeyPressMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceMetricsRows)
	return nil
}

func (w *Workspace) handleConfigMediaCols(msg tea.KeyPressMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceMediaCols)
	return nil
}

func (w *Workspace) handleConfigMediaRows(msg tea.KeyPressMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceMediaRows)
	return nil
}

func (w *Workspace) handleConfigFocusedCols(msg tea.KeyPressMsg) tea.Cmd {
	switch w.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		w.config.SetPendingGridConfig(gridConfigWorkspaceSystemCols)
	case FocusTargetMedia:
		w.config.SetPendingGridConfig(gridConfigWorkspaceMediaCols)
	default:
		w.config.SetPendingGridConfig(gridConfigWorkspaceMetricsCols)
	}
	return nil
}

func (w *Workspace) handleConfigFocusedRows(msg tea.KeyPressMsg) tea.Cmd {
	switch w.focusMgr.Current() {
	case FocusTargetSystemMetrics:
		w.config.SetPendingGridConfig(gridConfigWorkspaceSystemRows)
	case FocusTargetMedia:
		w.config.SetPendingGridConfig(gridConfigWorkspaceMediaRows)
	default:
		w.config.SetPendingGridConfig(gridConfigWorkspaceMetricsRows)
	}
	return nil
}

// ---- Run Selection / Pinning ----

func (w *Workspace) toggleRunSelected(runKey string) tea.Cmd {
	if runKey == "" {
		return nil
	}

	if _, selected := w.selectedRuns[runKey]; selected {
		w.dropRun(runKey)
		return nil
	}

	// Resolve the run file before mutating selection state so we don't end up
	// "selected but unloadable" if the key can't be mapped to a .wandb file.
	wandbFile := runWandbFile(w.wandbDir, runKey)
	if wandbFile == "" {
		err := fmt.Errorf("workspace: unable to resolve .wandb file for run key %q", runKey)
		w.logger.CaptureError(err)
		return nil
	}

	w.selectedRuns[runKey] = true
	if w.pinnedRun == "" {
		w.pinnedRun = runKey
	}

	return w.initReaderCmd(runKey, wandbFile)
}

func (w *Workspace) handleToggleRunSelectedKey(msg tea.KeyPressMsg) tea.Cmd {
	if !w.runSelectorActive() {
		return nil
	}
	cur, ok := w.runs.CurrentItem()
	if !ok {
		return nil
	}
	return w.toggleRunSelected(cur.Key)
}

func (w *Workspace) togglePin(runKey string) {
	if runKey == "" {
		return
	}

	if w.pinnedRun == runKey {
		// Unpin but keep selection unchanged.
		w.pinnedRun = ""
		w.metricsGrid.drawVisible()
		return
	}

	w.pinnedRun = runKey
	w.refreshPinnedRun()
	w.metricsGrid.drawVisible()
}

func (w *Workspace) handlePinRunKey(msg tea.KeyPressMsg) tea.Cmd {
	if !w.runSelectorActive() {
		return nil
	}
	cur, ok := w.runs.CurrentItem()
	if !ok {
		return nil
	}

	runKey := cur.Key

	// Preserve existing behavior: pinning should select the run if it's not selected,
	// so its series exists and can be promoted/drawn.
	if !w.selectedRuns[runKey] {
		cmd := w.toggleRunSelected(runKey)
		if cmd == nil {
			return nil
		}
		// toggleRunSelected may auto-pin when pinnedRun was empty.
		// Only toggle if we still need to pin.
		if w.pinnedRun != runKey {
			w.togglePin(runKey)
		}
		return cmd
	}

	w.togglePin(runKey)
	return nil
}

// ---- Sidebar Navigation ----

func (w *Workspace) handleRunsVerticalNav(msg tea.KeyPressMsg) tea.Cmd {
	switch {
	case w.focusMgr.IsTarget(FocusTargetConsoleLogs):
		switch msg.String() {
		case "up":
			w.consoleLogsPane.Up()
		case "down":
			w.consoleLogsPane.Down()
		}
	case w.focusMgr.IsTarget(FocusTargetRunsList):
		switch msg.String() {
		case "up":
			w.runs.Up()
		case "down":
			w.runs.Down()
		}
	case w.focusMgr.IsTarget(FocusTargetOverview):
		switch msg.String() {
		case "up":
			w.runOverviewSidebar.navigateUp()
		case "down":
			w.runOverviewSidebar.navigateDown()
		}
	}
	return nil
}

// ---- Focus Region Cycling ----

func (w *Workspace) handleSidebarTabNav(msg tea.KeyPressMsg) tea.Cmd {
	direction := 1
	if msg.Code == tea.KeyTab && msg.Mod == tea.ModShift {
		direction = -1
	}
	withinFn := func(dir int) bool {
		if w.focusMgr.IsTarget(FocusTargetOverview) {
			return w.cycleOverviewSection(dir)
		}
		return false
	}
	w.focusMgr.TabWithinOrAdvance(direction, withinFn)
	return nil
}

func (w *Workspace) handleRunsPageNav(msg tea.KeyPressMsg) tea.Cmd {
	switch {
	case w.focusMgr.IsTarget(FocusTargetConsoleLogs):
		switch msg.String() {
		case "left":
			w.consoleLogsPane.PageUp()
		case "right":
			w.consoleLogsPane.PageDown()
		}
	case w.focusMgr.IsTarget(FocusTargetRunsList):
		switch msg.String() {
		case "left":
			w.runs.PageUp()
		case "right":
			w.runs.PageDown()
		}
	case w.focusMgr.IsTarget(FocusTargetOverview):
		switch msg.String() {
		case "left":
			w.runOverviewSidebar.navigatePageUp()
		case "right":
			w.runOverviewSidebar.navigatePageDown()
		}
	}
	return nil
}

func (w *Workspace) handleRunsHome(msg tea.KeyPressMsg) tea.Cmd {
	if !w.runSelectorActive() {
		return nil
	}
	w.runs.Home()
	return nil
}

func (w *Workspace) activeSystemMetricsGrid() *SystemMetricsGrid {
	cur, ok := w.runs.CurrentItem()
	if !ok {
		return nil
	}
	return w.systemMetrics[cur.Key]
}

func (w *Workspace) handlePrevSystemMetricsPage(tea.KeyPressMsg) tea.Cmd {
	if g := w.activeSystemMetricsGrid(); g != nil {
		g.Navigate(-1)
	}
	return nil
}

func (w *Workspace) handleNextSystemMetricsPage(tea.KeyPressMsg) tea.Cmd {
	if g := w.activeSystemMetricsGrid(); g != nil {
		g.Navigate(1)
	}
	return nil
}

func (w *Workspace) handleConfigSystemCols(tea.KeyPressMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceSystemCols)
	return nil
}

func (w *Workspace) handleConfigSystemRows(tea.KeyPressMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceSystemRows)
	return nil
}

// handleFocusRuns moves focus to the runs list if it's visible.
//
// This gives Esc a natural "return home" feel in workspace mode:
// wherever focus currently is, Esc snaps it back to the run selector.
func (w *Workspace) handleFocusRuns(tea.KeyPressMsg) tea.Cmd {
	if w.runsAnimState.TargetVisible() {
		w.focusMgr.SetTarget(FocusTargetRunsList, 1)
	}
	return nil
}

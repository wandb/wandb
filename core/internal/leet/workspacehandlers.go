package leet

import (
	"fmt"
	"os"
	"time"

	tea "github.com/charmbracelet/bubbletea"
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

func (w *Workspace) handleKeyMsg(msg tea.KeyMsg) tea.Cmd {
	// Filter mode takes priority.
	if w.runOverviewSidebar.IsFilterMode() {
		return w.handleOverviewFilter(msg)
	}
	if w.metricsGrid.IsFilterMode() {
		w.metricsGrid.handleMetricsFilterKey(msg)
		return nil
	}

	// Grid config capture takes priority.
	if w.config.IsAwaitingGridConfig() {
		w.metricsGrid.handleGridConfigNumberKey(msg, w.computeViewports())
		return nil
	}

	// Dispatch via key map.
	if handler, ok := w.keyMap[normalizeKey(msg.String())]; ok {
		return handler(w, msg)
	}
	return nil
}

func (w *Workspace) handleMouse(msg tea.MouseMsg) tea.Cmd {
	// Clicks in the left sidebar clear all chart focus.
	if w.runsAnimState.IsVisible() && msg.X < w.runsAnimState.Value() {
		w.clearChartFocus()
		return nil
	}

	// Clicks in the right sidebar clear all chart focus.
	if w.runOverviewSidebar.IsVisible() {
		if msg.X >= w.width-w.runOverviewSidebar.Width() {
			w.clearChartFocus()
			return nil
		}
	}

	// Determine vertical region within the central column.
	reserved := w.consoleLogsPane.Height() + w.systemMetricsPane.Height()
	metricsHeight := max(w.height-StatusBarHeight-reserved, 1)

	if msg.Y < metricsHeight {
		return w.handleMetricsMouse(msg, metricsHeight)
	}

	if w.systemMetricsPane.IsVisible() &&
		msg.Y < metricsHeight+w.systemMetricsPane.Height() {
		return w.handleSystemMetricsMouse(msg, metricsHeight)
	}

	// Clicks in the logs pane clear all chart focus.
	if w.consoleLogsPane.IsVisible() && msg.Y >= metricsHeight+w.systemMetricsPane.Height() {
		w.clearChartFocus()
		return nil
	}

	// Bottom bar area — no chart interaction.
	return nil
}

func (w *Workspace) handleMetricsMouse(msg tea.MouseMsg, metricsHeight int) tea.Cmd {
	const (
		gridPaddingX = 1
		headerOffset = 1 // metrics header line
	)

	leftOffset := w.runsAnimState.Value()
	rightOffset := w.runOverviewSidebar.Width()

	adjustedX := msg.X - leftOffset - gridPaddingX
	adjustedY := msg.Y - headerOffset
	if adjustedX < 0 || adjustedY < 0 {
		return nil
	}

	contentWidth := max(w.width-leftOffset-rightOffset, 0)
	dims := w.metricsGrid.CalculateChartDimensions(contentWidth, metricsHeight)

	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	me := tea.MouseEvent(msg)

	switch me.Button {
	case tea.MouseButtonLeft:
		if me.Action == tea.MouseActionPress {
			w.clearCurrentSystemMetricsFocus()
			w.metricsGrid.HandleClick(row, col)
		}
	case tea.MouseButtonRight:
		alt := me.Alt
		switch me.Action {
		case tea.MouseActionPress:
			w.metricsGrid.StartInspection(adjustedX, row, col, dims, alt)
		case tea.MouseActionRelease:
			w.metricsGrid.EndInspection()
		case tea.MouseActionMotion:
			w.metricsGrid.UpdateInspection(adjustedX, row, col, dims)
		}
	case tea.MouseButtonWheelUp:
		w.metricsGrid.HandleWheel(adjustedX, row, col, dims, true)
	case tea.MouseButtonWheelDown:
		w.metricsGrid.HandleWheel(adjustedX, row, col, dims, false)
	}

	return nil
}

func (w *Workspace) handleSystemMetricsMouse(msg tea.MouseMsg, metricsHeight int) tea.Cmd {
	me := tea.MouseEvent(msg)
	if me.Button != tea.MouseButtonLeft || me.Action != tea.MouseActionPress {
		return nil
	}

	cur, ok := w.runs.CurrentItem()
	if !ok {
		return nil
	}
	grid := w.systemMetrics[cur.Key]
	if grid == nil {
		return nil
	}

	leftOffset := w.runsAnimState.Value()
	adjustedX := msg.X - leftOffset - systemMetricsPaneContentPadding
	adjustedY := msg.Y - metricsHeight - systemMetricsPaneBorderLines - systemMetricsPaneHeaderLines
	if adjustedX < 0 || adjustedY < 0 {
		return nil
	}

	dims := grid.calculateChartDimensions()
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	w.metricsGrid.clearFocus()
	grid.HandleMouseClick(row, col)

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

func (w *Workspace) handleSystemMetricsPaneAnimation(now time.Time) tea.Cmd {
	done := w.systemMetricsPane.Update(now)
	w.recalculateLayout()
	if done {
		return nil
	}
	return w.systemMetricsPaneAnimationCmd()
}

// ---- UI components Toggle Handlers ----

func (w *Workspace) handleToggleRunsSidebar(msg tea.KeyMsg) tea.Cmd {
	leftWillBeVisible := !w.runsAnimState.IsVisible()
	rightIsVisible := w.runOverviewSidebar.IsVisible()

	w.resolveFocusAfterVisibilityChange(
		leftWillBeVisible, rightIsVisible, w.consoleLogsPane.IsExpanded())
	w.updateSidebarDimensions(leftWillBeVisible, rightIsVisible)
	w.runsAnimState.Toggle()
	w.recalculateLayout()

	return w.runsAnimationCmd()
}

func (w *Workspace) handleToggleOverviewSidebar(msg tea.KeyMsg) tea.Cmd {
	rightWillBeVisible := !w.runOverviewSidebar.IsVisible()
	leftIsVisible := w.runsAnimState.IsVisible()

	w.resolveFocusAfterVisibilityChange(
		leftIsVisible, rightWillBeVisible, w.consoleLogsPane.IsExpanded())
	w.updateSidebarDimensions(leftIsVisible, rightWillBeVisible)
	w.runOverviewSidebar.Toggle()
	w.recalculateLayout()

	return w.runOverviewAnimationCmd()
}

func (w *Workspace) handleToggleConsoleLogsPane(msg tea.KeyMsg) tea.Cmd {
	bottomWillBeVisible := !w.consoleLogsPane.IsExpanded()

	w.resolveFocusAfterVisibilityChange(
		w.runsAnimState.IsExpanded(), w.runOverviewSidebar.IsExpanded(), bottomWillBeVisible)
	w.updateMiddlePaneHeights(w.systemMetricsPane.IsExpanded(), bottomWillBeVisible)
	w.consoleLogsPane.Toggle()
	w.recalculateLayout()

	return w.consoleLogsPaneAnimationCmd()
}

// ---- Reader / Watcher Commands ----

// initReaderCmd initializes a WandbReader for the given run asynchronously.
func (w *Workspace) initReaderCmd(runKey, runPath string) tea.Cmd {
	return func() tea.Msg {
		reader, err := NewWandbReader(runPath, w.logger)
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
func (w *Workspace) readAllChunkCmd(run *workspaceRun) tea.Cmd {
	if run == nil || run.reader == nil {
		return nil
	}

	return func() tea.Msg {
		msg := run.reader.ReadAllRecordsChunked()
		if msg == nil {
			return nil
		}
		if batch, ok := msg.(ChunkedBatchMsg); ok {
			return WorkspaceChunkedBatchMsg{
				RunKey: run.key,
				Batch:  batch,
			}
		}
		return msg
	}
}

// readAvailableCmd drains any new records for a live workspace run.
func (w *Workspace) readAvailableCmd(run *workspaceRun) tea.Cmd {
	if run == nil || run.reader == nil {
		return nil
	}

	return func() tea.Msg {
		msg := run.reader.ReadAvailableRecords()
		if msg == nil {
			return nil
		}
		if batch, ok := msg.(BatchedRecordsMsg); ok {
			return WorkspaceBatchedRecordsMsg{
				RunKey: run.key,
				Batch:  batch,
			}
		}
		return msg
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
func (w *Workspace) ensureLiveStreaming(run *workspaceRun) tea.Cmd {
	if run == nil || run.reader == nil || run.state != RunStateRunning {
		return nil
	}

	var watcherCmd tea.Cmd

	if run.watcher == nil {
		ch := make(chan tea.Msg, 1) // coalesce notifications for this run
		run.watcher = NewWatcherManager(ch, w.logger)

		if err := run.watcher.Start(run.wandbPath); err != nil {
			w.logger.CaptureError(fmt.Errorf(
				"workspace: failed to start watcher for %s: %v", run.key, err))
			run.watcher = nil
		} else {
			watcherCmd = w.waitForWatcher(run.key)
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
func (w *Workspace) stopWatcher(run *workspaceRun) {
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

	run := &workspaceRun{
		key:       msg.RunKey,
		wandbPath: msg.RunPath,
		reader:    msg.Reader,
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
		return w.readAvailableCmd(run)
	}

	if !w.anyRunRunning() {
		w.heartbeatMgr.Stop()
	}

	return nil
}

// handleWorkspaceRecord updates per‑run and metrics state for an individual record.
func (w *Workspace) handleWorkspaceRecord(run *workspaceRun, msg tea.Msg) {
	switch m := msg.(type) {
	case RunMsg:
		w.getOrCreateRunOverview(run.key).ProcessRunMsg(m)
		run.state = RunStateRunning
		w.syncLiveRunState()

	case HistoryMsg:
		w.metricsGrid.ProcessHistory(m)
		if w.pinnedRun != "" {
			w.refreshPinnedRun()
		}
		if w.hasLiveRuns.Load() {
			w.heartbeatMgr.Reset(w.hasLiveRuns.Load)
		}

	case StatsMsg:
		grid := w.getOrCreateSystemMetricsGrid(run.key)
		for metricName, value := range m.Metrics {
			grid.AddDataPoint(metricName, m.Timestamp, value)
		}

	case SystemInfoMsg:
		w.getOrCreateRunOverview(run.key).ProcessSystemInfoMsg(m.Record)

	case SummaryMsg:
		w.getOrCreateRunOverview(run.key).ProcessSummaryMsg(m.Summary)

	case ConsoleLogMsg:
		w.getOrCreateConsoleLogs(run.key).ProcessRaw(m.Text, m.IsStderr, m.Time)

	case FileCompleteMsg:
		switch m.ExitCode {
		case 0:
			run.state = RunStateFinished
		default:
			run.state = RunStateFailed
		}
		w.getOrCreateRunOverview(run.key).SetRunState(run.state)
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
		cmds = append(cmds, w.readAvailableCmd(run))
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

	return batchCmds(w.readAvailableCmd(run), watcherCmd)
}

func (w *Workspace) handleQuit(msg tea.KeyMsg) tea.Cmd {
	w.logger.Debug("workspace: quit requested")

	if w.heartbeatMgr != nil {
		w.heartbeatMgr.Stop()
	}
	for _, run := range w.runsByKey {
		if run == nil {
			continue
		}
		w.stopWatcher(run)
		if run.reader != nil {
			run.reader.Close()
		}
	}

	return tea.Quit
}

// ---- Navigation Handlers ----

func (w *Workspace) handlePrevPage(msg tea.KeyMsg) tea.Cmd {
	w.metricsGrid.Navigate(-1)
	return nil
}

func (w *Workspace) handleNextPage(msg tea.KeyMsg) tea.Cmd {
	w.metricsGrid.Navigate(1)
	return nil
}

func (w *Workspace) handleEnterMetricsFilter(msg tea.KeyMsg) tea.Cmd {
	w.metricsGrid.EnterFilterMode()
	return nil
}

func (w *Workspace) handleClearMetricsFilter(msg tea.KeyMsg) tea.Cmd {
	if w.metricsGrid.FilterQuery() != "" {
		w.metricsGrid.ClearFilter()
	}
	if w.focus != nil {
		w.focus.Reset()
	}
	return nil
}

func (w *Workspace) handleEnterOverviewFilter(tea.KeyMsg) tea.Cmd {
	w.runOverviewSidebar.EnterFilterMode()
	return nil
}

func (w *Workspace) handleClearOverviewFilter(tea.KeyMsg) tea.Cmd {
	if w.runOverviewSidebar.IsFiltering() {
		w.runOverviewSidebar.ClearFilter()
	}
	return nil
}

// handleOverviewFilter handles overview filter keyboard input.
func (w *Workspace) handleOverviewFilter(msg tea.KeyMsg) tea.Cmd {
	switch msg.Type {
	case tea.KeyEsc:
		w.runOverviewSidebar.ExitFilterMode(false)
	case tea.KeyEnter:
		w.runOverviewSidebar.ExitFilterMode(true)
	case tea.KeyTab:
		w.runOverviewSidebar.ToggleFilterMatchMode()
	case tea.KeyBackspace, tea.KeySpace, tea.KeyRunes:
		w.runOverviewSidebar.UpdateFilterDraft(msg)
		w.runOverviewSidebar.ApplyFilter()
		w.runOverviewSidebar.updateSectionHeights()
	}
	return nil
}

func (w *Workspace) handleConfigMetricsCols(msg tea.KeyMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceMetricsCols)
	return nil
}

func (w *Workspace) handleConfigMetricsRows(msg tea.KeyMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceMetricsRows)
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

func (w *Workspace) handleToggleRunSelectedKey(msg tea.KeyMsg) tea.Cmd {
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

func (w *Workspace) handlePinRunKey(msg tea.KeyMsg) tea.Cmd {
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

func (w *Workspace) handleRunsVerticalNav(msg tea.KeyMsg) tea.Cmd {
	switch {
	case w.consoleLogsPane.Active():
		switch msg.String() {
		case "up":
			w.consoleLogsPane.Up()
		case "down":
			w.consoleLogsPane.Down()
		}
	case w.runSelectorActive():
		switch msg.String() {
		case "up":
			w.runs.Up()
		case "down":
			w.runs.Down()
		}
	case w.runOverviewActive():
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

// focusRegion identifies a focusable UI region in the workspace.
type focusRegion int

const (
	focusRuns focusRegion = iota
	focusLogs
	focusOverview
)

// focusOrder defines the Tab-cycling order across workspace regions.
var focusOrder = []focusRegion{focusRuns, focusLogs, focusOverview}

func (w *Workspace) handleSidebarTabNav(msg tea.KeyMsg) tea.Cmd {
	direction := 1
	if msg.Type == tea.KeyShiftTab {
		direction = -1
	}

	cur := w.currentFocusRegion()

	// Try cycling within overview sections before leaving the region.
	if cur == focusOverview && w.cycleOverviewSection(direction) {
		return nil
	}

	w.cycleFocusRegion(cur, direction)
	return nil
}

// currentFocusRegion returns which focusable region currently holds focus.
func (w *Workspace) currentFocusRegion() focusRegion {
	switch {
	case w.consoleLogsPane.Active():
		return focusLogs
	case w.runs.Active:
		return focusRuns
	default:
		return focusOverview
	}
}

// cycleOverviewSection tries to move within overview sections.
//
// Returns true if the navigation was handled (i.e. we're not at a boundary).
func (w *Workspace) cycleOverviewSection(direction int) bool {
	firstSec, lastSec := w.runOverviewSidebar.focusableSectionBounds()
	if !w.runOverviewSidebar.animState.IsExpanded() || firstSec == -1 {
		return false
	}

	atBoundary := (direction == 1 && w.runOverviewSidebar.activeSection == lastSec) ||
		(direction == -1 && w.runOverviewSidebar.activeSection == firstSec)
	if atBoundary {
		return false
	}

	w.runOverviewSidebar.navigateSection(direction)
	return true
}

// cycleFocusRegion moves focus to the next available region in the given direction.
func (w *Workspace) cycleFocusRegion(cur focusRegion, direction int) {
	avail := w.regionAvailability()

	curIdx := 0
	for i, v := range focusOrder {
		if v == cur {
			curIdx = i
			break
		}
	}

	n := len(focusOrder)
	for step := 1; step <= n; step++ {
		nextIdx := ((curIdx+direction*step)%n + n) % n
		next := focusOrder[nextIdx]
		if avail[next] {
			w.setFocusRegion(next, direction)
			return
		}
	}
}

// regionAvailability returns which focus regions are currently usable.
func (w *Workspace) regionAvailability() map[focusRegion]bool {
	firstSec, _ := w.runOverviewSidebar.focusableSectionBounds()
	return map[focusRegion]bool{
		focusRuns:     w.runsAnimState.IsExpanded(),
		focusLogs:     w.consoleLogsPane.IsExpanded(),
		focusOverview: w.runOverviewSidebar.animState.IsExpanded() && firstSec != -1,
	}
}

// setFocusRegion clears all focus and activates the given region.
func (w *Workspace) setFocusRegion(region focusRegion, direction int) {
	w.runs.Active = false
	w.consoleLogsPane.SetActive(false)
	w.runOverviewSidebar.deactivateAllSections()

	switch region {
	case focusRuns:
		w.runs.Active = true
	case focusLogs:
		w.consoleLogsPane.SetActive(true)
	case focusOverview:
		firstSec, lastSec := w.runOverviewSidebar.focusableSectionBounds()
		if direction == 1 {
			w.runOverviewSidebar.setActiveSection(firstSec)
		} else {
			w.runOverviewSidebar.setActiveSection(lastSec)
		}
	}
}

func (w *Workspace) handleRunsPageNav(msg tea.KeyMsg) tea.Cmd {
	switch {
	case w.consoleLogsPane.Active():
		switch msg.String() {
		case "left":
			w.consoleLogsPane.PageUp()
		case "right":
			w.consoleLogsPane.PageDown()
		}
	case w.runSelectorActive():
		switch msg.String() {
		case "left":
			w.runs.PageUp()
		case "right":
			w.runs.PageDown()
		}
	case w.runOverviewActive():
		switch msg.String() {
		case "left":
			w.runOverviewSidebar.navigatePageUp()
		case "right":
			w.runOverviewSidebar.navigatePageDown()
		}
	}
	return nil
}

func (w *Workspace) handleRunsHome(msg tea.KeyMsg) tea.Cmd {
	if !w.runSelectorActive() {
		return nil
	}
	w.runs.Home()
	return nil
}

func (w *Workspace) handleToggleSystemMetricsPane(tea.KeyMsg) tea.Cmd {
	sysWillBeVisible := !w.systemMetricsPane.IsExpanded()
	logsVisible := w.consoleLogsPane.IsExpanded()

	w.updateMiddlePaneHeights(sysWillBeVisible, logsVisible)
	w.systemMetricsPane.Toggle()
	w.recalculateLayout()
	return w.systemMetricsPaneAnimationCmd()
}

func (w *Workspace) activeSystemMetricsGrid() *SystemMetricsGrid {
	cur, ok := w.runs.CurrentItem()
	if !ok {
		return nil
	}
	return w.systemMetrics[cur.Key]
}

func (w *Workspace) handlePrevSystemMetricsPage(tea.KeyMsg) tea.Cmd {
	if g := w.activeSystemMetricsGrid(); g != nil {
		g.Navigate(-1)
	}
	return nil
}

func (w *Workspace) handleNextSystemMetricsPage(tea.KeyMsg) tea.Cmd {
	if g := w.activeSystemMetricsGrid(); g != nil {
		g.Navigate(1)
	}
	return nil
}

func (w *Workspace) handleConfigSystemCols(tea.KeyMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceSystemCols)
	return nil
}

func (w *Workspace) handleConfigSystemRows(tea.KeyMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigWorkspaceSystemRows)
	return nil
}

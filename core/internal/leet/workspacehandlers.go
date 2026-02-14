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
	// Clicks in the left sidebar clear metrics focus.
	if w.runsAnimState.IsVisible() && msg.X < w.runsAnimState.Width() {
		w.metricsGrid.clearFocus()
		return nil
	}

	// Clicks in the right sidebar clear metrics focus.
	if w.runOverviewSidebar.IsVisible() {
		if msg.X >= w.width-w.runOverviewSidebar.Width() {
			w.metricsGrid.clearFocus()
			return nil
		}
	}

	return w.handleMetricsMouse(msg)
}

func (w *Workspace) handleMetricsMouse(msg tea.MouseMsg) tea.Cmd {
	const (
		gridPaddingX = 1
		gridPaddingY = 1
		headerOffset = 1 // metrics header lines
	)

	leftOffset := w.runsAnimState.Width()
	rightOffset := w.runOverviewSidebar.Width()

	adjustedX := msg.X - leftOffset - gridPaddingX
	adjustedY := msg.Y - gridPaddingY - headerOffset
	if adjustedX < 0 || adjustedY < 0 {
		return nil
	}

	contentWidth := max(w.width-leftOffset-rightOffset, 0)
	contentHeight := max(w.height-StatusBarHeight-w.bottomBar.Height(), 0)
	dims := w.metricsGrid.CalculateChartDimensions(contentWidth, contentHeight)

	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	me := tea.MouseEvent(msg)

	switch me.Button {
	case tea.MouseButtonLeft:
		if me.Action == tea.MouseActionPress {
			w.metricsGrid.HandleClick(row, col)
		}
	case tea.MouseButtonRight:
		// Holding Alt activates synchronised inspection across all charts
		// visible on the current page.
		alt := tea.MouseEvent(msg).Alt

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

func (w *Workspace) handleBottomBarAnimation() tea.Cmd {
	w.bottomBar.Update(time.Now())
	w.recalculateLayout()

	if w.bottomBar.IsAnimating() {
		return w.bottomBarAnimationCmd()
	}
	return nil
}

// ---- UI components Toggle Handlers ----

func (w *Workspace) handleToggleRunsSidebar(msg tea.KeyMsg) tea.Cmd {
	leftWillBeVisible := !w.runsAnimState.IsVisible()
	rightIsVisible := w.runOverviewSidebar.IsVisible()

	w.resolveSidebarFocus(leftWillBeVisible, rightIsVisible)
	w.updateSidebarDimensions(leftWillBeVisible, rightIsVisible)
	w.runsAnimState.Toggle()
	w.recalculateLayout()

	return w.runsAnimationCmd()
}

func (w *Workspace) handleToggleOverviewSidebar(msg tea.KeyMsg) tea.Cmd {
	rightWillBeVisible := !w.runOverviewSidebar.IsVisible()
	leftIsVisible := w.runsAnimState.IsVisible()

	w.resolveSidebarFocus(leftIsVisible, rightWillBeVisible)
	w.updateSidebarDimensions(leftIsVisible, rightWillBeVisible)
	w.runOverviewSidebar.Toggle()
	w.recalculateLayout()

	return w.runOverviewAnimationCmd()
}

func (w *Workspace) handleToggleBottomBar(msg tea.KeyMsg) tea.Cmd {
	w.bottomBar.UpdateExpandedHeight(max(w.height-StatusBarHeight, 0))
	w.bottomBar.Toggle()
	w.recalculateLayout()

	return w.bottomBarAnimationCmd()
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

	case SystemInfoMsg:
		w.getOrCreateRunOverview(run.key).ProcessSystemInfoMsg(m.Record)

	case SummaryMsg:
		w.getOrCreateRunOverview(run.key).ProcessSummaryMsg(m.Summary)

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

func (w *Workspace) handleConfigMetricsCols(msg tea.KeyMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigMetricsCols)
	return nil
}

func (w *Workspace) handleConfigMetricsRows(msg tea.KeyMsg) tea.Cmd {
	w.config.SetPendingGridConfig(gridConfigMetricsRows)
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

func (w *Workspace) handleSidebarTabNav(msg tea.KeyMsg) tea.Cmd {
	direction := 1
	if msg.Type == tea.KeyShiftTab {
		direction = -1
	}

	runsExpanded := w.runsAnimState.IsExpanded()
	overviewExpanded := w.runOverviewSidebar.animState.IsExpanded()

	if w.runs.Active {
		if !overviewExpanded {
			return nil
		}

		w.runs.Active = false

		if direction == 1 {
			w.runOverviewSidebar.selectFirstAvailableItem()
			return nil
		}

		_, last := w.runOverviewSectionBounds()
		if last != -1 {
			w.runOverviewSidebar.setActiveSection(last)
			return nil
		}

		w.runOverviewSidebar.selectFirstAvailableItem()
		return nil
	}

	// Overview sidebar is focused.
	if !overviewExpanded {
		// Can't keep focus on a hidden/collapsed sidebar.
		w.runs.Active = true
		w.runOverviewSidebar.deactivateAllSections()
		return nil
	}
	if !runsExpanded {
		// With no runs sidebar, keep cycling within the overview sections.
		w.runOverviewSidebar.navigateSection(direction)
		return nil
	}

	first, last := w.runOverviewSectionBounds()
	if first == -1 || last == -1 {
		// No navigable sections; return focus to the runs list.
		w.runs.Active = true
		w.runOverviewSidebar.deactivateAllSections()
		return nil
	}

	if direction == 1 && w.runOverviewSidebar.activeSection == last {
		w.runs.Active = true
		w.runOverviewSidebar.deactivateAllSections()
		return nil
	}
	if direction == -1 && w.runOverviewSidebar.activeSection == first {
		w.runs.Active = true
		w.runOverviewSidebar.deactivateAllSections()
		return nil
	}

	w.runOverviewSidebar.navigateSection(direction)
	return nil
}

// runOverviewSectionBounds returns the first and last sections with at least one
// visible item. If none exist, returns (-1, -1).
func (w *Workspace) runOverviewSectionBounds() (first, last int) {
	first, last = -1, -1
	if w.runOverviewSidebar == nil {
		return first, last
	}

	for i := range w.runOverviewSidebar.sections {
		section := &w.runOverviewSidebar.sections[i]
		if section.ItemsPerPage() == 0 || len(section.FilteredItems) == 0 {
			continue
		}
		if first == -1 {
			first = i
		}
		last = i
	}
	return first, last
}

func (w *Workspace) handleRunsPageNav(msg tea.KeyMsg) tea.Cmd {
	switch {
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

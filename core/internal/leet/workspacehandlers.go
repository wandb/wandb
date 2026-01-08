package leet

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
)

// workspaceRun holds per‑run state for the workspace multi‑run view.
type workspaceRun struct {
	key       string
	wandbPath string
	reader    *WandbReader
	watcher   *WatcherManager
	state     RunState
}

// initReaderCmd initializes a WandbReader for the given run asynchronously.
func (w *Workspace) initReaderCmd(runKey, runPath string) tea.Cmd {
	return func() tea.Msg {
		reader, err := NewWandbReader(runPath, w.logger)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return WorkspaceInitMsg{
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

// anyRunRunning reports whether any selected run is currently live.
func (w *Workspace) anyRunRunning() bool {
	for key, run := range w.runsByKey {
		if run == nil || run.state != RunStateRunning {
			continue
		}
		if !w.selectedRuns[key] {
			continue
		}
		return true
	}
	return false
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

	var cmds []tea.Cmd

	// Lazily start a watcher for this run.
	if run.watcher == nil {
		ch := make(chan tea.Msg, 1) // coalesce notifications for this run
		run.watcher = NewWatcherManager(ch, w.logger)

		if err := run.watcher.Start(run.wandbPath); err != nil {
			w.logger.CaptureError(fmt.Errorf(
				"workspace: failed to start watcher for %s: %v", run.key, err))
			run.watcher = nil
		} else {
			cmds = append(cmds, w.waitForWatcher(run.key))
		}
	}

	// Ensure the shared heartbeat is ticking while we have live runs.
	if w.heartbeatMgr != nil && w.anyRunRunning() {
		w.heartbeatMgr.Start(w.anyRunRunning)
	}

	if len(cmds) == 0 {
		return nil
	}
	if len(cmds) == 1 {
		return cmds[0]
	}
	return tea.Batch(cmds...)
}

// waitForWatcher blocks until the watcher for the given run emits a change
// and wraps the low-level FileChangedMsg with the originating run key.
func (w *Workspace) waitForWatcher(runKey string) tea.Cmd {
	return func() tea.Msg {
		run := w.runsByKey[runKey]
		if run == nil || run.watcher == nil {
			return nil
		}

		if msg := run.watcher.WaitForMsg(); msg != nil {
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

// handleWorkspaceInit stores the reader and starts the initial load for the run.
func (w *Workspace) handleWorkspaceInit(msg WorkspaceInitMsg) tea.Cmd {
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

	if w.metricsGrid != nil {
		w.metricsGrid.drawVisible()
	}

	var cmds []tea.Cmd
	if msg.Batch.HasMore {
		cmds = append(cmds, w.readAllChunkCmd(run))
	} else {
		// Initial load complete; if this run is live, wire up watcher + heartbeat.
		if cmd := w.ensureLiveStreaming(run); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	if len(cmds) == 0 {
		return nil
	}
	return tea.Batch(cmds...)
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

	if w.metricsGrid != nil {
		w.metricsGrid.drawVisible()
	}

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
		run.state = RunStateRunning

	case HistoryMsg:
		if w.metricsGrid != nil {
			w.metricsGrid.ProcessHistory(m)
			if w.pinnedRun != "" {
				w.refreshPinnedRun()
			}
		}
		if w.anyRunRunning() {
			w.heartbeatMgr.Reset(w.anyRunRunning)
		}

	case FileCompleteMsg:
		switch m.ExitCode {
		case 0:
			run.state = RunStateFinished
		default:
			run.state = RunStateFailed
		}
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
		// Keep listening for potential future live runs.
		return w.waitForLiveMsg
	}

	// Schedule the next heartbeat while we still have live runs.
	w.heartbeatMgr.Reset(w.anyRunRunning)

	var cmds []tea.Cmd
	for key, run := range w.runsByKey {
		if run == nil || run.state != RunStateRunning {
			continue
		}
		if !w.selectedRuns[key] {
			continue
		}
		cmds = append(cmds, w.readAvailableCmd(run))
	}

	cmds = append(cmds, w.waitForLiveMsg)
	return tea.Batch(cmds...)
}

// handleWorkspaceFileChanged reacts to a filesystem change for a given run.
func (w *Workspace) handleWorkspaceFileChanged(msg WorkspaceFileChangedMsg) tea.Cmd {
	run := w.runsByKey[msg.RunKey]
	if run == nil {
		return nil
	}

	var cmds []tea.Cmd

	// Drain any new records for this run.
	if cmd := w.readAvailableCmd(run); cmd != nil {
		cmds = append(cmds, cmd)
	}

	// Re‑arm watcher for the next change if we're still watching this run.
	if run.watcher != nil {
		cmds = append(cmds, w.waitForWatcher(msg.RunKey))
	}

	// Keep the heartbeat as a safety net when we still have live runs.
	if w.heartbeatMgr != nil && w.anyRunRunning() {
		w.heartbeatMgr.Reset(w.anyRunRunning)
	}

	if len(cmds) == 0 {
		return nil
	}
	if len(cmds) == 1 {
		return cmds[0]
	}
	return tea.Batch(cmds...)
}
